"""Guest checkout integration: disposable SQLite, actual production ledger, fake Stripe."""
import ast, hashlib, os, re, sqlite3, tempfile, unittest
from pathlib import Path
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask, session
from quick_pay import install_quick_pay, ensure_schema

class Sessions:
    def __init__(self): self.calls=[]; self.objects={}; self.keys={}; self.timeout=False
    def create(self, **kw):
        self.calls.append(kw); key=kw['idempotency_key']
        if key not in self.keys:
            sid='cs_test_'+str(len(self.keys)+1); self.keys[key]=sid
            self.objects[sid]=dict(id=sid,url='https://checkout.stripe.com/'+sid,status='open',payment_status='unpaid',mode='payment',currency='usd',amount_total=sum(x['price_data']['unit_amount']*x['quantity'] for x in kw['line_items']),metadata=kw['metadata'],payment_intent='pi_test')
        if self.timeout: self.timeout=False; raise TimeoutError('response lost')
        return self.objects[self.keys[key]]
    def retrieve(self,key): return self.objects[key].copy()
    def expire(self,key): self.objects[key]['status']='expired'; return self.retrieve(key)

class QuickPayTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=self.tmp.name+'/test.db'
        self.connect=lambda *a,**kw:sqlite3.connect(self.path)
        with self.connect() as c:
            c.executescript('''CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,amount REAL,status,charge_lessons REAL,invoice_type,enrollment_id,credits_applied INTEGER DEFAULT 0,coverage_title TEXT DEFAULT '',coverage_class TEXT DEFAULT '',coverage_start TEXT DEFAULT '',coverage_note TEXT DEFAULT '',due_date TEXT DEFAULT '');
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO settings VALUES('quick_pay_card_enabled','1');
            INSERT INTO settings VALUES('quick_pay_card_rate_bps','290');
            CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name,phone,email,active INTEGER);
            CREATE TABLE enrollments(id INTEGER PRIMARY KEY,course_type_name,teacher_name,lessons_left REAL,updated_at,duration INTEGER DEFAULT 30);
            CREATE TABLE invoice_allocations(id INTEGER PRIMARY KEY,invoice_id,parent_id,amount REAL,status,lock_token,locked_at,payment_method,stripe_checkout_session_id,stripe_payment_intent_id,paid_at,manual_payment_status,updated_at);
            CREATE TABLE payments(id INTEGER PRIMARY KEY,student_name,amount REAL,lessons_added REAL,payment_method,payment_date,enrollment_id,course_type_name,teacher_name,package_name,notes,visible_to_parent);
            CREATE TABLE student_ledger(id INTEGER PRIMARY KEY,student_name,entry_type,amount REAL,description,related_invoice_id,related_payment_id,related_schedule_id,created_at);
            INSERT INTO invoices(id,student_name,amount,status,charge_lessons,invoice_type,enrollment_id,credits_applied) VALUES(1,'Test Student',550,'unpaid',10,'tuition',1,0);
            INSERT INTO parent_profiles VALUES(2,'Test Guardian','5550100','test@example.invalid',1);
            INSERT INTO enrollments(id,course_type_name,teacher_name,lessons_left,updated_at) VALUES(1,'Piano','Teacher',0,'');
            INSERT INTO invoice_allocations(id,invoice_id,parent_id,amount,status) VALUES(3,1,2,550,'unpaid');''')
            ensure_schema(c.cursor())
        self.provider=Sessions(); self.permission=True; self.notices=[]
        self.app=Flask('test'); self.app.secret_key='test'; self.app.testing=True
        def refresh(cur, iid):
            states=[r[0] for r in cur.execute('SELECT status FROM invoice_allocations WHERE invoice_id=?',(iid,)).fetchall()]
            status='paid' if all(s=='paid' for s in states) else 'payment_processing' if 'processing' in states else 'unpaid'
            cur.execute('UPDATE invoices SET status=? WHERE id=?',(status,iid)); return status
        self.api=dict(sqlite3=SimpleNamespace(connect=self.connect),os=os,date=date,datetime=datetime,
            ensure_guardian_billing_schema=lambda:None,require_owner=lambda:session.get('owner',False),
            parent_can_access_student=lambda *a:self.permission,parent_has_student_permission=lambda *a:self.permission,
            configure_stripe=lambda:True,stripe=SimpleNamespace(checkout=SimpleNamespace(Session=self.provider)),
            public_url_for=lambda p:'https://billing.example.invalid'+p,hmusic_csrf_token=lambda:'test',
            refresh_invoice_status_from_allocations=refresh,notify_parent_payment_confirmed=lambda *a,**kw:self.notices.append((a,kw)),
            invoice_credit_to_grant=lambda *a:10,sync_invoice_allocations=lambda *a:[])
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='record_invoice_allocation_paid')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.api)
        install_quick_pay(self.app,self.api); self.client=self.app.test_client()
        self.env=patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':'whsec_test'}); self.env.start()
    def tearDown(self): self.env.stop(); self.tmp.cleanup()
    def make_link(self):
        with self.client.session_transaction() as s:s['owner']=True
        r=self.client.post('/owner/invoice/1/quick-pay',data={'action':'create','allocation_id':'3','payment_description':'10 private piano lessons, 30 minutes, teacher Teacher.','offer_card':'1'})
        self.assertEqual(r.status_code,200,r.text)
        token=re.search(r'https://billing.example.invalid/p/([A-Za-z0-9_-]+)',r.text)[1]
        with self.client.session_transaction() as s:s.clear()
        self.assertEqual(self.client.get('/p/'+token).status_code,200)
        return token
    def checkout(self,t,method='card'):return self.client.post('/p/'+t+'/checkout',data={'method':method,'fee_consent':'1'})
    def setup_sms(self):
        self.sms_calls=[]
        self.api.update(sms_config_status=lambda:(True,[]),
            hmusic_normalize_sms_phone=lambda p:'+16505550100' if p else None,
            send_sms_delivery=lambda *args:(self.sms_calls.append(args) or (True,'accepted')))
    def send_link(self,t):
        with self.client.session_transaction() as s:s['owner']=True
        return self.client.post('/owner/invoice/1/quick-pay',data={'action':'send_sms','token':t})
    def test_sms_explicit_recipient_and_double_click(self):
        self.setup_sms(); t=self.make_link()
        self.assertEqual(self.sms_calls,[])
        self.assertIn('SMS accepted',self.send_link(t).text)
        self.assertEqual(self.send_link(t).status_code,200)
        self.assertEqual(len(self.sms_calls),1)
        self.assertEqual(self.sms_calls[0][0],'+16505550100')
        self.assertEqual(self.sms_calls[0][3],'https://billing.example.invalid/p/'+t)
    def test_sms_rejects_changed_invoice_and_permission(self):
        self.setup_sms(); t=self.make_link(); self.permission=False
        self.assertEqual(self.send_link(t).status_code,409)
        self.permission=True
        with self.connect() as c:c.execute('UPDATE invoices SET amount=600')
        self.assertEqual(self.send_link(t).status_code,409)
        self.assertEqual(self.sms_calls,[])
    def test_sms_requires_owner_and_provider(self):
        self.setup_sms(); t=self.make_link()
        self.assertEqual(self.client.post('/owner/invoice/1/quick-pay',data={'action':'send_sms','token':t}).status_code,302)
        self.api['sms_config_status']=lambda:(False,['TWILIO_ACCOUNT_SID'])
        self.assertEqual(self.send_link(t).status_code,503)
        self.assertEqual(self.sms_calls,[])
    def test_sms_uncertain_response_does_not_resend(self):
        self.setup_sms(); t=self.make_link()
        def fail(*args):self.sms_calls.append(args); raise TimeoutError()
        self.api['send_sms_delivery']=fail
        self.assertIn('unconfirmed',self.send_link(t).text)
        self.send_link(t); self.assertEqual(len(self.sms_calls),1)
    def paid(self):
        obj=next(iter(self.provider.objects.values())); obj.update(status='complete',payment_status='paid')
        return self.api['handle_quick_pay_event'](dict(type='checkout.session.completed',data={'object':obj}))
    def test_card_repeat_click_and_callbacks_credit_once(self):
        t=self.make_link(); self.assertEqual(self.checkout(t).status_code,303); self.assertEqual(self.checkout(t).status_code,303)
        self.assertEqual(len(self.provider.keys),1); self.assertEqual(self.paid(),('ok',200)); self.assertEqual(self.paid(),('ok',200))
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*),SUM(amount) FROM payments').fetchone(),(1,550.0))
            self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],10)
            self.assertEqual(c.execute('SELECT payment_method FROM payments').fetchone()[0],'Stripe Card')
        self.assertEqual(len(self.notices),1)
        self.assertIn('Payment received',self.client.get('/p/'+t).text)
    def test_ach_processing_has_no_credits(self):
        t=self.make_link(); self.checkout(t,'ach'); obj=next(iter(self.provider.objects.values())); obj['status']='complete'
        self.api['handle_quick_pay_event'](dict(type='checkout.session.completed',data={'object':obj}))
        with self.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
        self.paid()
        with self.connect() as c:self.assertEqual(c.execute('SELECT payment_method FROM payments').fetchone()[0],'Stripe ACH')
    def test_timeout_retry_reuses_identical_session(self):
        t=self.make_link(); self.provider.timeout=True
        self.assertEqual(self.checkout(t).status_code,503); self.assertEqual(self.checkout(t).status_code,303)
        self.assertEqual(len(self.provider.keys),1); self.assertEqual(self.provider.calls[0],self.provider.calls[1])
    def test_changed_amount_expired_token_block(self):
        t=self.make_link()
        with self.connect() as c:c.execute('UPDATE invoice_allocations SET amount=600')
        self.assertEqual(self.checkout(t).status_code,409)
        with self.connect() as c:c.execute('UPDATE quick_payment_links SET expires_at=0')
        self.assertEqual(self.client.get('/p/'+t).status_code,404); self.assertEqual(len(self.provider.calls),0)
    def test_permissions_and_unknown_token(self):
        self.assertEqual(self.client.get('/owner/invoice/1/quick-pay').status_code,302)
        self.assertEqual(self.client.get('/p/wrong').status_code,404)
        t=self.make_link(); self.permission=False; self.assertEqual(self.checkout(t).status_code,409)
    def test_existing_checkout_blocks_second_payment(self):
        t=self.make_link()
        with self.connect() as c:c.execute("UPDATE invoice_allocations SET stripe_checkout_session_id='cs_existing'")
        self.assertEqual(self.checkout(t).status_code,409); self.assertEqual(len(self.provider.calls),0)
    def test_mismatched_amount_and_unsigned_event_rejected(self):
        t=self.make_link(); self.checkout(t); obj=next(iter(self.provider.objects.values())).copy(); obj.update(payment_status='paid',amount_total=1)
        event=dict(type='checkout.session.completed',data={'object':obj})
        self.assertEqual(self.api['handle_quick_pay_event'](event)[1],500)
        with patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':''}):self.assertEqual(self.api['handle_quick_pay_event'](event)[1],503)
        with self.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],0)
    def test_split_payment_only_assigned_share(self):
        with self.connect() as c:
            c.execute('UPDATE invoice_allocations SET amount=200 WHERE id=3')
            c.execute("INSERT INTO invoice_allocations(id,invoice_id,parent_id,amount,status) VALUES(4,1,9,350,'unpaid')")
        t=self.make_link(); self.checkout(t); self.assertEqual(next(iter(self.provider.objects.values()))['amount_total'],20580); self.paid()
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT SUM(amount) FROM payments').fetchone()[0],200)
            self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],0)
    def test_package_change_invalidates_link_even_if_share_unchanged(self):
        t=self.make_link()
        with self.connect() as c:c.execute('UPDATE invoices SET charge_lessons=20')
        self.assertEqual(self.checkout(t).status_code,409)
        self.assertEqual(len(self.provider.calls),0)

    def test_active_combined_payment_blocks_guest(self):
        t=self.make_link()
        from family_billing import ensure_schema
        with self.connect() as c:
            ensure_schema(c.cursor())
            c.execute("INSERT INTO family_payments(id,parent_id,request_key,method,status,total_cents,created_at) VALUES(7,2,'test','Stripe ACH','pending',55000,'now')")
            c.execute("INSERT INTO family_payment_items(family_payment_id,allocation_id,invoice_id,student_name,lessons,amount_cents) VALUES(7,3,1,'Test Student',10,55000)")
        self.assertEqual(self.checkout(t).status_code,409)

    def test_owner_mutations_are_blocked_during_checkout(self):
        self.app.add_url_rule('/legacy-edit/<int:invoice_id>',endpoint='edit_invoice',view_func=lambda invoice_id:'changed',methods=['POST'])
        t=self.make_link(); self.checkout(t)
        self.assertEqual(self.client.post('/legacy-edit/1').status_code,409)

    def test_credit_total_restrictions_and_separate_fee(self):
        t=self.make_link(); page=self.client.get('/p/'+t).text
        self.assertIn('$565.95',page); self.assertIn('What you are paying for',page)
        self.checkout(t); kw=self.provider.calls[0]
        self.assertEqual(kw['payment_method_options']['card']['restrictions']['funding_types_blocked'],['debit','prepaid'])
        self.assertEqual(kw['line_items'][1]['price_data']['unit_amount'],1595)
        self.assertEqual(kw['stripe_version'],'2026-09-30.endive')
        self.paid()
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT SUM(amount) FROM payments').fetchone()[0],550)
            self.assertEqual(c.execute('SELECT fee_cents FROM quick_payment_links').fetchone()[0],1595)
        self.assertIn('$565.95',self.client.get('/p/'+t).text)

    def test_no_credit_checkout_without_explicit_consent(self):
        t=self.make_link()
        self.assertEqual(self.client.post('/p/'+t+'/checkout',data={'method':'card'}).status_code,400)
        self.assertEqual(len(self.provider.calls),0)

    def test_ach_only_by_default_and_no_fee(self):
        with self.connect() as c:c.execute('DELETE FROM settings')
        t=self.make_link();page=self.client.get('/p/'+t).text
        self.assertNotIn('by credit card',page); self.assertEqual(self.checkout(t).status_code,400)
        self.assertEqual(self.checkout(t,'ach').status_code,303)
        self.assertEqual(len(self.provider.calls[0]['line_items']),1)
        self.assertEqual(self.provider.calls[0]['metadata']['surcharge_cents'],'0')

    def test_card_settings_require_rate_and_confirmation(self):
        with self.client.session_transaction() as s:s['owner']=True
        self.assertEqual(self.client.post('/owner/quick-pay-settings',data={'card_enabled':'1','card_percent':'3.5','card_requirements':'1'}).status_code,400)
        self.assertEqual(self.client.post('/owner/quick-pay-settings',data={'card_enabled':'1','card_percent':'2.9'}).status_code,400)
        self.assertEqual(self.client.post('/owner/quick-pay-settings',data={'card_enabled':'1','card_percent':'2.9','card_requirements':'1'}).status_code,200)

    def test_description_escaped_and_course_snapshot_enforced(self):
        t=self.make_link()
        with self.connect() as c:c.execute("UPDATE quick_payment_links SET payment_description='<script>alert(1)</script>'")
        text=self.client.get('/p/'+t).text
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',text);self.assertNotIn('<script>alert(1)</script>',text)
        with self.connect() as c:c.execute("UPDATE invoices SET coverage_title='Different course'")
        self.assertEqual(self.checkout(t,'ach').status_code,409)

    def test_revoke_expires_stripe_before_unlock(self):
        t=self.make_link(); self.checkout(t)
        with self.client.session_transaction() as s:s['owner']=True
        r=self.client.post('/owner/invoice/1/quick-pay',data={'action':'revoke','digest':hashlib.sha256(t.encode()).hexdigest()})
        self.assertEqual(r.status_code,302,r.text); self.assertEqual(next(iter(self.provider.objects.values()))['status'],'expired')
        self.assertEqual(self.client.get('/p/'+t).status_code,404)
        with self.connect() as c:self.assertEqual(c.execute('SELECT status,lock_token FROM invoice_allocations').fetchone(),('unpaid',None))

if __name__=='__main__': unittest.main()
