"""Downloads: confirmed ledger state, scoped access and no payment mutations."""
import sqlite3,tempfile,time,hashlib,unittest,ast
from pathlib import Path
from types import SimpleNamespace
from flask import Flask,session,request,redirect
from billing_documents import install_billing_documents,invoice_document,family_document,build_pdf,billing_records
from family_billing import install_family_billing,ensure_schema
from quick_pay import install_quick_pay,ensure_schema as quick_schema

class BillingDocumentsTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.permission=True
  self.app=Flask(__name__);self.app.secret_key='test';self.app.testing=True
  self.api=dict(sqlite3=SimpleNamespace(connect=self.connect),ensure_v321_schema=lambda:None,ensure_guardian_billing_schema=lambda:None,require_parent=lambda:bool(session.get('parent_id')),require_owner=lambda:bool(session.get('owner')),parent_can_access_student=lambda p,s:self.permission and p==1,parent_has_student_permission=lambda p,s,k:self.permission and p==1,configure_stripe=lambda:False)
  with self.connect() as c:
   c.executescript('''CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,charge_lessons,amount,status,created_at,due_date,coverage_title,coverage_class,coverage_start,coverage_note,enrollment_id,invoice_type,credits_applied DEFAULT 0);
CREATE TABLE parent_billing_profiles(parent_id,autopay_enabled,ach_enabled,status,updated_at);
CREATE TABLE enrollments(id INTEGER PRIMARY KEY,course_type_name,teacher_name,duration);
CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name,email,active);
CREATE TABLE invoice_allocations(id INTEGER PRIMARY KEY,invoice_id,parent_id,amount,status,payment_method,paid_at,lock_token,stripe_checkout_session_id);
INSERT INTO enrollments VALUES(1,'Private Piano','Ms. Chen',30);
INSERT INTO parent_profiles VALUES(1,'Alex Chen','test@example.invalid',1),(2,'Other guardian','other@example.invalid',1);
INSERT INTO invoices VALUES(240,'Mia Chen',10,550,'unpaid','2026-10-20','2026-10-28','Fall piano package','','2026-10-28','Weekly private piano.',1,'tuition',0);
INSERT INTO invoices SELECT 241,'Leo Chen',10,525,'unpaid',created_at,due_date,coverage_title,coverage_class,coverage_start,coverage_note,1,'tuition',0 FROM invoices WHERE id=240;
INSERT INTO invoice_allocations VALUES(1,240,1,400,'unpaid','','',NULL,NULL),(2,240,2,150,'paid','Zelle','2026-10-27',NULL,NULL),(3,241,1,525,'unpaid','','',NULL,NULL);''')
   ensure_schema(c.cursor());quick_schema(c.cursor())
   c.execute("INSERT INTO family_payments(id,parent_id,request_key,method,status,total_cents,created_at) VALUES(1,1,'test','Stripe ACH','submitted',92500,'2026-10-28')")
   c.execute("INSERT INTO family_payment_items(family_payment_id,allocation_id,invoice_id,student_name,enrollment_id,lessons,amount_cents,course_name,teacher_name) VALUES(1,1,240,'Mia Chen',1,10,40000,'Private Piano','Ms. Chen'),(1,3,241,'Leo Chen',1,10,52500,'Private Piano','Ms. Chen')")
  install_family_billing(self.app,self.api);install_quick_pay(self.app,self.api);install_billing_documents(self.app,self.api);self.client=self.app.test_client()
  self.ns=dict(self.api,request=request,redirect=redirect,session=session,ensure_billing_schema=lambda:None,stripe_is_configured=lambda:True,parent_app_meta=lambda *a:'',parent_bottom_nav=lambda *a:'')
  node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='parent_billing');node.decorator_list=[]
  exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.ns)
  self.app.add_url_rule('/parent_billing','parent_billing',self.ns['parent_billing'])
  with self.client.session_transaction() as s:s['parent_id']=1
 def connect(self,*a):return sqlite3.connect(self.path)
 def tearDown(self):self.tmp.cleanup()
 def paid(self):
  with self.connect() as c:
   c.execute("UPDATE invoice_allocations SET status='paid',payment_method='Stripe ACH',paid_at='2026-10-28' WHERE parent_id=1");c.execute("UPDATE family_payments SET status='paid',paid_at='2026-10-28'")
 def test_pdf_requires_confirmed_payment(self):
  self.assertEqual(self.client.get('/parent_invoice/240/invoice.pdf').status_code,200)
  self.assertEqual(self.client.get('/parent_invoice/240/receipt.pdf').status_code,409)
  with self.connect() as c:c.execute("UPDATE invoice_allocations SET status='processing' WHERE id=1")
  self.assertEqual(self.client.get('/parent_invoice/240/receipt.pdf').status_code,409)
  self.paid();r=self.client.get('/parent_invoice/240/receipt.pdf');self.assertEqual(r.status_code,200);self.assertTrue(r.data.startswith(b'%PDF'));self.assertIn('no-store',r.headers['Cache-Control'])
 def test_logged_out_wrong_parent_revoked_permission(self):
  with self.client.session_transaction() as s:s.clear()
  self.assertEqual(self.client.get('/parent_invoice/240/invoice.pdf').status_code,302)
  with self.client.session_transaction() as s:s['parent_id']=99
  self.assertEqual(self.client.get('/parent_invoice/240/invoice.pdf').status_code,403)
  with self.client.session_transaction() as s:s['parent_id']=1
  self.permission=False;self.assertEqual(self.client.get('/family_payment/1/invoice.pdf').status_code,403)
 def test_split_discloses_only_own_amount(self):
  with self.connect() as c:doc=invoice_document(c.cursor(),240,1)
  self.assertEqual(str(doc['total']),'400.00');self.assertTrue(doc['share']);self.assertNotIn('Other guardian',str(doc));self.assertNotIn('150.00',str(doc))
 def test_family_guest_scope_expiry(self):
  digest=hashlib.sha256(b'secret').hexdigest()
  with self.connect() as c:c.execute('INSERT INTO family_payment_links(token_hash,batch_id,expires_at) VALUES(?,?,?)',(digest,1,int(time.time())+1000))
  with self.client.session_transaction() as s:s.clear();s['family_guest_grant']=digest
  self.assertEqual(self.client.get('/family_payment/1/invoice.pdf').status_code,200);self.assertEqual(self.client.get('/family_payment/1/receipt.pdf').status_code,409);self.assertEqual(self.client.get('/parent_invoice/240/invoice.pdf').status_code,302)
  self.paid();self.assertEqual(self.client.get('/family_payment/1/receipt.pdf').status_code,200)
  with self.connect() as c:c.execute('UPDATE family_payment_links SET expires_at=0')
  self.assertEqual(self.client.get('/family_payment/1/invoice.pdf').status_code,403)
 def test_family_total_partial_payment(self):
  self.paid()
  with self.connect() as c:
   doc=family_document(c.cursor(),1);self.assertEqual(str(doc['total']),'925.00');self.assertEqual(len(doc['lines']),2);self.assertEqual(doc['lines'][0]['teacher'],'Ms. Chen');c.execute("UPDATE invoice_allocations SET status='processing' WHERE id=3")
  self.assertEqual(self.client.get('/family_payment/1/receipt.pdf').status_code,409)
 def test_read_only_and_no_pending_receipt_link(self):
  with self.connect() as c:
   before=c.execute('SELECT * FROM invoice_allocations').fetchall();html=billing_records(c.cursor(),1,self.api);self.assertIn('Download Invoice',html);self.assertNotIn('Download Receipt',html)
  self.client.get('/parent_invoice/240/invoice.pdf');self.client.get('/family_payment/1/invoice.pdf')
  with self.connect() as c:self.assertEqual(c.execute('SELECT * FROM invoice_allocations').fetchall(),before)
 def test_pdf_long_unicode(self):
  self.paid()
  with self.connect() as c:doc=family_document(c.cursor(),1)
  doc['payer']='家长 Chen';doc['lines']*=15;doc['lines'][0]['note']='Long course details and <unsafe> & notes. '*45
  self.assertTrue(build_pdf(doc,'receipt').startswith(b'%PDF'))
 def test_hidden_invoice_invalid_kind(self):
  self.assertEqual(self.client.get('/parent_invoice/240/anything.pdf').status_code,404)
  with self.connect() as c:c.execute("UPDATE invoices SET status='pending_owner_approval' WHERE id=240")
  self.assertEqual(self.client.get('/parent_invoice/240/invoice.pdf').status_code,404)

 def test_billing_page_downloads_and_brand(self):
  r=self.client.get('/parent_billing');self.assertEqual(r.status_code,200);self.assertIn(b'Invoices & receipts',r.data);self.assertIn(b'hmusic-icon.png',r.data);self.assertNotIn(b'Download Receipt',r.data)
  self.paid();r=self.client.get('/parent_billing');self.assertIn(b'Download Receipt',r.data)
 def test_card_surcharge_itemized_across_parent_downloads(self):
  self.paid()
  with self.connect() as c:
   c.execute("INSERT INTO quick_payment_links(token_hash,invoice_id,parent_id,allocation_id,amount_cents,expires_at,invoice_snapshot,status,method,fee_cents) VALUES('fee',240,1,1,40000,0,'snapshot','paid','card',1200)")
   doc=invoice_document(c.cursor(),240,1)
  self.assertEqual(str(doc['total']),'412.00');self.assertEqual(str(doc['lines'][-1]['amount']),'12.00')

class QuickDocumentTest(unittest.TestCase):
 def setUp(self):
  from test_quick_pay import QuickPayTest
  self.q=QuickPayTest();self.q.setUp()
  with self.q.connect() as c:c.execute("ALTER TABLE invoices ADD COLUMN created_at TEXT DEFAULT '2026-10-28'")
 def tearDown(self):self.q.tearDown()
 def test_guest_invoice_receipt_and_revocation(self):
  t=self.q.make_link();client=self.q.client
  self.assertEqual(client.get('/p/'+t+'/invoice.pdf').status_code,200)
  self.assertEqual(client.get('/p/'+t+'/receipt.pdf').status_code,409)
  with self.q.connect() as c:c.execute("UPDATE invoice_allocations SET status='paid',paid_at='2026-10-28',payment_method='Zelle'")
  self.assertEqual(client.get('/p/'+t+'/receipt.pdf').status_code,200)
  with self.q.connect() as c:c.execute('UPDATE quick_payment_links SET revoked=1')
  self.assertEqual(client.get('/p/'+t+'/receipt.pdf').status_code,404)
 def test_guest_permission_expiry_snapshot(self):
  t=self.q.make_link();self.q.permission=False
  self.assertEqual(self.q.client.get('/p/'+t+'/invoice.pdf').status_code,404)
  self.q.permission=True
  with self.q.connect() as c:c.execute("UPDATE invoices SET coverage_note='changed'")
  self.assertEqual(self.q.client.get('/p/'+t+'/invoice.pdf').status_code,409)
  with self.q.connect() as c:c.execute('UPDATE quick_payment_links SET expires_at=0')
  self.assertEqual(self.q.client.get('/p/'+t+'/invoice.pdf').status_code,404)

if __name__=='__main__':unittest.main()
