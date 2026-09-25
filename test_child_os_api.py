import os
import sqlite3
import tempfile
import unittest

from flask import Flask

from child_os_api import register_child_os_api


class ChildOsApiTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
        CREATE TABLE parent_profiles (id INTEGER PRIMARY KEY, parent_name TEXT, email TEXT, phone TEXT, active INTEGER);
        CREATE TABLE parent_students (parent_id INTEGER, student_name TEXT, relationship TEXT, active INTEGER);
        CREATE TABLE students (name TEXT, teacher TEXT, lessons_left INTEGER, free_cancel_used INTEGER);
        CREATE TABLE schedule (id INTEGER PRIMARY KEY, student_name TEXT, teacher TEXT, lesson_date TEXT, lesson_time TEXT, classroom TEXT, location TEXT, status TEXT, course_type_name TEXT, duration INTEGER);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, student_name TEXT, amount REAL, status TEXT, invoice_type TEXT, created_at TEXT, due_date TEXT, notes TEXT);
        CREATE TABLE reschedule_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, student_name TEXT, original_schedule_id INTEGER, original_date TEXT, original_time TEXT, original_teacher TEXT, original_classroom TEXT, requested_date TEXT, requested_time TEXT, reason TEXT, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE child_os_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, student_name TEXT, request_text TEXT, language TEXT, intent TEXT, risk_level TEXT, route_to TEXT, status TEXT, outcome TEXT, related_schedule_id INTEGER, created_at TEXT, updated_at TEXT);
        CREATE TABLE message_threads (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, student_name TEXT, parent_id INTEGER, thread_type TEXT, status TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, sender_role TEXT, sender_name TEXT, recipient_role TEXT, body TEXT, channel TEXT, created_at TEXT);
        INSERT INTO parent_profiles VALUES (1, 'Test Parent', 'parent@example.com', '555-0100', 1);
        INSERT INTO parent_students VALUES (1, 'Alaia', 'Parent', 1);
        INSERT INTO students VALUES ('Alaia', 'Coach', 6, 0);
        INSERT INTO schedule VALUES (10, 'Alaia', 'Coach', '2099-10-03', '14:00', 'Room A', 'Foster City', 'scheduled', 'Piano', 60);
        INSERT INTO invoices VALUES (20, 'Alaia', 268, 'open', 'tuition', '2099-09-01', '2099-09-30', 'October');
        """)
        conn.commit()
        conn.close()
        app = Flask(__name__)
        register_child_os_api(app, self.db_path, api_token="test-token")
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        os.unlink(self.db_path)

    def test_requires_service_token(self):
        result = self.client.get("/api/child-os/v1/families/1")
        self.assertEqual(result.status_code, 401)

    def test_reads_family_schedule_credits_and_invoices(self):
        family = self.client.get("/api/child-os/v1/families/1", headers=self.headers)
        schedule = self.client.get("/api/child-os/v1/students/Alaia/schedule?parent_id=1", headers=self.headers)
        credits = self.client.get("/api/child-os/v1/students/Alaia/credits?parent_id=1", headers=self.headers)
        invoices = self.client.get("/api/child-os/v1/students/Alaia/invoices?parent_id=1", headers=self.headers)
        self.assertEqual(family.status_code, 200)
        self.assertEqual(schedule.get_json()["schedule"][0]["id"], 10)
        self.assertEqual(credits.get_json()["credits"]["lessons_left"], 6)
        self.assertEqual(invoices.get_json()["invoices"][0]["amount"], 268)

    def test_reschedule_is_idempotent(self):
        headers = {**self.headers, "Idempotency-Key": "reschedule-1"}
        payload = {"parent_id": 1, "student_name": "Alaia", "schedule_id": 10, "requested_date": "2099-10-05", "requested_time": "15:00"}
        first = self.client.post("/api/child-os/v1/reschedule-requests", json=payload, headers=headers)
        second = self.client.post("/api/child-os/v1/reschedule-requests", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.get_json(), second.get_json())
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM reschedule_requests").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_money_and_withdrawal_never_execute(self):
        for action in ("make_payment", "request_refund", "drop_or_cancel_enrollment"):
            result = self.client.post(f"/api/child-os/v1/actions/{action}", headers=self.headers)
            self.assertEqual(result.status_code, 409)
            self.assertFalse(result.get_json()["executed"])
            self.assertEqual(result.get_json()["status"], "requires_parent_confirmation")


if __name__ == "__main__":
    unittest.main()

