import ast,json,sqlite3,unittest
from html import escape
from pathlib import Path
from types import SimpleNamespace
from flask import Flask,request,redirect
SOURCE=Path(__file__).with_name('app.py').read_text()
class DeleteTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript("CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,status);INSERT INTO invoices VALUES(187,'Student','unpaid');CREATE TABLE credits(balance);INSERT INTO credits VALUES(7);")
  db=self.db
  class Conn:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):pass
  self.ns=dict(require_owner=lambda:True,ensure_v321_schema=lambda:None,sqlite3=SimpleNamespace(connect=lambda *a:Conn()),request=request,redirect=redirect,escape=escape,json=json,hmusic_money=lambda x:f'{x:.2f}')
  for name in ('invoice_delete_action','delete_invoice'):
   n=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name==name);n.decorator_list=[];exec(compile(ast.Module(body=[n],type_ignores=[]),'app.py','exec'),self.ns)
  self.app=Flask(__name__)
 def tearDown(self):self.db.close()
 def delete(self,target='/invoices',iid=187):
  with self.app.test_request_context('/',method='POST',data={'return_to':target}):return self.ns['delete_invoice'](iid)
 def test_unpaid_delete_preserves_credits_and_returns_to_family(self):
  self.assertEqual(self.delete('/parent_admin/4559').location,'/parent_admin/4559');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],0);self.assertEqual(self.db.execute('SELECT balance FROM credits').fetchone()[0],7)
 def test_failed_delete(self):
  self.db.execute("UPDATE invoices SET status='payment_failed'");self.assertEqual(self.delete().location,'/invoices')
 def test_paid_and_processing_blocked(self):
  for status in ('paid','stripe_processing','square_processing','pending_confirmation'):
   self.db.execute('UPDATE invoices SET status=?',(status,));self.assertIn('Cannot Be Deleted',self.delete());self.assertEqual(self.db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
 def test_owner_required(self):
  self.ns['require_owner']=lambda:False;self.assertEqual(self.delete().location,'/owner_login');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
 def test_external_redirect_blocked(self):self.assertEqual(self.delete('//evil.example').location,'/invoices')
 def test_missing_404(self):self.assertEqual(self.delete(iid=999)[1],404)
 def test_button_confirmation_and_escaping(self):
  f=self.ns['invoice_delete_action'];s=f(187,'<script>x</script>',400,'unpaid','/parent_admin/4559');self.assertNotIn('<script>',s);self.assertIn('Delete invoice #187',s);self.assertIn('$400.00',s);self.assertIn('method="POST"',s);self.assertEqual(f(187,'Student',400,'paid'),'')
if __name__=='__main__':unittest.main()
