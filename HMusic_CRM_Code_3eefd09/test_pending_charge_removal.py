import ast,sqlite3,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from flask import Flask,request,redirect
class RemovalTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript("CREATE TABLE enrollments(id,student_name);INSERT INTO enrollments VALUES(1,'Abir'),(2,'Other');CREATE TABLE student_ledger(id,student_name,entry_type,amount,description,related_invoice_id,waived_at,created_at);INSERT INTO student_ledger VALUES(1,'Abir','pending_extra_charge',15,'Duplicate',NULL,NULL,'2026-10-31'),(2,'Abir','pending_last_min_fee',15,'Automatic',NULL,NULL,'2026-10-22');")
  db=self.db
  class Conn:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):db.rollback()
  self.ns=dict(require_owner=lambda:True,ensure_v321_schema=lambda:None,sqlite3=SimpleNamespace(connect=lambda *a:Conn()),request=request,redirect=redirect,datetime=datetime)
  tree=ast.parse(Path(__file__).with_name('app.py').read_text())
  for name in ('remove_enrollment_invoice_charge','hmusic_pending_invoice_charge_total','hmusic_pending_invoice_charges'):
   node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);node.decorator_list=[];exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.ns)
  self.app=Flask(__name__)
 def tearDown(self):self.db.close()
 def remove(self,e=1,c=1):
  with self.app.test_request_context('/',method='POST'):return self.ns['remove_enrollment_invoice_charge'](e,c)
 def test_total_audit_and_repeat(self):
  self.assertEqual(self.remove().status_code,302)
  row=self.db.execute('SELECT entry_type,amount,description,waived_at FROM student_ledger WHERE id=1').fetchone();self.assertEqual(row[:2],('voided_extra_charge',15));self.assertIn('Removed by owner at',row[2]);self.assertTrue(row[3]);self.assertEqual(self.ns['hmusic_pending_invoice_charge_total'](self.db.cursor(),'Abir'),15);self.assertEqual(self.remove()[1],409)
 def test_invoiced_blocked(self):
  self.db.execute('UPDATE student_ledger SET related_invoice_id=12 WHERE id=1');self.db.commit();self.assertEqual(self.remove()[1],409)
 def test_wrong_student_and_auto_fee_blocked(self):
  self.assertEqual(self.remove(e=2)[1],409);self.assertEqual(self.remove(c=2)[1],409)
 def test_owner_and_missing(self):
  self.assertEqual(self.remove(e=999)[1],404);self.ns['require_owner']=lambda:False;self.assertEqual(self.remove().location,'/owner_login')
if __name__=='__main__':unittest.main()
