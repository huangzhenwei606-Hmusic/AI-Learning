from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile
import unittest

from flask import Flask, session
from director_portal import register_director_portal, ensure_schema


class DirectorPortalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'test.db')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY,username,role,display_name,linked_teacher_name);
                INSERT INTO users VALUES (1,'xueyang','teacher','Xueyang Wang','Xueyang Wang'),(2,'other','teacher','Other','Other');
                CREATE TABLE teachers(teacher_name,active);
                INSERT INTO teachers VALUES('Xueyang Wang',1),('Other',1);
                CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name,active);
                INSERT INTO parent_profiles VALUES(1,'Family One',1),(2,'Family Two',1),(3,'Disabled Family',0);
                CREATE TABLE parent_students(parent_id,student_name,active);
                INSERT INTO parent_students VALUES(1,'Student One',1),(2,'Student Two',1);
                CREATE TABLE schedule(student_name,teacher,course_type_name,classroom,lesson_date,status);
                INSERT INTO schedule VALUES('Student One','Xueyang Wang','Piano','Room A','2099-01-01','scheduled'),
                    ('Student Two','Other','Violin','Room B','2099-01-01','scheduled');
                CREATE TABLE message_threads(id INTEGER PRIMARY KEY AUTOINCREMENT,subject,parent_id,teacher_name,
                    thread_type,is_group,owner_observer,related_type,related_id,status,created_at,updated_at);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,thread_id,sender_role,sender_name,recipient_role,body,channel,created_at);
                CREATE TABLE notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_role,user_key,title,body,link_url,related_type,related_id,created_at);
                CREATE TABLE message_participants(thread_id,participant_role,participant_key);
                CREATE TABLE message_attachments(id INTEGER PRIMARY KEY,message_id,stored_filename,original_filename,mime_type);
            ''')
            db.commit()
        self.app = Flask(__name__)
        self.app.secret_key = 'tests'
        self.app.testing = True
        self.push = []
        self.push_failure = False
        def queue(*args, **kwargs):
            if self.push_failure:
                raise RuntimeError('provider unavailable')
            self.push.append((args, kwargs))
            return len(self.push)
        def participants(cursor, thread_id, parent_id, teacher_name, owner_observer=1):
            cursor.execute("INSERT INTO message_participants VALUES (?,'parent',?)",(thread_id,str(parent_id)))
            cursor.execute("INSERT INTO message_participants VALUES (?,'owner','owner')",(thread_id,))
        @self.app.get('/teacher_dashboard')
        def dashboard():
            return '<html><body>Teacher tools</body></html>'
        @self.app.get('/registration')
        @self.app.get('/registration/complete')
        @self.app.get('/group-registration/example')
        @self.app.get('/trial-enrollment/example')
        def public_family_form():
            return '<html><body><h1>New student registration</h1><form method="POST"></form></body></html>'
        @self.app.get('/payroll')
        def payroll():
            return 'Owner financial data'
        register_director_portal(self.app, dict(
            sqlite3=SimpleNamespace(connect=lambda _: sqlite3.connect(self.path)),
            require_owner=lambda: session.get('user_role')=='owner',
            hmusic_csrf_token=lambda: 'test-token',
            sync_thread_default_participants=participants,
            queue_notification_delivery=queue,
            HMUSIC_UPLOAD_DIR=self.tmp.name,
        ))
        self.client = self.app.test_client()
        self.login('teacher')

    def login(self, role, username='xueyang', parent_id=1):
        with self.client.session_transaction() as s:
            s.clear()
            s['user_role'] = role
            s['username'] = username
            if role == 'teacher':
                s['teacher_name'] = 'Xueyang Wang'
            if role == 'parent':
                s['parent_id'] = parent_id

    def sql(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as db:
            result = db.execute(sql,params).fetchall()
            db.commit()
            return result

    def director(self):
        self.login('teacher')
        r = self.client.post('/role/switch', data={'role':'director'})
        self.assertEqual(r.status_code,302)

    def draft(self, **kwargs):
        data = dict(kind='message', title='School news', body='Hello families',audience='all')
        data.update(kwargs)
        r = self.client.post('/director/compose',data=data)
        self.assertEqual(r.status_code,302,r.get_data(as_text=True))
        return r.location

    def publish(self, url):
        r = self.client.post(url,data={'action':'publish'})
        self.assertEqual(r.status_code,302,r.get_data(as_text=True))

    def test_public_forms_never_show_staff_navigation_even_when_owner_logged_in(self):
        for role in ('owner','teacher','director','parent',None):
            self.login(role)
            for path in ('/registration','/registration/complete','/group-registration/example','/trial-enrollment/example'):
                response=self.client.get(path)
                # The Director scope may block unrelated public routes; no management links may leak.
                if response.status_code==200:
                    html=response.get_data(as_text=True)
                    self.assertIn('New student registration',html)
                    for link in ('/owner/directors','/director','/role/switch','/school/announcements'):
                        self.assertNotIn(link,html)
        self.login('owner')
        self.assertIn('Director permissions',self.client.get('/director').get_data(as_text=True))

    def test_parent_and_anonymous_cannot_open_management_pages(self):
        for role in ('parent',None):
            self.login(role)
            for path in ('/director','/director/inbox','/director/compose','/owner/directors'):
                self.assertEqual(self.client.get(path).status_code,403)
                self.assertIn(self.client.post(path,data={}).status_code,(403,405))

    def test_role_switch_teacher_preserved_and_owner_denied(self):
        html = self.client.get('/teacher_dashboard').get_data(as_text=True)
        self.assertIn('Switch to Director', html)
        self.director()
        with self.client.session_transaction() as s:
            self.assertNotIn('teacher_name',s)
        self.assertEqual(self.client.get('/payroll').status_code,403)
        self.assertEqual(self.client.get('/owner/directors').status_code,403)
        self.assertEqual(self.client.post('/role/switch',data={'role':'teacher'}).status_code,302)
        with self.client.session_transaction() as s:
            self.assertEqual(s['teacher_name'],'Xueyang Wang')
        self.assertEqual(self.sql('SELECT role FROM users WHERE id=1'),[('teacher',)])

    def test_revoke_active_session_and_no_regrant(self):
        self.director()
        self.login('owner','owner')
        self.assertEqual(self.client.post('/owner/directors',data={'user_id':'1'}).status_code,200)
        self.login('director')
        self.assertEqual(self.client.get('/director').status_code,302)
        with closing(sqlite3.connect(self.path)) as db:
            ensure_schema(db)
        self.assertEqual(self.sql('SELECT enabled FROM director_access WHERE user_id=1'),[(0,)])
        self.assertEqual(self.client.post('/role/switch',data={'role':'director'}).status_code,403)

    def test_native_login_entry_keeps_director_workspace(self):
        self.director()
        response = self.client.get('/teacher_login?native_app=1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/director')
        self.assertEqual(self.client.get('/payroll').status_code, 403)
        self.assertEqual(self.client.get('/teacher_dashboard').status_code, 403)

    def test_private_broadcast_preview_idempotence_and_push(self):
        self.director()
        url = self.draft(push='1')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM messages'),[(0,)])
        self.assertEqual(self.push,[])
        self.assertIn('Recipients (2)',self.client.get(url).get_data(as_text=True))
        self.publish(url)
        self.publish(url)
        self.assertEqual(self.sql('SELECT parent_id,is_group FROM message_threads ORDER BY parent_id'),[(1,0),(2,0)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM messages'),[(2,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM notifications'),[(2,)])
        self.assertEqual(len(self.push),2)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM message_participants WHERE participant_role='teacher'"),[(0,)])
        self.assertEqual(self.sql("SELECT DISTINCT sender_name FROM messages"),[('H-Music School Office',)])

    def test_parent_reply_school_only_and_handled_reopens(self):
        self.director()
        self.publish(self.draft())
        tid = self.sql('SELECT id FROM message_threads WHERE parent_id=1')[0][0]
        self.sql("INSERT INTO messages(thread_id,sender_role,sender_name,body) VALUES (?,'parent','Family One','Please help')",(tid,))
        self.assertIn('Please help',self.client.get(f'/director/inbox/{tid}').get_data(as_text=True))
        self.assertEqual(self.client.post(f'/director/inbox/{tid}',data={'action':'reply','body':'Happy to help'}).status_code,302)
        self.assertEqual(self.client.post(f'/director/inbox/{tid}',data={'action':'handled'}).status_code,302)
        self.assertIn('Handled',self.client.get('/director/inbox').get_data(as_text=True))
        self.sql("INSERT INTO messages(thread_id,sender_role,sender_name,body) VALUES (?,'parent','Family One','One more question')",(tid,))
        self.assertIn('1 new replies',self.client.get('/director/inbox').get_data(as_text=True))
        self.sql("INSERT INTO message_threads(id,subject,parent_id) VALUES (999,'Private teacher thread',1)")
        self.assertEqual(self.client.get('/director/inbox/999').status_code,404)

    def test_announcement_audience_privacy_and_safe_rendering(self):
        self.director()
        url = self.draft(kind='event',audience='selected',parent_ids=['1'],title='<script>bad()</script>',body='<img src=x onerror=alert(1)>')
        self.publish(url)
        pid = url.rsplit('/',1)[1]
        self.login('parent',parent_id=1)
        html = self.client.get('/school/announcements/'+pid).get_data(as_text=True)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>bad()',html)
        self.assertNotIn('/director/compose',html)
        self.login('parent',parent_id=2)
        self.assertEqual(self.client.get('/school/announcements/'+pid).status_code,404)
        self.assertNotIn('bad()',self.client.get('/school/announcements').get_data(as_text=True))
        self.assertEqual(self.client.get('/director/inbox').status_code,403)

    def test_permissions_server_enforced_owner_review(self):
        self.director()
        url = self.draft()
        grants = dict(inbox=True,reply=False,broadcast=True,publish=False,push=False,approval=True)
        self.sql('UPDATE director_access SET permissions=? WHERE user_id=1',(json.dumps(grants),))
        self.assertEqual(self.client.post(url,data={'action':'publish'}).status_code,403)
        self.assertEqual(self.client.post('/director/compose',data=dict(kind='event',title='Event',body='Details')).status_code,403)
        self.assertEqual(self.client.post('/director/compose',data=dict(kind='message',title='News',body='Details',push='1')).status_code,403)
        self.assertEqual(self.client.post(url,data={'action':'submit'}).status_code,302)
        self.login('owner','owner')
        self.publish(url)
        self.login('director')
        tid = self.sql('SELECT id FROM message_threads LIMIT 1')[0][0]
        self.assertEqual(self.client.post(f'/director/inbox/{tid}',data={'action':'reply','body':'No permission'}).status_code,403)
        self.assertNotIn('No permission',str(self.sql('SELECT body FROM messages')))

    def test_filters_edit_and_invalid_urls(self):
        self.director()
        url = self.draft(audience='teacher',audience_value='Xueyang Wang')
        self.assertEqual(self.sql('SELECT recipients FROM school_posts'),[('[1]',)])
        self.assertEqual(self.client.post(url,data={'action':'save','title':'Edited','body':'New wording'}).status_code,302)
        self.publish(url)
        self.assertEqual(self.sql('SELECT body FROM messages'),[('New wording',)])
        self.assertEqual(self.client.post(url,data={'action':'save','title':'Edited','body':'Too late'}).status_code,409)
        self.assertEqual(self.client.post('/director/compose',data=dict(kind='event',title='Event',body='Details',signup_url='javascript:alert(1)')).status_code,400)
        self.assertEqual(self.client.post('/director/compose',data=dict(kind='message',title='News',body='Details',audience='selected',parent_ids=['3'])).status_code,400)

    def test_push_retry_without_duplicate_family_messages(self):
        self.director()
        url = self.draft(push='1')
        self.push_failure = True
        with self.assertLogs(self.app.logger,level='ERROR'):
            self.publish(url)
        self.assertEqual(self.sql('SELECT DISTINCT push_state FROM school_deliveries'),[('failed',)])
        self.push_failure = False
        self.assertEqual(self.client.post(url,data={'action':'retry'}).status_code,302)
        self.assertEqual(len(self.push),2)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM messages'),[(2,)])

    def test_other_teacher_and_password_change_cannot_switch(self):
        self.login('teacher',username='other')
        self.assertEqual(self.client.post('/role/switch',data={'role':'director'}).status_code,403)
        self.login('teacher')
        with self.client.session_transaction() as s:
            s['must_change_password']=True
        self.assertEqual(self.client.post('/role/switch',data={'role':'director'}).status_code,403)

    def test_parent_initiated_office_messages_are_visible_without_teacher_private_threads(self):
        self.director()
        self.sql("INSERT INTO message_threads(id,subject,parent_id,thread_type) VALUES (900,'School question',1,'parent_director')")
        self.sql("INSERT INTO messages(thread_id,sender_role,sender_name,body) VALUES (900,'parent','Family One','School question body')")
        self.assertIn('School question',self.client.get('/director/inbox').get_data(as_text=True))
        self.assertIn('School question body',self.client.get('/director/inbox/900').get_data(as_text=True))
        self.assertEqual(self.client.post('/director/inbox/900',data={'action':'reply','body':'Office answer'}).status_code,302)
        self.sql("INSERT INTO message_threads(id,subject,parent_id,thread_type) VALUES (901,'Tuition',1,'invoice')")
        self.assertEqual(self.client.get('/director/inbox/901').status_code,404)

    def test_attachment_school_scope(self):
        self.director()
        self.publish(self.draft())
        mid = self.sql('SELECT id FROM messages LIMIT 1')[0][0]
        (Path(self.tmp.name)/'note.txt').write_text('Private school attachment')
        self.sql("INSERT INTO message_attachments VALUES(1,?,'note.txt','Note.txt','text/plain')",(mid,))
        self.sql("INSERT INTO message_attachments VALUES(2,999,'note.txt','Other.txt','text/plain')")
        with self.client.get('/director/attachments/1') as response:
            self.assertEqual(response.get_data(as_text=True),'Private school attachment')
        self.assertEqual(self.client.get('/director/attachments/2').status_code,404)


if __name__ == '__main__':
    unittest.main()
