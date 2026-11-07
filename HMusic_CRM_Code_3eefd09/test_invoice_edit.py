import ast,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from flask import Flask,request,redirect

class InvoiceEditTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:')
  self.db.executescript('''
  CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,charge_lessons,amount,status,invoice_type,created_at,due_date,payment_methods,coverage_title,coverage_class,coverage_start,coverage_note,subtotal_amount,discount_amount DEFAULT 0);
  INSERT INTO invoices VALUES(169,'Student',20,2170,'unpaid','initial','2026-10-06','2026-10-06','ach,zelle','','','','',2170,0);
  CREATE TABLE student_ledger(id INTEGER PRIMARY KEY,related_invoice_id,related_payment_id,entry_type,amount);
  INSERT INTO student_ledger VALUES(2638,169,NULL,'invoiced_extra_charge',440);
  INSERT INTO student_ledger VALUES(2639,169,NULL,'invoiced_last_min_fee',30);
  INSERT INTO student_ledger VALUES(2640,169,11,'invoice_payment',500);
  INSERT INTO student_ledger VALUES(2641,170,NULL,'invoiced_extra_charge',25);
  CREATE TABLE parent_students(id,parent_id,student_name,active);
  CREATE TABLE parent_profiles(id,parent_name,email,active);
  CREATE TABLE students(name,parent_email);
  CREATE TABLE enrollments(id,lessons_left);
  INSERT INTO enrollments VALUES(208,-21);
  ''')
  db=self.db
  class Conn:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):pass
  self.ns=dict(require_owner=lambda:True,ensure_v321_schema=lambda:None,sqlite3=SimpleNamespace(connect=lambda *a:Conn()),request=request,redirect=redirect,quote=quote)
  tree=ast.parse(Path(__file__).with_name('app.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='edit_invoice');fn.decorator_list=[]
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'invoice-edit','exec'),self.ns);self.app=Flask(__name__)
 def tearDown(self):self.db.close()
 def edit(self,amount='2090'):
  with self.app.test_request_context('/',method='POST',data={'amount':amount,'charge_lessons':'20','due_date':'2026-10-06','payment_methods':['ach','zelle'],'coverage_title':'Package and ensemble','coverage_class':'20 private + 11 ensemble','coverage_note':'20 x 82.50 + 11 x 40','return_to':'/student_ledger/Student'}):return self.ns['edit_invoice'](169)
 def test_invoice_edit_preserves_component_charges_payments_and_credits(self):
  before=self.db.execute('SELECT * FROM student_ledger ORDER BY id').fetchall()
  self.assertEqual(self.edit().location,'/student_ledger/Student')
  self.assertEqual(self.db.execute('SELECT amount,charge_lessons,status,subtotal_amount FROM invoices').fetchone(),(2090,20,'unpaid',2090))
  self.assertEqual(before,self.db.execute('SELECT * FROM student_ledger ORDER BY id').fetchall())
  self.assertEqual(self.db.execute('SELECT lessons_left FROM enrollments').fetchone()[0],-21)
 def test_repeat_save_does_not_replace_440_component_with_2090_total(self):
  self.edit();self.edit();self.assertEqual(self.db.execute('SELECT amount FROM student_ledger WHERE id=2638').fetchone()[0],440)
 def test_edit_preserves_discount_and_updates_gross_subtotal(self):
  self.db.execute('UPDATE invoices SET discount_amount=25')
  self.edit('2000');self.assertEqual(self.db.execute('SELECT amount,subtotal_amount,discount_amount FROM invoices').fetchone(),(2000,2025,25))
 def test_owner_required(self):
  self.ns['require_owner']=lambda:False;self.assertEqual(self.edit().location,'/owner_login');self.assertEqual(self.db.execute('SELECT amount FROM invoices').fetchone()[0],2170)
if __name__=='__main__':unittest.main()
