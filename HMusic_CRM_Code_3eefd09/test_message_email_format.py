import ast
import base64
from contextlib import closing
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from message_email import message_context, render_content, MAX_IMAGE_BYTES

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJz0AAAAASUVORK5CYII=')


class MessageEmailFormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'test.db')
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript('''CREATE TABLE parent_profiles(id,email,active);
                INSERT INTO parent_profiles VALUES(1,'family@school.test',1),(2,'other@school.test',1);
                CREATE TABLE teachers(teacher_name,email,active);
                INSERT INTO teachers VALUES('Teacher One','teacher@school.test',1);
                CREATE TABLE message_threads(id,subject,parent_id,teacher_name);
                INSERT INTO message_threads VALUES(7,'Payment received for semester 9/1-11/10/2026',1,NULL),(8,'Other family',2,NULL);
                CREATE TABLE messages(id,thread_id,sender_role,body);
                INSERT INTO messages VALUES(10,7,'owner','Thank you for your payment.'),(11,7,'parent','Different reply'),(12,8,'owner','Other family');
                CREATE TABLE message_participants(thread_id,participant_role,participant_key,active);
                INSERT INTO message_participants VALUES(7,'parent','1',1);
                CREATE TABLE settings(key,value);
                CREATE TABLE message_attachments(id INTEGER PRIMARY KEY,message_id,original_filename,stored_filename,mime_type,content_base64);
                ''')
            c.execute('INSERT INTO message_attachments VALUES(1,10,?,?,?,?)',('课表.png','stored.png','image/png',base64.b64encode(PNG).decode()))
            c.execute('INSERT INTO message_attachments VALUES(2,11,?,?,?,?)',('reply.png','reply.png','image/png',base64.b64encode(b'OTHER REPLY').decode()))
            c.commit()
        self.delivered=[]
        class SMTP:
            def __init__(inner,*a,**k):pass
            def __enter__(inner):return inner
            def __exit__(inner,*a):pass
            def ehlo(inner):pass
            def starttls(inner):pass
            def login(inner,*a):pass
            def send_message(inner,message):self.delivered.append(message)
        self.api=dict(sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),
            HMUSIC_UPLOAD_DIR=self.tmp.name,
            get_message_upload_s3_config=lambda:None,
            hmusic_public_app_url=lambda path:'https://hmusic-crm.onrender.com/'+str(path).lstrip('/'),
            os=os,re=re,EmailMessage=EmailMessage,hmusic_is_real_email=lambda _:True,
            hmusic_is_email_suppressed=lambda *a:False,HMUSIC_TRANSACTIONAL_EMAIL='info@h-musicandarts.com',
            smtplib=SimpleNamespace(SMTP=SMTP,SMTP_SSL=SMTP),app=SimpleNamespace(logger=SimpleNamespace(exception=lambda *a:None)))
        node=next(n for n in ast.parse(Path(__file__).with_name('app.py').read_text()).body
            if isinstance(n,ast.FunctionDef) and n.name=='send_email_delivery')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.api)
        self.env=patch.dict(os.environ,dict(HMUSIC_SMTP_HOST='fake.invalid',HMUSIC_SMTP_USER='info@h-musicandarts.com',
            HMUSIC_SMTP_PASSWORD='test-only',HMUSIC_FROM_EMAIL='info@h-musicandarts.com',HMUSIC_SMTP_SECURITY='ssl'))
        self.env.start();self.addCleanup(self.env.stop)

    def sql(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as c:
            result=c.execute(sql,args).fetchall();c.commit();return result

    def send(self,recipient='family@school.test',mid=10,link='/message_thread/7'):
        return self.api['send_email_delivery'](recipient,'New message from H-Music','Hello <family> & thanks!',link,mid)

    def test_exact_subject_clickable_full_link_and_uploaded_image_in_mime(self):
        before=self.sql('SELECT * FROM message_attachments')
        ok,_=self.send();self.assertTrue(ok)
        message=BytesParser(policy=default).parsebytes(self.delivered[0].as_bytes())
        self.assertEqual(message['Subject'],'Payment received for semester 9/1-11/10/2026')
        self.assertEqual(message['From'],'info@h-musicandarts.com')
        self.assertEqual(message['Reply-To'],'info@h-musicandarts.com')
        self.assertIn('hmusic-thread-7',message['Message-ID'])
        self.assertIn('Open: https://hmusic-crm.onrender.com/message_thread/7',message.get_body(preferencelist=('plain',)).get_content())
        html=message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('href="https://hmusic-crm.onrender.com/message_thread/7"',html)
        self.assertIn('&lt;family&gt; &amp; thanks!',html)
        attachments=list(message.iter_attachments());self.assertEqual(len(attachments),1)
        self.assertEqual(attachments[0].get_filename(),'课表.png')
        self.assertEqual(attachments[0].get_payload(decode=True),PNG)
        self.assertEqual(before,self.sql('SELECT * FROM message_attachments'))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM messages'),[(3,)])

    def test_latest_reply_image_is_not_substituted_for_original_message(self):
        _,images=message_context(self.api,10,'family@school.test','/message_thread/7')
        self.assertEqual(images,[('课表.png','image/png',PNG)])
        _,images=message_context(self.api,11,'family@school.test','/message_thread/7')
        self.assertEqual(images[0][2],b'OTHER REPLY')

    def test_other_family_changed_recipient_or_wrong_link_is_blocked_before_smtp(self):
        for recipient,mid,link in [('other@school.test',10,'/message_thread/7'),('family@school.test',12,'/message_thread/7'),('family@school.test',999,'/message_thread/7')]:
            self.assertFalse(self.send(recipient,mid,link)[0])
        self.sql("UPDATE parent_profiles SET email='new@school.test' WHERE id=1")
        self.assertFalse(self.send()[0]);self.assertEqual(self.delivered,[])

    def test_object_storage_disk_and_missing_image(self):
        self.sql('UPDATE message_attachments SET content_base64=NULL WHERE id=1')
        (Path(self.tmp.name)/'stored.png').write_bytes(PNG)
        self.assertTrue(self.send()[0]);self.assertEqual(list(self.delivered[-1].iter_attachments())[0].get_payload(decode=True),PNG)
        (Path(self.tmp.name)/'stored.png').unlink()
        self.api['get_message_upload_s3_config']=lambda:{'bucket':'test'}
        self.api['message_upload_s3_key']=lambda config,name:'uploads/'+name
        requests=[]
        def get_object(**args):requests.append(args);return {'Body':BytesIO(PNG)}
        self.api['message_upload_s3_client']=lambda config:SimpleNamespace(get_object=get_object)
        self.assertTrue(self.send()[0]);self.assertEqual(requests,[{'Bucket':'test','Key':'uploads/stored.png'}])
        self.api['get_message_upload_s3_config']=lambda:None
        self.assertFalse(self.send()[0]);self.assertEqual(len(self.delivered),2)

    def test_invalid_storage_path_size_and_inactive_family_are_blocked(self):
        self.sql("UPDATE message_attachments SET content_base64=NULL,stored_filename='../private.png' WHERE id=1")
        self.assertFalse(self.send()[0])
        self.sql('UPDATE message_attachments SET content_base64=? WHERE id=1',('A'*(MAX_IMAGE_BYTES*4//3+8),))
        self.assertFalse(self.send()[0])
        self.sql('UPDATE parent_profiles SET active=0 WHERE id=1')
        self.assertFalse(self.send()[0]);self.assertEqual(self.delivered,[])

    def test_header_injection_and_non_message_notifications(self):
        self.sql("UPDATE message_threads SET subject=? WHERE id=7",('Hello\r\nBcc: other@school.test',))
        self.assertTrue(self.send()[0]);self.assertIsNone(self.delivered[-1]['Bcc'])
        ok,_=self.api['send_email_delivery']('family@school.test','School reminder','Upcoming lesson','/parent_dashboard')
        self.assertTrue(ok);self.assertEqual(self.delivered[-1]['Subject'],'School reminder')
        self.assertEqual(list(self.delivered[-1].iter_attachments()),[])
        plain,html=render_content(self.api,'Hello','https://hmusic-crm.onrender.com/parent_dashboard')
        self.assertNotIn('https://hmusic-crm.onrender.com/https:',plain)


if __name__=='__main__':unittest.main()
