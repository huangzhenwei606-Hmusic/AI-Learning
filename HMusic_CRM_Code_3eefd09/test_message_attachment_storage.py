"""Exercise attachment persistence and HTTP downloads without production data."""
import ast
import base64
from contextlib import closing
from datetime import datetime
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from flask import Flask, Response, redirect, send_from_directory
from werkzeug.datastructures import FileStorage

SOURCE = ast.parse(Path(__file__).with_name('app.py').read_text())

class AttachmentStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = os.path.join(self.temp.name, 'test.db')
        self.app = Flask(__name__)
        self.app.testing = True
        self.owner = True
        self.s3 = Mock()
        self.scope = dict(
            app=self.app, sqlite3=Mock(connect=lambda _: sqlite3.connect(self.db_path)),
            datetime=datetime, io=io, os=os, Response=Response,
            redirect=redirect, send_from_directory=send_from_directory,
            HMUSIC_UPLOAD_DIR=self.temp.name, ensure_v29_schema=lambda: None,
            require_owner=lambda: self.owner, require_parent=lambda: False,
            require_teacher=lambda: False,
            get_message_upload_s3_config=lambda: {'bucket':'test','prefix':'uploads'},
            message_upload_s3_client=lambda _: self.s3,
            message_upload_s3_key=lambda _, filename: 'uploads/' + filename,
        )
        nodes = [n for n in SOURCE.body if
                 isinstance(n, ast.FunctionDef) and n.name in
                 ('safe_upload_filename','save_message_attachments','message_upload') or
                 isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ALLOWED_UPLOAD_MIME_TYPES' for t in n.targets)]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<attachments>', 'exec'), self.scope)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE message_attachments (id INTEGER PRIMARY KEY, message_id, original_filename, stored_filename, mime_type, file_size, created_at, content_base64 TEXT)')

    def upload(self, payload=b'\x00\xffattachment bytes', filename='score.pdf'):
        file = FileStorage(stream=io.BytesIO(payload), filename=filename, content_type='application/pdf')
        self.scope['save_message_attachments'](42, [file])
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute('SELECT stored_filename, content_base64, file_size FROM message_attachments').fetchone()
        return payload, row

    def test_failed_s3_preserves_bytes_and_downloads_without_s3(self):
        def fail(stream, *args, **kwargs):
            stream.read(3)
            stream.close()
            raise RuntimeError('AuthorizationHeaderMalformed')
        self.s3.upload_fileobj.side_effect = fail
        payload, row = self.upload()
        self.assertEqual(base64.b64decode(row[1]), payload)
        self.assertEqual(row[2], len(payload))
        response = self.app.test_client().get('/message_uploads/' + row[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        self.assertIn('score.pdf', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.s3.head_object.assert_not_called()

    def test_client_construction_failure_uses_database(self):
        self.scope['message_upload_s3_client'] = Mock(side_effect=RuntimeError('bad config'))
        payload, row = self.upload()
        self.assertEqual(base64.b64decode(row[1]), payload)

    def test_successful_s3_keeps_normal_download(self):
        payload, row = self.upload()
        self.assertIsNone(row[1])
        self.s3.generate_presigned_url.return_value = 'https://storage.example.test/file'
        response = self.app.test_client().get('/message_uploads/' + row[0])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, 'https://storage.example.test/file')
        self.s3.head_object.assert_called_once()

    def test_local_upload_and_download_still_work(self):
        self.scope['get_message_upload_s3_config'] = lambda: None
        payload, row = self.upload()
        self.assertIsNone(row[1])
        response = self.app.test_client().get('/message_uploads/' + row[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        response.close()

    def test_database_attachment_still_requires_login(self):
        self.s3.upload_fileobj.side_effect = RuntimeError('storage unavailable')
        _, row = self.upload()
        self.owner = False
        response = self.app.test_client().get('/message_uploads/' + row[0])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/owner_login')

    def test_unsupported_files_are_not_stored(self):
        self.scope['save_message_attachments'](42, [FileStorage(stream=io.BytesIO(b'x'), filename='bad.exe', content_type='application/octet-stream')])
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_attachments').fetchone()[0], 0)
        self.s3.upload_fileobj.assert_not_called()

class AttachmentMigrationTest(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.scope = dict(
            using_postgres=lambda: True,
            sqlite3=Mock(connect=Mock(return_value=self.connection)),
        )
        node = next(n for n in SOURCE.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'ensure_postgres_message_attachment_schema')
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<migration>', 'exec'), self.scope)

    def test_postgres_migration_is_idempotent_and_committed(self):
        migrate = self.scope['ensure_postgres_message_attachment_schema']
        migrate()
        migrate()
        self.connection.execute.assert_called_with(
            'ALTER TABLE message_attachments ADD COLUMN IF NOT EXISTS content_base64 TEXT')
        self.assertEqual(self.connection.commit.call_count, 2)
        self.assertEqual(self.connection.close.call_count, 2)

    def test_migration_failure_rolls_back_and_closes(self):
        self.connection.execute.side_effect = RuntimeError('migration failed')
        with self.assertRaises(RuntimeError):
            self.scope['ensure_postgres_message_attachment_schema']()
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()
        self.connection.commit.assert_not_called()

    def test_sqlite_uses_legacy_schema(self):
        self.scope['using_postgres'] = lambda: False
        self.scope['ensure_postgres_message_attachment_schema']()
        self.scope['sqlite3'].connect.assert_not_called()

    def test_postgres_startup_runs_attachment_migration(self):
        node = next(n for n in SOURCE.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'initialize_runtime_database')
        scope = dict(using_postgres=lambda: True, time=Mock(), app=Mock(),
                     sqlite3=Mock(connect=Mock(return_value=self.connection)))
        scope['time'].perf_counter.side_effect = (1.0, 2.0)
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                scope.setdefault(call.func.id, Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<startup>', 'exec'), scope)
        scope['initialize_runtime_database']()
        scope['ensure_postgres_message_attachment_schema'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
