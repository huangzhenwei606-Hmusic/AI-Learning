"""Cancellation inbox/delivery tests without importing app or accessing production DB."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

TREE = ast.parse(Path(__file__).with_name('app.py').read_text())

def load(name, scope):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<cancellation>', 'exec'), scope)
    return scope[name]

class CancellationNotificationsTest(unittest.TestCase):
    def test_each_update_reaches_teacher_inbox_and_linked_notification(self):
        for state in ('pending', 'approved', 'rejected', 'withdrawn'):
            with self.subTest(state=state):
                scope = dict(get_or_create_message_thread=Mock(return_value=91),
                             add_message=Mock(), create_notification=Mock())
                notify = load('notify_teacher_parent_cancellation', scope)
                notify(24, 'Jenny Lee', 'Olivia Ma', '2026-10-09', '14:15', state)
                thread = scope['get_or_create_message_thread'].call_args.kwargs
                self.assertEqual(thread['teacher_name'], 'Jenny Lee')
                self.assertEqual(thread['related_id'], 24)
                message = scope['add_message'].call_args.args
                self.assertEqual(message[:4], (91, 'system', 'H-Music', 'teacher'))
                self.assertIn('Olivia Ma · 2026-10-09 14:15', message[4])
                delivery = scope['create_notification'].call_args.args
                self.assertEqual(delivery[:2], ('teacher', 'Jenny Lee'))
                self.assertEqual(delivery[4], '/message_thread/91')
                if state == 'pending':
                    self.assertIn('not confirmed yet', message[4])
                if state == 'approved':
                    self.assertIn('do not teach', message[4])

    def test_cancellation_email_is_immediate_for_teacher_and_owner(self):
        policy = load('hmusic_should_send_message_email_now', {})
        for role in ('teacher', 'owner'):
            self.assertTrue(policy(role, 'Parent cancellation request'))
            self.assertTrue(policy(role, 'Parent cancellation confirmed'))
            self.assertTrue(policy(role, 'Cancellation request withdrawn'))
            self.assertFalse(policy(role, 'Lesson reminder'))
        self.assertTrue(policy('parent', 'New message'))

    def test_review_updates_calendar_before_teacher_confirmation(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.db')
            db = sqlite3.connect(path)
            db.executescript('''CREATE TABLE schedule(id INTEGER, status TEXT);
                INSERT INTO schedule VALUES(3,'parent_cancel_pending_confirm');
                CREATE TABLE lesson_change_requests(id INTEGER,parent_id,student_name,schedule_id,
                request_type,original_date,original_time,teacher,classroom,policy_status,fee_preview,
                waiver_available,reason,status,owner_decision,owner_note,created_at,updated_at);
                INSERT INTO lesson_change_requests VALUES(24,2,'Olivia Ma',3,'cancel_lesson',
                '2026-10-09','14:15','Jenny Lee','Room 2','excused_24h',0,0,'Cancel',
                'pending',NULL,NULL,'2026-10-05',NULL);''')
            db.commit()
            db.close()
            def apply(schedule_id, status, **kwargs):
                with sqlite3.connect(path) as conn:
                    conn.execute('UPDATE schedule SET status=? WHERE id=?', (status, schedule_id))
                return {'ok': True}
            def notified(*args):
                with sqlite3.connect(path) as conn:
                    self.assertEqual(conn.execute('SELECT status FROM schedule').fetchone()[0], 'excused_24h')
                    self.assertEqual(conn.execute('SELECT status FROM lesson_change_requests').fetchone()[0], 'approved')
                self.assertEqual(args, (24, 'Jenny Lee', 'Olivia Ma', '2026-10-09', '14:15', 'approved'))
            notify = Mock(side_effect=notified)
            scope = dict(require_owner=lambda:True, ensure_v321_schema=lambda:None,
                sqlite3=SimpleNamespace(connect=lambda _: sqlite3.connect(path)),
                request=SimpleNamespace(method='POST',form={'action':'apply_policy'}),
                apply_lesson_status=apply,datetime=datetime,
                notify_teacher_parent_cancellation=notify,create_notification=Mock(),redirect=lambda url:url)
            review = load('lesson_change_request_detail', scope)
            self.assertEqual(review(24).split('?')[0], '/lesson_change_request/24')
            notify.assert_called_once()
            review(24)  # Repeated approval must not send another message.
            notify.assert_called_once()

if __name__ == '__main__':
    unittest.main()
