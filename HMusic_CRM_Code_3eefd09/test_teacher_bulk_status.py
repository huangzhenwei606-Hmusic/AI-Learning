import ast
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from flask import Flask, request

class TeacherBulkStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE group_session_teachers(schedule_id,teacher_name)')
            db.execute('CREATE TABLE schedule(id INTEGER PRIMARY KEY,teacher)')
            db.executemany('INSERT INTO schedule VALUES(?,?)',[(1,'Jenny'),(2,'Jenny'),(3,'Other')])
        self.calls=[];self.notices=[];self.allowed=True;self.failures=set()
        self.app=Flask(__name__)
        def apply(sid,status,**kw):
            self.calls.append((sid,status))
            return dict(ok=sid not in self.failures,error='Payroll locked' if sid in self.failures else '')
        scope=dict(request=request,teacher_api_identity=lambda:('Jenny',None),teacher_has_permission=lambda *a:self.allowed,
            sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),apply_lesson_status=apply,
            hmusic_queue_teacher_cancel_parent_notice=lambda sid:self.notices.append(sid) or 1,
            create_notification=lambda *a,**kw:None,calendar_status_label=lambda s:s)
        self.scope=scope
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='api_teacher_lesson_bulk_status');fn.decorator_list=[]
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),scope)
        self.app.add_url_rule('/bulk',view_func=scope[fn.name],methods=['POST'])
        self.client=self.app.test_client()

    def test_calendar_endpoint_contract(self):
        scope=dict(self.scope,ensure_calendar_lesson_panel_schema=lambda:None,require_teacher=lambda:True,
                   require_owner=lambda:False,session={'teacher_name':'Jenny'},
                   get_teacher_permissions=lambda name:{'attendance':self.allowed})
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='teacher_multi_select_action');fn.decorator_list=[]
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),scope)
        app=Flask('legacy');app.add_url_rule('/bulk',view_func=scope[fn.name],methods=['POST']);client=app.test_client()
        self.assertEqual(client.post('/bulk',json=dict(action='set_status',schedule_ids=[1,3],status='present')).status_code,403)
        self.assertEqual(self.calls,[])
        result=client.post('/bulk',json=dict(action='cancel_lessons',schedule_ids=[1,2],notify_parent_on_teacher_cancel=True)).json
        self.assertEqual(result['updated'],2);self.assertEqual(self.notices,[1,2])
        self.failures={2}
        result=client.post('/bulk',json=dict(action='set_status',schedule_ids=[1,2],status='present')).json
        self.assertEqual(result['updated'],1);self.assertEqual(result['errors'],['Payroll locked'])

    def test_updates_owned_selection_and_notifies_only_on_opt_in(self):
        response=self.client.post('/bulk',json=dict(schedule_ids=[1,2,1],status='present'))
        self.assertEqual(response.json['updated'],2);self.assertEqual(len(self.calls),2);self.assertEqual(self.notices,[])
        response=self.client.post('/bulk',json=dict(schedule_ids=[1,2],status='teacher_cancelled',notify_parent=True))
        self.assertEqual(response.json['parent_notices'],2);self.assertEqual(self.notices,[1,2])

    def test_permission_and_ownership_reject_before_any_change(self):
        self.allowed=False
        self.assertEqual(self.client.post('/bulk',json=dict(schedule_ids=[1],status='present')).status_code,403)
        self.allowed=True
        for ids in [[1,3],[1,999]]:
            self.assertEqual(self.client.post('/bulk',json=dict(schedule_ids=ids,status='present')).status_code,403)
        self.assertEqual(self.calls,[])

    def test_invalid_or_oversized_batches_do_not_partially_apply(self):
        for ids in [[],[1]*101,'1',[True],[1,'bad'],[0],[1.5]]:
            self.assertEqual(self.client.post('/bulk',json=dict(schedule_ids=ids,status='present')).status_code,400)
        self.assertEqual(self.calls,[])

    def test_locked_lesson_reported_without_hiding_success(self):
        self.failures={2}
        result=self.client.post('/bulk',json=dict(schedule_ids=[1,2],status='present')).json
        self.assertEqual(result['updated'],1);self.assertEqual(result['errors'],['Payroll locked'])

if __name__=='__main__':unittest.main()
