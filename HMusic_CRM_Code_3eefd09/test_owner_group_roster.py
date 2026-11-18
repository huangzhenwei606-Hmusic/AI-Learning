import ast
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from flask import Flask,session
from owner_group_roster import register_owner_group_roster

class OwnerGroupRosterTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=str(Path(self.tmp.name)/'db')
  with sqlite3.connect(self.path) as c:
   c.executescript('''CREATE TABLE students(name,parent_name);
    INSERT INTO students VALUES('A','Parent A'),('B','Parent B'),('C','Parent C'),('New child','New parent');
    CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name,teacher,lesson_date,lesson_time,classroom,status,course_type_name,schedule_type,package_type,duration,is_group,group_name,group_size,group_student_names,owner_calendar_updated_at,student_charge_amount,billing_decision);
    INSERT INTO schedule VALUES(1,'A','Teacher','2026-11-20','18:30','Room','present','Choir','weekly','unlimited',75,1,'Choir',2,'A, B','before',35,'existing_credits'),
    (2,'A','Teacher','2026-11-27','18:30','Room','scheduled','Choir','weekly','unlimited',75,1,'Choir',3,'A, B, C','before',35,'existing_credits'),
    (3,'A','Teacher','2026-11-13','18:30','Room','present','Choir','weekly','unlimited',75,1,'Choir',2,'A, B','before',35,'existing_credits'),
    (4,'A','Teacher','2026-12-04','18:30','Room','scheduled','Choir','weekly','unlimited',75,1,'Other choir',2,'A, B','before',35,'existing_credits'),
    (5,'A','Teacher','2026-11-20','19:30','Room','scheduled','Piano','weekly','unlimited',30,0,'',1,'','before',35,'existing_credits');
    ALTER TABLE schedule ADD COLUMN location TEXT DEFAULT '';
    UPDATE schedule SET student_name='C' WHERE id=2;
    CREATE TABLE group_schedule_students(id INTEGER PRIMARY KEY,schedule_id,student_name,parent_name,credit_units,student_rate,billing_rule,billing_status,attendance_status,created_at,updated_at,attendance_credit_applied DEFAULT 0,attendance_enrollment_id);
    INSERT INTO group_schedule_students(schedule_id,student_name,parent_name,credit_units,student_rate,billing_rule,billing_status,attendance_status,attendance_credit_applied) VALUES
    (1,'A','Parent A',1,35,'existing_credits','deduct_from_package','present',1),(1,'B','Parent B',1,35,'existing_credits','deduct_from_package','no_show',1),
    (2,'A','Parent A',1,35,'existing_credits','planned','scheduled',0),(2,'B','Parent B',1,35,'existing_credits','planned','scheduled',0),(2,'C','Parent C',1,25,'no_charge','no_charge','scheduled',0);''')
  self.credits=[]
  def row(cur,sid):
   cur.execute('SELECT id,student_name,teacher,lesson_date,lesson_time,classroom,status,course_type_name,schedule_type,package_type,duration,is_group,group_name,group_student_names FROM schedule WHERE id=?',(sid,));r=cur.fetchone()
   if not r:return None
   result=list(r[:11])+[0]*19;result[27]='';result[18]=r[11];result[28]=r[12];result[29]=r[13];return result
  scope=dict(datetime=datetime,hmusic_clean_student_picker_value=lambda n:n.split(' · ')[0].strip(),hmusic_name_key=lambda n:str(n or '').strip().casefold(),calendar_lesson_row=row,CALENDAR_GROUP_ATTENDANCE_STATUSES={'scheduled','present','no_show'},hmusic_apply_group_attendance_credit=lambda cur,sid,name,status:self.credits.append((sid,name,status)))
  tree=ast.parse(Path(__file__).with_name('app.py').read_text())
  for name in ['calendar_group_roster','sync_calendar_group_roster','calendar_following_lesson_ids']:
   fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
   exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),scope)
  api=dict(scope,sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),require_owner=lambda:session.get('owner',False),ensure_calendar_lesson_panel_schema=lambda:None)
  self.app=Flask(__name__);self.app.secret_key='test';self.app.testing=True
  register_owner_group_roster(self.app,api);self.client=self.app.test_client()
  with self.client.session_transaction() as s:s['owner']=True
 def add(self,scope='once',name='New child',sid=1):return self.client.post(f'/api/calendar-group-roster/{sid}/add',json=dict(student_name=name,scope=scope))
 def names(self,sid):
  with sqlite3.connect(self.path) as c:return [r[0] for r in c.execute('SELECT student_name FROM group_schedule_students WHERE schedule_id=? ORDER BY student_name',(sid,))]
 def test_once_is_idempotent_and_preserves_attendance_and_credit_flags(self):
  self.assertEqual(self.add().json['updated'],1);self.assertEqual(self.add().json['updated'],0)
  self.assertEqual(self.names(1),['A','B','New child']);self.assertEqual(self.names(2),['A','B','C'])
  self.assertEqual(self.credits,[(1,'New child','scheduled')])
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT student_name,attendance_status,attendance_credit_applied FROM group_schedule_students WHERE schedule_id=1 ORDER BY student_name').fetchall(),[('A','present',1),('B','no_show',1),('New child','scheduled',0)])
 def test_following_keeps_each_roster_and_excludes_past_and_other_class(self):
  self.assertEqual(self.add('following').json['updated'],2)
  self.assertEqual(self.names(2),['A','B','C','New child']);self.assertEqual(self.names(3),[]);self.assertEqual(self.names(4),[])
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute("SELECT student_rate,billing_rule FROM group_schedule_students WHERE student_name='C'").fetchone(),(25,'no_charge'))
 def test_unknown_invalid_scope_private_and_unauthorized_do_not_write(self):
  for response in [self.add(name='Missing'),self.add(scope='all'),self.add(sid=5)]:self.assertEqual(response.status_code,400)
  with self.client.session_transaction() as s:s['owner']=False
  self.assertEqual(self.add().status_code,403);self.assertEqual(self.names(1),['A','B']);self.assertEqual(self.credits,[])
 def test_failure_on_later_lesson_rolls_back_earlier_addition(self):
  with sqlite3.connect(self.path) as c:c.execute("UPDATE group_schedule_students SET student_name='Missing' WHERE schedule_id=2 AND student_name='C'")
  self.assertEqual(self.add('following').status_code,400);self.assertEqual(self.names(1),['A','B'])
