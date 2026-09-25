import json
import os
import secrets
import sqlite3
from datetime import date, datetime

from flask import Response, request


API_PREFIX = "/api/child-os/v1"
CONFIRMATION_ONLY_ACTIONS = {
    "make_payment",
    "request_refund",
    "drop_or_cancel_enrollment",
}


def register_child_os_api(app, db_path, api_token=None):
    token = api_token or os.environ.get("HMUSIC_CHILD_OS_API_TOKEN", "")

    def response(payload, status=200):
        return Response(
            json.dumps(payload, ensure_ascii=False, default=str),
            status=status,
            mimetype="application/json",
        )

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def row_dict(row):
        return {key: row[key] for key in row.keys()}

    def ensure_schema():
        conn = connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS child_os_api_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                parent_id INTEGER,
                student_name TEXT,
                status_code INTEGER NOT NULL,
                idempotency_key TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS child_os_api_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                response_json TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def authorized():
        if not token:
            return False, response({"error": "child_os_api_not_configured"}, 503)
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        if not secrets.compare_digest(supplied, expected):
            return False, response({"error": "unauthorized"}, 401)
        return True, None

    def parent_can_access(conn, parent_id, student_name):
        row = conn.execute(
            """SELECT 1 FROM parent_students
               WHERE parent_id=? AND lower(student_name)=lower(?)
               AND COALESCE(active, 1)=1 LIMIT 1""",
            (parent_id, student_name),
        ).fetchone()
        return row is not None

    def audit(action, status_code, parent_id=None, student_name=None, idem=None):
        conn = connect()
        conn.execute(
            """INSERT INTO child_os_api_audit
               (action, parent_id, student_name, status_code, idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (action, parent_id, student_name, status_code, idem, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()

    def idempotent_result(action):
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return None, None
        conn = connect()
        row = conn.execute(
            "SELECT action, response_json, status_code FROM child_os_api_idempotency WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        conn.close()
        if not row:
            return key, None
        if row["action"] != action:
            return key, response({"error": "idempotency_key_reused"}, 409)
        return key, response(json.loads(row["response_json"]), row["status_code"])

    def remember_idempotent(key, action, payload, status_code):
        if not key:
            return
        conn = connect()
        conn.execute(
            """INSERT OR IGNORE INTO child_os_api_idempotency
               (idempotency_key, action, response_json, status_code, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (key, action, json.dumps(payload, ensure_ascii=False), status_code,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()

    def require_auth():
        ok, failure = authorized()
        return failure if not ok else None

    ensure_schema()

    @app.get(f"{API_PREFIX}/policy")
    def child_os_api_policy():
        failure = require_auth()
        if failure:
            return failure
        return response({
            "automatic": ["read", "draft_message", "submit_absence", "submit_reschedule"],
            "confirm_every_time": sorted(CONFIRMATION_ONLY_ACTIONS),
        })

    @app.get(f"{API_PREFIX}/families/<int:parent_id>")
    def child_os_api_family(parent_id):
        failure = require_auth()
        if failure:
            return failure
        conn = connect()
        parent = conn.execute(
            "SELECT id, parent_name, email, phone FROM parent_profiles WHERE id=? AND COALESCE(active,1)=1",
            (parent_id,),
        ).fetchone()
        students = conn.execute(
            """SELECT ps.student_name, ps.relationship, s.teacher, s.lessons_left
               FROM parent_students ps LEFT JOIN students s ON lower(s.name)=lower(ps.student_name)
               WHERE ps.parent_id=? AND COALESCE(ps.active,1)=1 ORDER BY ps.student_name""",
            (parent_id,),
        ).fetchall()
        conn.close()
        if not parent:
            return response({"error": "family_not_found"}, 404)
        return response({"family": row_dict(parent), "students": [row_dict(row) for row in students]})

    @app.get(f"{API_PREFIX}/students/<student_name>/schedule")
    def child_os_api_schedule(student_name):
        failure = require_auth()
        if failure:
            return failure
        parent_id = request.args.get("parent_id", type=int)
        conn = connect()
        if not parent_id or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        rows = conn.execute(
            """SELECT id, lesson_date, lesson_time, teacher, classroom, location, status,
                      course_type_name, duration
               FROM schedule WHERE lower(student_name)=lower(?) AND lesson_date>=?
               ORDER BY lesson_date, lesson_time LIMIT 100""",
            (student_name, date.today().isoformat()),
        ).fetchall()
        conn.close()
        return response({"student_name": student_name, "schedule": [row_dict(row) for row in rows]})

    @app.get(f"{API_PREFIX}/students/<student_name>/credits")
    def child_os_api_credits(student_name):
        failure = require_auth()
        if failure:
            return failure
        parent_id = request.args.get("parent_id", type=int)
        conn = connect()
        if not parent_id or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        row = conn.execute(
            "SELECT lessons_left, free_cancel_used FROM students WHERE lower(name)=lower(?)",
            (student_name,),
        ).fetchone()
        conn.close()
        return response({"student_name": student_name, "credits": row_dict(row) if row else None})

    @app.get(f"{API_PREFIX}/students/<student_name>/invoices")
    def child_os_api_invoices(student_name):
        failure = require_auth()
        if failure:
            return failure
        parent_id = request.args.get("parent_id", type=int)
        conn = connect()
        if not parent_id or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        rows = conn.execute(
            """SELECT id, amount, status, invoice_type, created_at, due_date, notes
               FROM invoices WHERE lower(student_name)=lower(?) ORDER BY id DESC LIMIT 100""",
            (student_name,),
        ).fetchall()
        conn.close()
        return response({"student_name": student_name, "invoices": [row_dict(row) for row in rows]})

    @app.get(f"{API_PREFIX}/reschedule-options")
    def child_os_api_reschedule_options():
        failure = require_auth()
        if failure:
            return failure
        parent_id = request.args.get("parent_id", type=int)
        student_name = (request.args.get("student_name") or "").strip()
        conn = connect()
        if not parent_id or not student_name or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        rows = conn.execute(
            """SELECT id, lesson_date, lesson_time, teacher, classroom, location
               FROM schedule WHERE lower(student_name)=lower(?) AND lesson_date>=?
               AND COALESCE(status,'scheduled') IN ('', 'scheduled')
               ORDER BY lesson_date, lesson_time LIMIT 30""",
            (student_name, date.today().isoformat()),
        ).fetchall()
        conn.close()
        return response({"student_name": student_name, "lessons": [row_dict(row) for row in rows]})

    @app.post(f"{API_PREFIX}/absence-requests")
    def child_os_api_absence():
        failure = require_auth()
        if failure:
            return failure
        action = "submit_absence"
        idem, replay = idempotent_result(action)
        if replay:
            return replay
        data = request.get_json(silent=True) or {}
        parent_id = data.get("parent_id")
        student_name = str(data.get("student_name") or "").strip()
        schedule_id = data.get("schedule_id")
        conn = connect()
        if not parent_id or not student_name or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        lesson = conn.execute(
            "SELECT id FROM schedule WHERE id=? AND lower(student_name)=lower(?)",
            (schedule_id, student_name),
        ).fetchone()
        if not lesson:
            conn.close()
            return response({"error": "lesson_not_found"}, 404)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """INSERT INTO child_os_requests
               (parent_id, student_name, request_text, language, intent, risk_level,
                route_to, status, outcome, related_schedule_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'absence_request', 'teal', 'studio', 'submitted', ?, ?, ?, ?)""",
            (parent_id, student_name, data.get("reason") or "Absence request", data.get("language") or "en",
             "Absence submitted; schedule is unchanged until studio policy is applied.", schedule_id, now, now),
        )
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        payload = {"ok": True, "request_id": request_id, "status": "submitted", "schedule_changed": False}
        remember_idempotent(idem, action, payload, 201)
        audit(action, 201, parent_id, student_name, idem)
        return response(payload, 201)

    @app.post(f"{API_PREFIX}/reschedule-requests")
    def child_os_api_reschedule():
        failure = require_auth()
        if failure:
            return failure
        action = "submit_reschedule"
        idem, replay = idempotent_result(action)
        if replay:
            return replay
        data = request.get_json(silent=True) or {}
        parent_id = data.get("parent_id")
        student_name = str(data.get("student_name") or "").strip()
        schedule_id = data.get("schedule_id")
        conn = connect()
        if not parent_id or not student_name or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        lesson = conn.execute(
            """SELECT id, lesson_date, lesson_time, teacher, classroom FROM schedule
               WHERE id=? AND lower(student_name)=lower(?)""",
            (schedule_id, student_name),
        ).fetchone()
        if not lesson:
            conn.close()
            return response({"error": "lesson_not_found"}, 404)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """INSERT INTO reschedule_requests
               (parent_id, student_name, original_schedule_id, original_date, original_time,
                original_teacher, original_classroom, requested_date, requested_time, reason,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (parent_id, student_name, schedule_id, lesson["lesson_date"], lesson["lesson_time"],
             lesson["teacher"], lesson["classroom"], data.get("requested_date"),
             data.get("requested_time"), data.get("reason"), now, now),
        )
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        payload = {"ok": True, "request_id": request_id, "status": "pending"}
        remember_idempotent(idem, action, payload, 201)
        audit(action, 201, parent_id, student_name, idem)
        return response(payload, 201)

    @app.post(f"{API_PREFIX}/messages")
    def child_os_api_message():
        failure = require_auth()
        if failure:
            return failure
        action = "send_message"
        idem, replay = idempotent_result(action)
        if replay:
            return replay
        data = request.get_json(silent=True) or {}
        parent_id = data.get("parent_id")
        student_name = str(data.get("student_name") or "").strip()
        body = str(data.get("body") or "").strip()
        conn = connect()
        if not parent_id or not student_name or not parent_can_access(conn, parent_id, student_name):
            conn.close()
            return response({"error": "forbidden"}, 403)
        if not body:
            conn.close()
            return response({"error": "body_required"}, 400)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """INSERT INTO message_threads
               (subject, student_name, parent_id, thread_type, status, created_at, updated_at)
               VALUES (?, ?, ?, 'child_os', 'open', ?, ?)""",
            (data.get("subject") or "Child OS request", student_name, parent_id, now, now),
        )
        thread_id = cursor.lastrowid
        cursor = conn.execute(
            """INSERT INTO messages
               (thread_id, sender_role, sender_name, recipient_role, body, channel, created_at)
               VALUES (?, 'child_os', 'Child OS', 'owner', ?, 'api', ?)""",
            (thread_id, body, now),
        )
        message_id = cursor.lastrowid
        conn.commit()
        conn.close()
        payload = {"ok": True, "thread_id": thread_id, "message_id": message_id}
        remember_idempotent(idem, action, payload, 201)
        audit(action, 201, parent_id, student_name, idem)
        return response(payload, 201)

    @app.post(f"{API_PREFIX}/actions/<action>")
    def child_os_api_sensitive_action(action):
        failure = require_auth()
        if failure:
            return failure
        if action in CONFIRMATION_ONLY_ACTIONS:
            audit(action, 409)
            return response({
                "ok": False,
                "status": "requires_parent_confirmation",
                "action": action,
                "executed": False,
            }, 409)
        return response({"error": "unsupported_action"}, 404)
