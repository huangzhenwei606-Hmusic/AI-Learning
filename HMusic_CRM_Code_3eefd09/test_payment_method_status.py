"""Exercise production billing SQL without starting the app or touching its DB."""
import ast
from pathlib import Path
import sqlite3
import unittest

SOURCE = ast.parse(Path(__file__).with_name('app.py').read_text())

def function(name):
    return next(n for n in SOURCE.body if isinstance(n, ast.FunctionDef) and n.name == name)

class PaymentMethodStatusTest(unittest.TestCase):
    def test_manual_notice_is_not_ach_processing(self):
        scope = {}
        exec(compile(ast.Module(body=[function('refresh_invoice_status_from_allocations')], type_ignores=[]), '<billing>', 'exec'), scope)
        db = sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE invoices(id,status); CREATE TABLE invoice_allocations(invoice_id,status); INSERT INTO invoices VALUES(55,'payment_processing'); INSERT INTO invoice_allocations VALUES(55,'pending_confirmation');")
        refresh = scope['refresh_invoice_status_from_allocations']
        self.assertEqual(refresh(db.cursor(), 55), 'pending_confirmation')
        db.execute("INSERT INTO invoice_allocations VALUES(55,'processing')")
        self.assertEqual(refresh(db.cursor(), 55), 'payment_processing')
        db.execute("UPDATE invoice_allocations SET status='paid'")
        self.assertEqual(refresh(db.cursor(), 55), 'paid')

    def test_delayed_ach_callbacks_preserve_zelle(self):
        for name in ('stripe_invoice_success', 'stripe_webhook'):
            statements = [n.value for n in ast.walk(function(name)) if isinstance(n, ast.Constant) and isinstance(n.value, str) and 'UPDATE invoice_allocations' in n.value and "ELSE 'processing'" in n.value]
            self.assertTrue(statements)
            for sql in statements:
                db = sqlite3.connect(':memory:')
                db.executescript("CREATE TABLE invoice_allocations(id,invoice_id,parent_id,status,payment_method,stripe_checkout_session_id,stripe_payment_intent_id,lock_token,locked_at,updated_at); INSERT INTO invoice_allocations VALUES(1,55,2,'pending_confirmation','Zelle',NULL,NULL,NULL,NULL,NULL);")
                args = ('cs_old','pi_old','now',1,55,2,'cs_old') if name == 'stripe_invoice_success' else ('cs_old','pi_old','now',1,55,'cs_old')
                self.assertEqual(db.execute(sql,args).rowcount,0)
                self.assertEqual(db.execute('SELECT status FROM invoice_allocations').fetchone()[0],'pending_confirmation')
                db.execute("UPDATE invoice_allocations SET status='unpaid',payment_method='Stripe ACH',stripe_checkout_session_id='cs_old'")
                self.assertEqual(db.execute(sql,args).rowcount,1)
                self.assertEqual(db.execute('SELECT status FROM invoice_allocations').fetchone()[0],'processing')

    def test_paid_share_credit_is_never_repaired_twice(self):
        from datetime import datetime
        scope = {'datetime': datetime}
        nodes = [function('invoice_credit_to_grant'), function('repair_paid_invoice_credit')]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<billing>', 'exec'), scope)
        db = sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE enrollments(id,lessons_left,updated_at); CREATE TABLE payments(id,enrollment_id,notes,lessons_added); CREATE TABLE invoices(id,credits_applied); INSERT INTO enrollments VALUES(48,0,NULL); INSERT INTO invoices VALUES(55,1); INSERT INTO payments VALUES(106,48,'Invoice #55 share paid by parent #4765 · Owner confirmed',10);")
        invoice = (55, 'Max Ling', 10, 600, 'paid', 'initial_tuition', '2026-09-08', 48)
        self.assertEqual(scope['repair_paid_invoice_credit'](db.cursor(), invoice), 0)
        self.assertEqual(db.execute('SELECT lessons_left FROM enrollments').fetchone()[0], 0)

    def test_legacy_share_repair_updates_receipt_once(self):
        from datetime import datetime
        scope = {'datetime': datetime}
        exec(compile(ast.Module(body=[function('invoice_credit_to_grant'), function('repair_paid_invoice_credit')], type_ignores=[]), '<billing>', 'exec'), scope)
        db = sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE enrollments(id,lessons_left,updated_at); CREATE TABLE payments(id,enrollment_id,notes,lessons_added); CREATE TABLE invoices(id,credits_applied); INSERT INTO enrollments VALUES(48,0,NULL); INSERT INTO invoices VALUES(55,1); INSERT INTO payments VALUES(106,48,'Invoice #55 share paid by parent #4765 · Owner confirmed',0);")
        invoice = (55, 'Max Ling', 10, 600, 'paid', 'initial_tuition', '2026-09-08', 48)
        self.assertEqual(scope['repair_paid_invoice_credit'](db.cursor(), invoice), 10)
        self.assertEqual(db.execute('SELECT lessons_added FROM payments').fetchone()[0], 10)
        db.execute('UPDATE enrollments SET lessons_left=0')
        self.assertEqual(scope['repair_paid_invoice_credit'](db.cursor(), invoice), 0)

    def test_old_zelle_status_repairs_without_changing_paid_or_ach(self):
        statements = [n.value for n in ast.walk(function('invoices')) if isinstance(n, ast.Constant) and isinstance(n.value,str) and "SET status = 'pending_confirmation'" in n.value]
        self.assertEqual(len(statements),1)
        db = sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE invoices(id,status); CREATE TABLE invoice_allocations(invoice_id,status); INSERT INTO invoices VALUES(1,'payment_processing'),(2,'payment_processing'),(3,'paid'); INSERT INTO invoice_allocations VALUES(1,'pending_confirmation'),(2,'processing'),(2,'pending_confirmation'),(3,'pending_confirmation');")
        db.execute(statements[0])
        self.assertEqual(db.execute('SELECT status FROM invoices ORDER BY id').fetchall(), [('pending_confirmation',),('payment_processing',),('paid',)])

if __name__ == '__main__':
    unittest.main()
