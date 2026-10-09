import ast
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace


class ConflictTests(unittest.TestCase):
    def check_conflict(self, status='scheduled', row_room=2, row_location=2, row_teacher='Other', row_time='11:00'):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE schedule (id, student_name, teacher, classroom, lesson_time, duration, status, room_id, location_id, location, lesson_date)')
        conn.execute('INSERT INTO schedule VALUES (1, ?, ?, ?, ?, 30, ?, ?, ?, ?, ?)', ('Hazel', row_teacher, 'Room 3', row_time, status, row_room, row_location, 'Other campus', '2026-10-17'))
        tree = ast.parse(Path(__file__).with_name('app.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'schedule_has_conflict')
        scope = {'sqlite3': SimpleNamespace(connect=lambda _: conn), 'minutes_from_time_text': lambda t: int(t.split(':')[0])*60+int(t.split(':')[1]), 'safe_minutes': lambda d, fallback: int(d or fallback)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'conflict', 'exec'), scope)
        return scope['schedule_has_conflict']('Xu Huang', 'Room 3', '2026-10-17', '11:00', room_id=1, location_id=1, location='Target campus')['has_conflict']

    def test_different_room_same_name(self):
        self.assertFalse(self.check_conflict())

    def test_same_room(self):
        self.assertTrue(self.check_conflict(row_room=1, row_location=1))

    def test_teacher_conflict_across_locations(self):
        self.assertTrue(self.check_conflict(row_teacher='Xu Huang'))

    def test_cancelled_lesson_does_not_block(self):
        for status in ['last_min_cancel', 'excused_24h', 'teacher_cancelled', 'cancel_24h']:
            with self.subTest(status=status):
                self.assertFalse(self.check_conflict(status=status, row_room=1, row_location=1))

    def test_adjacent_lesson(self):
        self.assertFalse(self.check_conflict(row_room=1, row_time='10:30'))

    def test_legacy_room_uses_location(self):
        self.assertFalse(self.check_conflict(row_room=0, row_location=2))
        self.assertTrue(self.check_conflict(row_room=0, row_location=1))


if __name__ == '__main__':
    unittest.main()
