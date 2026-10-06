import ast,sqlite3,unittest
from pathlib import Path
from datetime import datetime,date
from types import SimpleNamespace
from flask import Flask,request
from html import escape
SOURCE=Path(__file__).with_name('app.py').read_text()
class ApprovalTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript('''CREATE TABLE enrollments(id INTEGER,student_name,course_type_name,final_price,package_amount,package_lessons,auto_renew_lessons,lessons_left,renewal_reminder_sent_at,auto_renew_enabled,updated_at);INSERT INTO enrollments VALUES(1,'Student','Piano',60,600,10,10,0,NULL,1,NULL);CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,schedule_id,charge_lessons,amount,status,invoice_type,created_at,enrollment_id,due_date,notes,credits_applied);''');self.sent=[]
  self.ns={'datetime':datetime,'date':date,'hmusic_attach_pending_invoice_charges':lambda *a:None}
  for name in ['create_enrollment_invoice','maybe_handle_enrollment_renewal']:
   f=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name==name);f.decorator_list=[];exec(compile(ast.Module(body=[f],type_ignores=[]),'app.py','exec'),self.ns)
 def tearDown(self):
  self.db.close()
 def test_auto_generation_is_draft_no_credits_and_deduplicated(self):
  fn=self.ns['maybe_handle_enrollment_renewal'];cur=self.db.cursor();events=fn(cur,1,'Student');self.assertEqual(len(events),1);self.assertNotIn('parent_id',events[0]);self.assertEqual(cur.execute('SELECT status,credits_applied FROM invoices').fetchone(),('pending_owner_approval',0));self.assertEqual(cur.execute('SELECT lessons_left FROM enrollments').fetchone()[0],0);self.assertEqual(fn(cur,1,'Student'),[]);self.assertEqual(cur.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
 def test_auto_disabled_still_requires_owner_for_reminder(self):
  self.db.execute('UPDATE enrollments SET auto_renew_enabled=0');events=self.ns['maybe_handle_enrollment_renewal'](self.db.cursor(),1,'Student');self.assertEqual(len(events),1);self.assertNotIn('parent_id',events[0]);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],0)
 def test_review_get_does_not_publish_post_does(self):
  self.ns['maybe_handle_enrollment_renewal'](self.db.cursor(),1,'Student');self.db.commit()
  db=self.db
  class Connection:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):pass
  self.ns.update(sqlite3=SimpleNamespace(connect=lambda *a:Connection()),require_owner=lambda:True,ensure_v321_schema=lambda:None,get_primary_parent_for_student=lambda *a:9,request=request,redirect=lambda p:p,escape=escape,hmusic_money=lambda x:f'{x:.2f}',notify_parent_tuition_due=lambda *a,**kw:self.sent.append((a,kw)))
  f=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='review_invoice_notice');f.decorator_list=[];exec(compile(ast.Module(body=[f],type_ignores=[]),'app.py','exec'),self.ns)
  app=Flask(__name__)
  with app.test_request_context('/',method='GET'):self.assertIn('Confirm and send',self.ns['review_invoice_notice'](1))
  self.assertEqual(self.sent,[]);self.assertEqual(db.execute('SELECT status FROM invoices').fetchone()[0],'pending_owner_approval')
  with app.test_request_context('/',method='POST'):self.ns['review_invoice_notice'](1)
  self.assertEqual(db.execute('SELECT status FROM invoices').fetchone()[0],'unpaid');self.assertTrue(self.sent[0][1]['owner_approved'])
 def test_parent_access_filters_drafts(self):
  tree=ast.parse(SOURCE)
  for name in ['parent_dashboard','parent_profile','parent_invoice','stripe_invoice_checkout','square_invoice_checkout']:
   f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);self.assertIn('pending_owner_approval',ast.get_source_segment(SOURCE,f))
if __name__=='__main__':unittest.main()
