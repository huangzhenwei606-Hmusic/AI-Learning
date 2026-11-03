import re,sqlite3,unittest
from types import SimpleNamespace
from flask import Flask
from custom_invoices import register_custom_invoices
from test_family_billing import FamilyBillingTests

class CustomInvoiceTests(unittest.TestCase):
 tearDown=FamilyBillingTests.tearDown
 balances=FamilyBillingTests.balances
 create=FamilyBillingTests.create
 settle=FamilyBillingTests.settle
 def setUp(self):
  FamilyBillingTests.setUp(self)
  self.conn.executescript("CREATE TABLE students(name TEXT PRIMARY KEY); INSERT INTO students VALUES('Seth'),('Valerie'),('Unrelated'); CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name TEXT); INSERT INTO parent_profiles VALUES(1,'Test Parent');")
  for col in ('schedule_id INTEGER','created_at TEXT','due_date TEXT','notes TEXT','subtotal_amount REAL','discount_amount REAL','payment_methods TEXT','package_options TEXT','coverage_title TEXT','coverage_class TEXT','coverage_start TEXT','coverage_note TEXT'):
   self.conn.execute('ALTER TABLE invoices ADD COLUMN '+col)
  self.conn.execute("ALTER TABLE enrollments ADD COLUMN status TEXT DEFAULT 'active'")
  self.conn.execute('ALTER TABLE enrollments ADD COLUMN duration INTEGER DEFAULT 30');self.conn.commit();self.owner=True
  def sync(cur,iid,student,amount,status):
   cur.execute("INSERT INTO invoice_allocations(invoice_id,parent_id,amount,status) VALUES(?,1,?,'unpaid')",(iid,amount))
  api=dict(require_owner=lambda:self.owner,ensure_v321_schema=lambda:None,ensure_guardian_billing_schema=lambda:None,sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),sync_invoice_allocations=sync,hmusic_csrf_token=lambda:'test')
  self.app=Flask(__name__);self.app.secret_key='test';self.app.testing=True;register_custom_invoices(self.app,api);self.client=self.app.test_client();self.url='/owner/family/1/custom-invoice'
 def form(self,**changes):
  page=self.client.get(self.url);self.assertEqual(page.status_code,200)
  data=dict(student_name='Seth',kind='custom',title='Materials <fee>',description='Book and lesson details',amount='82.50',credits='0',enrollment_id='',due_date='2026-11-07',action='preview',request_key=re.search(r'name="request_key" value="([^"]+)"',page.text)[1]);data.update(changes);return data
 def newest(self):
  return self.conn.execute('SELECT id,charge_lessons,amount,status,invoice_type,enrollment_id,credits_applied FROM invoices ORDER BY id DESC').fetchone()
 def test_fee_only_and_repeat(self):
  data=self.form();r=self.client.post(self.url,data=data);self.assertEqual(r.status_code,302,r.text)
  inv=self.newest();self.assertEqual(inv[1:],(0,82.5,'unpaid','custom_invoice',None,0));self.assertEqual(r.location,f'/owner/invoice/{inv[0]}/quick-pay');self.assertEqual(self.balances(),[-3,-3,-1,8])
  aid=self.conn.execute('SELECT id FROM invoice_allocations WHERE invoice_id=?',(inv[0],)).fetchone()[0]
  for _ in range(2):self.api['record_invoice_allocation_paid'](self.conn.cursor(),aid,'Zelle');self.conn.commit()
  self.assertEqual(self.balances(),[-3,-3,-1,8]);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1);self.assertEqual(self.client.post(self.url,data=data).status_code,400)
 def test_fractional_credit_only_after_all_shares_pay(self):
  r=self.client.post(self.url,data=self.form(kind='makeup',enrollment_id='1',credits='.5'));self.assertEqual(r.status_code,302,r.text);iid=self.newest()[0];self.assertEqual(self.balances()[0],-3)
  self.conn.execute('UPDATE invoice_allocations SET amount=40 WHERE invoice_id=?',(iid,));self.conn.execute("INSERT INTO invoice_allocations(invoice_id,parent_id,amount,status) VALUES(?,2,42.5,'unpaid')",(iid,));ids=[r[0] for r in self.conn.execute('SELECT id FROM invoice_allocations WHERE invoice_id=?',(iid,))];self.conn.commit()
  self.api['record_invoice_allocation_paid'](self.conn.cursor(),ids[0],'Stripe ACH');self.conn.commit();self.assertEqual(self.balances()[0],-3)
  for _ in range(2):self.api['record_invoice_allocation_paid'](self.conn.cursor(),ids[1],'Stripe ACH');self.conn.commit()
  self.assertEqual(self.balances()[0],-2.5)
 def test_draft_has_no_payment_or_credit(self):
  r=self.client.post(self.url,data=self.form(action='draft',enrollment_id='1',credits='2'));self.assertEqual(r.status_code,302,r.text);inv=self.newest();self.assertEqual(inv[3],'pending_owner_approval');self.assertEqual(r.location,f'/review_invoice_notice/{inv[0]}');self.assertEqual(self.balances()[0],-3);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
 def test_invalid_inputs_and_access(self):
  for changes in (dict(credits='-1'),dict(credits='nan'),dict(credits='.3'),dict(amount='Infinity'),dict(amount='0'),dict(amount='1.001'),dict(credits='1'),dict(student_name='Unrelated'),dict(credits='1',enrollment_id='2'),dict(enrollment_id='4')):
   with self.subTest(changes=changes):self.assertEqual(self.client.post(self.url,data=self.form(**changes)).status_code,400)
  self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],3);self.owner=False;self.assertEqual(self.client.get(self.url).location,'/owner_login')
 def test_combined_custom_invoice(self):
  r=self.client.post(self.url,data=self.form(enrollment_id='1',credits='2'));self.assertEqual(r.status_code,302,r.text);iid=self.newest()[0];aid=self.conn.execute('SELECT id FROM invoice_allocations WHERE invoice_id=?',(iid,)).fetchone()[0];bid=self.create(ids=(aid,2),key='custom',method='Stripe ACH');self.settle(bid,method='Stripe ACH',amount=58250);self.assertEqual(self.balances()[0],-1);self.settle(bid,method='Stripe ACH',amount=58250);self.assertEqual(self.balances()[0],-1)

 def test_duplicate_request_key_cannot_create_a_second_invoice(self):
  data=self.form();self.assertEqual(self.client.post(self.url,data=data).status_code,302)
  with self.client.session_transaction() as session:
   session['custom_invoice_key_1']=data['request_key']
  self.assertEqual(self.client.post(self.url,data=data).status_code,302)
  self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],4)
 def test_fee_only_can_be_combined_without_course(self):
  self.client.post(self.url,data=self.form());iid=self.newest()[0];aid=self.conn.execute('SELECT id FROM invoice_allocations WHERE invoice_id=?',(iid,)).fetchone()[0]
  bid=self.create(ids=(aid,2),key='fee');self.settle(bid,amount=58250)
  self.assertEqual(self.balances()[0],-3)

class CustomGuestCheckoutTests(unittest.TestCase):
 def test_guest_ach_custom_credit_and_fee_only(self):
  import ast
  from pathlib import Path
  from test_quick_pay import QuickPayTest
  for credits in (0,0.5):
   with self.subTest(credits=credits):
    q=QuickPayTest();q.setUp()
    try:
     node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='invoice_credit_to_grant')
     exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),q.api)
     with q.connect() as c:c.execute("UPDATE invoices SET invoice_type='custom_invoice',charge_lessons=?",(credits,))
     token=q.make_link();self.assertEqual(q.checkout(token,'ach').status_code,303)
     obj=next(iter(q.provider.objects.values()));obj['status']='complete'
     q.api['handle_quick_pay_event'](dict(type='checkout.session.completed',data={'object':obj}))
     with q.connect() as c:self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],0)
     self.assertEqual(q.paid(),('ok',200));self.assertEqual(q.paid(),('ok',200))
     with q.connect() as c:
      self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],credits)
      self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1)
    finally:q.tearDown()
