import sqlite3,tempfile,unittest,os,json
from datetime import datetime
from unittest.mock import Mock,patch
from flask import Flask
from studio_operations import Operations,register_operations,reminder_nodes,LA
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/db';self.connect=lambda:sqlite3.connect(self.path)
  c=self.connect();c.executescript('''
  CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name TEXT,teacher TEXT,lesson_date TEXT,lesson_time TEXT,duration INTEGER,classroom TEXT,location TEXT,status TEXT,weekday TEXT,schedule_type TEXT,notes TEXT);
  INSERT INTO schedule VALUES(1,'Child','Teacher','2027-01-10','10:00',45,'A','Center','scheduled','','private','');
  INSERT INTO schedule VALUES(2,'Other','Teacher','2027-01-11','10:30',45,'A','Center','scheduled','','private','');
  CREATE TABLE teacher_time_off_requests(id INTEGER,teacher_name TEXT,start_date TEXT,end_date TEXT,start_time TEXT,end_time TEXT,all_day INTEGER,status TEXT);
  CREATE TABLE notification_delivery_queue(id INTEGER PRIMARY KEY,status TEXT,related_type TEXT,related_id INTEGER);
  CREATE TABLE parent_students(parent_id INTEGER,student_name TEXT,active INTEGER);
  CREATE TABLE teachers(teacher_name TEXT);INSERT INTO teachers VALUES('Teacher');
  CREATE TABLE inquiries(id INTEGER PRIMARY KEY,student_name TEXT,parent_name TEXT,parent_email TEXT,phone TEXT,parent_profile_id INTEGER,status TEXT,trial_teacher TEXT,trial_date TEXT,trial_time TEXT,trial_location TEXT,trial_duration TEXT,trial_status TEXT,owner_verified INTEGER,next_follow_up_at TEXT,follow_up_status TEXT,converted_student_name TEXT,updated_at TEXT);
  INSERT INTO inquiries(id,student_name,parent_email,status) VALUES(1,'Child','p@example.com','Inquiry');
  CREATE TABLE enrollments(id INTEGER PRIMARY KEY,student_name TEXT,package_lessons INTEGER,package_amount REAL);INSERT INTO enrollments VALUES(1,'Child',10,600);
  CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name TEXT,status TEXT,amount REAL,enrollment_id INTEGER,invoice_type TEXT);
  ''');c.close()
  self.api={'hmusic_public_app_url':lambda p:'https://crm.example'+p,'queue_direct_delivery':Mock(return_value=None)};self.s=Operations(self.connect,self.api);self.thread=patch('studio_operations.threading.Thread');self.thread.start()
 def tearDown(self):self.thread.stop();self.tmp.cleanup()
 def move(self):return self.s.prepare('reschedule',{'lesson_id':1,'date':'2027-01-12','time':'09:00'},'owner')['id']
 def test_conflict(self):
  with self.assertRaises(ValueError):self.s.prepare('reschedule',{'lesson_id':1,'date':'2027-01-11','time':'10:00'},'owner')
 def test_move_replay(self):
  p=self.move();r=self.s.execute(p,'owner');self.assertEqual(r['result']['lesson']['lesson_date'],'2027-01-12');self.assertEqual(self.s.execute(p,'owner')['result'],r['result'])
 def test_stale(self):
  p=self.move();c=self.connect();c.execute("UPDATE schedule SET lesson_time='08:00' WHERE id=1");c.commit();c.close()
  with self.assertRaises(ValueError):self.s.execute(p,'owner')
 def test_actor(self):
  with self.assertRaises(ValueError):self.s.execute(self.move(),'other')
 def test_expired(self):
  p=self.move();c=self.connect();c.execute("UPDATE studio_operations SET expires='2000' WHERE id=?",(p,));c.commit();c.close()
  with self.assertRaises(ValueError):self.s.execute(p,'owner')
 def test_trial(self):
  p=self.s.prepare('trial',{'inquiry_id':1,'teacher':'Teacher','date':'2027-01-14','time':'11:00','duration':30,'classroom':'B','channels':['email']},'owner')['id'];self.s.execute(p,'owner');self.s.execute(p,'owner');c=self.connect();self.assertEqual(c.execute("SELECT count(*) FROM schedule WHERE schedule_type='trial'").fetchone()[0],1);c.close()
 def test_workflow_dedup(self):
  p=self.s.prepare('workflow',{'inquiry_id':1,'first_schedule_id':1,'channels':['email'],'followup_body':'','enabled':True},'owner')['id'];self.s.execute(p,'owner');c=self.s.db();now=datetime(2027,1,7,10,tzinfo=LA);self.s.generate(c,now);self.s.generate(c,now);c.commit();self.assertEqual(c.execute('SELECT count(*) FROM studio_tasks').fetchone()[0],1);c.execute('UPDATE studio_workflows SET enabled=0');c.commit();c.close();self.s.tick();self.api['queue_direct_delivery'].assert_not_called()
 def test_dst(self):
  nodes=dict(reminder_nodes('2027-03-15','10:00'));self.assertEqual(nodes['d3'].strftime('%Y-%m-%d %H:%M'),'2027-03-12 09:00');self.assertEqual(nodes['d0'].hour,8)
 def test_invoice(self):
  def create(cur,*a,**kw):cur.execute("INSERT INTO invoices VALUES(1,'Child','unpaid',600,1,'initial')");return 1
  self.api['create_enrollment_invoice']=create;p=self.s.prepare('invoice',{'enrollment_id':1},'owner')['id'];self.assertEqual(self.s.execute(p,'owner')['result']['invoice']['amount'],600)
 def test_message_outbox_sends_once_and_records_real_status(self):
  def queue(*a,**kw):
   c=self.connect();c.execute("INSERT INTO notification_delivery_queue VALUES(1,'pending','studio_task',1)");c.commit();c.close();return 1
  def send(qid):
   c=self.connect();c.execute("UPDATE notification_delivery_queue SET status='sent' WHERE id=?",(qid,));c.commit();c.close()
  self.api['queue_direct_delivery']=Mock(side_effect=queue);self.api['send_queued_email_now']=Mock(side_effect=send)
  p=self.s.prepare('message',{'target_kind':'inquiry','target_id':1,'channels':['email'],'title':'Hello','body':'Approved copy'},'owner')['id']
  self.s.execute(p,'owner');self.s.tick();self.s.tick();r=self.s.status(p,'owner');self.assertEqual(r['tasks'][0]['result']['channels'][0]['state'],'sent');self.api['send_queued_email_now'].assert_called_once()
 def test_cancelled_course_does_not_send_reminder(self):
  p=self.s.prepare('workflow',{'inquiry_id':1,'first_schedule_id':1,'channels':['email'],'followup_body':'','enabled':True},'owner')['id'];self.s.execute(p,'owner')
  c=self.s.db();self.s.generate(c,datetime(2027,1,7,10,tzinfo=LA));c.execute("UPDATE schedule SET status='cancelled' WHERE id=1");c.commit();c.close();self.s.tick();self.api['queue_direct_delivery'].assert_not_called()
 def test_new_followup_requires_explicit_date(self):
  with self.assertRaises(ValueError):self.s.prepare('workflow',{'inquiry_id':1,'channels':['email'],'followup_body':'Hello','enabled':True},'owner')
 def test_failed_send_is_not_silently_retried(self):
  def queue(*a,**kw):
   c=self.connect();c.execute("INSERT INTO notification_delivery_queue VALUES(1,'pending','studio_task',1)");c.commit();c.close();return 1
  def fail(qid):
   c=self.connect();c.execute("UPDATE notification_delivery_queue SET status='failed' WHERE id=?",(qid,));c.commit();c.close()
  self.api['queue_direct_delivery']=Mock(side_effect=queue);self.api['send_queued_email_now']=Mock(side_effect=fail)
  p=self.s.prepare('message',{'target_kind':'inquiry','target_id':1,'channels':['email'],'title':'Hi','body':'Hello'},'owner')['id'];self.s.execute(p,'owner');self.s.tick();self.s.tick();self.assertEqual(self.s.status(p,'owner')['tasks'][0]['state'],'attention');self.api['send_queued_email_now'].assert_called_once()
 def test_sms_owner_retry_preserved_but_background_never_retries_failed(self):
  import ast,pathlib,types
  source=pathlib.Path(__file__).with_name('app.py').read_text();tree=ast.parse(source)
  functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('send_queued_sms_now','hmusic_send_queued_sms')]
  cur=Mock();cur.fetchone.return_value=('sms','+15555550100','Title','Body','/parent_dashboard','failed');cur.rowcount=1
  conn=Mock();conn.cursor.return_value=cur;sender=Mock(return_value=(True,'accepted'))
  scope={'sqlite3':types.SimpleNamespace(connect=lambda *a:conn),'ensure_v33_schema':lambda:None,'send_sms_delivery':sender,'mark_delivery_status':Mock()}
  exec(compile(ast.Module(body=functions,type_ignores=[]),'<sms-sender>','exec'),scope)
  self.assertFalse(scope['send_queued_sms_now'](1)[0]);sender.assert_not_called()
  self.assertTrue(scope['hmusic_send_queued_sms'](1,retry_failed=True)[0]);sender.assert_called_once()
 def test_read_token(self):
  app=Flask(__name__);register_operations(app,self.connect,self.api)
  with patch.dict(os.environ,{'HMUSIC_AGENT_WRITE_TOKEN':'w'*40,'HMUSIC_AGENT_READ_TOKEN':'r'*40}):self.assertEqual(app.test_client().post('/api/studio-agent/v1/operations/prepare',json={},headers={'Authorization':'Bearer '+'r'*40,'X-Studio-Actor':'owner'}).status_code,401)
if __name__=='__main__':unittest.main()
