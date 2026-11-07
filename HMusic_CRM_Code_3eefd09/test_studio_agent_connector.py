import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from studio_agent_connector import register_blueprint


class StudioAgentConnectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.db'
        c = sqlite3.connect(self.db)
        c.executescript('''
            CREATE TABLE schedule(id INTEGER,student_name TEXT,teacher TEXT,
                lesson_date TEXT,lesson_time TEXT,duration INTEGER,classroom TEXT,
                location TEXT,status TEXT,private_note TEXT);
            INSERT INTO schedule VALUES(1,'Fixture','Teacher','2026-11-06','14:00',45,
                'Room 1','Campus','scheduled','Do not export');
            INSERT INTO schedule VALUES(2,'Outside range','Teacher','2026-12-01','14:00',30,
                'Room 1','Campus','scheduled','Do not export');
            CREATE TABLE students(id INTEGER,name TEXT,parent_email TEXT,password TEXT);
            INSERT INTO students VALUES(1,'Fixture','private@example.invalid','private');
        ''')
        c.close()
        self.app = Flask(__name__)
        register_blueprint(self.app, lambda: sqlite3.connect(self.db))
        self.client = self.app.test_client()
        self.path = '/api/studio-agent/v1/snapshot?start=2026-11-06&end=2026-11-12'
        self.token = 'test-scoped-read-token-' + 'x' * 32
        self.env = patch.dict(os.environ, {'HMUSIC_AGENT_READ_TOKEN':self.token})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_authentication_is_required_and_defaults_to_disabled(self):
        self.assertEqual(self.client.get(self.path).status_code,401)
        self.assertEqual(self.client.get(self.path,headers={'Authorization':'Bearer wrong'}).status_code,401)
        with patch.dict(os.environ, {'HMUSIC_AGENT_READ_TOKEN':''}):
            self.assertEqual(self.client.get(self.path).status_code,503)

    def test_read_is_scoped_and_does_not_modify_database(self):
        before = hashlib.sha256(self.db.read_bytes()).digest()
        r = self.client.get(self.path,headers={'Authorization':'Bearer '+self.token})
        self.assertEqual(r.status_code,200)
        d = r.get_json()
        self.assertEqual(len(d['lessons']),1)
        self.assertNotIn('private_note',d['lessons'][0])
        self.assertNotIn('password',d['students'][0])
        self.assertNotIn('parent_email',d['students'][0])
        self.assertFalse(d['capabilities']['write'])
        self.assertIn('no-store',r.headers['Cache-Control'])
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).digest())

    def test_invalid_dates_and_non_read_methods_are_rejected(self):
        headers={'Authorization':'Bearer '+self.token}
        self.assertEqual(self.client.get(self.path.replace('2026-11-06','2026-02-30'),headers=headers).status_code,400)
        self.assertEqual(self.client.get(self.path.replace('2026-11-12','2027-01-12'),headers=headers).status_code,400)
        self.assertEqual(self.client.post(self.path,headers=headers).status_code,405)

    def test_full_app_registers_service_and_skips_request_side_effects(self):
        # Never inherit a deployment's production DB or startup migration settings.
        with patch.dict(os.environ, {'HMUSIC_DB_PATH':str(self.db), 'DATABASE_URL':'',
                                    'HMUSIC_PREPARE_DB_ON_STARTUP':'0',
                                    'HMUSIC_SECRET_KEY':'test-only-studio-agent-secret'}):
            import app as crm
        self.assertIn('studio_agent_readonly.snapshot',crm.app.view_functions)
        with crm.app.test_request_context(self.path):
            with patch.object(crm,'ensure_production_schema',side_effect=AssertionError('must not initialize')):
                self.assertIsNone(crm.prepare_database_for_request())


if __name__=='__main__': unittest.main()
