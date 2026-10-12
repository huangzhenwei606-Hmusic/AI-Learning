import ast
from datetime import datetime
from pathlib import Path
import sqlite3
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock


class AttendanceCreditsTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
        CREATE TABLE schedule(id,course_type_id,course_type_name,duration,teacher);
        CREATE TABLE enrollments(id,student_name,course_type_id,course_type_name,duration,teacher_name,status,lessons_left,updated_at);
        CREATE TABLE group_schedule_students(id,schedule_id,student_name,credit_units,billing_rule,attendance_credit_applied,attendance_enrollment_id);
        INSERT INTO schedule VALUES(1,5,'Ensemble',60,'Mike');
        INSERT INTO enrollments VALUES(8,'A',5,'Ensemble',60,'Mike','active',10,NULL);
        INSERT INTO enrollments VALUES(9,'A',2,'Piano',30,'Mike','active',20,NULL);
        INSERT INTO enrollments VALUES(10,'B',5,'Ensemble',60,'Mike','active',6,NULL);
        INSERT INTO group_schedule_students VALUES(1,1,'A',1,'existing_credits',0,NULL);
        INSERT INTO group_schedule_students VALUES(2,1,'B',0.5,'existing_credits',0,NULL);
        ''')
        scope = dict(datetime=datetime, hmusic_teacher_name_matches=lambda a,b:a==b)
        tree = ast.parse(Path(__file__).with_name('app.py').read_text())
        for name in ('hmusic_attendance_enrollment','hmusic_apply_group_attendance_credit'):
            node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<attendance>','exec'),scope)
        self.resolve = scope['hmusic_attendance_enrollment']
        self.apply = scope['hmusic_apply_group_attendance_credit']

    def balance(self, id=8):
        return self.db.execute('SELECT lessons_left FROM enrollments WHERE id=?',(id,)).fetchone()[0]

    def test_present_repeat_and_reversal(self):
        for _ in range(2): self.apply(self.db.cursor(),1,'A','present')
        self.assertEqual(self.balance(),9)
        self.assertEqual(self.balance(9),20)
        for _ in range(2): self.apply(self.db.cursor(),1,'A','scheduled')
        self.assertEqual(self.balance(),10)

    def test_participant_fractional_credits(self):
        self.apply(self.db.cursor(),1,'B','present')
        self.assertEqual(self.balance(10),5.5)
        self.assertEqual(self.balance(),10)

    def test_no_charge(self):
        self.db.execute("UPDATE group_schedule_students SET billing_rule='no_charge' WHERE student_name='A'")
        self.apply(self.db.cursor(),1,'A','present')
        self.assertEqual(self.balance(),10)

    def test_missing_link_and_wrong_student(self):
        self.assertEqual(self.resolve(self.db.cursor(),1,'A'),8)
        self.assertEqual(self.resolve(self.db.cursor(),1,'A',10),8)

    def test_ambiguous_wallet_rejects_without_debit(self):
        self.db.execute("INSERT INTO enrollments VALUES(11,'A',5,'Ensemble',60,'Mike','active',3,NULL)")
        with self.assertRaises(ValueError): self.apply(self.db.cursor(),1,'A','present')
        self.assertEqual(self.balance(),10)

    def test_missing_legacy_course_metadata_single_wallet(self):
        self.db.execute("UPDATE schedule SET course_type_id=NULL,course_type_name=NULL")
        self.assertEqual(self.resolve(self.db.cursor(),1,'B'),10)
        self.assertIsNone(self.resolve(self.db.cursor(),1,'A'))

    def test_duration_change_does_not_discard_unique_course_wallet(self):
        self.db.execute("UPDATE schedule SET duration=45")
        self.apply(self.db.cursor(),1,'A','present')
        self.assertEqual(self.balance(),9)
        self.assertEqual(self.balance(9),20)

    def test_id_takes_precedence_over_duplicate_course_names(self):
        self.db.execute("INSERT INTO enrollments VALUES(11,'A',7,'Ensemble',60,'Mike','active',3,NULL)")
        self.assertEqual(self.resolve(self.db.cursor(),1,'A'),8)

    def test_malformed_duration_is_not_a_server_error(self):
        self.db.execute("UPDATE enrollments SET duration='45 minutes' WHERE id=8")
        self.assertEqual(self.resolve(self.db.cursor(),1,'A'),8)

    def test_known_different_course_never_uses_single_wallet(self):
        self.db.execute("UPDATE schedule SET course_type_id=2,course_type_name='Piano'")
        self.assertIsNone(self.resolve(self.db.cursor(),1,'B'))

    def test_private_present_links_debits_once_and_cancel_refunds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'credits.db')
            db = sqlite3.connect(path)
            self.db.backup(db)
            for column in ('student_name TEXT','charge_lessons REAL','enrollment_id INTEGER',
                           'student_charge_amount REAL','teacher_pay_amount REAL','lesson_date TEXT',
                           'lesson_time TEXT','policy_waiver_applied INTEGER','pending_fee_amount REAL',
                           'is_group INTEGER','status TEXT','student_charge_units REAL','teacher_pay_units REAL',
                           'revenue_amount REAL','payroll_amount REAL','profit_amount REAL',
                           'cancellation_reason TEXT','cancelled_at TEXT'):
                db.execute('ALTER TABLE schedule ADD COLUMN '+column)
            db.execute("UPDATE schedule SET student_name='A',charge_lessons=0,is_group=0,lesson_date='2026-10-10'")
            db.execute('CREATE TABLE student_ledger(student_name,entry_type,amount,description,related_invoice_id,related_payment_id,related_schedule_id,created_at)')
            db.commit(); db.close()
            scope = dict(datetime=datetime, sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(path)),
                         ensure_v321_schema=lambda:None, is_payroll_locked=lambda _:False,
                         hmusic_teacher_name_matches=lambda a,b:a==b,
                         hmusic_waiver_holder=lambda *args:dict(used=0,allowance=0),
                         get_business_rule=lambda status:dict(student_charge_percent=100,teacher_pay_percent=100,deduct_lesson=int(status=='present')),
                         maybe_handle_enrollment_renewal=lambda *args:[],
                         hmusic_policy_status_label=lambda s:s, app=SimpleNamespace(logger=Mock()))
            tree = ast.parse(Path(__file__).with_name('app.py').read_text())
            for name in ('hmusic_attendance_enrollment','apply_lesson_status'):
                node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
                exec(compile(ast.Module(body=[node],type_ignores=[]),'<private-attendance>','exec'),scope)
            for _ in range(2): self.assertTrue(scope['apply_lesson_status'](1,'present')['ok'])
            with sqlite3.connect(path) as check:
                self.assertEqual(check.execute('SELECT lessons_left FROM enrollments WHERE id=8').fetchone()[0],9)
                self.assertEqual(check.execute('SELECT enrollment_id FROM schedule').fetchone()[0],8)
            self.assertTrue(scope['apply_lesson_status'](1,'scheduled')['ok'])
            with sqlite3.connect(path) as check:
                self.assertEqual(check.execute('SELECT lessons_left FROM enrollments WHERE id=8').fetchone()[0],10)

    def tearDown(self):
        self.db.close()


if __name__ == '__main__': unittest.main()
