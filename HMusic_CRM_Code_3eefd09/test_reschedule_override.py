import ast, unittest
from pathlib import Path
from types import SimpleNamespace
from html import escape
from datetime import datetime
source=Path(__file__).with_name('app.py').read_text()
fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='approve_reschedule')
fn.decorator_list=[]
class Tests(unittest.TestCase):
 def run_route(self,form,allowed=True):
  writes=[]
  class DB:
   def cursor(self): return self
   def execute(self,sql,args=()):
    if sql.lstrip().startswith('UPDATE'): writes.append((sql,args))
   def fetchone(self): return (13,1,'Test',2,'pending','Teacher','Room',30,None,None,None,0,0,'Campus')
   def close(self): pass
   def commit(self): pass
  scope=dict(require_owner=lambda:allowed,redirect=lambda x:x,ensure_v28_schema=lambda:None,ensure_location_room_schema=lambda:None,request=SimpleNamespace(form=form),datetime=datetime,sqlite3=SimpleNamespace(connect=lambda _:DB()),schedule_has_conflict=lambda *a,**k:{'has_conflict':True,'message':'Teacher conflict <test>'},escape=escape,log_parent_activity=lambda *a:None,create_reschedule_message_event=lambda *a,**k:None)
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'route','exec'),scope)
  return scope['approve_reschedule'](13),writes
 def test_default_blocks_and_preserves_escaped_inputs(self):
  result,writes=self.run_route(dict(approved_date='2026-11-30',approved_time='19:00',owner_note='A "quote" <note>'))
  self.assertFalse(writes)
  self.assertIn('Ignore conflict and approve',result)
  self.assertIn('confirm(',result)
  self.assertIn('&quot;quote&quot; &lt;note&gt;',result)
 def test_explicit_override_approves_and_audits(self):
  result,writes=self.run_route(dict(approved_date='2026-11-30',approved_time='19:00',ignore_conflict='1',owner_note='Manager note'))
  self.assertEqual(result,'/reschedule_request/13')
  self.assertEqual(len(writes),2)
  self.assertIn('Conflict explicitly overridden by manager',writes[1][1][2])
 def test_override_requires_owner(self):
  result,writes=self.run_route({'ignore_conflict':'1'},False)
  self.assertEqual(result,'/owner_login')
  self.assertFalse(writes)
unittest.main()
