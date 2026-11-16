from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from flask import Flask, session
from calendar_parent_message import register_calendar_parent_message


class ParentComposerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        path=str(Path(self.tmp.name)/'test.db')
        connect=lambda _:sqlite3.connect(path)
        with closing(connect('')) as c:
            c.executescript('''CREATE TABLE schedule(id,student_name,teacher,lesson_date,lesson_time,is_group,duration,location,classroom);
                INSERT INTO schedule VALUES(1,'Daniel','Jason','2026-11-16','16:15',0,30,'Main studio','Room 3'),(2,'Group','Jason','2026-11-17','16:00',1,60,'Main studio','Room 2');
                CREATE TABLE parent_profiles(id,parent_name,email,phone,active);
                INSERT INTO parent_profiles VALUES(1,'Parent','parent@example.test','123',1),(2,'Other','other@example.test','456',1);
                CREATE TABLE parent_students(parent_id,student_name,active);
                INSERT INTO parent_students VALUES(1,'Daniel',1),(2,'Other child',1);''');c.commit()
        self.calls=[]
        self.app=Flask(__name__);self.app.secret_key='test';self.app.testing=True
        @self.app.get('/calendar')
        def calendar():return '<html><head></head><body>Calendar</body></html>'
        self.api=dict(sqlite3=SimpleNamespace(connect=connect),require_owner=lambda:session.get('role')=='owner',ensure_v29_schema=lambda:None,
            smtp_config_status=lambda:(True,[]),sms_config_status=lambda:(False,[]),
            calendar_group_roster=lambda *a:[dict(student_name='Daniel')],calendar_lesson_row=lambda *a:None,
            validate_message_channels=lambda *a:self.calls.append(('validate',a[2],a[3])),
            get_or_create_message_thread=lambda *a,**kw:self.calls.append(('thread',kw)) or 20,
            add_message=lambda *a:self.calls.append(('message',a)) or 30,
            create_notification=lambda *a,**kw:self.calls.append(('notify',a,kw)))
        register_calendar_parent_message(self.app,self.api);self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['role']='owner'
    def send(self,**kw):
        return self.client.post('/api/calendar-parent-message/1',json=dict(parent_id=1,student='Daniel',body='Hello parent',channels=['email'],token='a'*32,**kw))
    def test_context_and_read_do_not_send_or_link(self):
        d=self.client.get('/api/calendar-parent-message/1').json
        self.assertEqual(d['lesson']['display_time'],'04:15 PM–04:45 PM PST');self.assertEqual(d['lesson']['room'],'Room 3');self.assertEqual([p['id'] for p in d['parents']],[1]);self.assertEqual(self.calls,[])
        self.assertIn(b'calendar_parent_message.js',self.client.get('/calendar').data)
        self.assertEqual([p['id'] for p in self.client.get('/api/calendar-parent-message/2').json['parents']],[1])
    def test_send_parent_only_selected_channels_and_duplicate(self):
        self.assertTrue(self.send().json['ok']);self.assertTrue(self.send().json['ok'])
        msgs=[c for c in self.calls if c[0]=='message'];self.assertEqual(len(msgs),1)
        self.assertEqual(msgs[0][1],(20,'owner','Manager','parent','Hello parent'))
        notify=next(c for c in self.calls if c[0]=='notify');self.assertEqual(notify[1][0:2],('parent','1'));self.assertEqual(notify[2]['delivery_channels'],['email'])
    def test_unlinked_parent_and_missing_message_rejected(self):
        for p in [dict(parent_id=2,student='Daniel',body='Hi',channels=[]),dict(parent_id=1,student='Other child',body='Hi',channels=[]),dict(parent_id=1,student='Daniel',body='',channels=[])]:
            self.assertGreaterEqual(self.client.post('/api/calendar-parent-message/1',json=p).status_code,400)
        self.assertEqual(self.calls,[])
    def test_owner_only(self):
        for role in ['teacher','parent',None]:
            with self.client.session_transaction() as s:s['role']=role
            self.assertEqual(self.client.get('/api/calendar-parent-message/1').status_code,403);self.assertEqual(self.send().status_code,403)
        self.assertEqual(self.calls,[])
    def test_provider_error_saved_and_not_resent(self):
        def fail(*a,**kw):raise RuntimeError('provider unavailable')
        self.api['create_notification']=fail
        self.assertIn('do not resend',self.send().json['message']);self.send()
        self.assertEqual(len([c for c in self.calls if c[0]=='message']),1)
