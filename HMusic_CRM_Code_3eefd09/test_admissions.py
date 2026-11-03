import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask, session, request
from admissions import register_admissions, seed, ensure_schema, quote, sync_order, digest, now

class AdmissionsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/db'
  self.app=Flask(__name__);self.app.secret_key='test';self.app.logger.disabled=True
  self.provider=SimpleNamespace(checkout=SimpleNamespace(Session=SimpleNamespace(create=Mock(),retrieve=Mock(),expire=Mock())))
  self.api={'sqlite3':SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)), 'require_owner':lambda:session.get('user_role')=='owner','hmusic_csrf_token':lambda:'csrf','configure_stripe':lambda:True,'stripe':self.provider,'public_url_for':lambda p:'https://school.example'+p}
  register_admissions(self.app,self.api)
  @self.app.post('/test-register')
  def test_register():
   o=self.api['admissions_prepare'](request.form)
   return self.api['admissions_finish'](o,1)
  self.client=self.app.test_client();self.catalog=self.client.get('/api/website/admissions').json;self.teacher=self.catalog['teachers'][0]['id']
 def tearDown(self):self.tmp.cleanup()
 def owner(self):
  with self.client.session_transaction() as s:s['user_role']='owner'
 def coupon(self,**kw):
  self.owner();d=dict(code='WELCOME10',kind='percent',value=1000,teacher_ids=[],partner_id='',starts_at='',ends_at='',max_uses=20,per_student=1,min_cents=0,active=True,notes='');d.update(kw)
  r=self.client.post('/api/admissions/coupons',json=d);self.assertEqual(r.status_code,200,r.data);return d
 def order(self,code='',key='first'):
  with self.client.session_transaction() as s:s['admissions_keys']=[key]
  r=self.client.post('/test-register',data={'teacher_id':self.teacher,'lesson_minutes':'30','admission_code':code,'admissions_key':key,'parent_email':'parent@example.com','student_name':'Child','age':'7','policy_version':self.catalog['policy']['version'],'guardian_signature':'Parent','signed_date':'2026-11-03'})
  self.assertEqual(r.status_code,303,r.data)
  return r.location
 def test_partner_directory_and_idempotent_migration(self):
  self.assertEqual(len(self.catalog['partners']),4)
  for school in self.catalog['partners']:
   for course in school['programs']:
    self.assertEqual(course['schedule'],'Follow your school schedule. Our staff will follow up with you.')
    self.assertTrue(course['informationUrl'].startswith('https://www.hmusicandart.com/'))
  with closing(sqlite3.connect(self.path)) as conn:
   cfg=json.loads(conn.execute('SELECT published FROM admissions_settings').fetchone()[0]);cfg['partners'][0]['address']='Edited address'
   conn.execute('UPDATE admissions_settings SET published=?',(json.dumps(cfg),));conn.commit();ensure_schema(conn)
   self.assertEqual(json.loads(conn.execute('SELECT published FROM admissions_settings').fetchone()[0])['partners'][0]['address'],'Edited address')
 def test_partner_registration_context_and_no_generic_charge(self):
  for course,program in [('circle-piano','Group Class'),('private-instruments','Private Lesson')]:
   values={'partner_id':'dreamers-thinkers','partner_course':course,'program_interest':program}
   with self.app.test_request_context():
    self.assertIsNone(self.api['admissions_prepare'](values))
    snapshot=json.loads(self.api['admissions_partner_snapshot'](values))
    self.assertEqual(snapshot['school'],'Dreamers & Thinkers');self.assertEqual(snapshot['course_id'],course)
    with self.assertRaises(ValueError):self.api['admissions_prepare']({**values,'teacher_id':self.teacher})
   with self.app.test_request_context('/registration?partner=dreamers-thinkers&course='+course):
    html=self.api['admissions_decorate']('<html><section></section><select name="program_interest" required><option>Private Lesson</option></select>')
    self.assertIn('name="partner_course" value="'+course+'"',html);self.assertNotIn('admissions-registration.js',html)
  self.provider.checkout.Session.create.assert_not_called()
 def test_partner_registration_rejects_unknown_and_mismatched_course(self):
  with self.app.test_request_context():
   for values in [{'partner_id':'unknown','partner_course':'circle-piano'},{'partner_id':'hanlin','partner_course':'bad'},{'partner_course':'circle-piano'},{'partner_id':'hanlin','partner_course':'circle-piano','program_interest':'Private Lesson'}]:
    with self.assertRaises(ValueError):self.api['admissions_prepare'](values)
 def test_partner_course_links_and_publishing_validation(self):
  self.owner();d=self.client.get('/api/admissions/admin').json
  d['catalog']['partners'][0]['programs'][0]['registrationUrl']='javascript:alert(1)'
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,400)
  d['catalog']['partners'][0]['programs'][0]['registrationUrl']=''
  d['catalog']['partners'][0]['programs'][0]['schedule']='Mondays at 3 PM';d['publish']=True
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,200)
  self.assertEqual(self.client.get('/api/website/admissions').json['partners'][0]['programs'][0]['schedule'],'Mondays at 3 PM')
 def test_center_selection_is_validated_and_preserved(self):
  with self.app.test_request_context('/registration?location=center-edgewater'):
   html=self.api['admissions_decorate']('<html><section></section>')
   self.assertIn('951 M Edgewater',html);self.assertIn('name="center_id" value="center-edgewater"',html)
   snapshot=json.loads(self.api['admissions_partner_snapshot']({'center_id':'center-marlin'}))
   self.assertEqual(snapshot['location_id'],'center-marlin')
   with self.assertRaises(ValueError):self.api['admissions_prepare']({'center_id':'unknown'})
   with self.assertRaises(ValueError):self.api['admissions_prepare']({'center_id':'center-edgewater','partner_id':'hanlin'})
 def test_owner_guards_and_public_data(self):
  self.assertEqual(self.client.get('/admissions-admin').status_code,302)
  for path in ['/api/admissions/admin','/api/admissions/coupons','/api/admissions/orders']:
   self.assertEqual(self.client.get(path).status_code,403)
  self.assertEqual(self.client.post('/api/admissions/order-action',json={}).status_code,403)
  data=self.client.get('/api/website/admissions');self.assertEqual(data.headers['Access-Control-Allow-Origin'],'*');self.assertNotIn('coupons',data.json)
 def test_prices_include_chloe_new_tier_and_voice(self):
  chloe=next(t for t in self.catalog['teachers'] if t['name']=='Chloe Lu');self.assertEqual(chloe['prices'],{'30':60000,'45':90000,'60':120000})
  self.assertEqual(len([t for t in self.catalog['teachers'] if t['name']=='Jenny Lee']),2)
 def test_draft_publish_conflict(self):
  self.owner();d=self.client.get('/api/admissions/admin').json;d['catalog']['teachers'][0]['prices']['30']=70000
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,200)
  self.assertEqual(self.client.get('/api/website/admissions').json['teachers'][0]['prices']['30'],65000)
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,409)
  d['revision']+=1;d['publish']=True;self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,200)
  self.assertEqual(self.client.get('/api/website/admissions').json['teachers'][0]['prices']['30'],70000)
 def test_invalid_prices_and_script_urls_rejected(self):
  self.owner();d=self.client.get('/api/admissions/admin').json;d['catalog']['teachers'][0]['prices']['30']=-1
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,400)
  d['catalog']=copy.deepcopy(self.catalog);d['catalog']['events']=[dict(id='event',title='Recital',active=True,url='javascript:alert(1)')]
  self.assertEqual(self.client.post('/api/admissions/admin',json=d).status_code,400)
 def test_discount_scope_expiry_minimum_and_usage(self):
  self.coupon(max_uses=1)
  q=self.client.post('/api/admissions/quote',json={'teacher_id':self.teacher,'duration':30,'code':'welcome10','total':1}).json
  self.assertEqual(q['total'],58500);self.assertEqual(q['discount'],6500)
  self.order('WELCOME10')
  self.assertEqual(self.client.post('/api/admissions/quote',json={'teacher_id':self.teacher,'duration':30,'code':'WELCOME10'}).status_code,400)
  self.coupon(code='EXPIRED',ends_at='2000-01-01T00:00:00+00:00')
  self.assertEqual(self.client.post('/api/admissions/quote',json={'teacher_id':self.teacher,'duration':30,'code':'EXPIRED'}).status_code,400)
  self.coupon(code='SCOPED',teacher_ids=['other-teacher'])
  self.assertEqual(self.client.post('/api/admissions/quote',json={'teacher_id':self.teacher,'duration':30,'code':'SCOPED'}).status_code,400)
 def test_duplicate_registration_and_checkout_use_same_order(self):
  url=self.order();self.assertEqual(self.order(),url)
  oid=url.split('/')[2];obj={'id':'cs_first','url':'https://checkout.stripe.com/first','mode':'payment','currency':'usd','amount_total':65000,'payment_status':'unpaid','status':'open','metadata':{'admissions_order':oid}}
  self.provider.checkout.Session.create.return_value=obj;self.provider.checkout.Session.retrieve.return_value=obj
  self.assertEqual(self.client.post(url+'/checkout').location,obj['url']);self.assertEqual(self.client.post(url+'/checkout').location,obj['url'])
  self.provider.checkout.Session.create.assert_called_once();self.assertEqual(self.provider.checkout.Session.create.call_args.kwargs['idempotency_key'],'admissions-'+oid)
  self.assertEqual(self.client.get(url).status_code,200)
  with closing(sqlite3.connect(self.path)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM admissions_orders').fetchone()[0],1)
 def test_paid_requires_matching_provider_and_never_regresses(self):
  url=self.order();oid=url.split('/')[2]
  with closing(sqlite3.connect(self.path)) as c:
   c.execute("UPDATE admissions_orders SET checkout_id='cs_test' WHERE id=?",(oid,));c.commit()
   obj={'id':'cs_test','mode':'payment','currency':'usd','amount_total':1,'payment_status':'paid','status':'complete','metadata':{'admissions_order':oid}}
   with self.assertRaises(ValueError):sync_order(c,obj)
   obj['amount_total']=65000;obj['payment_status']='unpaid';self.assertEqual(sync_order(c,obj),'processing')
   obj['payment_status']='paid';self.assertEqual(sync_order(c,obj),'paid')
   obj['payment_status']='unpaid';self.assertEqual(sync_order(c,obj),'paid')
 def test_unguessable_receipt_and_paid_order_cannot_cancel(self):
  url=self.order();oid=url.split('/')[2];self.assertEqual(self.client.get('/enrollment-order/'+oid+'/wrong-token').status_code,404)
  with closing(sqlite3.connect(self.path)) as c:c.execute("UPDATE admissions_orders SET status='paid' WHERE id=?",(oid,));c.commit()
  self.owner();self.assertEqual(self.client.post('/api/admissions/order-action',json={'id':oid,'action':'cancel'}).status_code,409)
 def test_cancel_unsubmitted_order_releases_code_but_not_paid(self):
  self.coupon(max_uses=1);url=self.order('WELCOME10');oid=url.split('/')[2]
  self.assertEqual(self.client.post('/api/admissions/order-action',json={'id':oid,'action':'cancel'}).status_code,200)
  self.assertEqual(self.client.post('/api/admissions/quote',json={'teacher_id':self.teacher,'duration':30,'code':'WELCOME10'}).status_code,200)
 def test_webhook_retrieves_provider_not_unsigned_payload(self):
  self.api['handle_admissions_event'] # registered without separate webhook bypass
  url=self.order();oid=url.split('/')[2]
  with closing(sqlite3.connect(self.path)) as c:c.execute("UPDATE admissions_orders SET checkout_id='cs_real' WHERE id=?",(oid,));c.commit()
  obj={'id':'cs_real','mode':'payment','currency':'usd','amount_total':65000,'payment_status':'unpaid','status':'open','metadata':{'admissions_order':oid}}
  self.provider.checkout.Session.retrieve.return_value=obj
  with self.app.test_request_context():self.api['handle_admissions_event']({'data':{'object':{**obj,'payment_status':'paid'}}})
  with closing(sqlite3.connect(self.path)) as c:self.assertEqual(c.execute('SELECT status FROM admissions_orders WHERE id=?',(oid,)).fetchone()[0],'checkout')
 def test_policy_and_registration_form_are_current(self):
  with self.app.test_request_context('/registration?teacher='+self.teacher):
   html=self.api['admissions_decorate']('<html><body><form method="POST"><section>Student</section><div class="policy-body">Old policy</div></form></body></html>')
   self.assertIn('$15 (30 minutes)',html);self.assertNotIn('Old policy',html);self.assertIn('admissions_key',html)

if __name__=='__main__':unittest.main()

class AdmissionBillingTests(AdmissionsTests):
 def test_manager_posting_reuses_one_invoice_and_net_package_amount(self):
  import ast
  from pathlib import Path
  from datetime import datetime,date
  with closing(sqlite3.connect(self.path)) as c:
   c.executescript('''CREATE TABLE students(id INTEGER PRIMARY KEY,name TEXT);
    INSERT INTO students VALUES(1,'Child');
    CREATE TABLE course_types(id INTEGER PRIMARY KEY,name TEXT,duration INTEGER,active INTEGER,is_group INTEGER);
    INSERT INTO course_types VALUES(1,'Private Lesson',30,1,0);
    CREATE TABLE enrollments(id INTEGER PRIMARY KEY,student_name,course_type_id,course_type_name,teacher_name,duration,student_billing_method,base_price,final_price,lessons_left,status,notes,package_amount,package_lessons,auto_renew_enabled,auto_renew_lessons,created_at,updated_at);
    CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name,schedule_id,charge_lessons,amount,status,invoice_type,created_at,enrollment_id,due_date,notes,credits_applied,discount_code,discount_amount,stripe_checkout_session_id);
    CREATE TABLE inquiries(id INTEGER PRIMARY KEY,converted_enrollment_id); INSERT INTO inquiries(id) VALUES(1);''')
  source=ast.parse(Path(__file__).with_name('app.py').read_text());node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='create_enrollment_invoice');scope={'datetime':datetime,'date':date};exec(compile(ast.Module(body=[node],type_ignores=[]),'invoice','exec'),scope)
  self.api.update(ensure_v321_schema=lambda:None,ensure_guardian_billing_schema=lambda:None,create_enrollment_invoice=scope['create_enrollment_invoice'],finalize_stripe_invoice_payment=Mock(return_value=True))
  self.coupon();url=self.order('WELCOME10');oid=url.split('/')[2]
  with closing(sqlite3.connect(self.path)) as c:c.execute("UPDATE admissions_orders SET status='paid',checkout_id='cs_paid' WHERE id=?",(oid,));c.commit()
  self.owner()
  for _ in range(2):
   r=self.client.post('/api/admissions/attach',json={'id':oid,'student_id':1,'course_type_id':1});self.assertEqual(r.status_code,200,r.data)
  with closing(sqlite3.connect(self.path)) as c:
   self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT amount,discount_amount FROM invoices').fetchone(),(585,65))
   self.assertEqual(c.execute('SELECT lessons_left,package_lessons FROM enrollments').fetchone(),(0,10))

class AdmissionRouteCompatibilityTests(unittest.TestCase):
 def test_all_legacy_app_endpoint_names_can_coexist(self):
  import ast
  from pathlib import Path
  app=Flask(__name__)
  tree=ast.parse(Path(__file__).with_name('app.py').read_text())
  for n in tree.body:
   if isinstance(n,ast.FunctionDef) and any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='app' and d.func.attr in ['route','get','post'] for d in n.decorator_list):
    app.add_url_rule('/legacy/'+n.name,endpoint=n.name,view_func=lambda:'legacy')
  register_admissions(app,{'require_owner':lambda:False})
  self.assertIn('hmusic_admissions_checkout',app.view_functions)
