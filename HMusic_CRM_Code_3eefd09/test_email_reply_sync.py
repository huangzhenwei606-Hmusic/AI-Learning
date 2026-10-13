import ast
from datetime import datetime
from email.message import EmailMessage
import io
import logging
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import email_reply_sync as sync


class EmailReplySyncTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE parent_profiles(id,parent_name,email,active);
            CREATE TABLE message_threads(id,parent_id,teacher_name,student_name,updated_at);
            CREATE TABLE message_participants(thread_id,participant_role,participant_key,display_name,active,last_read_at);
            CREATE TABLE messages(id INTEGER PRIMARY KEY,thread_id,sender_role,sender_name,recipient_role,body,channel,created_at,read_at);
            CREATE TABLE message_attachments(message_id,original_filename,stored_filename,mime_type,file_size,created_at,content_base64);
            CREATE TABLE notifications(user_role,user_key,title,body,link_url,related_type,related_id,created_at,read_at);
            CREATE TABLE notification_delivery_queue(user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,status,created_at);
            INSERT INTO parent_profiles VALUES(1,'Lucy parent','parent@example.com',1),(2,'Other parent','other@example.com',1);
            INSERT INTO message_threads VALUES(341,1,'Xu Huang','Lucy',NULL),(342,2,'Mike','Other',NULL);
            INSERT INTO message_participants VALUES(341,'teacher','Xu Huang','Xu Huang',1,'2026-01-01'),(341,'owner','owner','Owner',1,'2026-01-01');
        ''')
        sync.ensure_schema(self.db)
        self.api = dict(sync_participants=Mock(),safe_filename=lambda name:name,
                        allowed_mime_types={'application/pdf','text/plain'},logger=logging.getLogger('test'))

    def email(self, sender='parent@example.com', link=341, auth=True, reference=False, html=False, attachment=False):
        message = EmailMessage()
        message['From'] = sender
        message['To'] = 'studio@gmail.com'
        message['Subject'] = 'Re: New message from Xu Huang'
        message['Message-ID'] = '<reply-1@example.com>'
        if auth:
            message['Authentication-Results'] = 'mx.google.com; dmarc=pass header.from=example.com'
        if reference:
            message['In-Reply-To'] = '<abc.hmusic-thread-341@example.com>'
        quote = f'On Tue, Xu wrote:\n> Original message\n> Open: https://hmusic-crm.onrender.com/message_thread/{link}'
        message.set_content('Yes, thank you!\n\n'+quote)
        if html:
            message.clear_content()
            message.set_content(f'<p>Yes, thank you!</p><blockquote>Open: https://hmusic-crm.onrender.com/message_thread/{link}</blockquote>',subtype='html')
        if attachment:
            message.add_attachment(b'%PDF-test',maintype='application',subtype='pdf',filename='score.pdf')
        return message.as_bytes()

    def test_legacy_reply_imports_original_conversation_and_notifies_teacher(self):
        result = sync.import_reply(self.db,self.email(),self.api)
        self.assertTrue(result['imported'])
        self.assertEqual(self.db.execute('SELECT thread_id,body,channel FROM messages').fetchone(),(341,'Yes, thank you!','email'))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notifications WHERE user_role='teacher' AND user_key='Xu Huang'").fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT DISTINCT channel FROM notification_delivery_queue').fetchall(),[('push',)])

    def test_repeat_does_not_duplicate_message_or_notifications(self):
        sync.import_reply(self.db,self.email(),self.api)
        self.assertEqual(sync.import_reply(self.db,self.email(),self.api)['reason'],'duplicate')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],2)

    def test_sender_cannot_write_another_parents_conversation(self):
        self.assertFalse(sync.import_reply(self.db,self.email(link=342),self.api)['imported'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)

    def test_spoofed_sender_and_unknown_parent_are_rejected(self):
        for raw in (self.email(auth=False),self.email(sender='unknown@example.com')):
            self.assertFalse(sync.import_reply(self.db,raw,self.api)['imported'])

    def test_future_message_id_reference_matches_without_quoted_link(self):
        message = EmailMessage()
        message['From']='parent@example.com'
        message['Authentication-Results']='mx.google.com; dmarc=pass'
        message['In-Reply-To']='<abc.hmusic-thread-341@studio.example>'
        message['Message-ID']='<new@example.com>'
        message.set_content('Sounds good!')
        self.assertTrue(sync.import_reply(self.db,message.as_bytes(),self.api)['imported'])

    def test_html_reply_and_attachment_survive(self):
        result=sync.import_reply(self.db,self.email(html=True,attachment=True),self.api)
        self.assertTrue(result['imported'])
        self.assertEqual(self.db.execute('SELECT body FROM messages').fetchone()[0],'Yes, thank you!')
        import base64
        self.assertEqual(base64.b64decode(self.db.execute('SELECT content_base64 FROM message_attachments').fetchone()[0]),b'%PDF-test')

    def test_non_message_email_is_not_imported(self):
        message=EmailMessage()
        message['From']='parent@example.com'
        message['Authentication-Results']='mx.google.com; dmarc=pass'
        message.set_content('An unrelated email')
        self.assertEqual(sync.import_reply(self.db,message.as_bytes(),self.api)['reason'],'missing_or_ambiguous_conversation')

    def test_inactive_parent_is_not_imported(self):
        self.db.execute('UPDATE parent_profiles SET active=0 WHERE id=1')
        self.assertFalse(sync.import_reply(self.db,self.email(),self.api)['imported'])

    def test_transaction_failure_can_retry_without_losing_email(self):
        self.db.commit()
        self.api['sync_participants'].side_effect=RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            sync.import_reply(self.db,self.email(),self.api)
        self.db.rollback()
        self.api['sync_participants'].side_effect=None
        self.assertTrue(sync.import_reply(self.db,self.email(),self.api)['imported'])

    def test_mailbox_sync_peeks_without_marking_mail_read_and_deduplicates(self):
        raw=self.email()
        headers=b'From: parent@example.com\r\nMessage-ID: <reply-1@example.com>\r\n\r\n'
        client=Mock()
        client.select.return_value=('OK',[b'1'])
        def uid(operation,*args):
            if operation=='search': return ('OK',[b'7'])
            if 'HEADER.FIELDS' in args[-1]: return ('OK',[(b'1 (UID 7 BODY[HEADER.FIELDS] {99}',headers),b')'])
            return ('OK',[(b'1 (RFC822.SIZE 99 BODY[] {99}',raw),b')'])
        client.uid.side_effect=uid
        proxy=SimpleNamespace(cursor=self.db.cursor,execute=self.db.execute,
                              commit=self.db.commit,rollback=self.db.rollback,close=lambda:None)
        api={**self.api,'connect':lambda:proxy}
        config=dict(host='imap.gmail.com',port=993,user='studio@gmail.com',password='test',folder='INBOX')
        factory=Mock(return_value=client)
        self.assertEqual(sync.sync_mailbox(api,config,factory)['imported'],1)
        self.assertEqual(sync.sync_mailbox(api,config,factory)['imported'],0)
        client.select.assert_called_with('INBOX',readonly=True)
        fetches=[call.args[-1] for call in client.uid.call_args_list if call.args[0]=='fetch']
        self.assertTrue(all('BODY.PEEK' in command for command in fetches))
        self.assertEqual(sum('RFC822.SIZE' in command for command in fetches),1)

    def test_participants_are_not_reinserted_without_database_unique_constraint(self):
        self.db.execute('ALTER TABLE message_participants ADD COLUMN is_observer INTEGER')
        self.db.execute('ALTER TABLE message_participants ADD COLUMN created_at TEXT')
        source=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='ensure_message_participant')
        scope={'datetime':datetime}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<participant>','exec'),scope)
        for _ in range(3):
            scope['ensure_message_participant'](self.db.cursor(),341,'teacher','Xu Huang','Xu Huang')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM message_participants WHERE participant_role='teacher'").fetchone()[0],1)

    def test_notification_emails_have_stable_conversation_reply_headers(self):
        import re
        source=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='send_email_delivery')
        server=Mock()
        smtp=MagicMock()
        smtp.SMTP.return_value.__enter__.return_value=server
        scope=dict(re=re,EmailMessage=EmailMessage,smtplib=smtp,HMUSIC_TRANSACTIONAL_EMAIL="studio@gmail.com",
                   os=SimpleNamespace(environ={'HMUSIC_SMTP_HOST':'smtp.gmail.com','HMUSIC_SMTP_USER':'studio@gmail.com','HMUSIC_SMTP_PASSWORD':'test'}),
                   sqlite3=SimpleNamespace(connect=lambda _:SimpleNamespace(cursor=lambda:None,close=lambda:None)),
                   hmusic_is_real_email=lambda _:True,hmusic_is_email_suppressed=lambda *args:False)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<delivery>','exec'),scope)
        result=scope['send_email_delivery']('parent@example.com','New message','Hello','/message_thread/341')
        self.assertTrue(result[0])
        message=server.send_message.call_args.args[0]
        self.assertIn('hmusic-thread-341',message['Message-ID'])
        self.assertEqual(message['Reply-To'],'studio@gmail.com')

    def test_mailbox_defaults_and_opt_out(self):
        env=dict(HMUSIC_SMTP_HOST='smtp.gmail.com',HMUSIC_SMTP_USER='studio@gmail.com',HMUSIC_SMTP_PASSWORD='test')
        self.assertEqual(sync.mailbox_config(env)['host'],'imap.gmail.com')
        env['HMUSIC_EMAIL_REPLY_SYNC']='0'
        self.assertIsNone(sync.mailbox_config(env))

    def test_teacher_unread_badge_increases_and_read_clears_it(self):
        self.db.execute("INSERT INTO message_participants VALUES(341,'teacher','Xu Huang','Xu Huang',1,'2026-01-01')")
        sync.import_reply(self.db,self.email(),self.api)
        source=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='get_unread_message_count')
        proxy=SimpleNamespace(cursor=self.db.cursor,close=lambda:None,commit=self.db.commit)
        scope=dict(sqlite3=SimpleNamespace(connect=lambda _:proxy),ensure_v29_schema=lambda:None)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<unread>','exec'),scope)
        self.assertEqual(scope['get_unread_message_count']('teacher','Xu Huang'),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notifications WHERE user_role='teacher'").fetchone()[0],1)
        read_node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='mark_message_thread_read')
        scope.update(datetime=datetime,get_message_identity=lambda:('teacher','Xu Huang'))
        exec(compile(ast.Module(body=[read_node],type_ignores=[]),'<read>','exec'),scope)
        scope['mark_message_thread_read'](341)
        self.assertEqual(scope['get_unread_message_count']('teacher','Xu Huang'),0)

if __name__=='__main__':
    unittest.main()
