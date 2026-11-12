import sqlite3
import unittest
from payment_reversal import ensure_schema, reverse, candidate

class ReversalTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.cur=self.db.cursor()
        self.db.executescript('''CREATE TABLE invoices(id,student_name,status,enrollment_id,credits_applied);
        INSERT INTO invoices VALUES(273,'Jayden','paid',296,1);
        CREATE TABLE enrollments(id,lessons_left,updated_at);INSERT INTO enrollments VALUES(296,7,'');
        CREATE TABLE invoice_allocations(id,invoice_id,status,payment_method,stripe_checkout_session_id,stripe_payment_intent_id,paid_at,manual_payment_status,lock_token,locked_at,amount);
        INSERT INTO invoice_allocations VALUES(2044,273,'paid','Zelle',NULL,NULL,'today','confirmed',NULL,NULL,550);
        CREATE TABLE family_payment_items(invoice_id,family_payment_id);CREATE TABLE family_payments(id,status);
        CREATE TABLE payments(id INTEGER PRIMARY KEY,student_name,amount,lessons_added,payment_method,payment_date,enrollment_id,course_type_name,teacher_name,package_name,notes,visible_to_parent);
        INSERT INTO payments VALUES(230,'Jayden',550,10,'Zelle','today',296,'Piano','Teacher','Tuition','Original',1);
        CREATE TABLE student_ledger(id INTEGER PRIMARY KEY,student_name,entry_type,amount,description,related_invoice_id,related_payment_id,related_schedule_id,created_at);
        INSERT INTO student_ledger VALUES(1,'Jayden','invoice_payment_share',550,'Original',273,230,NULL,'today');''')
        ensure_schema(self.cur);self.db.commit()
    def tearDown(self):self.db.close()
    def test_correction_retains_original_and_offsets_exact_credits(self):
        self.assertEqual(reverse(self.cur,273,230,'Mistaken Paid','owner-1'),10)
        self.assertEqual(self.cur.execute('SELECT lessons_left FROM enrollments').fetchone()[0],-3)
        self.assertEqual(self.cur.execute('SELECT status,credits_applied FROM invoices').fetchone(),('unpaid',0))
        self.assertEqual(self.cur.execute('SELECT status FROM invoice_allocations').fetchone()[0],'unpaid')
        self.assertEqual(self.cur.execute('SELECT amount,lessons_added,notes FROM payments WHERE id=230').fetchone(),(550,10,'Original'))
        self.assertEqual(self.cur.execute('SELECT SUM(amount),SUM(lessons_added) FROM payments').fetchone(),(0,0))
        self.assertEqual(self.cur.execute('SELECT SUM(amount) FROM student_ledger').fetchone()[0],0)
        self.assertEqual(self.cur.execute('SELECT reason,reversed_by FROM payment_reversals').fetchone(),('Mistaken Paid','owner-1'))
        with self.assertRaises(ValueError):reverse(self.cur,273,230,'Duplicate','owner-1')
        self.assertEqual(self.cur.execute('SELECT lessons_left FROM enrollments').fetchone()[0],-3)
    def test_online_payment_is_blocked(self):
        self.cur.execute("UPDATE invoice_allocations SET payment_method='Stripe ACH'")
        with self.assertRaises(ValueError):reverse(self.cur,273,230,'Oops','owner')
    def test_combined_payment_is_blocked(self):
        self.cur.execute("INSERT INTO family_payments VALUES(1,'paid')");self.cur.execute('INSERT INTO family_payment_items VALUES(273,1)')
        with self.assertRaises(ValueError):candidate(self.cur,273)
    def test_reason_and_payment_identity_are_required(self):
        for pid,reason in [(230,''),(231,'Oops')]:
            with self.assertRaises(ValueError):reverse(self.cur,273,pid,reason,'owner')
        self.assertEqual(self.cur.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1)
