from datetime import date
from pathlib import Path
import sqlite3,tempfile,unittest
from flask import Flask
from owner_dashboard import load_owner_dashboard

class OwnerDashboardTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'preview.db')
  db=sqlite3.connect(self.path);db.executescript('''
  CREATE TABLE students(name,lessons_left,status);
  INSERT INTO students VALUES('Course Student',0,'active'),('Legacy Student',-2,'active'),('Inactive Student',-8,'inactive'),('Archived Account',-5,'active'),('Old Student',0,'active');
  CREATE TABLE enrollments(id,student_name,course_type_name,teacher_name,status,lessons_left);
  INSERT INTO enrollments VALUES(1,'Course Student','Piano','Teacher A','active',5),(2,'Course Student','Group','Teacher A','active',1),(3,'Archived Account','Piano','Teacher B','archived',-1);
  CREATE TABLE schedule(id,student_name,teacher,lesson_date,lesson_time,duration,classroom,status,is_group,group_name);
  INSERT INTO schedule VALUES(1,'Course Student','Teacher A','2026-10-13','10:00',45,'Room 1','present',0,NULL),(2,'Legacy Student','Teacher A','2026-10-13','09:00',30,'Room 2','scheduled',0,NULL),(3,'Inactive Student','Teacher B','2026-10-13','11:00',30,'Room 3','teacher_cancelled',0,NULL),(4,'Archived Account','Teacher B','2026-10-14','11:00',30,'Room 3','scheduled',0,NULL),(5,'Old Student','Teacher A','2026-01-01','12:00',30,'Room 1','present',0,NULL),(6,'Course Student','Teacher A','2026-10-13','14:00',60,'Room 1','scheduled',1,'Ensemble');
  CREATE TABLE group_schedule_students(schedule_id,student_name);
  INSERT INTO group_schedule_students VALUES(6,'A'),(6,'B');
  CREATE TABLE payments(id,student_name,amount,payment_method,payment_date);
  INSERT INTO payments VALUES(1,'Course Student',100,'Zelle','2026-09-13'),(2,'Legacy Student',0.1,'Zelle','2026-10-12'),(3,'Course Student',0.2,'Zelle','2026-10-13');
  CREATE TABLE invoices(status,amount); INSERT INTO invoices VALUES('open',75),('paid',100),('void',50),('draft',30);
  CREATE TABLE reschedule_requests(id,student_name,original_date,requested_date,requested_time,status);INSERT INTO reschedule_requests VALUES(1,'Course Student','2026-10-14','2026-10-15','10:00','pending');
  CREATE TABLE sub_requests(id,student_name,teacher_name,lesson_date,lesson_time,status);INSERT INTO sub_requests VALUES(1,'Old Student','Teacher A','2026-08-14','10:00','pending');
  CREATE TABLE parent_booking_requests(status); CREATE TABLE lesson_change_requests(request_type,status);CREATE TABLE event_room_bookings(status);CREATE TABLE messages(recipient_role,read_at);CREATE TABLE inquiries(status,owner_verified);
  INSERT INTO inquiries VALUES('New Lead',0);
  ''');db.commit();db.close()
  self.homework=[(1,'A','Teacher A','2026-10-12','10:00','Room 1'),(5,'B','Teacher A','2026-01-01','10:00','Room 1')]
 def test_owner_inbox_count_includes_participant_messages(self):
  data=load_owner_dashboard(lambda _:sqlite3.connect(self.path),date(2026,10,13),self.homework,unread_message_count=4)
  self.assertEqual(data['messages'],4)
  self.assertTrue(any(t['kind']=='Message' and t['count']==4 for t in data['tasks']))
 def tearDown(self):self.tmp.cleanup()
 def data(self,selected=None):return load_owner_dashboard(lambda _:sqlite3.connect(self.path),date(2026,10,13),self.homework,selected)
 def test_credits_use_course_account_and_do_not_count_inactive_or_stale_students(self):
  d=self.data();self.assertEqual([(r['student'],r['course']) for r in d['renewals']],[('Legacy Student','Student credits'),('Course Student','Group')]);self.assertEqual(d['renewal_students'],2)
 def test_monthly_payments_exclude_prior_month_and_void_invoices(self):
  d=self.data();self.assertAlmostEqual(d['monthly_payments'],.3);self.assertEqual(d['open_invoice_total'],75);self.assertEqual(d['open_invoice_count'],1)
 def test_schedule_orders_lessons_and_keeps_group_roster_count(self):
  d=self.data();self.assertEqual([r['id'] for r in d['lessons']],[2,1,3,6]);self.assertEqual(d['lesson_count'],3);self.assertEqual(d['present_count'],1);self.assertEqual(d['lessons'][-1]['participants'],2)
 def test_old_pending_sub_requests_and_homework_do_not_enter_current_queue(self):
  d=self.data();self.assertFalse(any(r['kind']=='Substitute' for r in d['tasks']));self.assertEqual(d['homework_recent'],1);self.assertEqual(d['homework_history'],1);self.assertEqual(d['pending_count'],2)
 def test_day_navigation_and_invalid_dates(self):
  self.assertEqual(self.data('2026-10-14')['lesson_count'],1);self.assertEqual(self.data('bad')['day'],'2026-10-13')
 def test_home_is_read_only(self):
  self.data();db=sqlite3.connect(self.path);self.assertEqual(db.execute('SELECT lessons_left FROM students WHERE name=?',('Legacy Student',)).fetchone()[0],-2);db.close()
 def test_template_currency_escaping_and_retained_tools(self):
  app=Flask(__name__,template_folder=str(Path(__file__).with_name('templates')))
  from flask import render_template
  with app.app_context():html=render_template('owner_home.html',**self.data(),display_name='<script>alert(1)</script>')
  self.assertIn('$0.30',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)</script>',html)
  for route in ['/owner_reschedule_requests','/owner_sub_requests','/notification_queue','/teacher_rate_cards','/enrollments']:
   self.assertIn(route,html)

if __name__=='__main__':unittest.main()
