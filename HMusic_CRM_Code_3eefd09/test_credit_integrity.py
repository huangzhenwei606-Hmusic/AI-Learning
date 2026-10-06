import ast
import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote
from flask import Flask, request, redirect
from test_family_billing import FamilyBillingTests


class CreditIntegrityTests(FamilyBillingTests):
    def setUp(self):
        super().setUp()
        self.flask = Flask(__name__)
        names = {"edit_payment", "delete_payment", "update_student_course_credit", "repair_paid_invoice_credit", "pay_invoice", "edit_enrollment"}
        nodes = [n for n in ast.parse(Path(__file__).with_name("app.py").read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
        for n in nodes:
            n.decorator_list = []
        self.api.update(request=request, redirect=redirect, quote=quote,
            require_owner=lambda: True, ensure_v321_schema=lambda: None,
            ensure_guardian_billing_schema=lambda: None,
            sqlite3=SimpleNamespace(connect=lambda _: sqlite3.connect(self.path)),
            sync_invoice_allocations=Mock(), hmusic_lesson_count_label=str)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), self.api)

    def test_initial_tuition_negative_balance_and_retry(self):
        self.conn.execute("UPDATE invoices SET invoice_type='initial_tuition' WHERE id=3")
        self.conn.commit()
        result = self.api["record_invoice_allocation_paid"](self.conn.cursor(), 3, "Zelle")
        self.conn.commit()
        self.assertEqual(result["lessons_added"], 10)
        self.assertEqual(self.balances()[2], 9)
        description = self.conn.execute("SELECT description FROM student_ledger WHERE related_invoice_id=3").fetchone()[0]
        self.assertIn("Course credits: -1 + 10 = 9", description)
        self.api["record_invoice_allocation_paid"](self.conn.cursor(), 3, "Zelle")
        self.conn.commit()
        self.assertEqual(self.balances()[2], 9)

    def test_delete_payment_preserves_debt(self):
        self.conn.execute("UPDATE enrollments SET lessons_left=9 WHERE id=3")
        self.conn.execute("INSERT INTO payments(id,student_name,lessons_added,enrollment_id) VALUES(1,'Valerie',10,3)")
        self.conn.commit()
        with self.flask.test_request_context("/delete_payment/1", method="POST"):
            self.api["delete_payment"](1)
        self.assertEqual(self.balances()[2], -1)

    def test_stale_credit_form_cannot_overwrite_paid_balance(self):
        self.conn.execute("UPDATE enrollments SET lessons_left=9 WHERE id=3")
        self.conn.commit()
        with self.flask.test_request_context(method="POST", data={"enrollment_id":3,"lessons_left":-1,"expected_lessons_left":-1}):
            result = self.api["update_student_course_credit"]("Valerie")
        self.assertEqual(result[1], 409)
        self.assertEqual(self.balances()[2], 9)

    def test_owner_can_intentionally_set_negative_credit(self):
        with self.flask.test_request_context(method="POST", data={"enrollment_id":3,"lessons_left":-2,"expected_lessons_left":-1}):
            result = self.api["update_student_course_credit"]("Valerie")
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.balances()[2], -2)

    def test_missing_balance_snapshot_is_rejected(self):
        with self.flask.test_request_context(method="POST", data={"enrollment_id":3,"lessons_left":0}):
            result = self.api["update_student_course_credit"]("Valerie")
        self.assertEqual(result[1], 409)
        self.assertEqual(self.balances()[2], -1)

    def test_already_applied_invoice_cannot_grant_again(self):
        self.conn.execute("UPDATE invoices SET credits_applied=1,status='paid' WHERE id=3")
        self.conn.commit()
        invoice=(3,'Valerie',10,525,'paid','initial_tuition','date',3)
        self.assertEqual(self.api["repair_paid_invoice_credit"](self.conn.cursor(),invoice),0)
        self.assertEqual(self.balances()[2],-1)

    def test_open_paid_invoice_is_read_only(self):
        self.conn.execute("ALTER TABLE invoices ADD COLUMN created_at TEXT")
        self.conn.execute("CREATE TABLE parent_profiles(id INTEGER,parent_name TEXT,email TEXT)")
        self.conn.execute("UPDATE invoices SET status='paid',credits_applied=0 WHERE id=3")
        self.conn.commit()
        repair=Mock(side_effect=AssertionError("GET must not grant credit"))
        self.api["repair_paid_invoice_credit"]=repair
        with self.flask.test_request_context("/pay_invoice/3"):
            self.assertIn("Already Paid",self.api["pay_invoice"](3))
        repair.assert_not_called()
        self.assertEqual(self.balances()[2],-1)

    def test_stale_enrollment_form_cannot_overwrite_credits(self):
        for field in ["discount_type TEXT","discount_value REAL","status TEXT","auto_renew_enabled INTEGER","auto_renew_lessons REAL","notes TEXT"]:
            self.conn.execute("ALTER TABLE enrollments ADD COLUMN "+field)
        self.conn.execute("UPDATE enrollments SET lessons_left=9 WHERE id=3")
        self.conn.commit()
        with self.flask.test_request_context(method="POST",data={"lessons_left":0,"expected_lessons_left":-1}):
            result=self.api["edit_enrollment"](3)
        self.assertEqual(result[1],409)
        self.assertEqual(self.balances()[2],9)

    def test_edit_payment_preserves_negative_balance(self):
        self.conn.execute("INSERT INTO payments(id,student_name,amount,lessons_added,payment_method,payment_date,enrollment_id) VALUES(1,'Valerie',750,10,'Zelle','2026-10-06',3)")
        self.conn.commit()
        with self.flask.test_request_context(method="POST",data={"amount":675,"lessons_added":9,"payment_method":"Zelle"}):
            self.api["edit_payment"](1)
        self.assertEqual(self.balances()[2],-2)
