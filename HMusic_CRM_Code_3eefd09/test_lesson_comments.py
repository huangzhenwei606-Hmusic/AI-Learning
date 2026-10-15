"""Real database/API tests; no production students, attendance, or credits touched."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from flask import Flask, session

from lesson_comments import install_lesson_comments


class LessonCommentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'comments.db')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE schedule (id INTEGER PRIMARY KEY, student_name, teacher,
                    lesson_date, lesson_time, duration, status, charge_lessons, enrollment_id);
                INSERT INTO schedule VALUES (1,'Weini Xing','Jenny Lee','2026-10-20','16:15',45,'scheduled',0,NULL);
                INSERT INTO schedule VALUES (2,'Nora Zhang','Other Teacher','2026-10-20','17:00',30,'present',1,42);
                INSERT INTO schedule VALUES (3,NULL,'Jenny Lee','2026-10-21','16:00',30,'scheduled',0,NULL);
                CREATE TABLE enrollments (id INTEGER PRIMARY KEY, lessons_left);
                INSERT INTO enrollments VALUES (42,8);
            """)
            self.original_schedule = db.execute('SELECT * FROM schedule ORDER BY id').fetchall()
        self.app = Flask(__name__, static_folder='static')
        self.app.secret_key = 'isolated-test-session'
        self.app.testing = True

        @self.app.route('/calendar')
        def calendar():
            return '<html><head></head><body>Calendar</body></html>'

        @self.app.route('/teacher_dashboard')
        def teacher_dashboard():
            return '<html><head></head><body>Teacher calendar</body></html>'

        @self.app.route('/parent_dashboard')
        def parent_dashboard():
            return '<html><head></head><body>Family calendar</body></html>'

        install_lesson_comments(self.app, {
            'sqlite3': SimpleNamespace(connect=lambda _: sqlite3.connect(self.path)),
            'require_owner': lambda: session.get('user_role') == 'owner',
            'hmusic_teacher_name_matches': lambda a, b: str(a or '').strip().casefold() == str(b or '').strip().casefold(),
        })
        self.owner = self.client('owner')
        self.teacher = self.client('teacher','Jenny Lee')
        self.other = self.client('teacher','Other Teacher')
        self.parent = self.client('parent')

    def client(self, role=None, name=None):
        client = self.app.test_client()
        with client.session_transaction() as state:
            if role:
                state['user_role'] = role
            if name:
                state['teacher_name'] = name
        return client

    def post(self, client, body='Parent said Weini will arrive 10 minutes late.', lesson=1, parent=None):
        response = client.post(f'/api/lesson-comments/{lesson}', json={'body': body, 'parent_id':parent})
        self.assertEqual(response.status_code,201,response.get_json())
        return response.json['id']

    def read(self, client, lesson=1):
        response = client.get(f'/api/lesson-comments/{lesson}')
        self.assertEqual(response.status_code,200,response.get_json())
        return response.json

    def summary(self,client,ids='1,2,3'):
        response = client.get('/api/lesson-comments/summary?ids='+ids)
        self.assertEqual(response.status_code,200)
        return response.json['lessons']

    def test_owner_teacher_shared_replies_and_private_access(self):
        root = self.post(self.teacher)
        reply = self.post(self.owner,'Thanks. Please finish at the usual time.',parent=root)
        for client in (self.owner,self.teacher):
            data = self.read(client)
            self.assertEqual(len(data['comments']),2)
            self.assertEqual(data['comments'][1]['parent_id'],root)
        self.assertEqual(self.read(self.teacher)['comments'][1]['can_edit'],False)
        self.assertEqual(self.read(self.owner)['comments'][1]['id'],reply)
        for client in (self.parent,self.client(),self.client('parent','Jenny Lee')):
            for path in ('/api/lesson-comments/1','/api/lesson-comments/summary?ids=1'):
                self.assertEqual(client.get(path).status_code,401)
            self.assertEqual(client.post('/api/lesson-comments/1',json={'body':'private'}).status_code,401)
        self.assertEqual(self.other.get('/api/lesson-comments/1').status_code,403)
        self.assertNotIn('1',self.summary(self.other))
        self.assertEqual(self.other.patch(f'/api/lesson-comments/1/{reply}',json={'body':'hack','revision':1}).status_code,403)

    def test_unread_is_per_user_and_edit_reopens_unread(self):
        comment = self.post(self.teacher)
        self.assertTrue(self.summary(self.owner)['1']['unread'])
        boundary = self.read(self.owner)['event_id']
        self.assertEqual(self.owner.post('/api/lesson-comments/1/read',json={'event_id':boundary}).status_code,200)
        self.assertFalse(self.summary(self.owner)['1']['unread'])
        self.assertTrue(self.summary(self.teacher)['1']['unread'])
        self.assertEqual(self.teacher.patch(f'/api/lesson-comments/1/{comment}',json={'body':'Actually 15 minutes late.','revision':1}).status_code,200)
        self.assertTrue(self.summary(self.owner)['1']['unread'])
        # A delayed request from an older tab must not mark a new edit as read.
        self.owner.post('/api/lesson-comments/1/read',json={'event_id':boundary})
        self.assertTrue(self.summary(self.owner)['1']['unread'])
        self.assertEqual(self.read(self.owner)['comments'][0]['revision'],2)
        self.assertTrue(self.read(self.owner)['comments'][0]['edited_at'])

    def test_author_only_edit_and_conflict_preserves_latest_text(self):
        comment = self.post(self.teacher)
        path = f'/api/lesson-comments/1/{comment}'
        self.assertEqual(self.owner.patch(path,json={'body':'Owner overwrite','revision':1}).status_code,403)
        self.assertEqual(self.teacher.patch(path,json={'body':'New text','revision':1}).status_code,200)
        self.assertEqual(self.teacher.patch(path,json={'body':'Stale text','revision':1}).status_code,409)
        self.assertEqual(self.read(self.owner)['comments'][0]['body'],'New text')

    def test_cross_lesson_reply_and_invalid_payloads(self):
        root = self.post(self.owner,lesson=2)
        self.assertEqual(self.teacher.post('/api/lesson-comments/1',json={'body':'Wrong lesson','parent_id':root}).status_code,400)
        for data in ({'body':''},{'body':12},{'body':'x'*5001},['wrong']):
            self.assertEqual(self.owner.post('/api/lesson-comments/1',json=data).status_code,400)
        for ids in ('1 OR 1=1','-1',','.join(map(str,range(1,302)))):
            self.assertEqual(self.owner.get('/api/lesson-comments/summary?ids='+ids).status_code,400)
        self.assertEqual(self.owner.get('/api/lesson-comments/999').status_code,404)
        self.assertEqual(self.owner.post('/api/lesson-comments/1/read',json={'event_id':True}).status_code,400)
        self.assertEqual(self.owner.get('/api/lesson-comments/summary?ids=').json,{'ok':True,'lessons':{}})

    def test_no_student_record_or_credit_required_and_finances_unchanged(self):
        self.post(self.teacher,'Trial lesson reminder',lesson=3)
        self.assertEqual(self.read(self.owner,3)['lesson']['student'],'Lesson')
        self.post(self.owner)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM schedule ORDER BY id').fetchall(),self.original_schedule)
            self.assertEqual(db.execute('SELECT lessons_left FROM enrollments WHERE id=42').fetchone()[0],8)
        # Same teacher/student/series never propagates comments to another class.
        self.assertEqual(self.read(self.owner,2)['comments'],[])

    def test_reads_do_not_regress_and_parent_never_gets_assets(self):
        self.post(self.owner)
        boundary = self.read(self.teacher)['event_id']
        self.teacher.post('/api/lesson-comments/1/read',json={'event_id':boundary})
        self.teacher.post('/api/lesson-comments/1/read',json={'event_id':0})
        self.assertFalse(self.summary(self.teacher)['1']['unread'])
        for client, path in ((self.owner,'/calendar'),(self.teacher,'/teacher_dashboard')):
            html=client.get(path).text
            self.assertIn('/static/lesson_comments.js',html)
            self.assertIn('/static/lesson_comments.css',html)
        self.assertNotIn('lesson_comments',self.parent.get('/parent_dashboard').text)
        self.assertNotIn('lesson_comments',self.parent.get('/calendar').text)

    def test_permission_rechecked_after_lesson_teacher_changes(self):
        self.post(self.teacher)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE schedule SET teacher='Other Teacher' WHERE id=1")
            db.commit()
        self.assertEqual(self.teacher.get('/api/lesson-comments/1').status_code,403)
        self.assertEqual(self.teacher.post('/api/lesson-comments/1',json={'body':'old access'}).status_code,403)
        self.assertEqual(len(self.read(self.other)['comments']),1)

    def test_user_text_round_trips_and_responses_are_not_cached(self):
        text='<img src=x onerror=alert(1)>\nA & B "notes"'
        self.post(self.owner,text)
        response=self.teacher.get('/api/lesson-comments/1')
        self.assertEqual(response.json['comments'][0]['body'],text)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn('author_key',response.text)


if __name__ == '__main__':
    unittest.main()
