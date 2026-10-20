"""Real billing routes/SQL with isolated ledgers and provider session fixtures."""
import ast
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, redirect, request, session

SOURCE = ast.parse(Path(__file__).with_name('app.py').read_text())


class CheckoutSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/ledger.db'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''CREATE TABLE invoices(id,student_name,amount,status,
                stripe_checkout_session_id,stripe_payment_intent_id,autopay_status);
                CREATE TABLE invoice_allocations(id,invoice_id,parent_id,amount,status,
                stripe_checkout_session_id,stripe_payment_intent_id,lock_token,locked_at,payment_method,updated_at);
                INSERT INTO invoices VALUES(1,'Child',550,'payment_processing','cs_open',NULL,NULL);
                INSERT INTO invoice_allocations VALUES(3,1,2,550,'processing','cs_open',NULL,NULL,NULL,'Stripe ACH',NULL);''')
        self.provider = SimpleNamespace(checkout=SimpleNamespace(Session=SimpleNamespace(
            retrieve=Mock(return_value={'id':'cs_open','status':'open','payment_status':'unpaid',
                'payment_intent':'pi_unsubmitted','currency':'usd','amount_total':55000,
                'url':'https://checkout.stripe.com/existing',
                'metadata':{'invoice_id':'1','parent_id':'2','allocation_id':'3'}}))),
                PaymentIntent=SimpleNamespace(retrieve=Mock()))
        self.app = Flask(__name__); self.app.secret_key = 'test'; self.app.logger.disabled = True
        self.scope = dict(app=self.app,datetime=datetime,request=request,session=session,redirect=redirect,
            sqlite3=SimpleNamespace(connect=lambda _: sqlite3.connect(self.path)),stripe=self.provider,
            configure_stripe=lambda:True,ensure_v321_schema=lambda:None,ensure_billing_schema=lambda:None,
            ensure_guardian_billing_schema=lambda:None,require_parent=lambda:True,
            parent_can_access_student=lambda *a:True,parent_has_student_permission=lambda *a:True,
            sync_invoice_allocations=lambda *a:None,ensure_student_billing_rule=lambda *a:None,
            finalize_stripe_invoice_payment=Mock(),mark_stripe_invoice_payment_failed=Mock(),
            sync_quick_pay_checkout=Mock(return_value='unpaid'),sync_family_payment_status=Mock(return_value='unpaid'))
        names={'stripe_checkout_resume_url','refresh_invoice_status_from_allocations',
               'sync_stripe_invoice_payment','stripe_invoice_checkout'}
        nodes=[n for n in SOURCE.body if isinstance(n,ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<billing routes>','exec'),self.scope)
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['parent_id']=2

    def tearDown(self):
        self.tmp.cleanup()

    def test_parent_repeated_clicks_resume_existing_unsubmitted_checkout(self):
        for _ in range(2):
            response=self.client.get('/stripe/invoice/1/checkout')
            self.assertEqual(response.location,'https://checkout.stripe.com/existing')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM invoices').fetchone()[0],'unpaid')
            self.assertEqual(db.execute('SELECT stripe_checkout_session_id FROM invoice_allocations').fetchone()[0],'cs_open')
        self.scope['finalize_stripe_invoice_payment'].assert_not_called()

    def test_owner_recheck_keeps_legacy_session_payment_method_for_later_callback(self):
        self.assertEqual(self.scope['sync_stripe_invoice_payment'](1),'unpaid')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status,payment_method,stripe_checkout_session_id FROM invoice_allocations').fetchone(),
                             ('unpaid','Stripe ACH','cs_open'))

    def test_owner_recheck_delegates_guest_reservation_to_its_ledger(self):
        obj=self.provider.checkout.Session.retrieve.return_value
        obj['metadata']['quick_pay']='guest-digest'
        self.assertEqual(self.scope['sync_stripe_invoice_payment'](1),'unpaid')
        self.scope['sync_quick_pay_checkout'].assert_called_once_with(obj)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM invoice_allocations').fetchone()[0],'processing')

    def test_owner_recheck_delegates_reserved_family_bill(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE invoice_allocations SET lock_token='family:9'");db.commit()
        self.assertEqual(self.scope['sync_stripe_invoice_payment'](1),'unpaid')
        self.scope['sync_family_payment_status'].assert_called_once_with(9)
        self.provider.checkout.Session.retrieve.assert_not_called()

    def test_mismatched_share_cannot_resume_or_start_another_charge(self):
        self.provider.checkout.Session.retrieve.return_value['amount_total']=1
        response=self.client.get('/stripe/invoice/1/checkout')
        self.assertIn('stripe_incomplete=1',response.location)
        self.scope['finalize_stripe_invoice_payment'].assert_not_called()

    def test_submitted_legacy_checkout_is_not_reopened(self):
        obj=self.provider.checkout.Session.retrieve.return_value
        obj['status']='complete';obj['payment_intent']='pi_submitted'
        self.provider.PaymentIntent.retrieve.return_value={'status':'processing'}
        self.assertEqual(self.scope['sync_stripe_invoice_payment'](1),'processing')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM invoices').fetchone()[0],'payment_processing')
        self.scope['finalize_stripe_invoice_payment'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
