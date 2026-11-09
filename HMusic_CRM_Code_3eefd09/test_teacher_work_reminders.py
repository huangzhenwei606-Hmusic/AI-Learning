from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from flask import Flask,session
from teacher_work_reminders import register_teacher_work_reminders,LA

class TeacherWorkRemindersTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'test.db');self.day=(datetime.now(LA)+timedelta(days=3)).date().isoformat()
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''CREATE TABLE teachers(id INTEGER PRIMARY KEY,teacher_name,email,phone,active);
                INSERT INTO teachers VALUES(1,'Jenny Lee','jenny@example.org','+16505550100',1),(2,'Other Teacher','other@example.org','+16505550101',1);
                CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name,teacher,lesson_date,lesson_time,duration,location,classroom,status,course_type_name,is_group);
                CREATE TABLE group_schedule_students(schedule_id,student_name,attendance_status);''')
            db.execute('INSERT INTO schedule VALUES(1,?,?,?,?,?,?,?,?,?,?)',('Ella Lee','Jenny Lee',self.day,'16:00',30,'1101','Room 2','scheduled','Piano',0))
            db.execute('INSERT INTO schedule VALUES(2,?,?,?,?,?,?,?,?,?,?)',('Other Student','Other Teacher',self.day,'17:00',30,'951D','Room 1','scheduled','Piano',0));db.commit()
            self.original=db.execute('SELECT * FROM schedule').fetchall()
        self.app=Flask(__name__);self.app.secret_key='isolated-tests';self.app.testing=True
        self.sent=[];self.sms_ready=True
        def sender(channel):
            def send(*args):self.sent.append((channel,args));return True,'Accepted by provider'
            return send
        @self.app.get('/calendar')
        def calendar():return '<html><body><h1>Calendar</h1></body></html>'
        self.api=dict(sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),
            require_owner=lambda:session.get('role')=='owner',hmusic_normalize_sms_phone=lambda x:x if x.startswith('+1') else None,
            hmusic_is_real_email=lambda x:'@' in x,sms_config_status=lambda:(self.sms_ready,[]),smtp_config_status=lambda:(True,[]),
            send_sms_delivery=sender('sms'),send_email_delivery=sender('email'))
        register_teacher_work_reminders(self.app,self.api)
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['role']='owner'

    def preview(self,**overrides):
        data={'teacher_id':'1','kind':'new_lesson','channels':['sms','email'],'lesson_ids':['1'],'note':'Please confirm attendance.'}
        data.update(overrides)
        return self.client.post('/manager/teacher-work-reminders',data=data)

    def sql(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:
            result=db.execute(sql,args).fetchall();db.commit();return result

    def test_preview_send_and_replay_preserve_schedule(self):
        p=self.preview();self.assertEqual(p.status_code,302);self.assertEqual(self.sent,[])
        html=self.client.get(p.location).get_data(as_text=True)
        for text in ['Ella Lee','Jenny Lee','Room 2','16:00','04:00 PM']:
            if text!='16:00':self.assertIn(text,html)
        self.assertEqual(self.client.post(p.location).status_code,200)
        self.assertEqual([x[0] for x in self.sent],['email','sms'])
        self.assertEqual(self.client.post(p.location).status_code,200);self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sql('SELECT * FROM schedule'),self.original)
        self.assertEqual(self.sql('SELECT status FROM teacher_work_reminders'),[('sent',)])

    def test_time_change_requires_previous_time_and_shows_both(self):
        self.assertEqual(self.preview(kind='time_change').status_code,400)
        p=self.preview(kind='time_change',old_date=self.day,old_time='15:00')
        html=self.client.get(p.location).get_data(as_text=True)
        for text in ['Previous time (provided by manager)','03:00 PM','New time:','04:00 PM']:self.assertIn(text,html)

    def test_contacts_and_lesson_changes_invalidate_preview(self):
        p=self.preview();self.sql("UPDATE schedule SET lesson_time='17:00' WHERE id=1")
        self.assertEqual(self.client.post(p.location).status_code,409);self.assertEqual(self.sent,[])
        p=self.preview();self.sql("UPDATE teachers SET phone='+16505550102' WHERE id=1")
        self.assertEqual(self.client.post(p.location).status_code,409);self.assertEqual(self.sent,[])

    def test_recipient_access_and_wrong_lesson(self):
        self.assertEqual(self.preview(lesson_ids=['2']).status_code,400)
        with self.client.session_transaction() as s:s['role']='teacher'
        self.assertEqual(self.client.get('/manager/teacher-work-reminders').status_code,403)
        self.assertEqual(self.preview().status_code,403);self.assertEqual(self.sent,[])

    def test_missing_channel_configuration_and_contact(self):
        self.sms_ready=False;self.assertEqual(self.preview(channels=['sms']).status_code,503)
        self.assertEqual(self.preview(channels=['email']).status_code,302)
        self.sms_ready=True;self.sql("UPDATE teachers SET phone='' WHERE id=1")
        self.assertEqual(self.preview(channels=['sms']).status_code,400)

    def test_separate_preview_channel_overlap_does_not_repeat_sms(self):
        p=self.preview(channels=['sms']);self.client.post(p.location)
        p=self.preview(channels=['sms','email']);self.assertEqual(self.client.post(p.location).status_code,409)
        self.assertEqual(len(self.sent),1)

    def test_unknown_delivery_outcome_not_retried(self):
        def timeout(*args):
            self.sent.append(('sms',args))
            raise TimeoutError()
        self.api['send_sms_delivery']=timeout
        p=self.preview(channels=['sms'])
        self.assertEqual(self.client.post(p.location).status_code,200)
        self.assertEqual(self.sql('SELECT status FROM teacher_work_reminders'),[('unconfirmed',)])
        self.client.post(p.location)
        self.assertEqual(len(self.sent),1)

    def test_sms_transport_uncertain_return_blocks_a_new_draft(self):
        self.api['send_sms_delivery']=lambda *args:(False,'Twilio connection failed: timed out')
        p=self.preview(channels=['sms']);self.client.post(p.location)
        p=self.preview(channels=['sms'])
        self.assertEqual(self.client.post(p.location).status_code,409)

    def test_button_and_teacher_lesson_page(self):
        self.assertIn('Send teacher work reminder',self.client.get('/calendar').get_data(as_text=True))
        html=self.client.get('/manager/teacher-work-reminders?teacher_id=1').get_data(as_text=True)
        self.assertIn('Ella Lee',html);self.assertNotIn('Other Student',html)
        self.assertIn('Mobile SMS',html);self.assertIn('Email',html)

if __name__=='__main__':unittest.main()
