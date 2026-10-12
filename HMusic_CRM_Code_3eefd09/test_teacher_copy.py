import ast
from datetime import datetime,timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

class TeacherCopyTest(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:')
  self.db.executescript('''CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name,teacher,lesson_date,lesson_time,classroom,duration,course_type_id,course_type_name,schedule_type,package_type,enrollment_id,student_price,student_charge_amount,teacher_pay_amount,room_id,location_id,location,is_group,status,charge_lessons,policy_waiver_applied,pending_fee_amount,homework_assignment,private_note);
  CREATE TABLE group_schedule_students(id INTEGER PRIMARY KEY,schedule_id,student_name,parent_name,credit_units,student_rate,billing_rule,billing_status,attendance_status,attendance_credit_applied,attendance_enrollment_id);
  INSERT INTO schedule VALUES(1,'A','Mike','2026-10-11','10:00','Piano',45,2,'Private Lesson','weekly','unlimited',8,55,55,30,6,1,'951D',0,'present',1,1,15,'Old homework','Old note');
  INSERT INTO group_schedule_students VALUES(1,1,'A','Parent',0.5,25,'existing_credits','invoiced','present',0.5,8);
  ''')
  row=[None]*30
  for i,v in {0:1,1:'A',2:'Mike',3:'2026-10-11',4:'10:00',5:'Piano',6:'present',10:45,18:0,20:1,21:6,27:'951D'}.items():row[i]=v
  self.owner=False;self.teacher='Mike';self.allowed=True;self.conflict=False;self.locked=False
  self.data=dict(action='duplicate',schedule_id=1,date='2026-10-18',time='11:00')
  conn=SimpleNamespace(cursor=self.db.cursor,commit=self.db.commit,rollback=self.db.rollback,close=Mock())
  self.scope=dict(datetime=datetime,timedelta=timedelta,sqlite3=SimpleNamespace(connect=lambda _:conn),
   ensure_calendar_lesson_panel_schema=lambda:None,require_owner=lambda:self.owner,require_teacher=lambda:True,
   request=SimpleNamespace(get_json=lambda **kw:self.data),session={'teacher_name':self.teacher},
   calendar_lesson_row=lambda *args:row,get_teacher_permissions=lambda _:dict(add_own_schedule=self.allowed),
   TEACHER_PERMISSION_DEFAULTS={'add_own_schedule':1},is_payroll_locked=lambda _:self.locked,
   minutes_from_time_text=lambda t:60 if ':' in t else None,
   schedule_has_conflict=lambda *args,**kw:dict(has_conflict=self.conflict,message='Room occupied'),app=SimpleNamespace(logger=Mock()))
  tree=ast.parse(Path(__file__).with_name('app.py').read_text())
  for name in ('hmusic_name_key','hmusic_teacher_name_matches','hmusic_copy_lesson','calendar_lesson_action'):
   node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);node.decorator_list=[]
   exec(compile(ast.Module(body=[node],type_ignores=[]),'copy-test','exec'),self.scope)
 def tearDown(self):self.db.close()
 def call(self):return self.scope['calendar_lesson_action']()
 def test_teacher_copy_preserves_configuration_resets_attendance(self):
  result=self.call();self.assertTrue(result['ok'])
  r=self.db.execute('SELECT lesson_date,lesson_time,course_type_id,enrollment_id,student_charge_amount,teacher_pay_amount,room_id,status,charge_lessons,policy_waiver_applied,pending_fee_amount,homework_assignment FROM schedule WHERE id=?',(result['new_id'],)).fetchone()
  self.assertEqual(r,('2026-10-18','11:00',2,8,55,30,6,'scheduled',0,0,0,None))
  self.assertEqual(self.db.execute('SELECT status,charge_lessons FROM schedule WHERE id=1').fetchone(),('present',1))
 def test_teacher_cannot_copy_another_teachers_lesson(self):
  self.scope['session']['teacher_name']='Other';self.assertEqual(self.call()[1],403)
 def test_add_schedule_permission_required(self):
  self.allowed=False;self.assertEqual(self.call()[1],403)
 def test_conflict_does_not_create_duplicate(self):
  self.conflict=True;self.assertEqual(self.call()[1],409);self.assertEqual(self.db.execute('SELECT count(*) FROM schedule').fetchone()[0],1)
 def test_locked_payroll_month_rejected(self):
  self.locked=True;self.assertEqual(self.call()[1],400)
 def test_owner_can_still_copy(self):
  self.owner=True;self.allowed=False;self.assertTrue(self.call()['ok'])
 def test_group_roster_copied_without_previous_deductions(self):
  self.db.execute('UPDATE schedule SET is_group=1 WHERE id=1');result=self.call()
  r=self.db.execute('SELECT student_name,credit_units,student_rate,billing_status,attendance_status,attendance_credit_applied,attendance_enrollment_id FROM group_schedule_students WHERE schedule_id=?',(result['new_id'],)).fetchone()
  self.assertEqual(r,('A',0.5,25,'planned','scheduled',0,None))
 def test_invalid_date_rejected(self):
  self.data['date']='bad';self.assertEqual(self.call()[1],400)

if __name__=='__main__':unittest.main()
