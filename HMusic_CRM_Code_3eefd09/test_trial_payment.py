import sqlite3,tempfile,unittest
from types import SimpleNamespace as NS
from flask import Flask
from trial_payment import register_trial_payment
class TrialTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/db';self.leads=[];self.notices=[];self.calls=[];self.obj={};self.timeout=False
  def create(**kw):
   self.calls.append(kw);self.obj.update(id='cs_test',url='https://checkout.stripe.com/test',metadata=kw['metadata'],mode='payment',currency='usd',amount_total=kw['line_items'][0]['price_data']['unit_amount'],payment_status='unpaid',status='open')
   if self.timeout:raise TimeoutError()
   return self.obj
  self.api=dict(sqlite3=NS(connect=lambda *a,**k:sqlite3.connect(self.path)),os=NS(environ={'STRIPE_WEBHOOK_SECRET':'test'}),stripe=NS(checkout=NS(Session=NS(create=create,retrieve=lambda id:self.obj)),PaymentIntent=NS(retrieve=lambda id:{'status':'requires_payment_method'})),configure_stripe=lambda:True,public_url_for=lambda p:'https://school.example'+p,create_notification=lambda *a,**k:self.notices.append(a),v35_insert_trial_lead=lambda data,**kw:self.leads.append(data) or 17,hmusic_csrf_token=lambda:'test',require_owner=lambda:True)
  self.app=Flask(__name__);self.app.secret_key='test-only';register_trial_payment(self.app,self.api)
  self.data=dict(student_name='Child',parent_email='parent@example.com',trial_duration='30 mins',trial_fee='$1')
  self.app.add_url_rule('/submit','submit',lambda:self.api['start_trial_payment'](self.data),methods=['POST']);self.client=self.app.test_client()
 def tearDown(self):self.tmp.cleanup()
 def order(self):
  c=sqlite3.connect(self.path)
  try:return c.execute('SELECT amount_cents,status FROM trial_payment_orders').fetchone()
  finally:c.close()
 def event(self,kind='checkout.session.completed'):
  return self.api['handle_trial_payment_event']({'type':kind,'data':{'object':self.obj}})
 def test_server_fee_not_client_price(self):
  self.assertEqual(self.client.post('/submit').status_code,303);self.assertEqual(self.order()[0],3000);self.assertEqual(self.calls[0]['payment_method_types'],['us_bank_account']);self.assertNotIn('invoice_id',self.calls[0]['metadata'])
 def test_repeat_reuses_lead_and_checkout(self):
  self.client.post('/submit');self.client.post('/submit');self.assertEqual(len(self.leads),1);self.assertEqual(len(self.calls),1)
 def test_processing_paid_and_duplicate_callbacks(self):
  self.client.post('/submit');self.obj['status']='complete';self.event();self.assertEqual(self.order()[1],'processing');self.obj['payment_status']='paid';self.event('checkout.session.async_payment_succeeded');self.event('checkout.session.async_payment_succeeded');self.assertEqual(self.order()[1],'paid');self.assertEqual(len(self.notices),2);self.obj['payment_status']='unpaid';self.event('checkout.session.async_payment_failed');self.assertEqual(self.order()[1],'paid')
 def test_mismatch_cannot_mark_paid(self):
  self.client.post('/submit');self.obj.update(amount_total=1,payment_status='paid');self.assertEqual(self.event()[1],500);self.assertEqual(self.order()[1],'checkout')
 def test_requires_signed_webhook(self):
  self.client.post('/submit');self.api['os'].environ.clear();self.assertEqual(self.event()[1],503)
 def test_timeout_retry_same_key(self):
  self.timeout=True;self.assertEqual(self.client.post('/submit').status_code,503);self.timeout=False;self.assertEqual(self.client.post('/submit').status_code,303);self.assertEqual(self.calls[0],self.calls[1]);self.assertEqual(len(self.leads),1)
 def test_failure_is_not_paid(self):
  self.client.post('/submit');self.obj.update(status='complete',payment_intent='pi_test');self.event('checkout.session.async_payment_failed');self.assertEqual(self.order()[1],'failed')
 def test_notification_failure_is_retried_after_payment_was_saved(self):
  self.client.post('/submit');self.obj.update(status='complete',payment_status='paid')
  def fail(*a,**kw):raise RuntimeError('notification unavailable')
  self.api['create_notification']=fail;self.assertEqual(self.event()[1],500);self.assertEqual(self.order()[1],'paid')
  self.api['create_notification']=lambda *a,**kw:self.notices.append(a)
  self.assertEqual(self.event(),('ok',200));self.assertEqual(len(self.notices),1)
 def test_unknown_token_and_owner_access(self):
  self.assertEqual(self.client.post('/trial-payment/unknown/checkout').status_code,404);self.api['require_owner']=lambda:False;self.assertEqual(self.client.get('/owner/trial-payment/17').status_code,302)
if __name__=='__main__':unittest.main()

class PublicFormPaymentTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import ast
  from pathlib import Path
  cls.node=next(n for n in ast.parse(Path(__file__).with_name('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='public_trial_request');cls.node.decorator_list=[]
 def setUp(self):
  import ast
  from flask import request,session
  self.started=[];self.saved=[]
  self.ns=dict(request=request,session=session,ensure_v17_schema=lambda:None,v35_public_trial_form=lambda *a,**k:'invalid',start_trial_payment=lambda d:self.started.append(d) or 'checkout',v35_insert_trial_lead=lambda d,**k:self.saved.append(d) or 1,v35_public_trial_thank_you=lambda *a:'received')
  exec(compile(ast.Module(body=[self.node],type_ignores=[]),'app.py','exec'),self.ns)
  self.app=Flask(__name__);self.app.secret_key='test';self.app.add_url_rule('/trial',view_func=self.ns['public_trial_request'],methods=['POST'])
  self.data=dict(student_name='Child',parent_name='Parent',parent_email='parent@example.com',age='5',trial_duration='30 mins',trial_fee='$1',payment_method='ACH',preferred_date_1='Monday',preferred_time_1='16:00')
 def test_ach_form_uses_server_fee_and_guest_checkout(self):
  self.assertEqual(self.app.test_client().post('/trial',data=self.data).data,b'checkout');self.assertEqual(self.started[0]['trial_fee'],'$30');self.assertFalse(self.saved)
 def test_zelle_preserves_request_only_flow(self):
  self.data['payment_method']='Zelle';self.assertEqual(self.app.test_client().post('/trial',data=self.data).data,b'received');self.assertEqual(len(self.saved),1);self.assertFalse(self.started)
 def test_invalid_duration_cannot_start_payment(self):
  self.data['trial_duration']='1 mins';self.app.test_client().post('/trial',data=self.data);self.assertFalse(self.started)
 def test_15_minutes_age_rule(self):
  self.data.update(trial_duration='15 mins',age='6');self.app.test_client().post('/trial',data=self.data);self.assertFalse(self.started)
