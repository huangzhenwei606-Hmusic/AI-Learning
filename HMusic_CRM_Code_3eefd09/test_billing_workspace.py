import sqlite3
import unittest
from billing_workspace import billing_workspace_html

class BillingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.executescript("""CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name TEXT,email TEXT,active INTEGER,phone TEXT);
        CREATE TABLE invoices(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE invoice_allocations(id INTEGER PRIMARY KEY,parent_id INTEGER,invoice_id INTEGER,status TEXT);
        CREATE TABLE parent_students(parent_id INTEGER,student_name TEXT,active INTEGER);
        INSERT INTO parent_profiles VALUES(1,'A <Family>','a@example.invalid',1,'6505550100'),(2,'Inactive','b@example.invalid',0,''),(3,'Paid only','c@example.invalid',1,'');
        INSERT INTO invoices VALUES(1,'unpaid'),(2,'paid');
        INSERT INTO invoice_allocations VALUES(1,1,1,'unpaid'),(2,2,1,'unpaid'),(3,3,2,'paid');""")
        self.c.execute('ALTER TABLE invoices ADD COLUMN student_name TEXT')
        billing_workspace_html(self.c.cursor())
    def tearDown(self):self.c.close()
    def test_eligible_payers_and_escaping(self):
        html=billing_workspace_html(self.c.cursor())
        self.assertIn('A &lt;Family&gt;',html)
        self.assertNotIn('Inactive',html);self.assertNotIn('Paid only',html)
    def test_active_ach_offers_sms_and_paid_ach_keeps_history(self):
        for i,status,method in [(1,'creating','Stripe ACH'),(2,'paid','Stripe ACH'),(3,'creating','Zelle')]:
            self.c.execute("INSERT INTO family_payments(id,parent_id,request_key,method,status,total_cents,created_at) VALUES(?,1,?,?,?,377500,'2026-10-21')",(i,str(i),method,status))
        html=billing_workspace_html(self.c.cursor())
        self.assertIn('/family_payment/1/share',html)
        self.assertIn('/family_payment/2/share',html);self.assertIn('SMS history',html);self.assertNotIn('/family_payment/3/share',html)
        self.assertIn('$3,775.00',html)
    def test_render_does_not_send_or_change_payment(self):
        self.c.execute("INSERT INTO family_payments(parent_id,request_key,method,status,total_cents,created_at) VALUES(1,'r','Stripe ACH','creating',377500,'2026-10-21')")
        billing_workspace_html(self.c.cursor())
        self.assertEqual(self.c.execute('SELECT status,total_cents FROM family_payments').fetchone(),('creating',377500))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM family_payment_links').fetchone()[0],0)
    def test_empty_list(self):
        self.assertIn('No combined bills yet.',billing_workspace_html(self.c.cursor()))
    def test_new_invoice_parent_is_found_before_allocation_created(self):
        self.c.execute("INSERT INTO parent_profiles VALUES(4,'Hao Qi','hellohaoqi@example.invalid',1,'6505550101')")
        self.c.execute("INSERT INTO parent_students VALUES(4,'Sophia Yuan',1)")
        self.c.execute("INSERT INTO invoices VALUES(3,'unpaid','Sophia Yuan')")
        html=billing_workspace_html(self.c.cursor())
        self.assertIn('Hao Qi',html)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM invoice_allocations WHERE parent_id=4').fetchone()[0],0)
