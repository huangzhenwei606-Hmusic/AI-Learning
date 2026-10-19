"""Exercise the production invoice route using isolated billing data."""
import ast,json,secrets,sqlite3,unittest
from datetime import datetime
from html import escape
from pathlib import Path
from types import SimpleNamespace
from flask import Flask,request,redirect
SOURCE=ast.parse(Path(__file__).with_name('app.py').read_text())
class InvoiceUITest(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:',check_same_thread=False)
  self.db.executescript('''CREATE TABLE invoices(id,student_name,charge_lessons,amount,status,invoice_type,created_at,enrollment_id,due_date,notes,subtotal_amount,discount_code,discount_amount,payment_methods,manual_payment_status,package_options,coverage_title,coverage_class,coverage_start,coverage_note);
CREATE TABLE enrollments(id,auto_renew_enabled,auto_renew_lessons,course_type_name,teacher_name,duration,updated_at);
CREATE TABLE parent_profiles(id,parent_name);
CREATE TABLE invoice_allocations(id,invoice_id,parent_id,amount,status,payment_method,manual_payment_status,lock_token,locked_at,updated_at,stripe_checkout_session_id,stripe_payment_intent_id);
INSERT INTO invoices VALUES(120,'Alaia Huang',10,825,'unpaid','initial_tuition','2026-10-01',148,'2026-10-23','PRIVATE INTERNAL NOTE',825,'',0,'ach,zelle','','','Fall piano package','Private Piano · 45 min','2026-10-24','Your next 10 lessons, beginning October 24.');
INSERT INTO enrollments VALUES(148,0,10,'Private Lesson','Chloe Lu',45,'');
INSERT INTO parent_profiles VALUES(7,'Parent');
INSERT INTO invoice_allocations VALUES(1,120,7,825,'unpaid','','','','','','','');''')
  db=self.db
  class Connection:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def rollback(self):db.rollback()
   def close(self):pass
  self.app=Flask(__name__)
  self.ns=dict(request=request,redirect=redirect,escape=escape,datetime=datetime,json=json,secrets=secrets,session={'parent_id':7,'parent_name':'Parent'},sqlite3=SimpleNamespace(connect=lambda *a:Connection()),require_parent=lambda:True,ensure_v321_schema=lambda:None,ensure_guardian_billing_schema=lambda:None,parent_can_access_student=lambda *a:True,parent_has_student_permission=lambda *a:True,reopen_unsubmitted_stripe_allocation=lambda *a:False,ensure_student_billing_rule=lambda *a:('Alaia Huang','one_payer',7),sync_invoice_allocations=lambda q,*a:q.execute('SELECT id,parent_id,amount,status,payment_method FROM invoice_allocations WHERE invoice_id=120').fetchall(),stripe_is_configured=lambda:True,parent_app_meta=lambda *a:'<meta name="viewport" content="width=device-width,initial-scale=1">',parent_bottom_nav=lambda *a:'<nav class="parent-bottom-nav"><a>Home</a><a>Schedule</a><a>Messages</a><a class="active">Profile</a></nav>',create_invoice_message_event=lambda *a,**k:None)
  for name in ('hmusic_money','hmusic_lesson_count_label','hmusic_invoice_package_options','refresh_invoice_status_from_allocations','parent_invoice'):
   n=next(n for n in SOURCE.body if isinstance(n,ast.FunctionDef) and n.name==name);n.decorator_list=[];exec(compile(ast.Module(body=[n],type_ignores=[]),'app.py','exec'),self.ns)
 def render(self,method='GET',data=None):
  with self.app.test_request_context('/parent_invoice/120',method=method,data=data):return self.ns['parent_invoice'](120)
 def tearDown(self):self.db.close()
 def test_details_and_single_payer(self):
  h=self.render()
  for t in ('Coverage from','Oct 24, 2026','Oct 23, 2026','Chloe Lu','10 lessons × $82.50','Note from H-Music'):self.assertIn(t,h)
  for t in ('PRIVATE INTERNAL NOTE','Payment responsibility','Selected'):self.assertNotIn(t,h)
  self.assertIn('info@h-musicandarts.com',h);self.assertNotIn('hmusicjustplay@gmail.com',h);self.assertLess(h.index('ach-choice'),h.index('zelle-choice'));self.assertIn('Pay $825.00 by bank transfer',h);self.assertIn('name="autopay" value="1"',h);self.assertNotIn('name="autopay" value="1" checked',h)
 def test_escaping_and_missing_fields(self):
  self.db.execute("UPDATE invoices SET coverage_title='<script>x</script>',coverage_note='<img onerror=x>',coverage_start='',due_date=''")
  h=self.render();self.assertIn('&lt;script&gt;',h);self.assertNotIn('<img onerror',h);self.assertNotIn('Coverage from',h);self.assertNotIn('Payment due</dt>',h)
 def test_discount_and_choices(self):
  self.db.execute('UPDATE invoices SET amount=800,discount_amount=25,discount_code=?,package_options=?',('SAVE25',json.dumps([{'lessons':10,'amount':825},{'lessons':20,'amount':1600}])))
  h=self.render();self.assertIn('Discount (SAVE25)',h);self.assertIn('−$25.00',h);self.assertIn('select_package_option',h)
 def test_split_and_unassigned_guardian(self):
  self.db.execute("INSERT INTO invoice_allocations(id,invoice_id,parent_id,amount,status) VALUES(2,120,8,400,'unpaid')")
  self.assertIn('Payment responsibility',self.render());self.ns['session']['parent_id']=9;h=self.render();self.assertIn('assigned to another guardian',h);self.assertNotIn('ach-choice',h)
 def test_permission_and_pending_states(self):
  self.ns['parent_has_student_permission']=lambda p,n,perm:perm!='pay';self.assertNotIn('ach-choice',self.render());self.ns['parent_has_student_permission']=lambda *a:True
  for status in ('paid','processing','pending_confirmation'):
   self.db.execute('UPDATE invoice_allocations SET status=?',(status,));h=self.render();self.assertNotIn('ach-choice',h);self.assertNotIn('value="notify_paid"',h)
  self.assertIn('Awaiting verification',h)
 def test_unavailable_ach_opens_zelle(self):
  self.ns['stripe_is_configured']=lambda:False;h=self.render();self.assertIn('currently unavailable',h);self.assertIn('class="payment-choice zelle-choice" name="payment-method" open',h);self.assertNotIn('/checkout',h)
 def test_zelle_pending_not_paid(self):
  r=self.render('POST',{'action':'notify_paid','payment_method':'Zelle','payment_note':'ref123'});self.assertEqual(r.location,'/parent_invoice/120?payment_notice=sent');self.assertEqual(self.db.execute('SELECT status FROM invoice_allocations').fetchone()[0],'pending_confirmation');self.assertEqual(self.db.execute('SELECT status FROM invoices').fetchone()[0],'pending_confirmation');self.assertEqual(self.db.execute('SELECT amount FROM invoices').fetchone()[0],825);self.assertIn('Awaiting verification',self.render())
 def test_billing_access_denied(self):
  self.ns['parent_has_student_permission']=lambda *a:False;self.assertEqual(self.render()[1],403)
if __name__=='__main__':unittest.main()
