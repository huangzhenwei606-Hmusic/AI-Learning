import ast, smtplib, sqlite3, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from delivery_queue import queue_once
SCHEMA='CREATE TABLE notification_delivery_queue(id INTEGER PRIMARY KEY,user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,status,created_at);'
class QueueSafetyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=str(Path(self.temp.name)/'test.db')
  with closing(sqlite3.connect(self.path)) as c, c:c.executescript(SCHEMA)
 def tearDown(self):self.temp.cleanup()
 def queue(self,guardian='1',lesson=42,title='Nov 8 at 11:15',body='same lesson',kind='lesson_reminder',direct=False):
  with closing(sqlite3.connect(self.path,timeout=10)) as c, c:return queue_once(c,'parent',guardian,'email','family@example.test',title,body,'/parent',kind,lesson,direct=direct)
 def test_concurrent_duplicate_guardians_create_one_reminder(self):
  with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(lambda n:self.queue(str(n),42+n),range(24)))
  self.assertEqual(len(set(ids)),1)
  with closing(sqlite3.connect(self.path)) as c, c:self.assertEqual(c.execute('SELECT count(*) FROM notification_delivery_queue').fetchone()[0],1)
 def test_distinct_times_students_and_dates_not_lost(self):
  a=self.queue()
  for args in ({'title':'Nov 8 at 12:00'},{'body':'different student'},{'title':'Nov 9 at 11:15'}):self.assertNotEqual(a,self.queue(**args))
 def test_failed_uncertain_and_inflight_reminders_never_auto_recreated(self):
  ident=self.queue()
  for state in ('sending','sent','failed','unconfirmed'):
   with closing(sqlite3.connect(self.path)) as c, c:c.execute('UPDATE notification_delivery_queue SET status=?',(state,))
   self.assertEqual(ident,self.queue('duplicate guardian',99))
 def test_direct_identified_inflight_not_requeued(self):
  ident=self.queue(lesson=42,kind='trial_confirmation',direct=True)
  with closing(sqlite3.connect(self.path)) as c, c:c.execute("UPDATE notification_delivery_queue SET status='sending'")
  self.assertEqual(ident,self.queue(lesson=42,kind='trial_confirmation',direct=True))
 def test_ordinary_messages_keep_independent_message_ids(self):self.assertNotEqual(self.queue(kind='message',lesson=1),self.queue(kind='message',lesson=2))
 def test_postgres_transaction_lock(self):
  calls=[]
  class Cursor:
   lastrowid=8
   def execute(self,sql,args=()):calls.append((sql,args))
   def fetchone(self):return None
  c=SimpleNamespace(cursor=lambda:Cursor(),commit=lambda:None,rollback=lambda:None)
  self.assertEqual(queue_once(c,'parent','1','email','a@test','subject','body','/','lesson_reminder',1,postgres=True),8)
  self.assertIn('pg_advisory_xact_lock',calls[0][0]);self.assertIsInstance(calls[0][1][0],int)
class SenderSafetyTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript(SCHEMA);self.db.execute("INSERT INTO notification_delivery_queue (id,channel,destination,title,status) VALUES (1,'email','family@example.test','reminder','pending')")
  db=self.db
  class Conn:
   def cursor(self):return db.cursor()
   def commit(self):db.commit()
   def close(self):pass
  self.states=[];self.sent=[];self.ns=dict(sqlite3=SimpleNamespace(connect=lambda *a:Conn()),ensure_v33_schema=lambda:None,smtplib=smtplib)
  def mark(q,status,response):db.execute('UPDATE notification_delivery_queue SET status=? WHERE id=?',(status,q));self.states.append(status)
  self.ns.update(mark_delivery_status=mark,send_email_delivery=lambda *a:(self.sent.append(a) or (True,'ok')))
  tree=ast.parse(Path(__file__).with_name('app.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='send_queued_email_now');exec(compile(ast.Module(body=[fn],type_ignores=[]),'sender','exec'),self.ns)
 def tearDown(self):self.db.close()
 def test_double_send_and_explicit_retry_of_sent_blocked(self):
  f=self.ns['send_queued_email_now'];self.assertTrue(f(1)[0]);self.assertFalse(f(1,retry_failed=True)[0]);self.assertEqual(len(self.sent),1)
 def test_failed_requires_explicit_owner_retry(self):
  self.db.execute("UPDATE notification_delivery_queue SET status='failed'");f=self.ns['send_queued_email_now'];self.assertFalse(f(1)[0]);self.assertTrue(f(1,retry_failed=True)[0])
 def test_timeout_is_unconfirmed_and_cannot_be_retried(self):
  def timeout(*a):raise TimeoutError('unknown after DATA')
  self.ns['send_email_delivery']=timeout;f=self.ns['send_queued_email_now'];self.assertFalse(f(1)[0]);self.assertEqual(self.states,['unconfirmed']);self.assertFalse(f(1,retry_failed=True)[0])
 def test_manual_route_uses_claimed_sender(self):
  tree=ast.parse(Path(__file__).with_name('app.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='notification_queue_send');calls=[n.func.id for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)];self.assertIn('send_queued_email_now',calls);self.assertNotIn('send_email_delivery',calls)
if __name__=='__main__':unittest.main()
