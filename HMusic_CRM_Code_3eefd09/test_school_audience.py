import sqlite3
import unittest
from datetime import date
from werkzeug.datastructures import MultiDict
from school_audience import family_catalog,select_ids,rule_from_form,render_controls

class SchoolAudienceTest(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
  self.db.executescript('''CREATE TABLE students(name,status,active);
   CREATE TABLE parent_profiles(id,parent_name,email,active);
   CREATE TABLE parent_students(parent_id,student_name,active);
   CREATE TABLE schedule(id,student_name,lesson_date,status,teacher,course_type_name);
   CREATE TABLE group_schedule_students(schedule_id,student_name,attendance_status);''')
 def child(self,id,name,status='Active',active=1,parent=None):
  if parent is None:
   parent=id;self.db.execute('INSERT INTO parent_profiles VALUES(?,?,?,1)',(id,'Family '+str(id),f'family{id}@school.test'))
  self.db.execute('INSERT INTO students VALUES(?,?,?)',(name,status,active))
  self.db.execute('INSERT INTO parent_students VALUES(?,?,1)',(parent,name))
 def lesson(self,id,name,day,status='present'):
  self.db.execute("INSERT INTO schedule VALUES(?,?,?,?,'Teacher One','Piano')",(id,name,day,status))
 def catalog(self):return family_catalog(self.db,today=date(2026,11,10))
 def test_four_calendar_month_boundary_paused_new_student_and_missing_history(self):
  for id in range(1,8):self.child(id,'Student '+str(id),'Inactive' if id==4 else 'Active')
  self.lesson(1,'Student 1','2026-07-10');self.lesson(2,'Student 2','2026-07-09')
  self.lesson(3,'Student 3','2026-11-20','scheduled')
  self.lesson(4,'Student 4','2026-11-20','scheduled')
  self.lesson(5,'Student 5','2026-11-01','no_show');self.lesson(6,'Student 6','2026-11-01','excused_24h')
  self.assertEqual({f['id']:f['category'] for f in self.catalog()},{1:'current',2:'past',3:'current',4:'past',5:'review',6:'review',7:'review'})
 def test_sibling_family_current_wins_and_selectors_exclusions_are_unique(self):
  self.child(1,'Old child');self.lesson(1,'Old child','2025-01-01')
  self.child(2,'New child',parent=1);self.lesson(2,'New child','2026-11-20','scheduled')
  self.child(3,'Other child');self.lesson(3,'Other child','2026-11-20','scheduled')
  data=self.catalog();self.assertEqual(len(data),2);self.assertEqual(data[0]['category'],'current')
  rule=rule_from_form(MultiDict([('audience','teacher'),('audience_teachers','Teacher One'),('exclude_ids','3')]))
  self.assertEqual(select_ids(data,rule),[1])
  rule=rule_from_form(MultiDict([('audience','selected'),('parent_ids','1'),('parent_ids','1')]))
  self.assertEqual(select_ids(data,rule),[1])
 def test_group_attendance_overrides_header_but_cancelled_future_is_excluded(self):
  self.child(1,'Group child');self.lesson(1,'Group label','2026-10-10','scheduled')
  self.db.execute("INSERT INTO group_schedule_students VALUES(1,'Group child','present')")
  self.child(2,'Cancelled child');self.lesson(2,'Group label','2026-12-01','teacher_cancelled')
  self.db.execute("INSERT INTO group_schedule_students VALUES(2,'Cancelled child','scheduled')")
  cats={f['id']:f for f in self.catalog()};self.assertEqual(cats[1]['category'],'current');self.assertEqual(cats[2]['category'],'review')
 def test_inactive_account_omitted_and_json_cannot_break_out_of_script(self):
  self.child(1,'</script><img onerror=alert(1)>');self.child(2,'Other')
  self.db.execute('UPDATE parent_profiles SET active=0 WHERE id=2')
  data=self.catalog();self.assertEqual(len(data),1)
  html=render_controls(data);self.assertNotIn('</script><img',html);self.assertIn('\\u003c/script',html)
  self.assertIn('type="checkbox" name="channels" value="email"',html)
 def test_calendar_month_cutoff_clamps_month_end(self):
  self.child(1,'Boundary');self.lesson(1,'Boundary','2026-04-30')
  self.assertEqual(family_catalog(self.db,today=date(2026,8,31))[0]['category'],'current')
