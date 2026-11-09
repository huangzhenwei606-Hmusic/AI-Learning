import ast
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
from flask import jsonify,request,session,redirect
import test_teacher_work_reminders as base
from teacher_schedule_changes import register_teacher_schedule_changes

class TeacherScheduleChangesTest(base.TeacherWorkRemindersTest):
    def setUp(self):
        super().setUp()
        register_teacher_schedule_changes(self.app,self.api)
        self.change=self.app.extensions['teacher_schedule_changes']
        self.notices=[]
        self.sql('ALTER TABLE schedule ADD COLUMN weekday TEXT')
        self.original=self.sql('SELECT * FROM schedule')
        ns=dict(app=self.app,request=request,datetime=datetime,timedelta=timedelta,
            sqlite3=self.api['sqlite3'],require_owner=self.api['require_owner'],require_teacher=lambda:False,
            get_or_create_message_thread=lambda *a,**k:1,add_message=lambda *a,**k:None,
            create_notification=lambda *a,**k:self.notices.append((a,k)))
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reschedule_schedule')
        exec(compile(ast.Module(body=[f],type_ignores=[]),'app.py','exec'),ns)

        @self.app.post('/test/create')
        def create():
            db=self.api['sqlite3'].connect('hmusic.db');cur=db.cursor()
            cur.execute('INSERT INTO schedule(student_name,teacher,lesson_date,lesson_time,duration,location,classroom,status,course_type_name,is_group) VALUES(?,?,?,?,?,?,?,?,?,?)',('New Student','Jenny Lee',self.day,'18:00',30,'1101','Room 2','scheduled','Piano',0))
            sid=cur.lastrowid
            self.change['record'](cur,{},[sid])
            if request.form.get('fail'):
                db.rollback();db.close();return jsonify(ok=False),400
            db.commit();db.close()
            return redirect('/calendar') if request.form.get('redirect') else jsonify(ok=True)

        @self.app.post('/test/update')
        def update():
            db=self.api['sqlite3'].connect('hmusic.db');cur=db.cursor();before=self.change['capture'](cur,[1])
            cur.execute('UPDATE schedule SET lesson_time=? WHERE id=1',(request.form.get('time','16:00'),))
            self.change['record'](cur,before);db.commit();db.close();return jsonify(ok=True)

    def saved_url(self,response):
        self.assertTrue(response.json['ok']);return response.json['teacher_work_reminders'][0]

    def draft(self):
        return json.loads(self.sql('SELECT previews FROM teacher_schedule_change_batches ORDER BY created_at DESC LIMIT 1')[0][0])[0]['token']

    def test_real_drag_route_captures_old_time_and_defers_teacher_delivery(self):
        new_day=(datetime.strptime(self.day,'%Y-%m-%d')+timedelta(days=1)).date().isoformat()
        r=self.client.post('/reschedule_schedule',json={'schedule_id':1,'new_date':new_day,'old_date':'1999-01-01','old_time':'01:00'})
        url=self.saved_url(r);self.assertEqual(self.sent,[])
        self.assertTrue(self.notices)
        for _,kwargs in self.notices:
            self.assertFalse(kwargs['queue_delivery']);self.assertFalse(kwargs['send_email_now'])
        html=self.client.get(url).get_data(as_text=True)
        self.assertIn('Previous time:',html);self.assertIn('New time:',html)
        self.assertNotIn('1999',html);self.assertNotIn('name="old_time"',html)
        self.assertIn('04:00 PM',html);self.assertEqual(self.sent,[])
        token=self.draft();self.client.post(url,data={'channels_'+token:['sms']})
        self.assertEqual([s[0] for s in self.sent],['sms'])
        self.assertIn('Previous time:',self.sent[0][1][2])
        self.client.post(url,data={'channels_'+token:['sms']});self.assertEqual(len(self.sent),1)

    def test_time_update_uses_database_original_and_requires_confirmation(self):
        url=self.saved_url(self.client.post('/test/update',data={'time':'18:00','old_time':'01:00'}))
        html=self.client.get(url).get_data(as_text=True)
        self.assertIn('04:00 PM',html);self.assertIn('06:00 PM',html);self.assertNotIn('01:00 AM',html)
        self.assertEqual(self.sent,[])

    def test_new_lesson_popup_and_cancel_do_not_send(self):
        url=self.saved_url(self.client.post('/test/create'))
        html=self.client.get(url).get_data(as_text=True)
        self.assertIn('New Student',html);self.assertIn('New lesson:',html);self.assertNotIn('Previous time:',html)
        self.assertIn('Not now',html);self.assertEqual(self.sent,[])

    def test_noop_save_and_failed_save_do_not_offer_reminders(self):
        r=self.client.post('/test/update',data={'time':'16:00'});self.assertNotIn('teacher_work_reminders',r.json)
        r=self.client.post('/test/create',data={'fail':'1'});self.assertEqual(r.status_code,400)
        self.assertNotIn('teacher_work_reminders',r.json);self.assertEqual(self.sql('SELECT COUNT(*) FROM schedule'),[(2,)])
        self.assertEqual(self.sent,[])

    def test_redirect_save_opens_once_and_uses_saved_changes(self):
        r=self.client.post('/test/create',data={'redirect':'1'});self.assertEqual(r.status_code,302)
        html=self.client.get('/calendar').get_data(as_text=True)
        self.assertIn('HMusicTeacherWorkReminderPrompt([',html)
        self.assertNotIn('HMusicTeacherWorkReminderPrompt([',self.client.get('/calendar').get_data(as_text=True))
        self.assertEqual(self.sent,[])

    def test_later_edit_invalidates_the_earlier_saved_popup(self):
        url=self.saved_url(self.client.post('/test/update',data={'time':'18:00'}))
        self.sql("UPDATE schedule SET lesson_time='19:00' WHERE id=1")
        self.assertEqual(self.client.get(url).status_code,409);self.assertEqual(self.sent,[])

    def test_current_contacts_change_blocks_confirmation(self):
        url=self.saved_url(self.client.post('/test/create'));self.client.get(url);token=self.draft()
        self.sql("UPDATE teachers SET phone='+16505550199' WHERE id=1")
        self.assertEqual(self.client.post(url,data={'channels_'+token:['sms']}).status_code,409)
        self.assertEqual(self.sent,[])

    def test_save_while_logged_in_as_teacher_does_not_get_manager_popup(self):
        with self.client.session_transaction() as s:s['role']='teacher'
        r=self.client.post('/test/update',data={'time':'18:00'});self.assertNotIn('teacher_work_reminders',r.json)
        self.assertEqual(self.sent,[])

if __name__=='__main__':
    import unittest
    unittest.main()
