"""Run real route/message helpers in an isolated database; no real notifications."""
import ast
from contextlib import closing
from datetime import datetime
from html import escape
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from flask import Flask, request, session, redirect

class BookingTeacherSendTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/'booking.db')
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript('''
            CREATE TABLE parent_booking_requests(id INTEGER PRIMARY KEY,parent_id,student_name,request_type,
              preferred_date,preferred_time,preferred_teacher,preferred_room,notes,status,created_at,owner_note,
              confirmed_schedule_id,updated_at);
            INSERT INTO parent_booking_requests VALUES(1,42,'Ella Lee','schedule_change_note','','','Jenny Lee','',
              'Skip this week. Musical rehearsal.','pending_manager_review','2026-11-09','','',NULL);
            CREATE TABLE teachers(teacher_name,active);
            INSERT INTO teachers VALUES('Jenny Lee',1),('Other Teacher',1),('Inactive',0);
            CREATE TABLE message_threads(id INTEGER PRIMARY KEY,subject,student_name,parent_id,teacher_name,
              thread_type,is_group,owner_observer,related_type,related_id,status,created_at,updated_at);
            CREATE TABLE message_participants(thread_id,participant_role,participant_key,display_name,is_observer,
              active,created_at,UNIQUE(thread_id,participant_role,participant_key));
            CREATE TABLE messages(id INTEGER PRIMARY KEY,thread_id,sender_role,sender_name,recipient_role,body,channel,created_at);
            CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name,course_type_id,course_type_name,duration,teacher,room_id,lesson_date);
            CREATE TABLE course_types(id,name,duration,is_group,active);
            CREATE TABLE studio_locations(id,location_name,sort_order);
            CREATE TABLE studio_rooms(id,room_name,location_id,active,sort_order);
            ''')
        self.app=Flask(__name__);self.app.secret_key='test-only';self.app.testing=True
        self.notifications=[]
        self.ns=dict(app=self.app,request=request,session=session,redirect=redirect,escape=escape,datetime=datetime,
            sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.db)),
            require_owner=lambda:session.get('role')=='owner',
            ensure_parent_portal_feature_schema=lambda:None,ensure_v18_schema=lambda:None,
            ensure_location_room_schema=lambda:None,ensure_v29_schema=lambda:None,
            create_notification=lambda *a,**kw:self.notifications.append((a,kw)))
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        wanted={'parent_booking_request_review','get_or_create_message_thread','add_message',
                'ensure_message_participant','sync_thread_default_participants'}
        for node in tree.body:
            if isinstance(node,ast.FunctionDef) and node.name in wanted:
                exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.ns)
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s['role']='owner'

    def rows(self,sql):
        with closing(sqlite3.connect(self.db)) as con:return con.execute(sql).fetchall()

    def send(self,teacher='Jenny Lee',note='Please coordinate with the parent.'):
        return self.client.post('/parent_booking_request_review/1',data={
            'action':'send_teacher','teacher':teacher,'owner_note':note,'student_name':'Forged student'})

    def test_forward_without_date_does_not_schedule_or_confirm(self):
        response=self.send();self.assertEqual(response.status_code,302)
        messages=self.rows('SELECT recipient_role,body FROM messages')
        self.assertEqual(len(messages),1);self.assertEqual(messages[0][0],'teacher')
        for text in ['Ella Lee','Skip this week. Musical rehearsal.','Please coordinate with the parent.']:
            self.assertIn(text,messages[0][1])
        self.assertNotIn('Forged student',messages[0][1])
        self.assertEqual(self.rows('SELECT status,confirmed_schedule_id FROM parent_booking_requests'),[('pending_manager_review','')])
        self.assertEqual(self.rows('SELECT * FROM schedule'),[])
        self.assertEqual(self.rows('SELECT participant_role,participant_key FROM message_participants ORDER BY participant_role'),[('owner','owner'),('teacher','Jenny Lee')])
        self.assertEqual(self.notifications[0][0][:2],('teacher','Jenny Lee'))
        html=self.client.get(response.location).get_data(as_text=True)
        self.assertIn('Sent to Jenny Lee',html)
        self.assertIn('value="send_teacher" type="submit" formnovalidate',html)
        self.assertIn('Open teacher conversation',html)

    def test_duplicate_click_and_different_recipients(self):
        self.send();self.send()
        self.assertEqual(len(self.rows('SELECT * FROM messages')),1)
        self.assertEqual(len(self.notifications),1)
        self.send('Other Teacher')
        self.assertEqual(len(self.rows('SELECT * FROM messages')),2)
        self.assertEqual(len(self.rows('SELECT * FROM message_threads')),2)
        for tid,teacher in self.rows('SELECT id,teacher_name FROM message_threads'):
            self.assertEqual(self.rows(f"SELECT participant_key FROM message_participants WHERE participant_role='teacher' AND thread_id={tid}"),[(teacher,)])
        self.assertEqual(self.rows("SELECT * FROM message_participants WHERE participant_role='parent'"),[])

    def test_bad_recipient_and_non_owner_cannot_send(self):
        for teacher in ['', 'Inactive', 'Nonexistent']:self.assertEqual(self.send(teacher).status_code,400)
        with self.client.session_transaction() as s:s['role']='teacher'
        self.assertEqual(self.send().status_code,302)
        self.assertEqual(self.rows('SELECT * FROM messages'),[]);self.assertEqual(self.notifications,[])

    def test_changed_note_is_a_new_message(self):
        self.send(note='First update');self.send(note='Second update')
        self.assertEqual(len(self.rows('SELECT * FROM messages')),2);self.assertEqual(len(self.notifications),2)

if __name__=='__main__':unittest.main()
