"""Exercise the real edit_student handler against a disposable student database."""
import ast
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from html import escape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode
from flask import Flask, request, redirect, make_response, session

class StudentInactiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='edit_student')
        node.decorator_list=[]
        cls.handler_code=compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/test.db'
        self.connect=lambda *a,**kw:sqlite3.connect(self.path)
        with self.connect() as c:
            c.executescript("""CREATE TABLE students(name TEXT PRIMARY KEY,teacher,parent_name,parent_email,parent_phone,lessons_left REAL,status,program,lesson_length,internal_note);
            INSERT INTO students VALUES('Test Student','Teacher','Parent','parent@example.invalid','5550100',7,'Active','Piano private lesson','30 minutes','keep me');
            CREATE TABLE teachers(id,teacher_name,active);
            CREATE TABLE enrollments(id,student_name,status,teacher_name,lessons_left REAL);
            INSERT INTO enrollments VALUES(1,'Test Student','active','Teacher',7);
            CREATE TABLE schedule(student_name,teacher,lesson_date,lesson_time,classroom);
            INSERT INTO schedule VALUES('Test Student','Teacher','2026-10-01','10:00','Room');
            CREATE TABLE payments(student_name,amount REAL);
            INSERT INTO payments VALUES('Test Student',100);
            CREATE TABLE course_types(id,name,duration,active);
            CREATE TABLE parent_profiles(id,email,active);
            CREATE TABLE parent_students(id,parent_id,student_name,active);
            CREATE TABLE invoices(id,student_name,amount REAL,status);
            INSERT INTO invoices VALUES(1,'Test Student',100,'paid');""")
        self.app=Flask('student-status');self.app.secret_key='test';self.app.testing=True
        self.ns=dict(sqlite3=SimpleNamespace(connect=self.connect),request=request,redirect=redirect,
            require_owner=lambda:session.get('owner',False),ensure_v27_schema=lambda:None,
            ensure_teacher_management_schema=lambda:None,ensure_v321_schema=lambda:None,
            quote=quote,urlencode=urlencode,escape=escape,date=date,json=json,make_response=make_response,
            hmusic_student_total_course_credits=lambda *a:(7,[]),
            sync_parent_profile_for_student=lambda *a:None)
        exec(self.handler_code,self.ns)
        self.app.add_url_rule('/edit_student/<name>',view_func=self.ns['edit_student'],methods=['GET','POST'])
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['owner']=True
    def tearDown(self):self.tmp.cleanup()
    def test_click_saves_status_and_returns_visible_feedback(self):
        before=self.client.get('/edit_student/Test%20Student')
        self.assertIn('name="action" value="set_inactive"',before.text)
        r=self.client.post('/edit_student/Test%20Student',data={'action':'set_inactive'},follow_redirects=True)
        self.assertEqual(r.status_code,200)
        self.assertIn('Student set inactive. History and course credits are preserved.',r.text)
        self.assertIn('Student is inactive</button>',r.text)
        self.assertIn('>Inactive</span>',r.text)
        with self.connect() as c:self.assertEqual(c.execute('SELECT status FROM students').fetchone()[0],'Inactive')
    def test_status_only_ignores_unsaved_profile_and_credit_fields(self):
        with self.connect() as c:
            before=c.execute('SELECT * FROM students').fetchall()
            histories={t:c.execute('SELECT * FROM '+t).fetchall() for t in ('schedule','payments','enrollments','invoices')}
        for _ in range(2):
            self.assertEqual(self.client.post('/edit_student/Test%20Student',data={'action':'set_inactive','first_name':'Wrong','lessons_left':'0','parent_email':'wrong@example.invalid'}).status_code,302)
        with self.connect() as c:
            after=c.execute('SELECT * FROM students').fetchall()
            self.assertEqual(after[0][:6],before[0][:6]);self.assertEqual(after[0][7:],before[0][7:])
            for t,rows in histories.items():self.assertEqual(c.execute('SELECT * FROM '+t).fetchall(),rows)
    def test_requires_owner(self):
        with self.client.session_transaction() as s:s.clear()
        r=self.client.post('/edit_student/Test%20Student',data={'action':'set_inactive'})
        self.assertEqual(r.location,'/owner_login')
        with self.connect() as c:self.assertEqual(c.execute('SELECT status FROM students').fetchone()[0],'Active')
    def test_missing_student_is_not_success(self):
        r=self.client.post('/edit_student/Missing',data={'action':'set_inactive'})
        self.assertEqual(r.status_code,404)
    def test_normal_save_can_reactivate(self):
        self.client.post('/edit_student/Test%20Student',data={'action':'set_inactive'})
        r=self.client.post('/edit_student/Test%20Student',data={'first_name':'Test','last_name':'Student','status':'Active','teacher':'Teacher','lessons_left':'7'})
        self.assertEqual(r.status_code,302)
        with self.connect() as c:self.assertEqual(c.execute('SELECT status FROM students').fetchone()[0],'Active')
