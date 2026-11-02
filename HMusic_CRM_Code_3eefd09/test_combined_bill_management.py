"""Owner-only lifecycle actions preserve invoices, payments, credits and SMS history."""
import hashlib
import unittest
from unittest.mock import Mock
from test_family_billing import FamilyBillingTests
import family_billing as fb


class CombinedBillManagementTests(unittest.TestCase):
    tearDown = FamilyBillingTests.tearDown
    create = FamilyBillingTests.create
    settle = FamilyBillingTests.settle
    balances = FamilyBillingTests.balances
    setup_client = FamilyBillingTests.setup_client

    def setUp(self):
        FamilyBillingTests.setUp(self)
        self.bid = self.create(method='Stripe ACH')
        self.client, self.api = self.setup_client()
        self.api['require_owner'] = lambda: True
        self.api['stripe'].checkout.Session.expire = Mock()
        self.url = f'/owner/family_payment/{self.bid}/manage'
        self.digest = hashlib.sha256(b'old-link').hexdigest()
        self.conn.execute("INSERT INTO family_payment_links(token_hash,batch_id,expires_at,sms_status,sms_body) VALUES(?,?,9999999999,'accepted','Original SMS')", (self.digest,self.bid))
        self.conn.commit()

    def status(self):
        return self.conn.execute('SELECT status FROM family_payments WHERE id=?',(self.bid,)).fetchone()[0]

    def provider(self, **changes):
        self.conn.execute("UPDATE family_payments SET provider_id='cs_test',status='checkout' WHERE id=?",(self.bid,));self.conn.commit()
        obj=dict(id='cs_test',status='open',payment_status='unpaid',payment_intent=None,
                 metadata={'family_payment_id':str(self.bid),'parent_id':'1'},currency='usd',amount_total=155000)
        obj.update(changes)
        self.api['stripe'].checkout.Session.retrieve.return_value=obj
        self.api['stripe'].checkout.Session.expire.return_value=dict(obj,status='expired')
        return obj

    def test_cancel_unstarted_ach_keeps_invoices_and_history_and_can_recombine(self):
        self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,302)
        self.assertEqual(self.status(),'cancelled')
        self.assertEqual(self.balances(),[-3,-3,-1,8])
        self.assertEqual(list(self.conn.execute('SELECT status FROM invoices')), [('unpaid',)]*3)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT expires_at,sms_body FROM family_payment_links').fetchone(),(0,'Original SMS'))
        self.assertEqual(self.client.get('/f/old-link').status_code,404)
        new = self.create(method='Stripe ACH', key='recombine')
        self.assertNotEqual(new,self.bid)
        self.client.post(self.url,data={'action':'cancel'})
        self.assertEqual(fb.active_batch(self.conn.cursor(),1),new)

    def test_open_stripe_checkout_is_expired_before_release(self):
        self.provider()
        self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,302)
        self.api['stripe'].checkout.Session.expire.assert_called_once_with('cs_test')
        self.assertEqual(self.status(),'cancelled')
        self.assertEqual(self.balances(),[-3,-3,-1,8])

    def test_submitted_paid_and_unknown_checkout_cannot_cancel(self):
        for status in ('submitted','processing','checkout_starting','paid'):
            with self.subTest(status=status):
                self.conn.execute('UPDATE family_payments SET status=? WHERE id=?',(status,self.bid));self.conn.commit()
                self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,409)
                self.assertEqual(self.status(),status)
        self.assertEqual(self.conn.execute('SELECT expires_at FROM family_payment_links').fetchone()[0],9999999999)

    def test_provider_submitted_or_mismatched_payment_stays_locked(self):
        for changes in ({'status':'complete','payment_intent':'pi_started'}, {'payment_status':'paid'},
                        {'amount_total':1}, {'metadata':{'family_payment_id':'other'}}):
            with self.subTest(changes=changes):
                self.provider(**changes)
                self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,409)
                self.assertEqual(self.status(),'checkout')
                self.assertEqual(fb.active_batch(self.conn.cursor(),1),self.bid)
        self.api['stripe'].checkout.Session.expire.assert_not_called()

    def test_provider_failure_keeps_lock_and_links(self):
        self.provider();self.api['stripe'].checkout.Session.retrieve.side_effect=TimeoutError()
        self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,503)
        self.assertEqual(self.status(),'checkout')
        self.assertEqual(fb.active_batch(self.conn.cursor(),1),self.bid)
        self.assertEqual(self.conn.execute('SELECT expires_at FROM family_payment_links').fetchone()[0],9999999999)

    def test_expiration_must_be_confirmed(self):
        obj=self.provider();self.api['stripe'].checkout.Session.expire.return_value=obj
        self.assertEqual(self.client.post(self.url,data={'action':'cancel'}).status_code,409)
        self.assertEqual(self.status(),'checkout')

    def test_archive_restore_preserve_settled_records_and_live_receipt_link(self):
        self.settle(self.bid,method='Stripe ACH')
        before=list(self.conn.execute('SELECT * FROM payments'))
        self.assertEqual(self.client.post(self.url,data={'action':'archive'}).status_code,302)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM family_payment_archive').fetchone()[0],1)
        self.assertEqual(self.status(),'paid');self.assertEqual(self.balances(),[7,7,9,8])
        self.assertEqual(self.conn.execute('SELECT expires_at FROM family_payment_links').fetchone()[0],9999999999)
        self.assertEqual(list(self.conn.execute('SELECT * FROM payments')),before)
        self.assertEqual(self.client.post(self.url,data={'action':'restore'}).status_code,302)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM family_payment_archive').fetchone()[0],0)
        self.assertEqual(list(self.conn.execute('SELECT * FROM payments')),before)

    def test_owner_only_and_unpaid_cannot_archive(self):
        self.assertEqual(self.client.post(self.url,data={'action':'archive'}).status_code,409)
        self.api['require_owner']=lambda:False
        for action in ('cancel','archive','restore'):
            self.assertEqual(self.client.post(self.url,data={'action':action}).status_code,403)
        self.assertEqual(self.status(),'creating')
