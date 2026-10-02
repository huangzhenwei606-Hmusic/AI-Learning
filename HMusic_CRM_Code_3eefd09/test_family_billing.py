import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, date
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask
import family_billing as fb


PAYMENT_NODES=[n for n in ast.parse(Path(__file__).with_name('app.py').read_text()).body
    if isinstance(n,ast.FunctionDef) and n.name in {'invoice_credit_to_grant','refresh_invoice_status_from_allocations','record_invoice_allocation_paid'}]


class FamilyBillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=str(Path(self.tmp.name)/'test.db')
        self.conn=sqlite3.connect(self.path);cur=self.conn.cursor()
        cur.executescript('''
        CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name TEXT,charge_lessons REAL,amount REAL,status TEXT,invoice_type TEXT,enrollment_id INTEGER,credits_applied INTEGER DEFAULT 0);
        CREATE TABLE enrollments(id INTEGER PRIMARY KEY,student_name TEXT,course_type_name TEXT,teacher_name TEXT,lessons_left REAL,updated_at TEXT);
        CREATE TABLE invoice_allocations(id INTEGER PRIMARY KEY,invoice_id INTEGER,parent_id INTEGER,amount REAL,status TEXT,payment_method TEXT,manual_payment_status TEXT,lock_token TEXT,locked_at TEXT,paid_at TEXT,updated_at TEXT);
        CREATE TABLE payments(id INTEGER PRIMARY KEY,student_name TEXT,amount REAL,lessons_added REAL,payment_method TEXT,payment_date TEXT,enrollment_id INTEGER,course_type_name TEXT,teacher_name TEXT,package_name TEXT,notes TEXT,visible_to_parent INTEGER);
        CREATE TABLE student_ledger(id INTEGER PRIMARY KEY,student_name TEXT,entry_type TEXT,amount REAL,description TEXT,related_invoice_id INTEGER,related_payment_id INTEGER,related_schedule_id INTEGER,created_at TEXT);
        CREATE TABLE parent_students(parent_id INTEGER,student_name TEXT,active INTEGER);
        INSERT INTO enrollments VALUES(1,'Seth','Private','Mike',-3,NULL),(2,'Valerie','Private','Jenny',-3,NULL),(3,'Valerie','Private','Mike',-1,NULL),(4,'Unrelated','Private','Mike',8,NULL);
        INSERT INTO invoices VALUES(1,'Seth',10,525,'unpaid','package_invoice',1,0),(2,'Valerie',10,500,'unpaid','package_invoice',2,0),(3,'Valerie',10,525,'unpaid','package_invoice',3,0);
        INSERT INTO invoice_allocations(id,invoice_id,parent_id,amount,status) VALUES(1,1,1,525,'unpaid'),(2,2,1,500,'unpaid'),(3,3,1,525,'unpaid');
        INSERT INTO parent_students VALUES(1,'Seth',1),(1,'Valerie',1);
        ''')
        fb.ensure_schema(cur);self.conn.commit()
        self.api={'datetime':datetime,'date':date,'parent_has_student_permission':lambda p,s,k:p==1}
        exec(compile(ast.Module(body=PAYMENT_NODES,type_ignores=[]),'app.py','exec'),self.api)

    def tearDown(self):self.conn.close();self.tmp.cleanup()

    def create(self,method='Zelle',ids=(1,2,3),key='request'):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            bid=fb.create_batch(self.conn.cursor(),1,ids,method,key,self.api);self.conn.commit();return bid
        except Exception:self.conn.rollback();raise

    def settle(self,bid,method='Zelle',amount=155000):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            result=fb.settle_batch(self.conn.cursor(),bid,method,'reference',amount,self.api);self.conn.commit();return result
        except Exception:self.conn.rollback();raise

    def balances(self):return [r[0] for r in self.conn.execute('SELECT lessons_left FROM enrollments ORDER BY id')]

    def test_separate_course_credits_and_receipts(self):
        bid=self.create();self.assertTrue(self.settle(bid))
        self.assertEqual(self.balances(),[7,7,9,8])
        self.assertEqual(list(self.conn.execute('SELECT enrollment_id,amount,lessons_added FROM payments ORDER BY id')),[(1,525,10),(2,500,10),(3,525,10)])
        self.assertEqual(self.conn.execute('SELECT total_cents FROM family_payments').fetchone()[0],155000)

    def test_duplicate_confirmation_no_double_credit(self):
        bid=self.create();self.settle(bid);self.assertFalse(self.settle(bid));self.assertEqual(self.balances(),[7,7,9,8]);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],3)

    def test_simultaneous_callbacks_grant_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        bid=self.create()
        def callback(_):
            conn=sqlite3.connect(self.path,timeout=10)
            try:
                conn.execute('BEGIN IMMEDIATE')
                result=fb.settle_batch(conn.cursor(),bid,'Zelle','parallel',155000,self.api)
                conn.commit();return result
            finally:conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(callback,range(2)))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(self.balances(),[7,7,9,8])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],3)

    def test_duplicate_submit_returns_same_batch(self):
        bid=self.create();self.assertEqual(bid,self.create());self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM family_payments').fetchone()[0],1)

    def test_wrong_amount_is_atomic(self):
        bid=self.create()
        with self.assertRaises(fb.FamilyPaymentError):self.settle(bid,amount=150000)
        self.assertEqual(self.balances(),[-3,-3,-1,8]);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)

    def test_changed_course_rolls_back_all_lines(self):
        bid=self.create();self.conn.execute('UPDATE invoices SET enrollment_id=4 WHERE id=3');self.conn.commit()
        with self.assertRaises(fb.FamilyPaymentError):self.settle(bid)
        self.assertEqual(self.balances(),[-3,-3,-1,8]);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM invoice_allocations WHERE status="paid"').fetchone()[0],0)

    def test_invoice_total_drift_does_not_apply_any_credit(self):
        bid=self.create();self.conn.execute('UPDATE invoices SET amount=700 WHERE id=3');self.conn.commit()
        with self.assertRaises(fb.FamilyPaymentError):self.settle(bid)
        self.assertEqual(self.balances(),[-3,-3,-1,8])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)

    def test_changed_lesson_count_rolls_back(self):
        bid=self.create();self.conn.execute('UPDATE invoices SET charge_lessons=20 WHERE id=3');self.conn.commit()
        with self.assertRaises(fb.FamilyPaymentError):self.settle(bid)
        self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_missing_course_prevents_credit_invoice(self):
        self.conn.execute('UPDATE invoices SET enrollment_id=NULL WHERE id=3');self.conn.commit()
        with self.assertRaises(fb.FamilyPaymentError):self.create()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM family_payments').fetchone()[0],0)

    def test_second_batch_and_individual_settlement_blocked(self):
        self.create()
        with self.assertRaises(fb.FamilyPaymentError):self.create(key='second')
        result=self.api['record_invoice_allocation_paid'](self.conn.cursor(),1,'Stripe ACH')
        self.assertFalse(result['ok']);self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_other_parent_cannot_pay(self):
        self.conn.execute('UPDATE invoice_allocations SET parent_id=2 WHERE id=3');self.conn.commit()
        with self.assertRaises(fb.FamilyPaymentError):self.create()

    def test_split_guardians_credit_only_when_all_paid(self):
        self.conn.execute('UPDATE invoice_allocations SET amount=250 WHERE id=2')
        self.conn.execute("INSERT INTO invoice_allocations(id,invoice_id,parent_id,amount,status) VALUES(4,2,2,250,'unpaid')");self.conn.commit()
        bid=self.create();self.settle(bid,amount=130000);self.assertEqual(self.balances(),[7,-3,9,8])
        result=self.api['record_invoice_allocation_paid'](self.conn.cursor(),4,'Zelle');self.conn.commit()
        self.assertTrue(result['ok']);self.assertEqual(self.balances(),[7,7,9,8])

    def test_fee_gets_no_credit(self):
        self.conn.execute("UPDATE invoices SET invoice_type='cancellation_fee',enrollment_id=NULL WHERE id=3");self.conn.commit()
        bid=self.create();self.settle(bid);self.assertEqual(self.balances(),[7,7,-1,8])

    def test_payment_processing_does_not_grant(self):
        self.create(method='Stripe ACH');self.assertEqual(self.balances(),[-3,-3,-1,8]);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)

    def test_sql_translation_schema(self):
        from database_backend import _translate_sql
        class Recorder:
            def execute(self,sql,*args):
                translated=_translate_sql(sql);assert 'AUTOINCREMENT' not in translated
        fb.ensure_schema(Recorder())

    def setup_client(self):
        app=Flask(__name__);app.secret_key='test'
        # Routes and callbacks use the real settlement functions extracted above.
        api=dict(self.api)
        api.update(sqlite3=SimpleNamespace(connect=lambda *a:sqlite3.connect(self.path)),ensure_v321_schema=lambda:None,ensure_guardian_billing_schema=lambda:None,
            require_owner=lambda:False,require_parent=lambda:True,configure_stripe=lambda:True,square_is_configured=lambda:True,
            get_square_location_id=lambda:'loc',get_or_create_stripe_customer=lambda c,p:'cus_test',public_url_for=lambda p:'https://example.test'+p,
            secrets=__import__('secrets'),stripe=SimpleNamespace(checkout=SimpleNamespace(Session=SimpleNamespace(create=Mock(),retrieve=Mock()))),
            square_api_request=Mock(),sync_invoice_allocations=lambda *a:None)
        app.logger.disabled=True
        fb.install_family_billing(app,api)
        client=app.test_client()
        with client.session_transaction() as session:session['parent_id']=1
        return client,api

    def test_stripe_async_and_duplicate_webhook(self):
        bid=self.create(method='Stripe ACH');self.conn.execute("UPDATE family_payments SET provider_id='cs_test' WHERE id=?",(bid,));self.conn.commit()
        client,api=self.setup_client()
        obj={'id':'cs_test','metadata':{'family_payment_id':str(bid),'parent_id':'1'},'payment_status':'unpaid','currency':'usd','amount_total':155000,'payment_intent':'pi_test'}
        api['stripe'].checkout.Session.retrieve.return_value=obj
        event={'type':'checkout.session.completed','data':{'object':obj}}
        self.assertEqual(client.post('/stripe/webhook',json=event).status_code,200);self.assertEqual(self.balances(),[-3,-3,-1,8])
        obj['payment_status']='paid';event['type']='checkout.session.async_payment_succeeded'
        self.assertEqual(client.post('/stripe/webhook',json=event).status_code,200)
        self.assertEqual(client.post('/stripe/webhook',json=event).status_code,200);self.assertEqual(self.balances(),[7,7,9,8])

    def test_webhook_cannot_fake_provider_amount(self):
        bid=self.create(method='Stripe ACH');self.conn.execute("UPDATE family_payments SET provider_id='cs_test' WHERE id=?",(bid,));self.conn.commit()
        client,api=self.setup_client()
        obj={'id':'cs_test','metadata':{'family_payment_id':str(bid),'parent_id':'1'},'payment_status':'paid','currency':'usd','amount_total':1}
        api['stripe'].checkout.Session.retrieve.return_value=obj
        self.assertEqual(client.post('/stripe/webhook',json={'data':{'object':obj}}).status_code,503);self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_square_requires_completed_not_approved(self):
        bid=self.create(method='Square');self.conn.execute("UPDATE family_payments SET provider_id='order1' WHERE id=?",(bid,));self.conn.commit()
        client,api=self.setup_client()
        payment={'id':'payment1','order_id':'order1','status':'APPROVED','amount_money':{'amount':155000,'currency':'USD'}}
        order={'id':'order1','reference_id':f'hmusic-family-{bid}','location_id':'loc'}
        api['square_api_request'].side_effect=lambda path,**kw:{'payment':payment} if '/payments/' in path else {'order':order}
        event={'data':{'object':{'payment':payment}}}
        self.assertEqual(client.post('/square/webhook',json=event).status_code,200);self.assertEqual(self.balances(),[-3,-3,-1,8])
        payment['status']='COMPLETED'
        self.assertEqual(client.post('/square/webhook',json=event).status_code,200);self.assertEqual(self.balances(),[7,7,9,8])

    def test_checkout_retry_same_idempotency_key(self):
        bid=self.create(method='Stripe ACH');client,api=self.setup_client()
        api['stripe'].checkout.Session.create.return_value=SimpleNamespace(id='cs_new',url='https://stripe.test/pay')
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,302)
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,302)
        api['stripe'].checkout.Session.create.assert_called_once()
        self.assertEqual(api['stripe'].checkout.Session.create.call_args.kwargs['idempotency_key'],f'hmusic-family-{bid}')

    def test_manual_notice_has_no_credit(self):
        bid=self.create();client,api=self.setup_client()
        self.assertEqual(client.post(f'/family_payment/{bid}',data={'action':'notify'}).status_code,302)
        self.assertEqual(self.balances(),[-3,-3,-1,8])
        self.assertEqual(client.post(f'/family_payment/{bid}',data={'action':'confirm','received_amount':'1550'}).status_code,403)

    def test_expired_unsubmitted_stripe_releases_invoices(self):
        bid=self.create(method='Stripe ACH');self.conn.execute("UPDATE family_payments SET provider_id='cs_expired' WHERE id=?",(bid,));self.conn.commit()
        client,api=self.setup_client()
        api['stripe'].checkout.Session.retrieve.return_value={'id':'cs_expired','metadata':{'family_payment_id':str(bid),'parent_id':'1'},'status':'expired','payment_status':'unpaid','payment_intent':None}
        self.assertEqual(client.post(f'/family_payment/{bid}/check').status_code,302)
        self.assertEqual(self.conn.execute('SELECT status FROM family_payments').fetchone()[0],'cancelled')
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoice_allocations WHERE status='unpaid' AND lock_token IS NULL").fetchone()[0],3)
        self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_unconfirmed_owner_cancel_releases_without_credit(self):
        bid=self.create();client,api=self.setup_client();api['require_owner']=lambda:True
        self.assertEqual(client.post(f'/family_payment/{bid}',data={'action':'cancel'}).status_code,302)
        self.assertEqual(self.conn.execute('SELECT status FROM family_payments').fetchone()[0],'cancelled')
        self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_owner_confirms_manual_total(self):
        bid=self.create();client,api=self.setup_client();api['require_owner']=lambda:True
        self.assertEqual(client.post(f'/family_payment/{bid}',data={'action':'confirm','received_amount':'1550','payment_date':'2026-10-01'}).status_code,302)
        self.assertEqual(self.balances(),[7,7,9,8])

    def test_square_checkout_one_order_with_separate_items(self):
        bid=self.create(method='Square');client,api=self.setup_client()
        api['square_api_request'].return_value={'payment_link':{'order_id':'order1','url':'https://square.test/pay'}}
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,302)
        payload=api['square_api_request'].call_args.args[1]
        self.assertEqual([r['base_price_money']['amount'] for r in payload['order']['line_items']],[52500,50000,52500])
        self.assertEqual(payload['idempotency_key'],f'hmusic-family-{bid}')
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,302)
        api['square_api_request'].assert_called_once()

    def test_old_uncertain_checkout_is_not_recreated(self):
        bid=self.create(method='Stripe ACH')
        self.conn.execute("UPDATE family_payments SET created_at='2000-01-01 00:00:00' WHERE id=?",(bid,));self.conn.commit()
        client,api=self.setup_client()
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,409)
        api['stripe'].checkout.Session.create.assert_not_called()
        self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_provider_exception_keeps_same_reserved_bill(self):
        bid=self.create(method='Stripe ACH');client,api=self.setup_client()
        api['stripe'].checkout.Session.create.side_effect=RuntimeError('connection interrupted')
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,503)
        self.assertEqual(self.balances(),[-3,-3,-1,8])
        self.assertEqual(fb.active_batch(self.conn.cursor(),1),bid)
        api['stripe'].checkout.Session.create.side_effect=None
        api['stripe'].checkout.Session.create.return_value=SimpleNamespace(id='cs_retry',url='https://stripe.test/pay')
        self.assertEqual(client.post(f'/family_payment/{bid}/checkout').status_code,302)
        keys=[c.kwargs['idempotency_key'] for c in api['stripe'].checkout.Session.create.call_args_list]
        self.assertEqual(keys,[f'hmusic-family-{bid}',f'hmusic-family-{bid}'])

    def test_selection_and_receipt_render(self):
        client,api=self.setup_client()
        r=client.get('/family_billing/1');self.assertEqual(r.status_code,200);self.assertIn(b'Valerie',r.data)
        self.assertEqual(client.get('/family_billing/2').status_code,403)
        bid=self.create();r=client.get(f'/family_payment/{bid}');self.assertEqual(r.status_code,200);self.assertIn(b'$1,550.00',r.data)

if __name__=='__main__':unittest.main(verbosity=2)
