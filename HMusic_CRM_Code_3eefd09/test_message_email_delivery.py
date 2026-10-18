import ast,sqlite3,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
SOURCE=Path(__file__).with_name('app.py').read_text()
TREE=ast.parse(SOURCE)
class DeliveryTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript('''CREATE TABLE notification_delivery_queue(id INTEGER PRIMARY KEY,user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,status,created_at);CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_role,user_key,title,body,link_url,related_type,related_id,created_at,read_at);''');self.sent=[];db=self.db
  class Conn:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):pass
  self.ns=dict(sqlite3=SimpleNamespace(connect=lambda *a:Conn()),datetime=datetime,ensure_v29_schema=lambda:None,ensure_v33_schema=lambda:None,get_notification_destination=lambda *a:'parent@example.test',hmusic_normalize_email=lambda x:x,hmusic_is_real_email=lambda x:True,hmusic_is_email_suppressed=lambda *a:False,should_queue_sms_notification=lambda *a:False,app=SimpleNamespace(logger=SimpleNamespace(exception=lambda *a:None)))
  for name in ('hmusic_should_send_message_email_now','queue_notification_delivery','send_queued_email_now','create_notification'):
   n=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name);n.decorator_list=[];exec(compile(ast.Module(body=[n],type_ignores=[]),'app.py','exec'),self.ns)
  self.ns['send_email_delivery']=lambda *a:(self.sent.append(a) or (True,'SMTP accepted'))
  self.ns['mark_delivery_status']=lambda q,status,response:db.execute('UPDATE notification_delivery_queue SET status=? WHERE id=?',(status,q))
 def tearDown(self):self.db.close()
 def notify(self,mid,body='cancel class',link='/message_thread/370'):
  return self.ns['create_notification']('parent','1','New message from H-Music',body,link,related_type='message',related_id=mid)
 def test_new_messages_send_and_repeated_notification_does_not_resend(self):
  self.notify(1);self.notify(1);self.assertEqual(len(self.sent),1);self.assertEqual(self.db.execute("SELECT status FROM notification_delivery_queue WHERE channel='email'").fetchone()[0],'sent');self.notify(2);self.assertEqual(len(self.sent),2)
 def test_invoice_notification_sends_but_explicit_defer_is_respected(self):
  f=self.ns['create_notification'];f('parent','1','Tuition invoice sent','invoice ready','/message_thread/369');self.assertEqual(len(self.sent),1);f('parent','1','New message from H-Music','deferred','/message_thread/368',send_email_now=False);self.assertEqual(len(self.sent),1)
 def test_legacy_same_parent_different_content_or_thread_not_suppressed(self):
  q=self.ns['queue_notification_delivery'];args=('parent','1','New message from H-Music')
  a=q(*args,'first','/message_thread/1','email');self.assertEqual(a,q(*args,'first','/message_thread/1','email'));self.assertNotEqual(a,q(*args,'second','/message_thread/1','email'));self.assertNotEqual(a,q(*args,'first','/message_thread/2','email'))
 def test_reentrant_sender_cannot_send_claimed_queue(self):
  q=self.ns['queue_notification_delivery']('parent','1','New message','body','/message_thread/1','email');calls=[]
  def smtp(*args):
   calls.append(args);self.assertFalse(self.ns['send_queued_email_now'](q)[0]);return True,'ok'
  self.ns['send_email_delivery']=smtp;self.assertTrue(self.ns['send_queued_email_now'](q)[0]);self.assertFalse(self.ns['send_queued_email_now'](q)[0]);self.assertEqual(len(calls),1)
 def test_smtp_failure_recorded_without_touching_other_pending_mail(self):
  q=self.ns['queue_notification_delivery'];old=q('parent','1','old','body','/old','email');self.ns['send_email_delivery']=lambda *a:(False,'SMTP failed');self.notify(1);self.assertEqual(self.db.execute('SELECT status FROM notification_delivery_queue WHERE id=?',(old,)).fetchone()[0],'pending');self.assertEqual(self.db.execute("SELECT status FROM notification_delivery_queue WHERE related_id=1 AND channel='email'").fetchone()[0],'failed')
if __name__=='__main__':unittest.main()
