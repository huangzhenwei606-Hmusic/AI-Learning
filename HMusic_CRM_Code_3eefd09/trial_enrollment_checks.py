import os,tempfile,json
from datetime import datetime,timedelta
from unittest.mock import Mock
from werkzeug.datastructures import MultiDict
with tempfile.TemporaryDirectory() as temp:
 os.environ.update(HMUSIC_DB_PATH=temp+'/test.db',DATABASE_URL='',HMUSIC_PREPARE_DB_ON_STARTUP='0',HMUSIC_STUDIO_AUTOMATION='0',HMUSIC_ENABLE_AUTO_REMINDERS='0',HMUSIC_DISABLE_AUTO_BACKUP='1')
 import app as crm
 crm.ensure_production_schema();crm.ensure_v18c_schema();crm.ensure_guardian_billing_schema()
 # Keep actual ledger and invoice code, suppress all external communication in this isolated database.
 for key in ('create_notification','create_invoice_message_event','queue_direct_delivery','queue_notification_delivery','send_queued_email_now','send_queued_sms_now'):
  crm.__dict__[key]=Mock(return_value=None)
 s=crm.app.extensions['trial_enrollment'];c=s.db()
 c.execute("INSERT INTO inquiries(student_name,parent_name,parent_email,phone,source,status) VALUES('Integration Child','Test Parent','integration@example.invalid','+15555550100','Isolated end-to-end test','New')");iid=c.execute("SELECT id FROM inquiries WHERE student_name='Integration Child'").fetchone()[0]
 c.execute("INSERT OR IGNORE INTO teachers(teacher_name) VALUES('Xu Huang')")
 c.execute("INSERT INTO course_types(name,duration,active,is_group,student_billing_method,student_price,teacher_billing_method,teacher_pay) VALUES('Integration Piano',30,1,0,'Per Lesson',65,'Per Lesson',25)");ct=c.execute("SELECT id FROM course_types WHERE name='Integration Piano'").fetchone()[0];c.commit();c.close()
 jid=s.create(iid,['email']);d=(datetime.now(crm.LA if hasattr(crm,'LA') else __import__('zoneinfo').ZoneInfo('America/Los_Angeles')).date()+timedelta(days=3)).isoformat()
 s.add_window(MultiDict([('teacher_id','xu-huang-instrument'),('course_type_id',str(ct)),('date_from',d),('date_until',d),('start_time','09:00'),('end_time','12:00'),('classroom','Test room'),('location','Test center'),('weekdays',str(datetime.fromisoformat(d).weekday()))]))
 dates=[(datetime.fromisoformat(d).date()+timedelta(days=7+7*i)).isoformat() for i in range(10)]
 s.add_plan(jid,{'teacher_id':'xu-huang-instrument','course_type_id':str(ct),'dates':'\n'.join(dates),'time':'10:00','classroom':'Test room','location':'Test center'})
 s.offer(jid,dict(start=d,end=d,course_type_id=ct,trial_fee='30'))
 c=s.db();j=s.get(c,jid);c.close()
 from studio_operations import fingerprint,LA
 s.select(jid,0,fingerprint(json.loads(j['candidates'])));s.approve(jid)
 c=s.db();j=s.get(c,jid);end=datetime.now(LA)-timedelta(hours=3);c.execute("UPDATE schedule SET lesson_date=?,lesson_time=?,status='present' WHERE id=?",(end.date().isoformat(),(end-timedelta(minutes=30)).strftime('%H:%M'),j['trial_schedule_id']));c.commit();c.close();s.advance(jid,datetime.now(LA))
 c=s.db();j=s.get(c,jid);p=json.loads(j['plans'])[0];c.close();oid=s.accept(jid,p['id'],'Test Parent',p['quote']['policy']['version'])
 c=s.db();c.execute("UPDATE admissions_orders SET checkout_id='cs_isolated_test' WHERE id=?",(oid,));c.commit()
 from admissions import sync_order
 sync_order(c,{'id':'cs_isolated_test','mode':'payment','currency':'usd','amount_total':p['quote']['total'],'metadata':{'admissions_order':oid},'payment_status':'paid'});c.close()
 s.advance(jid,datetime.now(LA));s.advance(jid,datetime.now(LA));c=s.db();j=s.get(c,jid);result=json.loads(j['result'])
 assert j['stage']=='enrolled',j['stage']
 assert len(result['schedule_ids'])==10
 assert c.execute('SELECT lessons_left FROM enrollments WHERE id=?',(result['enrollment_id'],)).fetchone()[0]==10
 assert c.execute('SELECT count(*) FROM payments WHERE enrollment_id=?',(result['enrollment_id'],)).fetchone()[0]==1
 assert c.execute('SELECT status FROM invoices WHERE id=?',(result['invoice_id'],)).fetchone()[0]=='paid'
 assert c.execute('SELECT count(*) FROM schedule WHERE enrollment_id=?',(result['enrollment_id'],)).fetchone()[0]==10
 assert c.execute('SELECT teacher_pay_amount FROM schedule WHERE id=?',(result['schedule_ids'][0],)).fetchone()[0]==25
 client=crm.app.test_client()
 with client.session_transaction() as sess:sess['user_role']='owner'
 r=client.get('/studio-enrollment?_workspace=1');assert r.status_code==200,r.status_code
 r=client.post('/studio-enrollment',data={'action':'pause','jid':jid});assert r.status_code==302 and 'csrf_refresh=1' in r.location,r.status_code
 c2=s.db();assert s.get(c2,jid)['enabled']==1;c2.close()
 r=client.post('/studio-enrollment',json={'action':'pause','jid':jid});assert r.status_code==403,r.status_code
 print('Full CRM integration passed: verified order -> one paid invoice/payment -> 10 credits -> 10 lessons with payroll -> welcome outbox. CSRF enforced. No external messages or payments.')
 c.close()
