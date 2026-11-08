"""Isolated manager SMS preview/send tests; provider calls are fake."""
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from flask import Flask, session
from calendar_sms import LA, register_calendar_sms


class CalendarSmsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name)/'test.db')
        self.day = (datetime.now(LA)+timedelta(days=10)).date().isoformat()
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript('''CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name,teacher,lesson_date,lesson_time,duration,location,classroom,status,is_group);
                CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name,phone,active);
                CREATE TABLE parent_students(parent_id,student_name,active);
                CREATE TABLE parent_notification_preferences(parent_id,lesson_reminders);
                CREATE TABLE group_schedule_students(schedule_id,student_name);
                INSERT INTO parent_profiles VALUES(1,'Parent A','+16505550101',1),(2,'Parent B','+16505550102',1),(3,'Unrelated','+16505550103',1);
                INSERT INTO parent_students VALUES(1,'Student A',1),(2,'Student A',1),(3,'Student B',1);
                INSERT INTO parent_notification_preferences VALUES(1,1),(2,1);''')
            c.execute("INSERT INTO schedule VALUES(1,'Student A','Teacher A',?,'15:30',45,'Main studio','Room 3','scheduled',0)",(self.day,)); c.commit()
        self.calls=[];self.configured=True;self.accepted=True;self.raise_send=False
        def send(*args):
            self.calls.append(args)
            if self.raise_send: raise TimeoutError('response lost')
            return self.accepted,'provider accepted' if self.accepted else 'rejected'
        self.app=Flask(__name__, static_folder='static');self.app.secret_key='test';self.app.testing=True
        @self.app.get('/calendar')
        def calendar(): return '<html><head></head><body>Calendar</body></html>'
        register_calendar_sms(self.app,dict(sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),
            require_owner=lambda:session.get('user_role')=='owner',
            ensure_calendar_lesson_panel_schema=lambda:None, ensure_parent_portal_feature_schema=lambda:None,
            hmusic_normalize_sms_phone=lambda p:p if str(p).startswith('+1') and len(p)==12 else None,
            hmusic_clean_student_picker_value=lambda s:s,
            sms_config_status=lambda:(self.configured,[]),send_sms_delivery=send,
            calendar_group_roster=lambda c,s,r:[{'student_name':'Student A','attendance_status':'scheduled'},{'student_name':'Student B','attendance_status':'scheduled'}],
            calendar_lesson_row=lambda c,s:None))
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['user_role']='owner'
    def sql(self,query,args=()):
        with closing(sqlite3.connect(self.path)) as c:
            result=c.execute(query,args).fetchall();c.commit();return result
    def preview(self,ids=None,note=''):
        return self.client.post('/api/calendar-sms/lesson/1/preview',json={'parent_ids':ids or [1],'note':note})
    def draft(self,ids=None):
        response=self.preview(ids);self.assertEqual(response.status_code,200,response.json);return response.json['previews'][0]
    def send(self,token): return self.client.post('/api/calendar-sms/send/'+token,json={})
    def test_manager_only_for_every_endpoint(self):
        token=self.draft()['token']
        for role in ('teacher','parent',None):
            with self.client.session_transaction() as s:s['user_role']=role
            self.assertEqual(self.client.get('/api/calendar-sms/lessons').status_code,403)
            self.assertEqual(self.client.get('/api/calendar-sms/lesson/1').status_code,403)
            self.assertEqual(self.preview().status_code,403)
            self.assertEqual(self.send(token).status_code,403)
        self.assertEqual(self.calls,[])
    def test_preview_is_exact_and_does_not_send(self):
        d=self.draft();self.assertIn('Student A',d['body']);self.assertIn('03:30 PM–04:15 PM',d['body']);self.assertIn('Room 3',d['body'])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.send(d['token']).json['status'],'accepted')
        phone,title,body,link=self.calls[0];self.assertEqual('H-Music: '+title+'\n'+body,d['body']);self.assertEqual(link,'')
    def test_selected_parent_only_and_no_education_data_changes(self):
        original=self.sql('SELECT * FROM schedule')
        d=self.draft([2]);self.send(d['token']);self.assertEqual([x[0] for x in self.calls],['+16505550102']);self.assertEqual(self.sql('SELECT * FROM schedule'),original)
    def test_repeated_submit_does_not_resend(self):
        d=self.draft();self.send(d['token']);self.send(d['token']);self.assertEqual(len(self.calls),1)
    def test_shared_phone_deduplicated(self):
        self.sql("UPDATE parent_profiles SET phone='+16505550101' WHERE id=2")
        result=self.preview([1,2]);self.assertEqual(len(result.json['previews']),1)
    def test_unrelated_inactive_opted_out_invalid_phone_rejected(self):
        self.assertEqual(self.preview([3]).status_code,400)
        for query in ["UPDATE parent_profiles SET active=0 WHERE id=1","UPDATE parent_notification_preferences SET lesson_reminders=0 WHERE parent_id=1","UPDATE parent_profiles SET phone='' WHERE id=1"]:
            self.sql(query);self.assertEqual(self.preview().status_code,400)
            self.sql("UPDATE parent_profiles SET active=1,phone='+16505550101' WHERE id=1");self.sql('UPDATE parent_notification_preferences SET lesson_reminders=1 WHERE parent_id=1')
    def test_schedule_recipient_and_preference_rechecked(self):
        for query in ["UPDATE schedule SET classroom='Changed'", "UPDATE parent_profiles SET phone='+16505550109' WHERE id=1",'UPDATE parent_students SET active=0 WHERE parent_id=1','UPDATE parent_notification_preferences SET lesson_reminders=0 WHERE parent_id=1']:
            d=self.draft();self.sql(query);self.assertEqual(self.send(d['token']).status_code,409)
            self.sql("UPDATE schedule SET classroom='Room 3'");self.sql("UPDATE parent_profiles SET phone='+16505550101' WHERE id=1");self.sql('UPDATE parent_students SET active=1');self.sql('UPDATE parent_notification_preferences SET lesson_reminders=1')
        self.assertEqual(self.calls,[])
    def test_past_and_cancelled_lessons_blocked(self):
        for query in ["UPDATE schedule SET status='teacher_cancelled'", "UPDATE schedule SET status='scheduled',lesson_date='2000-01-01'"]:
            self.sql(query);self.assertEqual(self.preview().status_code,409)
    def test_expired_preview_blocked(self):
        d=self.draft();self.sql("UPDATE calendar_sms_reminders SET expires_at='2000-01-01T00:00:00+00:00'");self.assertEqual(self.send(d['token']).status_code,409)
    def test_provider_loss_is_unconfirmed_and_never_retried(self):
        self.raise_send=True;d=self.draft();self.assertEqual(self.send(d['token']).json['status'],'unconfirmed');self.send(d['token']);self.assertEqual(len(self.calls),1)
    def test_multiple_previews_cannot_duplicate_recent_send(self):
        a=self.draft();b=self.draft();self.send(a['token']);self.assertEqual(self.send(b['token']).status_code,409);self.assertEqual(len(self.calls),1)
    def test_provider_unavailable_blocks_preview_and_send(self):
        d=self.draft();self.configured=False;self.assertEqual(self.preview().status_code,503);self.assertEqual(self.send(d['token']).status_code,503);self.assertEqual(self.calls,[])
    def test_group_parents_are_scoped_to_roster(self):
        self.sql('UPDATE schedule SET is_group=1');d=self.client.get('/api/calendar-sms/lesson/1').json;self.assertEqual({p['id'] for p in d['parents']},{1,2,3})
        self.assertEqual(self.preview([3]).status_code,200)
    def test_month_teacher_filters_and_invalid_month(self):
        month=self.day[:7]
        self.assertEqual(len(self.client.get('/api/calendar-sms/lessons?month='+month+'&teacher=Teacher+A').json['lessons']),1)
        self.assertEqual(self.client.get('/api/calendar-sms/lessons?month='+month+'&teacher=Other').json['lessons'],[])
        self.assertEqual(self.client.get('/api/calendar-sms/lessons?month=2026-99').status_code,400)
    def test_assets_and_no_cache(self):
        self.assertIn('calendar_sms.js',self.client.get('/calendar').text)
        self.assertEqual(self.client.get('/api/calendar-sms/lesson/1').headers['Cache-Control'],'no-store')
        with self.client.session_transaction() as s:s['user_role']='parent'
        self.assertNotIn('calendar_sms.js',self.client.get('/calendar').text)
    def test_invalid_payloads(self):
        for payload in [{},{'parent_ids':[True]},{'parent_ids':[1],'note':'x'*401},{'parent_ids':[1],'note':7}]:
            self.assertEqual(self.client.post('/api/calendar-sms/lesson/1/preview',json=payload).status_code,400)
        self.assertEqual(self.client.post('/api/calendar-sms/lesson/1/preview',data='x').status_code,400)

if __name__=='__main__':unittest.main()
