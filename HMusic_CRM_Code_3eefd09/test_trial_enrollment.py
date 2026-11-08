import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime,timedelta
from unittest.mock import Mock,patch
from flask import Flask,session
from werkzeug.datastructures import MultiDict
from studio_operations import Operations,LA,record,fingerprint
from trial_enrollment import Journey,register_trial_enrollment
from admissions import quote,sync_order,register_admissions

class TrialEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/db';self.connect=lambda:sqlite3.connect(self.path)
        c=self.connect();c.executescript('''
CREATE TABLE inquiries(id INTEGER PRIMARY KEY,student_name TEXT,parent_name TEXT,parent_email TEXT,phone TEXT,source TEXT,notes TEXT,created_at TEXT,status TEXT,trial_teacher TEXT,trial_date TEXT,trial_time TEXT,trial_location TEXT,trial_duration TEXT,trial_status TEXT,owner_verified INTEGER,updated_at TEXT,converted_student_name TEXT,converted_enrollment_id INTEGER,parent_profile_id INTEGER,follow_up_status TEXT);
INSERT INTO inquiries(id,student_name,parent_name,parent_email,phone,source,status) VALUES(1,'Child','Parent','parent@example.com','+15555550100','Website trial request','Inquiry');
CREATE TABLE teachers(teacher_name TEXT);INSERT INTO teachers VALUES('Xu Huang');
CREATE TABLE course_types(id INTEGER PRIMARY KEY,name TEXT,duration INTEGER,active INTEGER,is_group INTEGER);INSERT INTO course_types VALUES(1,'Piano',30,1,0);
CREATE TABLE schedule(id INTEGER PRIMARY KEY AUTOINCREMENT,student_name TEXT,teacher TEXT,lesson_date TEXT,lesson_time TEXT,duration INTEGER,classroom TEXT,location TEXT,status TEXT,weekday TEXT,schedule_type TEXT,notes TEXT,enrollment_id INTEGER,course_type_name TEXT,final_price REAL,course_type_id INTEGER,student_billing_method TEXT,student_price REAL,student_charge_amount REAL,teacher_billing_method TEXT,teacher_pay REAL,teacher_pay_amount REAL,is_group INTEGER,start_date TEXT,package_type TEXT);
CREATE TABLE teacher_time_off_requests(id INTEGER,teacher_name TEXT,start_date TEXT,end_date TEXT,start_time TEXT,end_time TEXT,all_day INTEGER,status TEXT);
CREATE TABLE students(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,teacher TEXT,parent_name TEXT,parent_email TEXT,parent_phone TEXT,lessons_left REAL);
CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY AUTOINCREMENT,parent_name TEXT,email TEXT UNIQUE,phone TEXT,password TEXT,password_hash TEXT,must_change_password INTEGER,active INTEGER,created_at TEXT,updated_at TEXT);
CREATE TABLE parent_students(parent_id INTEGER,student_name TEXT,relationship TEXT,active INTEGER,created_at TEXT,UNIQUE(parent_id,student_name));
CREATE TABLE enrollments(id INTEGER PRIMARY KEY AUTOINCREMENT,student_name TEXT,course_type_id INTEGER,course_type_name TEXT,teacher_name TEXT,duration INTEGER,student_billing_method TEXT,base_price REAL,final_price REAL,lessons_left REAL,status TEXT,notes TEXT,package_amount REAL,package_lessons INTEGER,auto_renew_enabled INTEGER,created_at TEXT,updated_at TEXT);
CREATE TABLE invoices(id INTEGER PRIMARY KEY AUTOINCREMENT,enrollment_id INTEGER,status TEXT,amount REAL,discount_code TEXT,discount_amount REAL,stripe_checkout_session_id TEXT);
CREATE TABLE parent_notification_preferences(parent_id INTEGER,billing_alerts INTEGER,lesson_reminders INTEGER);
CREATE TABLE notification_delivery_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT,related_type TEXT,related_id INTEGER);
''');c.commit();c.close()
        self.app=Flask(__name__);self.app.secret_key='test-secret';self.app.logger.disabled=True
        self.api={'require_owner':lambda:session.get('user_role')=='owner','hmusic_csrf_token':lambda:'csrf','sqlite3':type('DB',(),{'connect':lambda _,name:self.connect()})(), 'configure_stripe':lambda:True,'stripe':Mock(),'public_url_for':lambda p:'https://school.example'+p,'hmusic_public_app_url':lambda p:'https://school.example'+p,'hmusic_password_hash':lambda value:'HASH:'+value,'create_notification':Mock(return_value=1),'queue_direct_delivery':Mock(return_value=None),'queue_notification_delivery':Mock(return_value=None),'logger':self.app.logger}
        def invoice(cur,eid,*args,**kwargs):
            amount=cur.execute('SELECT package_amount FROM enrollments WHERE id=?',(eid,)).fetchone()[0]
            cur.execute("INSERT INTO invoices(enrollment_id,status,amount) VALUES(?,'unpaid',?)",(eid,amount));return cur.lastrowid
        def finalize(iid,**kw):
            c=self.connect();inv=record(c,'SELECT * FROM invoices WHERE id=?',(iid,))
            if inv['status']!='paid':
                c.execute("UPDATE invoices SET status='paid' WHERE id=?",(iid,));c.execute('UPDATE enrollments SET lessons_left=lessons_left+package_lessons WHERE id=?',(inv['enrollment_id'],));c.commit()
            c.close();return True
        self.api['get_final_pricing']=lambda *a:{'teacher_billing_method':'Per Lesson','teacher_pay':25,'teacher_pay_amount':25}
        self.api['stripe'].checkout.Session.create.return_value={'id':'cs_new','url':'https://checkout.stripe.com/test'}
        self.api.update(create_enrollment_invoice=Mock(side_effect=invoice),finalize_stripe_invoice_payment=Mock(side_effect=finalize))
        register_admissions(self.app,self.api);self.ops=Operations(self.connect,self.api);self.s=register_trial_enrollment(self.app,self.ops,self.api);self.client=self.app.test_client()
        self.day=(datetime.now(LA).date()+timedelta(days=3)).isoformat();self.jid=self.s.create(1,['email'])
        self.s.add_window(MultiDict([('teacher_id','xu-huang-instrument'),('course_type_id','1'),('date_from',self.day),('date_until',self.day),('start_time','09:00'),('end_time','12:00'),('classroom','A'),('location','Center'),('weekdays',str(datetime.fromisoformat(self.day).weekday()))]))
        self.dates=[(datetime.now(LA).date()+timedelta(days=10+7*i)).isoformat() for i in range(10)]
        self.s.add_plan(self.jid,{'teacher_id':'xu-huang-instrument','course_type_id':1,'dates':'\n'.join(self.dates),'time':'10:00','classroom':'A','location':'Center'})
    def tearDown(self):self.tmp.cleanup()
    def j(self):
        c=self.s.db()
        try:return self.s.get(c,self.jid)
        finally:c.close()
    def offer(self):self.s.offer(self.jid,dict(start=self.day,end=self.day,course_type_id=1,trial_fee='30'))
    def trial(self):
        self.offer();j=self.j();self.s.select(self.jid,0,fingerprint(json.loads(j['candidates'])));self.s.approve(self.jid)
    def followup(self):
        self.trial();c=self.s.db();j=self.j();end=datetime.now(LA)-timedelta(hours=3)
        c.execute("UPDATE schedule SET lesson_date=?,lesson_time=?,status='present' WHERE id=?",(end.date().isoformat(),(end-timedelta(minutes=30)).strftime('%H:%M'),j['trial_schedule_id']));c.commit();c.close()
        self.s.advance(self.jid,datetime.now(LA));return self.j()
    def accept(self):
        j=self.followup();p=json.loads(j['plans'])[0]
        oid=self.s.accept(self.jid,p['id'],'Parent',p['quote']['policy']['version']);return oid
    def pay(self):
        oid=self.accept();c=self.s.db();o=record(c,'SELECT * FROM admissions_orders WHERE id=?',(oid,));c.execute('UPDATE admissions_orders SET checkout_id=? WHERE id=?',('cs_verified',oid));c.commit()
        sync_order(c,{'id':'cs_verified','metadata':{'admissions_order':oid},'mode':'payment','currency':'usd','amount_total':o['total'],'payment_status':'paid'});c.close();return oid
    def test_end_to_end_and_payment_replay(self):
        self.pay();self.s.advance(self.jid,datetime.now(LA));self.s.advance(self.jid,datetime.now(LA));self.s.fulfill(self.jid)
        j=self.j();self.assertEqual(j['stage'],'enrolled');ids=json.loads(j['result'])['schedule_ids'];self.assertEqual(len(ids),10)
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM schedule').fetchone()[0],11);self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],10);self.assertEqual(c.execute('SELECT count(*) FROM invoices').fetchone()[0],1)
        password=c.execute('SELECT password_hash FROM parent_profiles').fetchone()[0];self.assertTrue(password.startswith('HASH:'));self.assertNotIn('1234',password)
        self.assertEqual(c.execute("SELECT count(*) FROM studio_tasks WHERE task_key LIKE '%:welcome'").fetchone()[0],1);self.assertEqual(c.execute('SELECT first_schedule_id FROM studio_workflows').fetchone()[0],ids[0]);c.close()
    def test_public_does_not_create_account_before_verified_payment(self):
        oid=self.accept();j=self.j();self.assertEqual(j['stage'],'payment');self.s.advance(self.jid,datetime.now(LA));c=self.connect()
        self.assertEqual(c.execute('SELECT count(*) FROM parent_profiles').fetchone()[0],0);self.assertEqual(c.execute("SELECT count(*) FROM schedule WHERE enrollment_id IS NOT NULL").fetchone()[0],0);c.close()
        self.assertEqual(self.client.get(self.s.path(j)).status_code,200)
        order=self.client.get(self.s.order_path(j));self.assertEqual(order.status_code,200);self.assertIn(b'Continue to secure ACH payment',order.data)
    def test_processing_and_forged_amount_never_fulfill(self):
        oid=self.accept();c=self.s.db();o=record(c,'SELECT * FROM admissions_orders WHERE id=?',(oid,));c.execute("UPDATE admissions_orders SET checkout_id='cs_verified' WHERE id=?",(oid,));c.commit()
        obj={'id':'cs_verified','metadata':{'admissions_order':oid},'mode':'payment','currency':'usd','amount_total':o['total'],'payment_status':'unpaid','status':'complete'}
        sync_order(c,obj);self.assertEqual(record(c,'SELECT status FROM admissions_orders WHERE id=?',(oid,))['status'],'processing')
        with self.assertRaises(ValueError):sync_order(c,{**obj,'amount_total':1,'payment_status':'paid'})
        c.close();self.s.advance(self.jid,datetime.now(LA));self.assertEqual(self.j()['stage'],'payment')
    def test_payment_conflict_preserves_paid_order_and_creates_no_partial_lessons(self):
        oid=self.pay();c=self.connect();c.execute("INSERT INTO schedule(student_name,teacher,lesson_date,lesson_time,duration,classroom,location,status) VALUES('Other','Xu Huang',?,'10:00',30,'A','Center','scheduled')",(self.dates[-1],));c.commit();c.close()
        self.s.process();self.assertEqual(self.j()['stage'],'attention');c=self.connect();self.assertEqual(c.execute('SELECT status FROM admissions_orders WHERE id=?',(oid,)).fetchone()[0],'paid');self.assertEqual(c.execute("SELECT count(*) FROM schedule WHERE enrollment_id IS NOT NULL").fetchone()[0],0);c.close()
    def test_same_name_does_not_link_wrong_family(self):
        self.pay();c=self.connect();c.execute("INSERT INTO students(name,parent_email) VALUES('Child','other@example.com')");c.commit();c.close();self.s.process();self.assertEqual(self.j()['stage'],'attention');self.api['create_enrollment_invoice'].assert_not_called()
    def test_trial_requires_owner_approval_and_rechecks_conflict(self):
        self.offer();j=self.j();self.s.select(self.jid,0,fingerprint(json.loads(j['candidates'])));self.assertEqual(self.j()['stage'],'selected')
        c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM schedule').fetchone()[0],0);s=json.loads(self.j()['selected']);c.execute("INSERT INTO schedule(student_name,teacher,lesson_date,lesson_time,duration,classroom,location,status) VALUES('Other',?,?,?,30,'A','Center','scheduled')",(s['teacher'],s['date'],s['time']));c.commit();c.close()
        with self.assertRaises(ValueError):self.s.approve(self.jid)
    def test_trial_approval_replay_and_stale_choice(self):
        self.offer()
        with self.assertRaises(ValueError):self.s.select(self.jid,0,'old-version')
        j=self.j();self.s.select(self.jid,0,fingerprint(json.loads(j['candidates'])));self.s.approve(self.jid);self.s.approve(self.jid);c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM schedule').fetchone()[0],1);c.close()
    def test_cross_midnight_followup_is_not_missed_and_deduped(self):
        self.trial();c=self.connect();j=self.j();end=datetime.now(LA).replace(hour=23,minute=30)-timedelta(days=1)
        c.execute("UPDATE schedule SET lesson_date=?,lesson_time='23:00',status='present' WHERE id=?",(end.date().isoformat(),j['trial_schedule_id']));c.commit();c.close();self.s.advance(self.jid,end+timedelta(hours=1));j=self.j();self.assertEqual(j['stage'],'followup')
        c=self.connect();self.assertEqual(c.execute("SELECT count(*) FROM studio_tasks WHERE task_key LIKE '%:post-trial'").fetchone()[0],0);c.close()
        self.s.advance(self.jid,end+timedelta(hours=2));self.s.advance(self.jid,end+timedelta(hours=4));c=self.connect();self.assertEqual(c.execute("SELECT count(*) FROM studio_tasks WHERE task_key LIKE '%:post-trial'").fetchone()[0],1);c.close()
    def test_paused_journey_cancels_pending_send(self):
        self.offer();c=self.s.db();c.execute('UPDATE studio_enrollment_journeys SET enabled=0 WHERE id=?',(self.jid,));c.commit();task=record(c,'SELECT * FROM studio_tasks LIMIT 1');c.close();self.assertTrue(self.ops.deliver(task)['cancelled']);self.api['queue_direct_delivery'].assert_not_called()
    def test_new_module_does_not_activate_historical_families(self):
        c=self.connect();c.execute("INSERT INTO inquiries(id,student_name,parent_email) VALUES(2,'Historical','old@example.com')");c.commit();c.close();self.s.process();c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM studio_enrollment_journeys').fetchone()[0],1);c.close()
    def test_unauthorized_owner_and_tampered_family_link(self):
        self.assertEqual(self.client.get('/studio-enrollment').status_code,302);self.assertEqual(self.client.get('/trial-enrollment/forged').status_code,404)
        with self.client.session_transaction() as s:s['user_role']='owner'
        r=self.client.get('/studio-enrollment');self.assertEqual(r.status_code,200);self.assertIn('试听到报名'.encode(),r.data)
    def test_price_change_blocks_old_plan(self):
        j=self.followup();p=json.loads(j['plans'])[0];c=self.s.db();cfg=json.loads(c.execute('SELECT published FROM admissions_settings').fetchone()[0]);cfg['teachers'][0]['prices']['30']+=100;c.execute('UPDATE admissions_settings SET published=?',(json.dumps(cfg),));c.commit();c.close()
        with self.assertRaises(ValueError):self.s.accept(self.jid,p['id'],'Parent',p['quote']['policy']['version'])
    def test_changed_contact_does_not_receive_frozen_family_link(self):
        self.offer();c=self.s.db();task=record(c,'SELECT * FROM studio_tasks LIMIT 1');c.execute("UPDATE inquiries SET parent_email='other@example.com' WHERE id=1");c.commit();c.close();self.assertEqual(self.ops.deliver(task)['reason'],'family_identity_changed')
    def test_cancelled_trial_never_follows_up(self):
        self.trial();c=self.connect();c.execute("UPDATE schedule SET status='absent'");c.commit();c.close();self.s.process();self.assertEqual(self.j()['stage'],'attention')
    def test_activation_replaces_only_this_familys_legacy_followups(self):
        c=self.s.db();c.execute("INSERT INTO inquiries(id,student_name,parent_email) VALUES(2,'New Child','new@example.com')");c.execute("INSERT INTO studio_workflows VALUES(2,NULL,'[\"email\"]','Old follow-up',1,'old')");c.execute("INSERT INTO studio_workflows VALUES(3,NULL,'[\"email\"]','Unrelated follow-up',1,'old')");c.commit();c.close()
        self.s.create(2,['email']);c=self.s.db();self.assertEqual(c.execute('SELECT enabled FROM studio_workflows WHERE inquiry_id=2').fetchone()[0],0);self.assertEqual(c.execute('SELECT enabled FROM studio_workflows WHERE inquiry_id=3').fetchone()[0],1);c.close()
    def test_parent_reply_suppresses_redundant_followup(self):
        j=self.followup();c=self.s.db();c.execute("CREATE TABLE studio_communications(direction TEXT,family_refs TEXT,received_at TEXT)");c.execute("INSERT INTO studio_communications VALUES('inbound',?,?)",(json.dumps(['inquiry:1']),datetime.now(LA).isoformat()));c.commit();task=record(c,"SELECT * FROM studio_tasks WHERE task_key LIKE '%:post-trial'");c.close();self.assertEqual(self.ops.deliver(task)['reason'],'parent_already_replied')
    def test_dispatch_uses_family_link_and_records_accepted_delivery_once(self):
        self.offer()
        def queue(*a,**kw):
            c=self.connect();cur=c.execute("INSERT INTO notification_delivery_queue(status,related_type,related_id) VALUES('pending','studio_task',?)",(kw['related_id'],));qid=cur.lastrowid;c.commit();c.close();return qid
        def send(qid):
            c=self.connect();c.execute("UPDATE notification_delivery_queue SET status='sent' WHERE id=?",(qid,));c.commit();c.close()
        self.api['queue_direct_delivery']=Mock(side_effect=queue);self.api['send_queued_email_now']=Mock(side_effect=send)
        self.ops.tick();self.ops.tick();self.api['send_queued_email_now'].assert_called_once()
        link=self.api['queue_direct_delivery'].call_args.args[4];self.assertTrue(link.startswith('https://school.example/trial-enrollment/'))
        c=self.connect();self.assertEqual(c.execute('SELECT state FROM studio_tasks').fetchone()[0],'completed');c.close()
    def test_paid_invoice_failure_resumes_without_duplicate_credit(self):
        self.pay();real_finalize=self.api['finalize_stripe_invoice_payment'].side_effect
        self.api['finalize_stripe_invoice_payment'].side_effect=lambda *a,**kw:False
        self.s.process();j=self.j();self.assertEqual(j['stage'],'attention');self.assertIsNotNone(json.loads(j['result'])['invoice_id'])
        self.api['finalize_stripe_invoice_payment'].side_effect=real_finalize
        c=self.s.db();self.s.set_stage(c,self.jid,'payment',error='');c.commit();c.close();self.s.process();self.assertEqual(self.j()['stage'],'enrolled')
        self.api['create_enrollment_invoice'].assert_called_once();c=self.connect();self.assertEqual(c.execute('SELECT lessons_left FROM enrollments').fetchone()[0],10);c.close()
    def test_checkout_reuses_existing_admissions_payment(self):
        self.accept();j=self.j();r=self.client.post(self.s.order_path(j)+'/checkout');self.assertEqual(r.status_code,303);self.api['stripe'].checkout.Session.create.assert_called_once();kw=self.api['stripe'].checkout.Session.create.call_args.kwargs;self.assertEqual(kw['idempotency_key'],'admissions-'+j['order_id']);self.assertEqual(kw['metadata']['inquiry_id'],'1')

if __name__=='__main__':unittest.main()
