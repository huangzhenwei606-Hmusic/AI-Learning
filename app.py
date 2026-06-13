from flask import Flask, request, redirect, session, Response, send_from_directory
import sqlite3
import os
import smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta

from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.environ.get("HMUSIC_SECRET_KEY", "hmusic_secret_key")
HMUSIC_DB_PATH = os.environ.get("HMUSIC_DB_PATH", "hmusic.db")
HMUSIC_UPLOAD_DIR = os.environ.get("HMUSIC_UPLOAD_DIR", "message_uploads")
DB_NAME = "hmusic.db"
if not hasattr(sqlite3, "_hmusic_original_connect"):
    sqlite3._hmusic_original_connect = sqlite3.connect
_sqlite_connect = sqlite3._hmusic_original_connect


def hmusic_sqlite_connect(database, *args, **kwargs):
    if database == "hmusic.db":
        database = HMUSIC_DB_PATH
    return _sqlite_connect(database, *args, **kwargs)


sqlite3.connect = hmusic_sqlite_connect
OWNER_USERNAME = "owner"
OWNER_PASSWORD = "1234"


def require_owner():
    return session.get("user_role") == "owner"


def require_teacher():
    return session.get("teacher_name") is not None


def require_parent():
    return session.get("parent_id") is not None or session.get("parent_student_name") is not None
client = None


PARENT_APP_NAME = "H-Music"
PARENT_APP_THEME = "#4f46e5"


def parent_app_meta(title):
    return f"""
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <meta name="theme-color" content="{PARENT_APP_THEME}">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-title" content="{PARENT_APP_NAME}">
        <meta name="apple-mobile-web-app-status-bar-style" content="default">
        <link rel="manifest" href="/manifest.webmanifest">
        <link rel="icon" href="/hmusic-icon.svg" type="image/svg+xml">
        <link rel="apple-touch-icon" href="/hmusic-icon.svg">
        <script>
            if ("serviceWorker" in navigator) {{
                window.addEventListener("load", function() {{
                    navigator.serviceWorker.register("/sw.js").catch(function() {{}});
                }});
            }}
            let hmusicInstallPrompt = null;
            window.addEventListener("beforeinstallprompt", function(event) {{
                event.preventDefault();
                hmusicInstallPrompt = event;
                const installButton = document.querySelector("[data-install-app]");
                if (installButton) {{
                    installButton.hidden = false;
                }}
            }});
            function installParentApp() {{
                if (!hmusicInstallPrompt) {{
                    return;
                }}
                hmusicInstallPrompt.prompt();
                hmusicInstallPrompt = null;
                const installButton = document.querySelector("[data-install-app]");
                if (installButton) {{
                    installButton.hidden = true;
                }}
            }}
        </script>
    """


def parent_bottom_nav(active="home"):
    items = [
        ("home", "/parent_dashboard", "Home"),
        ("reschedule", "/parent_reschedule", "Reschedule"),
        ("messages", "/parent_messages", "Messages"),
        ("profile", "/parent_profile", "Profile"),
    ]
    links = ""
    for key, href, label in items:
        active_class = "active" if key == active else ""
        links += f'<a class="{active_class}" href="{href}">{label}</a>'
    return f'<nav class="parent-bottom-nav">{links}</nav>'


@app.route("/app_install")
def parent_app_install():
    return f"""
    <html>
    <head>
        {parent_app_meta("Install H-Music App")}
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                background: #f7f7fb;
                color: #111827;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            .container {{
                min-height: 100vh;
                max-width: 720px;
                margin: 0 auto;
                background: white;
                padding: max(26px, env(safe-area-inset-top)) 20px max(30px, env(safe-area-inset-bottom));
            }}
            .app-mark {{
                width: 64px;
                height: 64px;
                border-radius: 18px;
                background: {PARENT_APP_THEME};
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 34px;
                font-weight: 900;
                margin-bottom: 18px;
            }}
            h1 {{
                font-size: 34px;
                line-height: 1.05;
                margin: 0 0 10px;
            }}
            p {{
                color: #4b5563;
                line-height: 1.55;
            }}
            .steps {{
                display: grid;
                gap: 14px;
                margin: 22px 0;
            }}
            .step {{
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 16px;
                background: #fafafa;
            }}
            .step h2 {{
                margin: 0 0 10px;
                font-size: 18px;
            }}
            ol {{
                margin: 0;
                padding-left: 22px;
                color: #374151;
                line-height: 1.65;
            }}
            a.button {{
                display: inline-block;
                background: {PARENT_APP_THEME};
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 800;
                margin-right: 8px;
                margin-bottom: 8px;
            }}
            a.secondary {{
                background: #111827;
            }}
            @media (min-width: 900px) {{
                body {{ padding: 32px; }}
                .container {{
                    min-height: auto;
                    border-radius: 16px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                    padding: 34px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="app-mark">H</div>
            <h1>Install H-Music</h1>
            <p>Use the parent portal like an app from your phone home screen.</p>

            <div class="steps">
                <div class="step">
                    <h2>iPhone / iPad</h2>
                    <ol>
                        <li>Open this page in Safari.</li>
                        <li>Tap the Share button.</li>
                        <li>Choose Add to Home Screen.</li>
                        <li>Tap Add.</li>
                    </ol>
                </div>

                <div class="step">
                    <h2>Android</h2>
                    <ol>
                        <li>Open this page in Chrome.</li>
                        <li>Tap Install App if Chrome shows it, or open the browser menu.</li>
                        <li>Choose Install app or Add to Home screen.</li>
                    </ol>
                </div>
            </div>

            <a class="button" href="/app">Open Parent App</a>
            <a class="button secondary" href="/parent_login">Parent Login</a>
        </div>
    </body>
    </html>
    """


@app.route("/app")
def parent_app_entry():
    if require_parent():
        return redirect("/parent_dashboard")
    return redirect("/parent_login")


@app.route("/manifest.webmanifest")
@app.route("/manifest.json")
def parent_app_manifest():
    return Response(f"""{{
        "name": "H-Music Parent App",
        "short_name": "H-Music",
        "description": "Parent portal for H-Music lessons, messages, rescheduling, and account history.",
        "start_url": "/app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f7f7fb",
        "theme_color": "{PARENT_APP_THEME}",
        "icons": [
            {{
                "src": "/hmusic-icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }}
        ]
    }}""", mimetype="application/manifest+json")


@app.route("/sw.js")
def parent_app_service_worker():
    return Response("""
const CACHE_NAME = "hmusic-parent-v31-3";
const SHELL = ["/app_install", "/parent_login", "/hmusic-icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", function(event) {
  event.waitUntil(caches.open(CACHE_NAME).then(function(cache) {
    return cache.addAll(SHELL);
  }));
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(key) {
        return key !== CACHE_NAME;
      }).map(function(key) {
        return caches.delete(key);
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function(event) {
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(function() {
      return caches.match("/app_install");
    }));
  }
});
""", mimetype="application/javascript")


@app.route("/hmusic-icon.svg")
def parent_app_icon():
    return Response(f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="{PARENT_APP_THEME}"/>
  <circle cx="376" cy="142" r="46" fill="#facc15"/>
  <path d="M162 360c0 34 27 60 70 60 45 0 76-28 76-72V126h-46v206c0 25-13 42-34 42-18 0-29-11-29-27 0-15 11-26 28-26 8 0 16 2 24 6v-44c-11-4-22-6-34-6-32 0-55 18-55 83Z" fill="white"/>
  <path d="M307 126h80v44h-80z" fill="white" opacity=".95"/>
</svg>
""", mimetype="image/svg+xml")


def ensure_teacher_management_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_name TEXT UNIQUE
    )
    """)

    cursor.execute("PRAGMA table_info(teachers)")
    teacher_columns = [row[1] for row in cursor.fetchall()]
    for column_name, column_sql in [
        ("username", "username TEXT"),
        ("password", "password TEXT"),
        ("hourly_rate", "hourly_rate REAL DEFAULT 30"),
        ("email", "email TEXT"),
        ("phone", "phone TEXT"),
        ("active", "active INTEGER DEFAULT 1"),
        ("notes", "notes TEXT"),
        ("created_at", "created_at TEXT"),
        ("updated_at", "updated_at TEXT")
    ]:
        if column_name not in teacher_columns:
            cursor.execute(f"ALTER TABLE teachers ADD COLUMN {column_sql}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        display_name TEXT,
        linked_teacher_name TEXT,
        linked_student_name TEXT
    )
    """)

    owner_username = os.environ.get("HMUSIC_OWNER_USERNAME", OWNER_USERNAME)
    owner_password = os.environ.get("HMUSIC_OWNER_PASSWORD", OWNER_PASSWORD)
    owner_display_name = os.environ.get("HMUSIC_OWNER_DISPLAY_NAME", "Owner")

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'owner'")
    owner_count = cursor.fetchone()[0]
    if owner_count == 0:
        cursor.execute("""
        INSERT OR IGNORE INTO users (
            username,
            password,
            role,
            display_name
        )
        VALUES (?, ?, ?, ?)
        """, (
            owner_username,
            owner_password,
            "owner",
            owner_display_name
        ))

    conn.commit()
    conn.close()


def teacher_login_username(teacher_name):
    base = "".join(ch.lower() for ch in (teacher_name or "") if ch.isalnum())
    return base or "teacher"


@app.route("/")
def home():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(amount) FROM payments")
    total_revenue = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM students
    WHERE lessons_left <= 2
    """)
    renewal_count = cursor.fetchone()[0]

    cursor.execute("""
    SELECT name, lessons_left
    FROM students
    WHERE lessons_left <= 2
    ORDER BY lessons_left ASC
    LIMIT 5
    """)
    renewal_students = cursor.fetchall()

    cursor.execute("""
    SELECT student_name, amount, payment_method, payment_date
    FROM payments
    ORDER BY id DESC
    LIMIT 5
    """)
    recent_payments = cursor.fetchall()

    cursor.execute("""
    SELECT COUNT(*)
    FROM reschedule_requests
    WHERE status = 'pending'
    """)
    pending_reschedule_count = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT id, student_name, original_date, original_time, requested_date, requested_time
    FROM reschedule_requests
    WHERE status = 'pending'
    ORDER BY id DESC
    LIMIT 5
    """)
    pending_reschedules = cursor.fetchall()

    cursor.execute("""
    SELECT COUNT(*)
    FROM messages
    WHERE recipient_role = 'owner'
    AND read_at IS NULL
    """)
    unread_owner_messages = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM sub_requests
    WHERE status = 'pending'
    """)
    pending_sub_count = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT id, teacher_name, student_name, lesson_date, lesson_time
    FROM sub_requests
    WHERE status = 'pending'
    ORDER BY id DESC
    LIMIT 5
    """)
    pending_sub_requests = cursor.fetchall()

    cursor.execute("""
    SELECT COUNT(*)
    FROM invoices
    WHERE status IS NULL OR status != 'paid'
    """)
    unpaid_invoice_count = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM invoices
    WHERE status IS NULL OR status != 'paid'
    """)
    unpaid_invoice_total = cursor.fetchone()[0] or 0

    conn.close()

    renewal_html = ""
    if renewal_students:
        for student in renewal_students:
            renewal_html += f"""
            <div class="row">
                <a href="/student/{student[0]}">{student[0]}</a>
                <span>{student[1]} lessons left</span>
            </div>
            """
    else:
        renewal_html = "<p class='muted'>No students need renewal.</p>"

    payments_html = ""
    if recent_payments:
        for payment in recent_payments:
            payments_html += f"""
            <div class="row">
                <span>{payment[0]}</span>
                <span>${payment[1]} · {payment[2]} · {payment[3]}</span>
            </div>
            """
    else:
        payments_html = "<p class='muted'>No recent payments.</p>"

    attention_html = ""
    if pending_reschedules:
        for r in pending_reschedules:
            attention_html += f"""
            <div class="task-row high">
                <div>
                    <span class="task-badge">Reschedule</span>
                    <a href="/reschedule_request/{r[0]}">Request #{r[0]} · {r[1]}</a>
                </div>
                <span>{r[2]} {r[3]} → {r[4]} {r[5]}</span>
            </div>
            """
    if pending_sub_requests:
        for r in pending_sub_requests:
            attention_html += f"""
            <div class="task-row medium">
                <div>
                    <span class="task-badge">Sub</span>
                    <a href="/owner_sub_requests">Request #{r[0]} · {r[2]}</a>
                </div>
                <span>{r[1]} · {r[3]} {r[4]}</span>
            </div>
            """
    if unread_owner_messages:
        attention_html += f"""
        <div class="task-row medium">
            <div>
                <span class="task-badge">Message</span>
                <a href="/messages">{unread_owner_messages} unread owner message(s)</a>
            </div>
            <span>Review inbox</span>
        </div>
        """
    if unpaid_invoice_count:
        attention_html += f"""
        <div class="task-row low">
            <div>
                <span class="task-badge">Invoice</span>
                <a href="/invoices">{unpaid_invoice_count} open invoice(s)</a>
            </div>
            <span>${unpaid_invoice_total} outstanding</span>
        </div>
        """
    if not attention_html:
        attention_html = "<p class='muted'>Nothing urgent right now.</p>"

    message_badge = f" ({unread_owner_messages})" if unread_owner_messages else ""
    reschedule_badge = f" ({pending_reschedule_count})" if pending_reschedule_count else ""
    sub_badge = f" ({pending_sub_count})" if pending_sub_count else ""
    invoice_badge = f" ({unpaid_invoice_count})" if unpaid_invoice_count else ""

    return f"""
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f6f8fa;
                margin: 0;
                color: #111827;
            }}
            .container {{
                max-width: 1100px;
                margin: 40px auto;
                padding: 0 24px;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 32px;
            }}
            .title h1 {{
                margin: 0;
                font-size: 32px;
            }}
            .title p {{
                margin: 8px 0 0;
                color: #6b7280;
            }}
            .nav a {{
                margin-left: 16px;
                text-decoration: none;
                color: #635bff;
                font-weight: 600;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
                margin-bottom: 24px;
            }}
            .attention-cards {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 12px;
                margin-bottom: 20px;
            }}
            .card {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 22px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.04);
                margin-bottom: 20px;
            }}
            .card .label {{
                color: #6b7280;
                font-size: 14px;
                margin-bottom: 10px;
            }}
            .card .value {{
                font-size: 30px;
                font-weight: 700;
            }}
            .attention-card {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 16px;
                text-decoration: none;
                color: #111827;
                box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            }}
            .attention-card .label {{
                color: #6b7280;
                font-size: 12px;
                margin-bottom: 8px;
            }}
            .attention-card .value {{
                font-size: 24px;
                font-weight: 800;
            }}
            .attention-card.alert .value {{
                color: #dc2626;
            }}
            .section {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 22px;
                margin-bottom: 20px;
            }}
            .section h2 {{
                margin-top: 0;
                font-size: 20px;
            }}
            .row {{
                display: flex;
                justify-content: space-between;
                padding: 12px 0;
                border-top: 1px solid #f0f0f0;
            }}
            .row a {{
                color: #111827;
                font-weight: 600;
                text-decoration: none;
            }}
            .row span:last-child {{
                color: #6b7280;
            }}
            .task-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 14px;
                padding: 12px 0 12px 12px;
                border-top: 1px solid #f0f0f0;
                border-left: 4px solid #d1d5db;
            }}
            .task-row.high {{
                border-left-color: #dc2626;
            }}
            .task-row.medium {{
                border-left-color: #f59e0b;
            }}
            .task-row.low {{
                border-left-color: #2563eb;
            }}
            .task-row a {{
                color: #111827;
                font-weight: 700;
                text-decoration: none;
            }}
            .task-row span:last-child {{
                color: #6b7280;
                white-space: nowrap;
            }}
            .task-badge {{
                display: inline-block;
                min-width: 78px;
                margin-right: 10px;
                padding: 4px 8px;
                border-radius: 999px;
                background: #eef2ff;
                color: #374151;
                font-size: 12px;
                font-weight: 800;
                text-align: center;
            }}

            .actions h3 {{
                margin-top: 22px;
                margin-bottom: 10px;
                color: #374151;
                font-size: 15px;
                font-weight: 700;
            }}

            .actions a {{
                display: inline-block;
                margin-right: 10px;
                margin-bottom: 10px;
                padding: 10px 14px;
                border-radius: 10px;
                background: #635bff;
                color: white;
                text-decoration: none;
                font-weight: 600;
            }}

            .actions {{
                display: flex;
                flex-direction: column;
                gap: 12px;
            }}

            .action-group {{
                margin-bottom: 15px;
            }}

            .muted {{
                color: #6b7280;
            }}
            @media (max-width: 760px) {{
                .container {{
                    margin: 20px auto;
                    padding: 0 14px;
                }}
                .header {{
                    display: block;
                }}
                .nav a {{
                    display: inline-block;
                    margin: 10px 10px 0 0;
                }}
                .cards,
                .attention-cards {{
                    grid-template-columns: repeat(2, 1fr);
                }}
                .row,
                .task-row {{
                    display: block;
                }}
                .task-row span:last-child {{
                    display: block;
                    margin-top: 6px;
                    white-space: normal;
                }}
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <div class="header">
                <div class="title">
                    <h1>H-Music CRM</h1>
                    <p>Good morning, Zhenwei 👋</p>
                </div>

                <div class="nav">
                    <a href="/students">Students</a>
                    <a href="/overdue">Renewals</a>
                    <a href="/calendar">Calendar</a>
                    <a href="/teacher_dashboard">Teacher Dashboard</a>
        <a href="/teachers">Teacher Management</a>
                </div>
            </div>

            <div class="cards">
                <div class="card">
                    <div class="label">Total Revenue</div>
                    <div class="value">${total_revenue}</div>
                </div>

                <div class="card">
                    <div class="label">Total Students</div>
                    <div class="value">{total_students}</div>
                </div>

                <div class="card">
                    <div class="label">Need Renewal</div>
                    <div class="value">{renewal_count}</div>
                </div>
            </div>

            <div class="section">
                <h2>Today Needs Attention</h2>
                <p class="muted">Sorted by operational priority: reschedules first, then coverage, messages, and money.</p>
                <div class="attention-cards">
                    <a class="attention-card {'alert' if pending_reschedule_count else ''}" href="/owner_reschedule_requests">
                        <div class="label">Pending Reschedules</div>
                        <div class="value">{pending_reschedule_count}</div>
                    </a>
                    <a class="attention-card {'alert' if unread_owner_messages else ''}" href="/messages">
                        <div class="label">Unread Messages</div>
                        <div class="value">{unread_owner_messages}</div>
                    </a>
                    <a class="attention-card {'alert' if pending_sub_count else ''}" href="/owner_sub_requests">
                        <div class="label">Sub Requests</div>
                        <div class="value">{pending_sub_count}</div>
                    </a>
                    <a class="attention-card {'alert' if unpaid_invoice_count else ''}" href="/invoices">
                        <div class="label">Open Invoices</div>
                        <div class="value">{unpaid_invoice_count}</div>
                        <div class="label">${unpaid_invoice_total}</div>
                    </a>
                    <a class="attention-card {'alert' if renewal_count else ''}" href="/overdue">
                        <div class="label">Low Lessons</div>
                        <div class="value">{renewal_count}</div>
                    </a>
                </div>
                {attention_html}
            </div>

            <div class="section">
                <h2>Renewal Needed</h2>
                {renewal_html}
            </div>

            <div class="section">
                <h2>Recent Payments</h2>
                {payments_html}
            </div>

            <div class="section actions">
    <h2>🚀 Quick Actions</h2>

    <h3>📅 Daily Operations</h3>
    <div class="action-group">
        <a href="/students">Students</a>
        <a href="/add_student">Add Student</a>
        <a href="/calendar">Calendar</a>
        <a href="/calendar/today">Today</a>
        <a href="/teacher_dashboard">Teacher Dashboard</a>
    </div>

    <h3>💰 Money</h3>
    <div class="action-group">
        <a href="/invoices">Invoices{invoice_badge}</a>
        <a href="/payroll">Teacher Payroll</a>
        <a href="/executive_dashboard">Executive Dashboard</a>
        <a href="/enrollment_payments">Enrollment Payments</a>
    </div>

    <h3>👨‍👩‍👧 Parent & Renewal</h3>
    <div class="action-group">
        <a href="/parent_portal">Parent Portal</a>
        <a href="/parents">Parent Management</a>
        <a href="/owner_reschedule_requests">Reschedule Requests{reschedule_badge}</a>
        <a href="/messages">Message Center{message_badge}</a>
        <a href="/open_slots">Open Slots</a>
        <a href="/renewal_emails">Renewal Emails</a>
        <a href="/enrollment_renewals">Enrollment Renewals</a>
    </div>

    <h3>🎯 CRM</h3>
    <div class="action-group">
        <a href="/inquiries">Inquiry CRM</a>
        <a href="/add_inquiry">Add Inquiry</a>
    </div>

    <h3>⚙️ Admin</h3>
    <div class="action-group">
        <a href="/owner_settings">Owner Settings</a>
        <a href="/owner_sub_requests">Sub Requests{sub_badge}</a>
        <a href="/teacher_rate_cards">Teacher Rate Cards</a>
        <a href="/rate_overrides">Course Pay Rates</a>
        <a href="/enrollments">Enrollments</a>
        <a href="/business_rules">Business Rules</a>
    </div>
            </div>

        </div>
    </body>
    </html>
    """


@app.route("/students")
def students():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, teacher, lessons_left
    FROM students
    ORDER BY name
    """)

    students = cursor.fetchall()
    conn.close()

    html = "<h1>Students</h1>"
    html += '<p><a href="/">Back to Dashboard</a></p>'

    for student in students:
        html += f"""
        <p>
        <a href="/student/{student[0]}">
            <strong>{student[0]}</strong>
        </a>
        | Teacher: {student[1]}
        | Lessons Left: {student[2]}
        </p>
        """

    return html




@app.route("/teachers")
def teachers():
    if not require_owner():
        return redirect("/owner_login")

    ensure_teacher_management_schema()
    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        t.id,
        t.teacher_name,
        COALESCE(t.username, ''),
        COALESCE(t.email, ''),
        COALESCE(t.phone, ''),
        COALESCE(t.hourly_rate, 30),
        COALESCE(t.active, 1),
        COALESCE(u.username, ''),
        COALESCE(u.password, ''),
        COALESCE((
            SELECT COUNT(*) FROM students s WHERE s.teacher = t.teacher_name
        ), 0),
        COALESCE((
            SELECT COUNT(*) FROM schedule sc WHERE sc.teacher = t.teacher_name
        ), 0),
        COALESCE((
            SELECT COUNT(*) FROM teacher_course_rates r WHERE r.teacher_name = t.teacher_name AND r.active = 1
        ), 0)
    FROM teachers t
    LEFT JOIN users u
        ON u.role = 'teacher'
        AND u.linked_teacher_name = t.teacher_name
    ORDER BY COALESCE(t.active, 1) DESC, t.teacher_name
    """)
    teacher_rows = cursor.fetchall()
    conn.close()

    rows = ""
    for t in teacher_rows:
        status = "Active" if t[6] == 1 else "Inactive"
        status_class = "active" if t[6] == 1 else "inactive"
        login_text = t[7] or t[2] or ""
        rows += f"""
        <tr>
            <td>{t[1]}</td>
            <td><span class="badge {status_class}">{status}</span></td>
            <td>{login_text}</td>
            <td>{t[3]}</td>
            <td>{t[4]}</td>
            <td>${t[5]}</td>
            <td>{t[9]}</td>
            <td>{t[10]}</td>
            <td>{t[11]}</td>
            <td>
                <a href="/edit_teacher/{t[0]}">Edit</a>
                <form method="POST" action="/toggle_teacher/{t[0]}" style="display:inline;">
                    <button type="submit">{'Deactivate' if t[6] == 1 else 'Reactivate'}</button>
                </form>
                <form method="POST" action="/delete_teacher/{t[0]}" style="display:inline;">
                    <button class="danger" type="submit">Delete</button>
                </form>
            </td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='10'>No teachers yet.</td></tr>"

    return f"""
    <html>
    <head>
        <title>Teacher Management</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            a.button, button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:8px 12px; border-radius:7px; text-decoration:none; font-weight:bold; margin-right:6px; cursor:pointer; }}
            button.danger {{ background:#dc2626; }}
            table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; vertical-align:top; }}
            th {{ background:#eeeeff; }}
            a {{ color:#5b5cff; font-weight:bold; }}
            .badge {{ display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:bold; }}
            .badge.active {{ background:#dcfce7; color:#166534; }}
            .badge.inactive {{ background:#e5e7eb; color:#374151; }}
            .note {{ color:#6b7280; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Teacher Management</h1>
            <p class="note">Use Teacher Course Rates for different pay by lesson type, trial, or group class.</p>
            <a class="button" href="/">Home</a>
            <a class="button" href="/add_teacher">Add Teacher</a>
            <a class="button" href="/rate_overrides">Teacher Course Rates</a>
            <a class="button" href="/add_teacher_course_rate">Add Course Pay</a>
            <a class="button" href="/course_types">Course Types</a>
            <table>
                <tr>
                    <th>Teacher</th>
                    <th>Status</th>
                    <th>Login</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Default Hourly</th>
                    <th>Students</th>
                    <th>Lessons</th>
                    <th>Course Pay Rules</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_teacher", methods=["GET", "POST"])
def add_teacher():
    if not require_owner():
        return redirect("/owner_login")

    ensure_teacher_management_schema()

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name")
        username = request.form.get("username") or teacher_login_username(teacher_name)
        password = request.form.get("password") or "1234"
        email = request.form.get("email")
        phone = request.form.get("phone")
        hourly_rate = request.form.get("hourly_rate") or 30
        active = int(request.form.get("active") or 1)
        notes = request.form.get("notes")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO teachers (
            teacher_name, username, password, email, phone, hourly_rate, active, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (teacher_name, username, password, email, phone, hourly_rate, active, notes, now, now))

        cursor.execute("""
        INSERT OR IGNORE INTO users (
            username, password, role, display_name, linked_teacher_name
        )
        VALUES (?, ?, ?, ?, ?)
        """, (username, password, "teacher", teacher_name, teacher_name))

        cursor.execute("""
        UPDATE users
        SET password = ?,
            role = 'teacher',
            display_name = ?,
            linked_teacher_name = ?
        WHERE username = ?
        """, (password, teacher_name, teacher_name, username))

        conn.commit()
        conn.close()
        return redirect("/teachers")

    return """
    <html>
    <head>
        <title>Add Teacher</title>
        <style>
            body { font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }
            .container { background:white; padding:30px; border-radius:12px; max-width:720px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }
            input, select, textarea { width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }
            button, a.button { display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Add Teacher</h1>
            <form method="POST">
                Teacher Name:<br>
                <input name="teacher_name" required>
                Login Username:<br>
                <input name="username">
                Login Password:<br>
                <input name="password" value="1234">
                Email:<br>
                <input type="email" name="email">
                Phone:<br>
                <input name="phone">
                Default Hourly Rate:<br>
                <input type="number" step="0.01" name="hourly_rate" value="30">
                Status:<br>
                <select name="active">
                    <option value="1">Active</option>
                    <option value="0">Inactive</option>
                </select>
                Notes:<br>
                <textarea name="notes" rows="3"></textarea>
                <button type="submit">Create Teacher</button>
                <a class="button" href="/teachers">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/edit_teacher/<int:teacher_id>", methods=["GET", "POST"])
def edit_teacher(teacher_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_teacher_management_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, teacher_name, username, password, email, phone, hourly_rate, active, notes
    FROM teachers
    WHERE id = ?
    """, (teacher_id,))
    teacher = cursor.fetchone()

    if not teacher:
        conn.close()
        return "<h1>Teacher not found</h1>"

    old_name = teacher[1]

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name")
        username = request.form.get("username") or teacher_login_username(teacher_name)
        password = request.form.get("password") or "1234"
        email = request.form.get("email")
        phone = request.form.get("phone")
        hourly_rate = request.form.get("hourly_rate") or 30
        active = int(request.form.get("active") or 1)
        notes = request.form.get("notes")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        UPDATE teachers
        SET teacher_name = ?,
            username = ?,
            password = ?,
            email = ?,
            phone = ?,
            hourly_rate = ?,
            active = ?,
            notes = ?,
            updated_at = ?
        WHERE id = ?
        """, (teacher_name, username, password, email, phone, hourly_rate, active, notes, now, teacher_id))

        for table, column in [
            ("students", "teacher"),
            ("schedule", "teacher"),
            ("teacher_open_slots", "teacher"),
            ("teacher_course_rates", "teacher_name"),
            ("teacher_rate_cards", "teacher_name")
        ]:
            cursor.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (teacher_name, old_name))

        cursor.execute("""
        INSERT OR IGNORE INTO users (
            username, password, role, display_name, linked_teacher_name
        )
        VALUES (?, ?, ?, ?, ?)
        """, (username, password, "teacher", teacher_name, teacher_name))

        cursor.execute("""
        UPDATE users
        SET username = ?,
            password = ?,
            role = 'teacher',
            display_name = ?,
            linked_teacher_name = ?
        WHERE linked_teacher_name = ?
        """, (username, password, teacher_name, teacher_name, old_name))

        conn.commit()
        conn.close()
        return redirect("/teachers")

    conn.close()

    def selected(value, current):
        return "selected" if value == current else ""

    return f"""
    <html>
    <head>
        <title>Edit Teacher</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:720px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select, textarea {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Edit Teacher</h1>
            <form method="POST">
                Teacher Name:<br>
                <input name="teacher_name" value="{teacher[1] or ''}" required>
                Login Username:<br>
                <input name="username" value="{teacher[2] or ''}">
                Login Password:<br>
                <input name="password" value="{teacher[3] or '1234'}">
                Email:<br>
                <input type="email" name="email" value="{teacher[4] or ''}">
                Phone:<br>
                <input name="phone" value="{teacher[5] or ''}">
                Default Hourly Rate:<br>
                <input type="number" step="0.01" name="hourly_rate" value="{teacher[6] or 30}">
                Status:<br>
                <select name="active">
                    <option value="1" {selected(1, teacher[7])}>Active</option>
                    <option value="0" {selected(0, teacher[7])}>Inactive</option>
                </select>
                Notes:<br>
                <textarea name="notes" rows="3">{teacher[8] or ''}</textarea>
                <button type="submit">Update Teacher</button>
                <a class="button" href="/teachers">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/toggle_teacher/<int:teacher_id>", methods=["POST"])
def toggle_teacher(teacher_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_teacher_management_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT active FROM teachers WHERE id = ?", (teacher_id,))
    teacher = cursor.fetchone()
    if not teacher:
        conn.close()
        return "<h1>Teacher not found</h1>"
    new_active = 0 if (teacher[0] or 1) == 1 else 1
    cursor.execute("UPDATE teachers SET active = ?, updated_at = ? WHERE id = ?", (new_active, datetime.now().strftime("%Y-%m-%d %H:%M"), teacher_id))
    conn.commit()
    conn.close()
    return redirect("/teachers")


@app.route("/delete_teacher/<int:teacher_id>", methods=["POST"])
def delete_teacher(teacher_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_teacher_management_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_name FROM teachers WHERE id = ?", (teacher_id,))
    teacher = cursor.fetchone()
    if not teacher:
        conn.close()
        return "<h1>Teacher not found</h1>"

    teacher_name = teacher[0]
    reference_count = 0
    for table, column in [
        ("students", "teacher"),
        ("schedule", "teacher"),
        ("teacher_open_slots", "teacher"),
        ("teacher_course_rates", "teacher_name"),
        ("teacher_rate_cards", "teacher_name")
    ]:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (teacher_name,))
        reference_count += cursor.fetchone()[0] or 0

    if reference_count:
        cursor.execute("UPDATE teachers SET active = 0, updated_at = ? WHERE id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M"), teacher_id))
    else:
        cursor.execute("DELETE FROM users WHERE linked_teacher_name = ?", (teacher_name,))
        cursor.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))

    conn.commit()
    conn.close()
    return redirect("/teachers")


@app.route("/add_student", methods=["GET", "POST"])
def add_student():
    if not require_owner():
        return redirect("/owner_login")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name")
        teacher = request.form.get("teacher")
        parent_name = request.form.get("parent_name")
        parent_email = request.form.get("parent_email")
        lessons_left = request.form.get("lessons_left") or 0

        cursor.execute("""
        INSERT INTO students (
            name,
            teacher,
            parent_name,
            parent_email,
            lessons_left
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            teacher,
            parent_name,
            parent_email,
            int(float(lessons_left or 0))
        ))

        conn.commit()
        conn.close()

        return redirect(f"/student/{name}")

    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teachers = cursor.fetchall()
    conn.close()

    teacher_options = "".join([f'<option value="{t[0]}">{t[0]}</option>' for t in teachers])

    return f"""
    <html>
    <head>
        <title>Add Student</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:720px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Add Student</h1>
            <form method="POST">
                Student Name:<br>
                <input name="name" required>

                Primary Teacher:<br>
                <select name="teacher">{teacher_options}</select>

                Parent Name:<br>
                <input name="parent_name">

                Parent Email:<br>
                <input type="email" name="parent_email">

                Lessons Left:<br>
                <input type="number" name="lessons_left" value="0">

                <button type="submit">Create Student</button>
                <a class="button" href="/students">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/edit_student/<name>", methods=["GET", "POST"])
def edit_student(name):
    if not require_owner():
        return redirect("/owner_login")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        teacher = request.form.get("teacher")
        parent_name = request.form.get("parent_name")
        parent_email = request.form.get("parent_email")
        lessons_left = request.form.get("lessons_left") or 0

        cursor.execute("""
        UPDATE students
        SET teacher = ?,
            parent_name = ?,
            parent_email = ?,
            lessons_left = ?
        WHERE name = ?
        """, (
            teacher,
            parent_name,
            parent_email,
            int(float(lessons_left or 0)),
            name
        ))

        conn.commit()
        conn.close()

        return redirect(f"/student/{name}")

    cursor.execute("""
    SELECT name, teacher, parent_name, parent_email, lessons_left
    FROM students
    WHERE name = ?
    """, (name,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return "<h1>Student not found</h1>"

    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teachers = cursor.fetchall()
    conn.close()

    teacher_options = ""
    for t in teachers:
        selected = "selected" if t[0] == student[1] else ""
        teacher_options += f'<option value="{t[0]}" {selected}>{t[0]}</option>'

    return f"""
    <html>
    <head>
        <title>Edit Student</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:720px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Edit Student - {student[0]}</h1>
            <form method="POST">
                Primary Teacher:<br>
                <select name="teacher">{teacher_options}</select>

                Parent Name:<br>
                <input name="parent_name" value="{student[2] or ''}">

                Parent Email:<br>
                <input type="email" name="parent_email" value="{student[3] or ''}">

                Lessons Left:<br>
                <input type="number" name="lessons_left" value="{student[4] or 0}">

                <button type="submit">Save Student</button>
                <a class="button" href="/student/{student[0]}">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/student/<name>")
def student_detail(name):
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, teacher, parent_email, lessons_left
    FROM students
    WHERE name = ?
    """, (name,))

    student = cursor.fetchone()

    if not student:
        conn.close()
        return "<h1>Student not found</h1>"

    cursor.execute("""
    SELECT lesson_date, lesson_content, performance, homework
    FROM lessons
    WHERE student_name = ?
    ORDER BY id DESC
    """, (name,))

    lessons = cursor.fetchall()

    cursor.execute("""
    SELECT payment_date, amount, lessons_added, payment_method
    FROM payments
    WHERE student_name = ?
    ORDER BY id DESC
    """, (name,))

    payments = cursor.fetchall()
    conn.close()

    lesson_html = ""
    if lessons:
        for lesson in lessons:
            lesson_html += f"""
            <hr>
            <p>
            <strong>{lesson[0]}</strong><br>
            Lesson: {lesson[1]}<br>
            Performance: {lesson[2]}<br>
            Homework: {lesson[3]}
            </p>
            """
    else:
        lesson_html = "<p>No lesson history found.</p>"

    payment_html = ""
    if payments:
        for payment in payments:
            payment_html += f"""
            <hr>
            <p>
            <strong>{payment[0]}</strong><br>
            Amount: ${payment[1]}<br>
            Lessons Added: {payment[2]}<br>
            Method: {payment[3]}
            </p>
            """
    else:
        payment_html = "<p>No payment history found.</p>"

    renewal_status = ""
    if student[3] <= 2:
        renewal_status = "<h3 style='color:red;'>⚠ Renewal Needed</h3>"

    return f"""
    <h1>{student[0]}</h1>

    <p>Teacher: {student[1]}</p>
    <p>Parent Email: {student[2]}</p>
    <p>Lessons Left: {student[3]}</p>

    {renewal_status}

    <p><a href="/add_lesson/{student[0]}">Add Lesson</a></p>
    <p><a href="/payment/{student[0]}">Receive Payment</a></p>
    <p><a href="/edit_student/{student[0]}">Edit Student / Teacher Link</a></p>
    <p><a href="/generate_parent_email/{student[0]}">Generate Parent Email</a></p>
    <p><a href="/send_parent_email/{student[0]}">Send Parent Email</a></p>
    <p><a href="/students">Back to Students</a></p>
    <p><a href="/student_ledger/{student[0]}">Student Ledger</a></p>

    <h2>Lesson History</h2>
    {lesson_html}

    <h2>Payment History</h2>
    {payment_html}
    """


@app.route("/add_lesson/<name>", methods=["GET", "POST"])
def add_lesson(name):
    if request.method == "POST":
        lesson_date = request.form["lesson_date"]
        lesson_content = request.form["lesson_content"]
        performance = request.form["performance"]
        homework = request.form["homework"]

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO lessons
        (
            student_name,
            lesson_content,
            performance,
            homework,
            lesson_date
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            name,
            lesson_content,
            performance,
            homework,
            lesson_date
        ))

        cursor.execute("""
        UPDATE students
        SET lessons_left = lessons_left - 1
        WHERE name = ?
        """, (name,))

        conn.commit()
        conn.close()

        return f"""
        <h1>Lesson Saved!</h1>
        <p>{name}</p>
        <p><a href="/student/{name}">Back to Student</a></p>
        """

    return f"""
    <h1>Add Lesson - {name}</h1>

    <form method="POST">
        Date:<br>
        <input name="lesson_date"><br><br>

        Lesson Content:<br>
        <input name="lesson_content"><br><br>

        Performance:<br>
        <input name="performance"><br><br>

        Homework:<br>
        <input name="homework"><br><br>

        <button type="submit">Save</button>
    </form>

    <p><a href="/student/{name}">Back to Student</a></p>
    """


@app.route("/payment/<name>", methods=["GET", "POST"])
def payment(name):
    if request.method == "POST":
        amount = float(request.form["amount"])
        lessons_added = int(request.form["lessons_added"])
        payment_method = request.form["payment_method"]
        payment_date = request.form["payment_date"]

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO payments
        (
            student_name,
            amount,
            lessons_added,
            payment_method,
            payment_date
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            name,
            amount,
            lessons_added,
            payment_method,
            payment_date
        ))

        payment_id = cursor.lastrowid

        cursor.execute("""
        INSERT INTO student_ledger (
            student_name,
            entry_type,
            amount,
            description,
            related_invoice_id,
            related_payment_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            "payment",
            amount,
            "Payment received",
            None,
            payment_id,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        cursor.execute("""
        UPDATE students
        SET lessons_left = lessons_left + ?
        WHERE name = ?
        """,
        (
            lessons_added,
            name
        ))

        conn.commit()
        conn.close()

        return f"""
        <h1>Payment Recorded!</h1>

        <p>Student: {name}</p>
        <p>Amount: ${amount}</p>
        <p>Lessons Added: {lessons_added}</p>
        <p>Payment Method: {payment_method}</p>
        <p>Payment Date: {payment_date}</p>

        <p><a href="/student/{name}">Back to Student</a></p>
        """

    return f"""
    <h1>Receive Payment - {name}</h1>

    <form method="POST">
        Amount:<br>
        <input name="amount"><br><br>

        Lessons Added:<br>
        <input name="lessons_added"><br><br>

        Payment Method:<br>
        <input name="payment_method"><br><br>

        Payment Date:<br>
        <input name="payment_date"><br><br>

        <button type="submit">Save Payment</button>
    </form>

    <p><a href="/student/{name}">Back to Student</a></p>
    """


@app.route("/generate_parent_email/<name>")
def generate_parent_email(name):
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT lesson_date, lesson_content, performance, homework
    FROM lessons
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 1
    """, (name,))

    lesson = cursor.fetchone()
    conn.close()

    if not lesson:
        return f"""
        <h1>No lesson found for {name}</h1>
        <p><a href="/student/{name}">Back to Student</a></p>
        """

    prompt = f"""
You are a professional piano teacher.

Write a warm, professional parent update email based on this lesson.

Student: {name}
Date: {lesson[0]}
Lesson Content: {lesson[1]}
Performance: {lesson[2]}
Homework: {lesson[3]}

Requirements:
- Warm and encouraging
- Clear and concise
- Mention what the student worked on
- Mention performance
- Mention homework
- End with H-Music
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    email_text = response.choices[0].message.content

    return f"""
    <h1>Parent Email - {name}</h1>

    <pre>{email_text}</pre>

    <p><a href="/student/{name}">Back to Student</a></p>
    """


@app.route("/send_parent_email/<name>")
def send_parent_email(name):
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT parent_email
    FROM students
    WHERE name = ?
    """, (name,))

    student = cursor.fetchone()

    cursor.execute("""
    SELECT lesson_date, lesson_content, performance, homework
    FROM lessons
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 1
    """, (name,))

    lesson = cursor.fetchone()

    if not student:
        conn.close()
        return "<h1>Student not found</h1>"

    if not lesson:
        conn.close()
        return f"""
        <h1>No lesson found for {name}</h1>
        <p><a href="/student/{name}">Back to Student</a></p>
        """

    parent_email = student[0]

    email_text = f"""
Dear Parent,

Today {name} worked on {lesson[1]}.

Performance:
{lesson[2]}

Homework:
{lesson[3]}

Thank you,
H-Music
"""

    msg = EmailMessage()
    msg["Subject"] = f"{name}'s Piano Lesson Update"
    msg["From"] = "huangzhenwei606@gmail.com"
    msg["To"] = parent_email
    msg.set_content(email_text)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            "huangzhenwei606@gmail.com",
            os.getenv("GMAIL_APP_PASSWORD")
        )
        smtp.send_message(msg)

    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    INSERT INTO email_logs
    (
        student_name,
        email_type,
        sent_date,
        status
    )
    VALUES (?, ?, ?, ?)
    """, (
        name,
        "parent_feedback",
        today,
        "sent"
    ))

    conn.commit()
    conn.close()

    return f"""
    <h1>Email Sent Successfully!</h1>

    <p>Student: {name}</p>
    <p>To: {parent_email}</p>

    <pre>{email_text}</pre>

    <p><a href="/student/{name}">Back to Student</a></p>
    """


@app.route("/overdue")
def overdue():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, lessons_left, parent_email
    FROM students
    WHERE lessons_left <= 2
    ORDER BY lessons_left ASC
    """)

    students = cursor.fetchall()
    conn.close()

    html = """
    <h1>⚠ Overdue / Renewal Needed</h1>
    <p><a href="/">Back to Dashboard</a></p>
    <hr>
    """

    if len(students) == 0:
        html += "<h3>No students need renewal.</h3>"

    for student in students:
        html += f"""
        <p>
        <strong>{student[0]}</strong><br>
        Lessons Left: {student[1]}<br>
        Parent Email: {student[2]}<br>

        <a href="/student/{student[0]}">View Student</a>
        </p>
        <hr>
        """

    return html


@app.route("/generate_all_feedback/<teacher_name>")
def generate_all_feedback(teacher_name):
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT student_name
    FROM lessons
    WHERE student_name IN (
        SELECT name FROM students WHERE teacher = ?
    )
    AND lesson_date = ?
    """, (teacher_name, today))

    lessons = cursor.fetchall()

    for lesson in lessons:
        student_name = lesson[0]

        cursor.execute("""
        INSERT INTO email_logs
        (
            student_name,
            email_type,
            sent_date,
            status
        )
        VALUES (?, ?, ?, ?)
        """, (
            student_name,
            "parent_feedback",
            today,
            "generated"
        ))

    conn.commit()
    conn.close()

    return f"""
    <h1>All Feedback Generated</h1>
    <p>{len(lessons)} feedback records marked as generated.</p>
    <p><a href="/teacher/{teacher_name}">Back to Teacher Dashboard</a></p>
    """


@app.route("/send_all_feedback/<teacher_name>")
def send_all_feedback(teacher_name):
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT student_name
    FROM lessons
    WHERE student_name IN (
        SELECT name FROM students WHERE teacher = ?
    )
    AND lesson_date = ?
    """, (teacher_name, today))

    lessons = cursor.fetchall()

    sent_count = 0

    for lesson in lessons:
        student_name = lesson[0]

        cursor.execute("""
        SELECT parent_email
        FROM students
        WHERE name = ?
        """, (student_name,))

        result = cursor.fetchone()

        if result:
            parent_email = result[0]

            cursor.execute("""
            SELECT lesson_date, lesson_content, performance, homework
            FROM lessons
            WHERE student_name = ?
            ORDER BY id DESC
            LIMIT 1
            """, (student_name,))

            lesson_detail = cursor.fetchone()

            if lesson_detail:
                email_text = f"""
Dear Parent,

Today {student_name} worked on {lesson_detail[1]}.

Performance:
{lesson_detail[2]}

Homework:
{lesson_detail[3]}

Thank you,
H-Music
"""

                msg = EmailMessage()
                msg["Subject"] = f"{student_name}'s Piano Lesson Update"
                msg["From"] = "huangzhenwei606@gmail.com"
                msg["To"] = parent_email
                msg.set_content(email_text)

                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                    smtp.login(
                        "huangzhenwei606@gmail.com",
                        os.getenv("GMAIL_APP_PASSWORD")
                    )
                    smtp.send_message(msg)

                cursor.execute("""
                INSERT INTO email_logs
                (
                    student_name,
                    email_type,
                    sent_date,
                    status
                )
                VALUES (?, ?, ?, ?)
                """, (
                    student_name,
                    "parent_feedback",
                    today,
                    "sent"
                ))

                sent_count += 1

    conn.commit()
    conn.close()

    return f"""
    <h1>All Emails Sent</h1>
    <p>{sent_count} parent emails sent successfully.</p>
    <p><a href="/teacher/{teacher_name}">Back to Teacher Dashboard</a></p>
    """


@app.route("/calendar")
def calendar():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        lesson_date,
        lesson_time,
        student_name,
        teacher,
        classroom,
        weekday,
        schedule_type,
        package_type
    FROM schedule
    ORDER BY lesson_date, lesson_time
    """)

    schedules = cursor.fetchall()
    conn.close()

    rows = ""

    for item in schedules:
        lesson_date = item[0]
        lesson_time = item[1]
        student_name = item[2]
        teacher = item[3]
        classroom = item[4]
        weekday = item[5]
        schedule_type = item[6]
        package_type = item[7]

        rows += f"""
        <tr>
            <td>{lesson_date}</td>
            <td>{weekday}</td>
            <td>{lesson_time}</td>
            <td>{student_name}</td>
            <td>{teacher}</td>
            <td>{classroom}</td>
            <td>{schedule_type}</td>
            <td>{package_type}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Calendar</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}

            h1 {{
                margin-bottom: 20px;
            }}

            a.button {{
                display: inline-block;
                background: #5b5cff;
                color: white;
                padding: 10px 16px;
                border-radius: 6px;
                text-decoration: none;
                margin-right: 10px;
                font-weight: bold;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 25px;
            }}

            th, td {{
                text-align: left;
                padding: 12px;
                border-bottom: 1px solid #eee;
            }}

            th {{
                background: #f0f0ff;
            }}

            tr:hover {{
                background: #fafafa;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Calendar V2</h1>

            <a class="button" href="/">Home</a>
            <a class="button" href="/add_schedule">Add Schedule</a>
            <a class="button" href="/room_schedule">Room Schedule</a>
            <a class="button" href="/owner_dashboard">Owner Dashboard</a>

            <table>
                <tr>
                    <th>Date</th>
                    <th>Day</th>
                    <th>Time</th>
                    <th>Student</th>
                    <th>Teacher</th>
                    <th>Room</th>
                    <th>Type</th>
                    <th>Package</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/calendar/today")
def calendar_today():
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT lesson_time, student_name, teacher, classroom, location
    FROM schedule
    WHERE lesson_date = ?
    ORDER BY lesson_time
    """, (today,))

    schedules = cursor.fetchall()
    conn.close()

    rows = ""

    for s in schedules:
        rows += f"""
        <tr>
            <td>{s[0]}</td>
            <td><a href="/student/{s[1]}">{s[1]}</a></td>
            <td>{s[2]}</td>
            <td>{s[3]}</td>
            <td>{s[4]}</td>
        </tr>
        """

    return f"""
    <h1>Today's Schedule</h1>
    <p>{today}</p>

    <table border="1" cellpadding="8">
        <tr>
            <th>Time</th>
            <th>Student</th>
            <th>Teacher</th>
            <th>Room</th>
            <th>Location</th>
        </tr>
        {rows}
    </table>

    <br>
    <a href="/calendar">Back Calendar</a>
    """

@app.route("/add_schedule", methods=["GET", "POST"])
def add_schedule():
    ensure_v18_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_name TEXT UNIQUE,
        hourly_rate REAL DEFAULT 30
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classrooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_name TEXT UNIQUE
    )
    """)

    cursor.executemany("""
    INSERT OR IGNORE INTO teachers (teacher_name)
    VALUES (?)
    """, [
        ("Zhenwei",),
        ("Jason",),
        ("Hyewon",)
    ])

    cursor.executemany("""
    INSERT OR IGNORE INTO classrooms (room_name)
    VALUES (?)
    """, [
        ("Room 1",),
        ("Room 2",),
        ("Room 3",),
        ("Trial Room",)
    ])

    conn.commit()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        teacher = request.form.get("teacher")
        classroom = request.form.get("classroom")
        weekday = request.form.get("weekday")
        lesson_time = request.form.get("lesson_time")
        schedule_type = request.form.get("schedule_type")
        package_type = request.form.get("package_type")
        start_date = request.form.get("start_date")
        course_type_id = request.form.get("course_type_id")

        cursor.execute("""
        SELECT
            id,
            name,
            duration,
            student_billing_method,
            student_price,
            teacher_billing_method,
            teacher_pay,
            is_group
        FROM course_types
        WHERE id = ?
        """, (course_type_id,))

        course = cursor.fetchone()

        if not course:
            conn.close()
            return "<h1>Course Type not found</h1>"

        course_id = course[0]
        course_name = course[1]
        duration = course[2]
        student_billing_method = course[3]
        student_price = course[4]
        teacher_billing_method = course[5]
        teacher_pay = course[6]
        is_group = course[7]

        effective_pricing = get_final_pricing(
            student_name,
            teacher,
            course_type_id
        )

        if not effective_pricing:
            conn.close()
            return "<h1>Final pricing not found</h1>"

        course_id = effective_pricing["course_id"]
        course_name = effective_pricing["course_name"]
        duration = effective_pricing["duration"]

        student_billing_method = effective_pricing["student_billing_method"]
        student_price = effective_pricing["student_price"]

        teacher_billing_method = effective_pricing["teacher_billing_method"]
        teacher_pay = effective_pricing["teacher_pay"]

        student_charge_amount = effective_pricing["student_charge_amount"]
        teacher_pay_amount = effective_pricing["teacher_pay_amount"]
        is_group = effective_pricing["is_group"]

        if schedule_type == "one_time":
            number_of_lessons = 1
        elif package_type == "10":
            number_of_lessons = 10
        elif package_type == "12":
            number_of_lessons = 12
        else:
            number_of_lessons = 24

        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        generated_count = 0

        for i in range(number_of_lessons):
            if schedule_type == "weekly":
                lesson_date_obj = start_date_obj + timedelta(days=7 * i)
            else:
                lesson_date_obj = start_date_obj

            lesson_date = lesson_date_obj.strftime("%Y-%m-%d")

            cursor.execute("""
            INSERT INTO schedule (
                student_name,
                teacher,
                classroom,
                weekday,
                lesson_time,
                schedule_type,
                package_type,
                start_date,
                lesson_date,
                course_type_id,
                course_type_name,
                duration,
                student_billing_method,
                student_price,
                teacher_billing_method,
                teacher_pay,
                student_charge_amount,
                teacher_pay_amount,
                is_group,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                student_name,
                teacher,
                classroom,
                weekday,
                lesson_time,
                schedule_type,
                package_type,
                start_date,
                lesson_date,
                course_id,
                course_name,
                duration,
                student_billing_method,
                student_price,
                teacher_billing_method,
                teacher_pay,
                student_charge_amount,
                teacher_pay_amount,
                is_group,
                "scheduled"
            ))

            generated_count += 1

        conn.commit()
        conn.close()

        return f"""
        <h1>Schedule Generated!</h1>

        <p>{generated_count} lesson(s) created for {student_name}.</p>
        <p>Teacher: {teacher}</p>
        <p>Room: {classroom}</p>
        <p>Course: {course_name}</p>
        <p>Duration: {duration} mins</p>
        <p>Student Charge Per Lesson: ${student_charge_amount}</p>
        <p>Teacher Pay Per Lesson: ${teacher_pay_amount}</p>
        <p>Start Date: {start_date}</p>
        <p>Time: {lesson_time}</p>

        <a href="/calendar">Back to Calendar</a><br>
        <a href="/add_schedule">Add Another Schedule</a><br>
        <a href="/course_types">Manage Course Types</a>
        """

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)
    teachers = cursor.fetchall()

    cursor.execute("""
    SELECT room_name
    FROM classrooms
    ORDER BY room_name
    """)
    classrooms = cursor.fetchall()

    cursor.execute("""
    SELECT
        id,
        name,
        duration,
        student_billing_method,
        student_price,
        teacher_billing_method,
        teacher_pay,
        is_group
    FROM course_types
    WHERE active = 1
    ORDER BY name, duration
    """)
    course_types = cursor.fetchall()

    conn.close()

    teacher_options = ""
    for teacher in teachers:
        teacher_options += f"""
        <option value="{teacher[0]}">{teacher[0]}</option>
        """

    classroom_options = ""
    for classroom in classrooms:
        classroom_options += f"""
        <option value="{classroom[0]}">{classroom[0]}</option>
        """

    course_options = ""
    for c in course_types:
        student_charge = calculate_course_amount(c[3], c[4], c[2])
        teacher_amount = calculate_course_amount(c[5], c[6], c[2])
        group_label = "Group" if c[7] == 1 else "Single"

        course_options += f"""
        <option value="{c[0]}">
            {c[1]} - {c[2]} mins - {group_label} - Student ${student_charge} - Teacher ${teacher_amount}
        </option>
        """

    return f"""
    <html>
    <head>
        <title>Add Schedule</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                max-width: 760px;
            }}

            input, select {{
                width: 100%;
                padding: 9px;
                margin-top: 6px;
                margin-bottom: 16px;
                font-size: 14px;
            }}

            button {{
                background: #635bff;
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 8px;
                font-weight: bold;
            }}

            a {{
                color: #635bff;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <h1>Add Schedule</h1>

            <p>
                <a href="/calendar">Back to Calendar</a> |
                <a href="/course_types">Manage Course Types</a>
            </p>

            <form method="POST">

                Student:<br>
                <input name="student_name" required>

                Teacher:<br>
                <select name="teacher">
                    {teacher_options}
                </select>

                Room:<br>
                <select name="classroom">
                    {classroom_options}
                </select>

                Course Type:<br>
                <select name="course_type_id">
                    {course_options}
                </select>

                Day of Week:<br>
                <select name="weekday">
                    <option value="Monday">Monday</option>
                    <option value="Tuesday">Tuesday</option>
                    <option value="Wednesday">Wednesday</option>
                    <option value="Thursday">Thursday</option>
                    <option value="Friday">Friday</option>
                    <option value="Saturday">Saturday</option>
                    <option value="Sunday">Sunday</option>
                </select>

                Time:<br>
                <input type="time" name="lesson_time" required>

                Schedule Type:<br>
                <select name="schedule_type">
                    <option value="one_time">One Time</option>
                    <option value="weekly">Weekly</option>
                </select>

                Package:<br>
                <select name="package_type">
                    <option value="10">10 Lessons</option>
                    <option value="12">12 Lessons</option>
                    <option value="unlimited">Unlimited</option>
                </select>

                Start Date:<br>
                <input type="date" name="start_date" required>

                <button type="submit">Generate Schedule</button>

            </form>

        </div>
    </body>
    </html>
    """


@app.route("/room_schedule")
def room_schedule():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        lesson_date,
        lesson_time,
        classroom,
        student_name,
        teacher,
        location
    FROM schedule
    ORDER BY lesson_date, classroom, lesson_time
    """)

    schedules = cursor.fetchall()
    conn.close()

    rows = ""

    for s in schedules:
        rows += f"""
        <tr>
            <td>{s[0]}</td>
            <td>{s[1]}</td>
            <td>{s[2]}</td>
            <td><a href="/student/{s[3]}">{s[3]}</a></td>
            <td>{s[4]}</td>
            <td>{s[5]}</td>
        </tr>
        """

    return f"""
    <h1>Room Schedule</h1>

    <p>This page helps teachers and owner find available rooms.</p>

    <table border="1" cellpadding="8">
        <tr>
            <th>Date</th>
            <th>Time</th>
            <th>Room</th>
            <th>Student</th>
            <th>Teacher</th>
            <th>Location</th>
        </tr>

        {rows}
    </table>

    <br>

    <a href="/calendar">Back to Calendar</a>
    """

@app.route("/room_availability", methods=["GET", "POST"])
def room_availability():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    selected_date = request.form.get("selected_date")

    if not selected_date:
        selected_date = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT room_name
    FROM classrooms
    ORDER BY room_name
    """)
    rooms = [row[0] for row in cursor.fetchall()]

    time_slots = [
        "09:00", "09:30",
        "10:00", "10:30",
        "11:00", "11:30",
        "12:00", "12:30",
        "13:00", "13:30",
        "14:00", "14:30",
        "15:00", "15:30",
        "16:00", "16:30",
        "17:00", "17:30",
        "18:00", "18:30",
        "19:00", "19:30",
        "20:00"
    ]

    header_cells = ""
    for room in rooms:
        header_cells += f"<th>{room}</th>"

    table_rows = ""

    for time_slot in time_slots:
        row_html = f"<tr><td class='time-cell'>{time_slot}</td>"

        for room in rooms:
            slot_start = datetime.strptime(time_slot, "%H:%M")
            slot_end = slot_start + timedelta(minutes=30)

            cursor.execute("""
            SELECT student_name, teacher, lesson_time
            FROM schedule
            WHERE lesson_date = ?
            AND classroom = ?
            """, (selected_date, room))

            all_bookings = cursor.fetchall()
            bookings = []

            for booking in all_bookings:
                booking_time = datetime.strptime(booking[2], "%H:%M")

                if slot_start <= booking_time < slot_end:
                    bookings.append(booking)

            if len(bookings) == 0:
                cell_class = "available"
                cell_content = "Available"

            elif len(bookings) == 1:
                cell_class = "occupied"

                student_name = bookings[0][0]
                teacher = bookings[0][1]
                actual_time = bookings[0][2]

                cell_content = f"""
                {actual_time}<br>
                <b>Occupied</b>
                """

            else:
                cell_class = "conflict"

                conflict_items = ""
                for booking in bookings:
                    student_name = booking[0]
                    teacher = booking[1]
                    actual_time = booking[2]

                    conflict_items += f"""
                    {actual_time}<br>
                    """

                cell_content = f"""
                <strong>CONFLICT</strong><br>
                {conflict_items}
                """

            row_html += f"""
            <td class="{cell_class}">
                {cell_content}
            </td>
            """

        row_html += "</tr>"
        table_rows += row_html

    conn.close()

    return f"""
    <html>
    <head>
        <title>Room Availability</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}

            h1 {{
                margin-bottom: 20px;
            }}

            form {{
                margin-bottom: 25px;
            }}

            input, button {{
                padding: 8px;
                font-size: 14px;
            }}

            button {{
                background: #5b5cff;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 9px 16px;
                font-weight: bold;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}

            th {{
                background: #eeeeff;
                padding: 12px;
                border: 1px solid #ddd;
            }}

            td {{
                padding: 12px;
                border: 1px solid #ddd;
                text-align: center;
                min-width: 120px;
            }}

            .time-cell {{
                font-weight: bold;
                background: #f5f5f5;
            }}

            .available {{
                background: #e8f8ed;
                color: #1b7f3a;
                font-weight: bold;
            }}

            .occupied {{
                background: #e5e5e5;
                color: #333;
            }}

            .conflict {{
                background: #ffdddd;
                color: #b00020;
                font-weight: bold;
            }}

            .legend {{
                margin-top: 20px;
            }}

            .legend span {{
                display: inline-block;
                padding: 8px 12px;
                border-radius: 6px;
                margin-right: 10px;
                font-weight: bold;
            }}

            .green {{
                background: #e8f8ed;
                color: #1b7f3a;
            }}

            .gray {{
                background: #e5e5e5;
                color: #333;
            }}

            .red {{
                background: #ffdddd;
                color: #b00020;
            }}

            a.button {{
                display: inline-block;
                margin-top: 25px;
                background: #5b5cff;
                color: white;
                padding: 10px 16px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Room Availability</h1>

            <form method="POST">
                Date:
                <input type="date" name="selected_date" value="{selected_date}">
                <button type="submit">View</button>
            </form>

            <div class="legend">
                <span class="green">Available</span>
                <span class="gray">Occupied</span>
                <span class="red">Conflict</span>
            </div>

            <table>
                <tr>
                    <th>Time</th>
                    {header_cells}
                </tr>
                {table_rows}
            </table>

            <a class="button" href="/calendar">Back to Calendar</a>
        </div>
    </body>
    </html>
    """

@app.route("/teacher_dashboard")
def teacher_dashboard():

    if session.get("user_role") != "teacher":
        return redirect("/teacher_login")

    teacher_name = session.get("teacher_name")
    unread_messages = get_unread_message_count("teacher", teacher_name)
    message_label = f"Messages ({unread_messages})" if unread_messages else "Messages"
    today_obj = date.today()
    today = today_obj.strftime("%Y-%m-%d")

    view = request.args.get("view", "month")
    selected_month = request.args.get("month", today_obj.strftime("%Y-%m"))
    selected_week = request.args.get("week")

    if selected_week:
        week_start = datetime.strptime(selected_week, "%Y-%m-%d").date()
    else:
        week_start = today_obj - timedelta(days=today_obj.weekday())

    week_end = week_start + timedelta(days=6)

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if view == "week":
        cursor.execute("""
        SELECT id, lesson_date, lesson_time, student_name, classroom, status
        FROM schedule
        WHERE teacher = ?
        AND lesson_date >= ?
        AND lesson_date <= ?
        ORDER BY lesson_date, lesson_time
        """, (
            teacher_name,
            week_start.strftime("%Y-%m-%d"),
            week_end.strftime("%Y-%m-%d")
        ))
    else:
        cursor.execute("""
        SELECT id, lesson_date, lesson_time, student_name, classroom, status
        FROM schedule
        WHERE teacher = ?
        AND lesson_date LIKE ?
        ORDER BY lesson_date, lesson_time
        """, (teacher_name, selected_month + "%"))

    lessons = cursor.fetchall()
    conn.close()

    lessons_by_date = {}
    for lesson in lessons:
        lessons_by_date.setdefault(lesson[1], []).append(lesson)

    def status_class(status):
        status = status or "scheduled"
        if status == "present":
            return "present"
        if status == "no_show":
            return "noshow"
        if str(status).startswith("cancel"):
            return "cancel"
        if status == "excused_24h":
            return "excused"
        return "scheduled"

    def lesson_block(lesson):
        lesson_id = lesson[0]
        lesson_time = lesson[2]
        student_name = lesson[3]
        room = lesson[4]
        status = lesson[5] or "scheduled"
        cls = status_class(status)

        return f"""
        <div class="lesson {cls}">
            <div class="lesson-main">
                <span class="lesson-time">{lesson_time}</span>
                <span class="lesson-student">{student_name}</span>
            </div>
            <div class="lesson-room">{room}</div>

            <form method="POST" action="/update_lesson_status" class="status-form">
                <input type="hidden" name="schedule_id" value="{lesson_id}">
            <select name="status">
                <option value="present">Present</option>
                <option value="no_show">No Show</option>
                <option value="cancel_3h">Cancel &lt; 3h</option>
                <option value="cancel_12h">Cancel &lt; 12h</option>
                <option value="cancel_24h">Cancel &lt; 24h</option>
                <option value="excused_24h">Cancel &gt; 24h</option>
                <option value="teacher_cancelled">Teacher Cancel</option>
                <option value="makeup">Makeup</option>
            </select>
                <button type="submit">Update</button>
            </form>
        </div>
        """

    def mobile_agenda():
        agenda_html = ""

        for lesson_date in sorted(lessons_by_date.keys()):
            agenda_html += f"""
            <div class="mobile-day">
                <div class="mobile-date">{lesson_date}</div>
            """

            for lesson in lessons_by_date[lesson_date]:
                agenda_html += lesson_block(lesson)

            agenda_html += "</div>"

        if agenda_html == "":
            agenda_html = "<div class='mobile-day'>No lessons found.</div>"

        return agenda_html

    if view == "week":
        content_cells = ""

        for i in range(7):
            current_day = week_start + timedelta(days=i)
            current_date = current_day.strftime("%Y-%m-%d")
            day_lessons = lessons_by_date.get(current_date, [])

            lesson_html = ""
            for lesson in day_lessons:
                lesson_html += lesson_block(lesson)

            content_cells += f"""
            <div class="week-cell">
                <div class="day-number">
                    {current_day.strftime("%a")} {current_day.strftime("%m/%d")}
                    {"<span class='today-badge'>Today</span>" if current_date == today else ""}
                </div>
                {lesson_html}
            </div>
            """

        prev_week = (week_start - timedelta(days=7)).strftime("%Y-%m-%d")
        next_week = (week_start + timedelta(days=7)).strftime("%Y-%m-%d")

        calendar_html = f"""
        <div class="week-nav">
            <a href="/teacher_dashboard?view=week&week={prev_week}">← Previous Week</a>
            <strong>{week_start.strftime("%b %d")} - {week_end.strftime("%b %d")}</strong>
            <a href="/teacher_dashboard?view=week&week={next_week}">Next Week →</a>
        </div>

        <div class="week-grid">
            {content_cells}
        </div>
        """

        title = f"Week of {week_start.strftime('%b %d, %Y')}"

    else:
        year = int(selected_month[:4])
        month = int(selected_month[5:7])
        month_start = date(year, month, 1)

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        days_in_month = (next_month - month_start).days
        first_weekday = month_start.weekday()

        cells = ""

        for _ in range(first_weekday):
            cells += "<div class='month-cell empty-cell'></div>"

        for day in range(1, days_in_month + 1):
            current_date = f"{selected_month}-{day:02d}"
            day_lessons = lessons_by_date.get(current_date, [])

            today_badge = ""
            if current_date == today:
                today_badge = "<span class='today-badge'>Today</span>"

            lesson_html = ""
            for lesson in day_lessons:
                lesson_html += lesson_block(lesson)

            cells += f"""
            <div class="month-cell">
                <div class="day-number">{day} {today_badge}</div>
                {lesson_html}
            </div>
            """

        calendar_html = f"""
        <div class="month-grid">
            <div class="day-header">Mon</div>
            <div class="day-header">Tue</div>
            <div class="day-header">Wed</div>
            <div class="day-header">Thu</div>
            <div class="day-header">Fri</div>
            <div class="day-header">Sat</div>
            <div class="day-header">Sun</div>
            {cells}
        </div>
        """

        title = month_start.strftime("%B %Y")

    total_lessons = len(lessons)
    present_count = len([l for l in lessons if l[5] == "present"])
    no_show_count = len([l for l in lessons if l[5] == "no_show"])
    cancel_count = len([l for l in lessons if str(l[5]).startswith("cancel")])
    student_count = len(set([l[3] for l in lessons]))

    return f"""
    <html>
    <head>
        <title>Teacher Calendar</title>
        <style>
            body {{
                margin: 0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
                background: #f7f8fc;
                color: #111827;
            }}

            .topbar {{
                height: 62px;
                background: white;
                border-bottom: 1px solid #e5e7eb;
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 0 28px;
            }}

            .brand {{
                font-size: 22px;
                font-weight: 850;
            }}

            .user {{
                font-weight: 700;
            }}

            .container {{
                max-width: 1380px;
                margin: 0 auto;
                padding: 24px 28px;
            }}

            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 14px;
            }}

            h1 {{
                font-size: 32px;
                margin: 0;
            }}

            .controls {{
                display: flex;
                gap: 10px;
                align-items: center;
            }}

            input, button, select {{
                font-size: 12px;
                padding: 6px 8px;
            }}

            button, .tab {{
                border: 1px solid #ddd;
                background: white;
                border-radius: 10px;
                font-weight: 750;
                text-decoration: none;
                color: #111827;
                padding: 8px 14px;
            }}

            .tab.active {{
                background: #f1efff;
                color: #5b5cff;
                border-color: #c9c2ff;
            }}

            .legend {{
                display: flex;
                justify-content: flex-end;
                gap: 18px;
                font-size: 12px;
                margin-bottom: 12px;
            }}

            .dot {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                display: inline-block;
                margin-right: 5px;
            }}

            .blue {{ background:#3b82f6; }}
            .green {{ background:#16a34a; }}
            .red {{ background:#dc2626; }}
            .orange {{ background:#f59e0b; }}
            .gray {{ background:#9ca3af; }}

            .calendar {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 16px;
                overflow: hidden;
            }}

            .month-grid {{
                display: grid;
                grid-template-columns: repeat(7, 1fr);
            }}

            .day-header {{
                height: 38px;
                background: #fafafa;
                border-bottom: 1px solid #e5e7eb;
                border-right: 1px solid #e5e7eb;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: 800;
            }}

            .month-cell {{
                min-height: 116px;
                border-right: 1px solid #e5e7eb;
                border-bottom: 1px solid #e5e7eb;
                padding: 8px;
                background: white;
            }}

            .week-nav {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 12px;
            }}

            .week-nav a {{
                color: #5b5cff;
                font-weight: 800;
                text-decoration: none;
            }}

            .week-grid {{
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                gap: 10px;
            }}

            .week-cell {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                min-height: 420px;
                padding: 8px;
            }}

            .empty-cell {{
                background: #f9fafb;
            }}

            .day-number {{
                font-size: 13px;
                font-weight: 850;
                margin-bottom: 6px;
            }}

            .today-badge {{
                background: #7c5cff;
                color: white;
                font-size: 9px;
                padding: 2px 6px;
                border-radius: 999px;
                margin-left: 4px;
            }}

            .lesson {{
                border-radius: 7px;
                padding: 4px 6px;
                margin-bottom: 4px;
                font-size: 10px;
                border-left: 4px solid #3b82f6;
                background: #eff6ff;
            }}

            .lesson.present {{
                background: #ecfdf3;
                border-left-color: #16a34a;
            }}

            .lesson.noshow {{
                background: #fff1f2;
                border-left-color: #dc2626;
            }}

            .lesson.cancel {{
                background: #fffbeb;
                border-left-color: #f59e0b;
            }}

            .lesson.excused {{
                background: #f3f4f6;
                border-left-color: #9ca3af;
            }}

            .lesson-main {{
                display: flex;
                gap: 5px;
                align-items: center;
            }}

            .lesson-time,
            .lesson-student {{
                font-size: 10px;
                font-weight: 850;
            }}

            .lesson-room {{
                color: #6b7280;
                font-size: 9px;
                margin-top: 1px;
            }}

            .status-form {{
                display: none;
                margin-top: 5px;
            }}

            .lesson:hover .status-form {{
                display: block;
            }}

            .status-form select {{
                width: 100%;
                font-size: 10px;
                padding: 3px;
                margin-bottom: 3px;
            }}

            .status-form button {{
                width: 100%;
                background: #5b5cff;
                color: white;
                border: none;
                font-size: 10px;
                padding: 4px;
            }}

            .summary {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 12px;
                margin-top: 20px;
            }}

            .summary-card {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 14px;
            }}

            .summary-label {{
                color: #6b7280;
                font-size: 12px;
            }}

            .summary-value {{
                font-size: 24px;
                font-weight: 850;
                margin-top: 4px;
            }}

            .mobile-agenda {{
                display: none;
            }}

            @media (max-width: 760px) {{
                .topbar {{
                    height: 52px;
                    padding: 0 12px;
                }}

                .brand {{
                    font-size: 17px;
                }}

                .user {{
                    font-size: 11px;
                }}

                .container {{
                    padding: 12px 10px;
                }}

                .header {{
                    display: block;
                }}

                h1 {{
                    font-size: 21px;
                    margin-bottom: 10px;
                }}

                .controls {{
                    flex-wrap: wrap;
                    gap: 6px;
                }}

                .legend {{
                    display: none;
                }}

                .calendar {{
                    display: none;
                }}

                .week-nav,
                .week-grid {{
                    display: none;
                }}

                .mobile-agenda {{
                    display: block;
                }}

                .mobile-day {{
                    background: white;
                    border: 1px solid #e5e7eb;
                    border-radius: 12px;
                    padding: 8px;
                    margin-bottom: 8px;
                }}

                .mobile-date {{
                    font-size: 12px;
                    font-weight: 850;
                    margin-bottom: 6px;
                }}

                .lesson {{
                    font-size: 9px;
                    padding: 5px 6px;
                    margin-bottom: 5px;
                }}

                .lesson-time,
                .lesson-student {{
                    font-size: 9px;
                }}

                .lesson-room {{
                    font-size: 8px;
                }}

                .status-form {{
                    display: none;
                }}

                .summary {{
                    grid-template-columns: repeat(2, 1fr);
                    gap: 8px;
                }}

                .summary-card {{
                    padding: 10px;
                }}

                .summary-value {{
                    font-size: 20px;
                }}
            }}
        </style>
    </head>

    <body>
        <div class="topbar">
            <div class="brand">♪ H-Music</div>
            <div class="user">
                Welcome, {teacher_name}
                &nbsp; <a href="/teacher_logout">Logout</a>
            </div>
        </div>

        <div class="container">

            <div class="header">
                <h1>{title}</h1>

                <div class="controls">
                    <a class="tab {'active' if view == 'month' else ''}" href="http://127.0.0.1:5001/teacher_dashboard?view=month">Month</a>
                    <a class="tab {'active' if view == 'week' else ''}" href="http://127.0.0.1:5001/teacher_dashboard?view=week">Week</a>
                    <a class="tab" href="/teacher_sub_request">Sub Request</a>
                    <a class="tab" href="/teacher_reschedule">Reschedule</a>
                    <a class="tab" href="/teacher_messages">{message_label}</a>
                    <a class="tab" href="/open_slots">Open Slots</a>
                    
                    <form method="GET">
                        <input type="hidden" name="view" value="{view}">
                        {"<input type='month' name='month' value='" + selected_month + "'>" if view == "month" else "<input type='date' name='week' value='" + week_start.strftime("%Y-%m-%d") + "'>"}
                        <button type="submit">View</button>
                    </form>
                </div>
            </div>

            <div class="legend">
                <span><span class="dot blue"></span>Scheduled</span>
                <span><span class="dot green"></span>Present</span>
                <span><span class="dot red"></span>No Show</span>
                <span><span class="dot orange"></span>Cancelled</span>
                <span><span class="dot gray"></span>Excused</span>
            </div>

            <div class="calendar">
                {calendar_html}
            </div>

            <div class="mobile-agenda">
                {mobile_agenda()}
            </div>

            <div class="summary">
                <div class="summary-card">
                    <div class="summary-label">Lessons</div>
                    <div class="summary-value">{total_lessons}</div>
                </div>

                <div class="summary-card">
                    <div class="summary-label">Present</div>
                    <div class="summary-value">{present_count}</div>
                </div>

                <div class="summary-card">
                    <div class="summary-label">No Show</div>
                    <div class="summary-value">{no_show_count}</div>
                </div>

                <div class="summary-card">
                    <div class="summary-label">Cancelled</div>
                    <div class="summary-value">{cancel_count}</div>
                </div>

                <div class="summary-card">
                    <div class="summary-label">Students</div>
                    <div class="summary-value">{student_count}</div>
                </div>
            </div>

        </div>
    </body>
    </html>
    """

@app.route("/teacher_login", methods=["GET", "POST"])
def teacher_login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        SELECT username, role, display_name, linked_teacher_name
        FROM users
        WHERE username = ?
        AND password = ?
        AND role = 'teacher'
        """, (username, password))

        user = cursor.fetchone()
        conn.close()

        if user:
            session.clear()
            session["user_role"] = user[1]
            session["username"] = user[0]
            session["display_name"] = user[2]
            session["teacher_name"] = user[3]

            return redirect("/teacher_dashboard")

        return """
        <h2>Login Failed</h2>
        <p>Please check your username and password.</p>
        <a href="/teacher_login">Try Again</a>
        """

    return """
    <h1>Teacher Login</h1>

    <form method="POST">

        Username:<br>
        <input name="username"><br><br>

        Password:<br>
        <input type="password" name="password"><br><br>

        <button type="submit">
            Login
        </button>

    </form>
    """

@app.route("/teacher_logout")
def teacher_logout():
    session.clear()
    return redirect("/teacher_login")


# =========================
# V26.5 Stabilization
# Unified lesson status application
# =========================

def get_parent_cancel_status(lesson_date, lesson_time):
    lesson_datetime_str = lesson_date + " " + lesson_time

    try:
        lesson_datetime = datetime.strptime(
            lesson_datetime_str,
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        lesson_datetime = datetime.strptime(
            lesson_datetime_str,
            "%Y-%m-%d %I:%M %p"
        )

    hours_before = (lesson_datetime - datetime.now()).total_seconds() / 3600

    if hours_before < 3:
        return "cancel_3h"
    if hours_before < 12:
        return "cancel_12h"
    if hours_before < 24:
        return "cancel_24h"
    return "excused_24h"


def apply_lesson_status(schedule_id, status, actor="system", reason=None, allowed_student_name=None):
    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        student_name,
        charge_lessons,
        enrollment_id,
        student_charge_amount,
        teacher_pay_amount,
        lesson_date,
        lesson_time
    FROM schedule
    WHERE id = ?
    """, (schedule_id,))

    lesson = cursor.fetchone()

    if not lesson:
        conn.close()
        return {"ok": False, "error": "Lesson not found"}

    student_name = lesson[0]

    if allowed_student_name and student_name != allowed_student_name:
        conn.close()
        return {"ok": False, "error": "Permission denied"}

    previous_charge_lessons = lesson[1] if lesson[1] is not None else 0
    enrollment_id = lesson[2]
    student_charge_amount = lesson[3] or 0
    teacher_pay_amount = lesson[4] or 0
    lesson_date = lesson[5] or ""
    payroll_month = lesson_date[:7]

    if payroll_month and is_payroll_locked(payroll_month):
        conn.close()
        return {"ok": False, "error": f"Payroll is locked for {payroll_month}"}

    business_rule = get_business_rule(status)

    student_charge_percent = business_rule["student_charge_percent"]
    teacher_pay_percent = business_rule["teacher_pay_percent"]
    deduct_lesson = business_rule["deduct_lesson"]

    student_charge_units = student_charge_percent / 100
    teacher_pay_units = teacher_pay_percent / 100

    revenue_amount = round(student_charge_amount * student_charge_units, 2)
    payroll_amount = round(teacher_pay_amount * teacher_pay_units, 2)
    profit_amount = round(revenue_amount - payroll_amount, 2)

    new_charge_lessons = 1 if deduct_lesson == 1 else 0
    lesson_delta = new_charge_lessons - previous_charge_lessons

    cancelled_at = None
    cancellation_reason = None
    if status.startswith("cancel") or status == "excused_24h":
        cancelled_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        cancellation_reason = reason

    cursor.execute("""
    UPDATE schedule
    SET status = ?,
        charge_lessons = ?,
        student_charge_units = ?,
        teacher_pay_units = ?,
        revenue_amount = ?,
        payroll_amount = ?,
        profit_amount = ?,
        cancellation_reason = ?,
        cancelled_at = ?
    WHERE id = ?
    """, (
        status,
        new_charge_lessons,
        student_charge_units,
        teacher_pay_units,
        revenue_amount,
        payroll_amount,
        profit_amount,
        cancellation_reason,
        cancelled_at,
        schedule_id,
    ))

    if lesson_delta != 0:
        if enrollment_id:
            cursor.execute("""
            UPDATE enrollments
            SET lessons_left = lessons_left - ?,
                updated_at = ?
            WHERE id = ?
            """, (
                lesson_delta,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                enrollment_id
            ))
        else:
            cursor.execute("""
            UPDATE students
            SET lessons_left = lessons_left - ?
            WHERE name = ?
            """, (
                lesson_delta,
                student_name
            ))

    try:
        cursor.execute("""
        DELETE FROM student_ledger
        WHERE related_schedule_id = ?
        """, (schedule_id,))
    except:
        pass

    try:
        cursor.execute("""
        INSERT INTO student_ledger (
            student_name,
            entry_type,
            amount,
            description,
            related_invoice_id,
            related_payment_id,
            related_schedule_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_name,
            status,
            -revenue_amount,
            f"{business_rule['rule_label']} | Actor: {actor} | Student Charge: {student_charge_percent}% | Teacher Pay: {teacher_pay_percent}% | Deduct Lesson: {deduct_lesson} | Revenue: ${revenue_amount} | Payroll: ${payroll_amount} | Profit: ${profit_amount}",
            None,
            None,
            schedule_id,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
    except:
        pass

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "student_name": student_name,
        "status": status,
        "charge_lessons": new_charge_lessons,
        "revenue_amount": revenue_amount,
        "payroll_amount": payroll_amount,
        "profit_amount": profit_amount,
    }


@app.route("/parent_cancel", methods=["GET", "POST"])
def parent_cancel():
    if not require_parent():
        return redirect("/parent_login")

    student_name = session["parent_student_name"]

    if request.method == "POST":
        schedule_id = request.form.get("schedule_id")
        reason = request.form.get("reason")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        SELECT student_name, lesson_date, lesson_time
        FROM schedule
        WHERE id = ?
        """, (schedule_id,))

        lesson = cursor.fetchone()
        conn.close()

        if not lesson:
            return "<h1>Lesson not found</h1>"

        if lesson[0] != student_name:
            return "<h1>Permission denied</h1>"

        cancel_status = get_parent_cancel_status(lesson[1], lesson[2])
        result = apply_lesson_status(
            schedule_id,
            cancel_status,
            actor="parent",
            reason=reason,
            allowed_student_name=student_name
        )

        if not result["ok"]:
            return f"""
            <h1>Cancellation Not Submitted</h1>
            <p>{result["error"]}</p>
            <p><a href="/parent_dashboard">Back to Parent Portal</a></p>
            """

        log_parent_activity(
            session.get("parent_id"),
            result["student_name"],
            "cancel_lesson",
            f"Parent cancelled lesson #{schedule_id}; status {result['status']}; charge {result['charge_lessons']} lesson(s).",
            schedule_id
        )

        return f"""
        <h1>Cancellation Submitted</h1>
        <p>Student: {result["student_name"]}</p>
        <p>Status: {result["status"]}</p>
        <p>Charge: {result["charge_lessons"]} lesson(s)</p>
        <p><a href="/parent_dashboard">Back to Parent Portal</a></p>
        """

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT id, lesson_date, lesson_time, teacher, classroom, status
    FROM schedule
    WHERE student_name = ?
    AND lesson_date >= ?
    AND (status IS NULL OR status = '' OR status = 'scheduled')
    ORDER BY lesson_date, lesson_time
    """, (student_name, today))

    lessons = cursor.fetchall()
    conn.close()

    lessons_html = ""

    for lesson in lessons:
        lessons_html += f"""
        <form method="POST" style="border:1px solid #ddd; padding:15px; margin:15px 0;">
            <p><b>{lesson[1]} {lesson[2]}</b></p>
            <p>Teacher: {lesson[3]}</p>
            <p>Room: {lesson[4]}</p>
            <p>Status: {lesson[5] or "scheduled"}</p>

            <input type="hidden" name="schedule_id" value="{lesson[0]}">

            Reason:<br>
            <input name="reason"><br><br>

            <button type="submit">Cancel This Lesson</button>
        </form>
        """

    if not lessons:
        lessons_html = "<p>No upcoming lessons found.</p>"

    return f"""
    <h1>Parent Cancel Lesson</h1>
    <p>Student: {student_name}</p>

    <hr>

    {lessons_html}

    <br>
    <a href="/parent_dashboard">Back to Parent Portal</a>
    """

@app.route("/update_lesson_status", methods=["POST"])
def update_lesson_status():

    if "teacher_name" not in session:
        return redirect("/teacher_login")

    schedule_id = request.form.get("schedule_id")
    status = request.form.get("status")

    result = apply_lesson_status(
        schedule_id,
        status,
        actor=f"teacher:{session.get('teacher_name')}"
    )

    if not result["ok"]:
        return f"""
        <h1>Lesson Status Not Updated</h1>
        <p>{result["error"]}</p>
        <p><a href="/teacher_dashboard">Back to Teacher Dashboard</a></p>
        """

    return redirect("/teacher_dashboard")

@app.route("/invoices")
def invoices():

    if not require_owner():
        return redirect("/owner_login")
    
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        charge_lessons,
        amount,
        status,
        invoice_type,
        created_at
    FROM invoices
    ORDER BY id DESC
    """)

    invoices = cursor.fetchall()
    conn.close()

    rows = ""

    for invoice in invoices:
        if invoice[4] == "paid":
            action_html = "Paid"
        else:
            action_html = f'<a href="/pay_invoice/{invoice[0]}">Mark Paid</a>'

        rows += f"""
        <tr>
            <td>{invoice[0]}</td>
            <td>{invoice[1]}</td>
            <td>{invoice[2]}</td>
            <td>${invoice[3]}</td>
            <td>{invoice[4]}</td>
            <td>{invoice[5]}</td>
            <td>{invoice[6]}</td>
            <td>{action_html}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Invoices</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}

            th {{
                background: #eeeeff;
                padding: 10px;
                border: 1px solid #ddd;
            }}

            td {{
                padding: 10px;
                border: 1px solid #ddd;
            }}

            a.button {{
                display: inline-block;
                margin-top: 25px;
                background: #5b5cff;
                color: white;
                padding: 10px 16px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Invoices</h1>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Student</th>
                    <th>Charge Lessons</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Type</th>
                    <th>Created At</th>
                    <th>Action</th>
                </tr>

                {rows}
            </table>

            <a class="button" href="/">Back Home</a>
        </div>
    </body>
    </html>
    """

@app.route("/pay_invoice/<int:invoice_id>", methods=["GET", "POST"])
def pay_invoice(invoice_id):
    if not require_owner():
        return redirect("/owner_login")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        charge_lessons,
        amount,
        status,
        invoice_type,
        created_at
    FROM invoices
    WHERE id = ?
    """, (invoice_id,))

    invoice = cursor.fetchone()

    if not invoice:
        conn.close()
        return "<h1>Invoice not found</h1>"

    if invoice[4] == "paid":
        conn.close()
        return f"""
        <h1>Invoice Already Paid</h1>
        <p>Invoice #{invoice_id} is already marked as paid.</p>
        <p><a href="/invoices">Back to Invoices</a></p>
        """

    if request.method == "POST":
        payment_date = request.form.get("payment_date")
        payment_method = request.form.get("payment_method")

        if not payment_date:
            payment_date = date.today().strftime("%Y-%m-%d")

        if not payment_method:
            payment_method = "Manual"

        student_name = invoice[1]
        amount = invoice[3]

        # Invoice payment 不增加课包节数，只是把欠款冲平
        cursor.execute("""
        INSERT INTO payments
        (
            student_name,
            amount,
            lessons_added,
            payment_method,
            payment_date
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            student_name,
            amount,
            0,
            payment_method,
            payment_date
        ))

        payment_id = cursor.lastrowid

        cursor.execute("""
        UPDATE invoices
        SET status = ?
        WHERE id = ?
        """, ("paid", invoice_id))

        cursor.execute("""
        INSERT INTO student_ledger (
            student_name,
            entry_type,
            amount,
            description,
            related_invoice_id,
            related_payment_id,
            related_schedule_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_name,
            "invoice_payment",
            amount,
            f"Invoice #{invoice_id} paid",
            invoice_id,
            payment_id,
            None,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        conn.commit()
        conn.close()

        return f"""
        <h1>Invoice Paid!</h1>
        <p>Invoice #{invoice_id}</p>
        <p>Student: {student_name}</p>
        <p>Amount: ${amount}</p>
        <p>Payment Method: {payment_method}</p>
        <p>Payment Date: {payment_date}</p>
        <p><a href="/invoices">Back to Invoices</a></p>
        <p><a href="/student_ledger/{student_name}">View Student Ledger</a></p>
        """

    conn.close()

    return f"""
    <h1>Pay Invoice #{invoice[0]}</h1>

    <p>Student: {invoice[1]}</p>
    <p>Charge Lessons: {invoice[2]}</p>
    <p>Amount: ${invoice[3]}</p>
    <p>Type: {invoice[5]}</p>
    <p>Status: {invoice[4]}</p>

    <form method="POST">
        Payment Date:<br>
        <input type="date" name="payment_date" value="{date.today().strftime('%Y-%m-%d')}"><br><br>

        Payment Method:<br>
        <input name="payment_method" value="Manual"><br><br>

        <button type="submit">Confirm Payment</button>
    </form>

    <p><a href="/invoices">Back to Invoices</a></p>
    """

@app.route("/owner_settings")
def owner_settings():

    if not require_owner():
        return redirect("/owner_login")
    
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        free_cancel_per_package = request.form.get("free_cancel_per_package")
        default_lesson_rate = request.form.get("default_lesson_rate")
        cancel_3h_charge = request.form.get("cancel_3h_charge")
        cancel_12h_charge = request.form.get("cancel_12h_charge")
        cancel_24h_charge = request.form.get("cancel_24h_charge")

        settings_to_update = {
            "free_cancel_per_package": free_cancel_per_package,
            "default_lesson_rate": default_lesson_rate,
            "cancel_3h_charge": cancel_3h_charge,
            "cancel_12h_charge": cancel_12h_charge,
            "cancel_24h_charge": cancel_24h_charge,
        }

        for key, value in settings_to_update.items():
            cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
            """, (key, value))

        conn.commit()
        conn.close()

        return """
        <h1>Settings Saved!</h1>
        <p><a href="/owner_settings">Back to Settings</a></p>
        <p><a href="/">Back Home</a></p>
        """

    cursor.execute("""
    SELECT key, value
    FROM settings
    """)

    settings_rows = cursor.fetchall()
    conn.close()

    settings = {}
    for row in settings_rows:
        settings[row[0]] = row[1]

    return f"""
    <html>
    <head>
        <title>Owner Settings</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                max-width: 700px;
            }}

            label {{
                font-weight: bold;
            }}

            input {{
                width: 100%;
                padding: 10px;
                margin: 8px 0 20px 0;
                font-size: 15px;
            }}

            button {{
                background: #5b5cff;
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 6px;
                font-weight: bold;
            }}

            a {{
                color: #5b5cff;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Owner Billing Settings</h1>

            <form method="POST">

                <label>Free Cancel Per Package</label>
                <input name="free_cancel_per_package" value="{settings.get('free_cancel_per_package', '1')}">

                <label>Default Lesson Rate ($)</label>
                <input name="default_lesson_rate" value="{settings.get('default_lesson_rate', '50')}">

                <label>Cancel Within 3 Hours Charge</label>
                <input name="cancel_3h_charge" value="{settings.get('cancel_3h_charge', '1')}">

                <label>Cancel Within 12 Hours Charge</label>
                <input name="cancel_12h_charge" value="{settings.get('cancel_12h_charge', '0.75')}">

                <label>Cancel Within 24 Hours Charge</label>
                <input name="cancel_24h_charge" value="{settings.get('cancel_24h_charge', '0.5')}">

                <button type="submit">Save Settings</button>

            </form>

            <br>
            <a href="/">Back Home</a>
        </div>
    </body>
    </html>
    """
@app.route("/student_ledger/<name>")
def student_ledger(name):
    if not require_owner():
        if not require_parent():
            return redirect("/parent_login")
        if not parent_can_access_student(session.get("parent_id"), name):
            return "<h1>Permission denied</h1>"

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        entry_type,
        amount,
        description,
        created_at
    FROM student_ledger
    WHERE student_name = ?
    ORDER BY id DESC
    """, (name,))

    entries = cursor.fetchall()

    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM student_ledger
    WHERE student_name = ?
    """, (name,))

    balance = cursor.fetchone()[0]

    conn.close()

    rows = ""

    for entry in entries:
        rows += f"""
        <tr>
            <td>{entry[3]}</td>
            <td>{entry[0]}</td>
            <td>${entry[1]}</td>
            <td>{entry[2]}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Student Ledger</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}

            .balance {{
                font-size: 28px;
                font-weight: bold;
                margin: 20px 0;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}

            th {{
                background: #eeeeff;
                padding: 10px;
                border: 1px solid #ddd;
            }}

            td {{
                padding: 10px;
                border: 1px solid #ddd;
            }}

            a.button {{
                display: inline-block;
                margin-top: 25px;
                background: #5b5cff;
                color: white;
                padding: 10px 16px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>{name} Ledger</h1>

            <div class="balance">
                Balance: ${balance}
            </div>

            <table>
                <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Description</th>
                </tr>

                {rows}
            </table>

            <a class="button" href="/student/{name}">Back to Student</a>
        </div>
    </body>
    </html>
    """
@app.route("/parent_portal")
def parent_portal():
    if require_parent():
        return redirect("/parent_dashboard")
    return redirect("/parent_login")


# =========================
# V27 Parent Pro
# Parent profiles, multi-student access, and parent activity logs
# =========================

def ensure_v27_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS parent_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_name TEXT,
        email TEXT UNIQUE,
        phone TEXT,
        password TEXT DEFAULT '1234',
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS parent_students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        student_name TEXT,
        relationship TEXT DEFAULT 'Parent',
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_parent_students_unique
    ON parent_students(parent_id, student_name)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS parent_activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        student_name TEXT,
        action_type TEXT,
        description TEXT,
        related_schedule_id INTEGER,
        created_at TEXT
    )
    """)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    SELECT name, parent_name, parent_email
    FROM students
    WHERE parent_email IS NOT NULL
    AND parent_email != ''
    """)

    students = cursor.fetchall()

    for student in students:
        student_name = student[0]
        parent_name = student[1] or (student[2].split("@")[0] if "@" in student[2] else "Parent")
        parent_email = student[2]

        cursor.execute("""
        INSERT OR IGNORE INTO parent_profiles (
            parent_name,
            email,
            password,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            parent_name,
            parent_email,
            "1234",
            1,
            now,
            now
        ))

        cursor.execute("""
        SELECT id
        FROM parent_profiles
        WHERE email = ?
        """, (parent_email,))

        parent = cursor.fetchone()

        if parent:
            cursor.execute("""
            INSERT OR IGNORE INTO parent_students (
                parent_id,
                student_name,
                relationship,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """, (
                parent[0],
                student_name,
                "Parent",
                1,
                now
            ))

    conn.commit()
    conn.close()


def get_parent_students(parent_id):
    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        s.name,
        s.teacher,
        s.parent_email,
        s.lessons_left
    FROM parent_students ps
    JOIN students s
        ON ps.student_name = s.name
    WHERE ps.parent_id = ?
    AND ps.active = 1
    ORDER BY s.name
    """, (parent_id,))

    students = cursor.fetchall()
    conn.close()

    return students


def parent_can_access_student(parent_id, student_name):
    if not parent_id:
        return session.get("parent_student_name") == student_name

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id
    FROM parent_students
    WHERE parent_id = ?
    AND student_name = ?
    AND active = 1
    """, (parent_id, student_name))

    row = cursor.fetchone()
    conn.close()

    return row is not None


def log_parent_activity(parent_id, student_name, action_type, description, related_schedule_id=None):
    if not parent_id:
        return

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO parent_activity_logs (
        parent_id,
        student_name,
        action_type,
        description,
        related_schedule_id,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        parent_id,
        student_name,
        action_type,
        description,
        related_schedule_id,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    conn.close()


@app.route("/v27_setup")
def v27_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM parent_profiles")
    parent_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM parent_students")
    link_count = cursor.fetchone()[0]

    conn.close()

    return f"""
    <h1>V27 Parent Pro Setup Complete</h1>
    <p>Parent Profiles: {parent_count}</p>
    <p>Parent Student Links: {link_count}</p>
    <p>Default seeded parent password: 1234</p>
    <p><a href="/parent_login">Parent Login</a></p>
    <p><a href="/">Back Home</a></p>
    """



@app.route("/parents")
def parents():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        p.id,
        p.parent_name,
        p.email,
        p.phone,
        p.active,
        COUNT(ps.id),
        MAX(a.created_at)
    FROM parent_profiles p
    LEFT JOIN parent_students ps
        ON p.id = ps.parent_id
        AND ps.active = 1
    LEFT JOIN parent_activity_logs a
        ON p.id = a.parent_id
    GROUP BY p.id, p.parent_name, p.email, p.phone, p.active
    ORDER BY p.parent_name, p.email
    """)

    parents_data = cursor.fetchall()
    conn.close()

    rows = ""
    for p in parents_data:
        status = "Active" if p[4] == 1 else "Inactive"
        rows += f"""
        <tr>
            <td><a href="/parent_admin/{p[0]}">{p[1] or ''}</a></td>
            <td>{p[2] or ''}</td>
            <td>{p[3] or ''}</td>
            <td>{p[5] or 0}</td>
            <td>{status}</td>
            <td>{p[6] or ''}</td>
            <td><a href="/edit_parent_admin/{p[0]}">Edit</a></td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='7'>No parent profiles yet.</td></tr>"

    return f"""
    <html>
    <head>
        <title>Parent Management</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .actions {{
                margin-bottom: 20px;
            }}
            a.button {{
                display: inline-block;
                background: #5b5cff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #eeeeff;
            }}
            a {{
                color: #5b5cff;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Parent Management</h1>

            <div class="actions">
                <a class="button" href="/">Home</a>
                <a class="button" href="/add_parent">Add Parent</a>
                <a class="button" href="/v27_setup">Run V27 Setup</a>
            </div>

            <table>
                <tr>
                    <th>Parent</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Students</th>
                    <th>Status</th>
                    <th>Last Activity</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_parent", methods=["GET", "POST"])
def add_parent():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    if request.method == "POST":
        parent_name = request.form.get("parent_name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password") or "1234"
        active = request.form.get("active") or "1"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT OR IGNORE INTO parent_profiles (
            parent_name,
            email,
            phone,
            password,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            parent_name,
            email,
            phone,
            password,
            int(active),
            now,
            now
        ))

        cursor.execute("""
        SELECT id
        FROM parent_profiles
        WHERE email = ?
        """, (email,))
        parent = cursor.fetchone()

        conn.commit()
        conn.close()

        if parent:
            return redirect(f"/parent_admin/{parent[0]}")

        return redirect("/parents")

    return """
    <html>
    <head>
        <title>Add Parent</title>
        <style>
            body { font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }
            .container { background:white; padding:30px; border-radius:12px; max-width:680px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }
            input, select { width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }
            button, a.button { display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Add Parent</h1>
            <form method="POST">
                Parent Name:<br>
                <input name="parent_name" required>

                Email:<br>
                <input type="email" name="email" required>

                Phone:<br>
                <input name="phone">

                Password:<br>
                <input name="password" value="1234">

                Active:<br>
                <select name="active">
                    <option value="1">Active</option>
                    <option value="0">Inactive</option>
                </select>

                <button type="submit">Create Parent</button>
                <a class="button" href="/parents">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/parent_admin/<int:parent_id>")
def parent_admin(parent_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, parent_name, email, phone, password, active, created_at, updated_at
    FROM parent_profiles
    WHERE id = ?
    """, (parent_id,))
    parent = cursor.fetchone()

    if not parent:
        conn.close()
        return "<h1>Parent not found</h1>"

    cursor.execute("""
    SELECT id, student_name, relationship, active, created_at
    FROM parent_students
    WHERE parent_id = ?
    ORDER BY active DESC, student_name
    """, (parent_id,))
    linked_students = cursor.fetchall()

    cursor.execute("""
    SELECT name, teacher, parent_email
    FROM students
    WHERE name NOT IN (
        SELECT student_name
        FROM parent_students
        WHERE parent_id = ?
        AND active = 1
    )
    ORDER BY name
    """, (parent_id,))
    available_students = cursor.fetchall()

    cursor.execute("""
    SELECT student_name, action_type, description, created_at
    FROM parent_activity_logs
    WHERE parent_id = ?
    ORDER BY id DESC
    LIMIT 20
    """, (parent_id,))
    activities = cursor.fetchall()

    conn.close()

    linked_rows = ""
    for s in linked_students:
        status = "Active" if s[3] == 1 else "Inactive"
        unlink_action = ""
        if s[3] == 1:
            unlink_action = f"""
            <form method="POST" action="/unlink_parent_student/{s[0]}" style="display:inline;">
                <button type="submit">Unlink</button>
            </form>
            """

        linked_rows += f"""
        <tr>
            <td>{s[1]}</td>
            <td>{s[2]}</td>
            <td>{status}</td>
            <td>{s[4]}</td>
            <td>{unlink_action}</td>
        </tr>
        """

    if not linked_rows:
        linked_rows = "<tr><td colspan='5'>No linked students.</td></tr>"

    student_options = ""
    for s in available_students:
        label = f"{s[0]} | Teacher: {s[1] or ''} | Current Email: {s[2] or ''}"
        student_options += f'<option value="{s[0]}">{label}</option>'

    if not student_options:
        student_options = '<option value="">No available students</option>'

    activity_rows = ""
    for a in activities:
        activity_rows += f"""
        <tr>
            <td>{a[3]}</td>
            <td>{a[0] or ''}</td>
            <td>{a[1]}</td>
            <td>{a[2]}</td>
        </tr>
        """

    if not activity_rows:
        activity_rows = "<tr><td colspan='4'>No activity yet.</td></tr>"

    status = "Active" if parent[5] == 1 else "Inactive"

    return f"""
    <html>
    <head>
        <title>Parent Detail</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 14px;
                margin: 20px 0;
            }}
            .card {{
                background: #f5f5ff;
                padding: 16px;
                border-radius: 10px;
                border: 1px solid #ddd;
            }}
            .label {{
                color: #6b7280;
                font-size: 13px;
            }}
            .value {{
                font-size: 20px;
                font-weight: bold;
                margin-top: 6px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 14px 0 28px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #eeeeff;
            }}
            select, input {{
                padding: 9px;
                font-size: 14px;
                margin-right: 8px;
            }}
            a.button, button {{
                display: inline-block;
                background: #5b5cff;
                color: white;
                border: none;
                padding: 9px 13px;
                border-radius: 7px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 7px;
                cursor: pointer;
            }}
            .danger {{
                background: #dc2626;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{parent[1] or 'Parent Detail'}</h1>

            <a class="button" href="/parents">Back</a>
            <a class="button" href="/edit_parent_admin/{parent[0]}">Edit Parent</a>
            <a class="button" href="/parent_login">Parent Login</a>

            <div class="cards">
                <div class="card">
                    <div class="label">Email</div>
                    <div class="value" style="font-size:15px;">{parent[2] or ''}</div>
                </div>
                <div class="card">
                    <div class="label">Phone</div>
                    <div class="value">{parent[3] or ''}</div>
                </div>
                <div class="card">
                    <div class="label">Password</div>
                    <div class="value">{parent[4] or ''}</div>
                </div>
                <div class="card">
                    <div class="label">Status</div>
                    <div class="value">{status}</div>
                </div>
            </div>

            <h2>Link Student</h2>
            <form method="POST" action="/link_parent_student/{parent[0]}">
                <select name="student_name">
                    {student_options}
                </select>
                Relationship:
                <input name="relationship" value="Parent">
                <button type="submit">Link Student</button>
            </form>

            <h2>Linked Students</h2>
            <table>
                <tr>
                    <th>Student</th>
                    <th>Relationship</th>
                    <th>Status</th>
                    <th>Linked At</th>
                    <th>Action</th>
                </tr>
                {linked_rows}
            </table>

            <h2>Parent Activity</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Student</th>
                    <th>Action</th>
                    <th>Description</th>
                </tr>
                {activity_rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/edit_parent_admin/<int:parent_id>", methods=["GET", "POST"])
def edit_parent_admin(parent_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        password = request.form.get("password")
        active = request.form.get("active") or "1"

        cursor.execute("""
        UPDATE parent_profiles
        SET parent_name = ?,
            phone = ?,
            password = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            parent_name,
            phone,
            password,
            int(active),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            parent_id
        ))

        conn.commit()
        conn.close()

        return redirect(f"/parent_admin/{parent_id}")

    cursor.execute("""
    SELECT id, parent_name, email, phone, password, active
    FROM parent_profiles
    WHERE id = ?
    """, (parent_id,))
    parent = cursor.fetchone()
    conn.close()

    if not parent:
        return "<h1>Parent not found</h1>"

    active_selected = "selected" if parent[5] == 1 else ""
    inactive_selected = "selected" if parent[5] == 0 else ""

    return f"""
    <html>
    <head>
        <title>Edit Parent</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:680px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Edit Parent</h1>
            <form method="POST">
                Parent Name:<br>
                <input name="parent_name" value="{parent[1] or ''}">

                Email:<br>
                <input value="{parent[2] or ''}" disabled>

                Phone:<br>
                <input name="phone" value="{parent[3] or ''}">

                Password:<br>
                <input name="password" value="{parent[4] or ''}">

                Active:<br>
                <select name="active">
                    <option value="1" {active_selected}>Active</option>
                    <option value="0" {inactive_selected}>Inactive</option>
                </select>

                <button type="submit">Save Parent</button>
                <a class="button" href="/parent_admin/{parent[0]}">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/link_parent_student/<int:parent_id>", methods=["POST"])
def link_parent_student(parent_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    student_name = request.form.get("student_name")
    relationship = request.form.get("relationship") or "Parent"

    if not student_name:
        return redirect(f"/parent_admin/{parent_id}")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT email
    FROM parent_profiles
    WHERE id = ?
    """, (parent_id,))
    parent = cursor.fetchone()

    if not parent:
        conn.close()
        return "<h1>Parent not found</h1>"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    INSERT OR IGNORE INTO parent_students (
        parent_id,
        student_name,
        relationship,
        active,
        created_at
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        parent_id,
        student_name,
        relationship,
        1,
        now
    ))

    cursor.execute("""
    UPDATE parent_students
    SET relationship = ?,
        active = 1
    WHERE parent_id = ?
    AND student_name = ?
    """, (
        relationship,
        parent_id,
        student_name
    ))

    cursor.execute("""
    UPDATE students
    SET parent_email = ?
    WHERE name = ?
    AND (parent_email IS NULL OR parent_email = '')
    """, (
        parent[0],
        student_name
    ))

    cursor.execute("""
    INSERT INTO parent_activity_logs (
        parent_id,
        student_name,
        action_type,
        description,
        related_schedule_id,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        parent_id,
        student_name,
        "owner_link_student",
        f"Owner linked {student_name} to parent profile.",
        None,
        now
    ))

    conn.commit()
    conn.close()

    return redirect(f"/parent_admin/{parent_id}")


@app.route("/unlink_parent_student/<int:link_id>", methods=["POST"])
def unlink_parent_student(link_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT parent_id, student_name
    FROM parent_students
    WHERE id = ?
    """, (link_id,))
    link = cursor.fetchone()

    if not link:
        conn.close()
        return "<h1>Link not found</h1>"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    UPDATE parent_students
    SET active = 0
    WHERE id = ?
    """, (link_id,))

    cursor.execute("""
    INSERT INTO parent_activity_logs (
        parent_id,
        student_name,
        action_type,
        description,
        related_schedule_id,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        link[0],
        link[1],
        "owner_unlink_student",
        f"Owner unlinked {link[1]} from parent profile.",
        None,
        now
    ))

    conn.commit()
    conn.close()

    return redirect(f"/parent_admin/{link[0]}")



# =========================
# V28 Reschedule Workflow
# Parent request + owner approval
# =========================

def ensure_v28_schema():
    ensure_v27_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reschedule_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        student_name TEXT,
        original_schedule_id INTEGER,
        original_date TEXT,
        original_time TEXT,
        original_teacher TEXT,
        original_classroom TEXT,
        requested_date TEXT,
        requested_time TEXT,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        owner_note TEXT,
        reviewed_by TEXT,
        reviewed_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("PRAGMA table_info(reschedule_requests)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    for column_name, column_sql in [
        ("requested_teacher", "requested_teacher TEXT"),
        ("requested_classroom", "requested_classroom TEXT"),
        ("requested_slot_source", "requested_slot_source TEXT"),
        ("approved_teacher", "approved_teacher TEXT"),
        ("approved_classroom", "approved_classroom TEXT")
    ]:
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE reschedule_requests ADD COLUMN {column_sql}")

    conn.commit()
    conn.close()




def parse_lesson_time_value(time_text):
    if not time_text:
        return None

    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(time_text.strip(), fmt)
        except ValueError:
            pass

    return None


def minutes_from_time_text(time_text):
    parsed = parse_lesson_time_value(time_text)
    if not parsed:
        return None
    return parsed.hour * 60 + parsed.minute


def time_text_from_minutes(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def ensure_v282_schema():
    ensure_v28_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teacher_open_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher TEXT,
        slot_date TEXT,
        slot_time TEXT,
        classroom TEXT,
        source TEXT DEFAULT 'manual',
        active INTEGER DEFAULT 1,
        notes TEXT,
        created_by TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_auto_open_slots(teachers=None, start_date=None, days_ahead=60, step_minutes=30):
    ensure_v28_schema()

    if not start_date:
        start_date = date.today().strftime("%Y-%m-%d")

    end_date = (datetime.strptime(start_date, "%Y-%m-%d").date() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    params = [start_date, end_date]
    teacher_filter = ""

    if teachers:
        teacher_filter = "AND teacher IN (" + ",".join(["?"] * len(teachers)) + ")"
        params.extend(teachers)

    cursor.execute(f"""
    SELECT teacher, lesson_date, lesson_time, duration, classroom, status
    FROM schedule
    WHERE lesson_date >= ?
    AND lesson_date <= ?
    {teacher_filter}
    AND teacher IS NOT NULL
    AND teacher != ''
    ORDER BY teacher, lesson_date, lesson_time
    """, params)

    lessons = cursor.fetchall()
    conn.close()

    by_teacher_day = {}

    for lesson in lessons:
        status = lesson[5] or "scheduled"
        if str(status).startswith("cancel") or status in ("excused_24h", "teacher_cancelled"):
            continue

        start_minute = minutes_from_time_text(lesson[2])
        if start_minute is None:
            continue

        try:
            duration = int(lesson[3] or 30)
        except:
            duration = 30

        key = (lesson[0], lesson[1])
        by_teacher_day.setdefault(key, []).append({
            "start": start_minute,
            "end": start_minute + duration,
            "classroom": lesson[4] or "",
        })

    slots = []

    for key, day_lessons in by_teacher_day.items():
        if len(day_lessons) < 2:
            continue

        teacher, slot_date = key
        day_lessons = sorted(day_lessons, key=lambda item: item["start"])

        for i in range(len(day_lessons) - 1):
            current_end = day_lessons[i]["end"]
            next_start = day_lessons[i + 1]["start"]

            slot_minute = current_end
            while slot_minute + step_minutes <= next_start:
                slots.append({
                    "teacher": teacher,
                    "slot_date": slot_date,
                    "slot_time": time_text_from_minutes(slot_minute),
                    "classroom": day_lessons[i]["classroom"] or day_lessons[i + 1]["classroom"],
                    "source": "auto_gap",
                    "notes": "Auto gap between first and last lessons",
                })
                slot_minute += step_minutes

    return slots


def get_manual_open_slots(teachers=None, start_date=None, days_ahead=60):
    ensure_v282_schema()

    if not start_date:
        start_date = date.today().strftime("%Y-%m-%d")

    end_date = (datetime.strptime(start_date, "%Y-%m-%d").date() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    params = [start_date, end_date]
    teacher_filter = ""

    if teachers:
        teacher_filter = "AND teacher IN (" + ",".join(["?"] * len(teachers)) + ")"
        params.extend(teachers)

    cursor.execute(f"""
    SELECT id, teacher, slot_date, slot_time, classroom, source, active, notes, created_by, created_at
    FROM teacher_open_slots
    WHERE slot_date >= ?
    AND slot_date <= ?
    {teacher_filter}
    ORDER BY slot_date, slot_time, teacher
    """, params)

    rows = cursor.fetchall()
    conn.close()

    slots = []
    for row in rows:
        slots.append({
            "id": row[0],
            "teacher": row[1],
            "slot_date": row[2],
            "slot_time": row[3],
            "classroom": row[4] or "",
            "source": row[5] or "manual",
            "active": row[6],
            "notes": row[7] or "",
            "created_by": row[8] or "",
            "created_at": row[9] or "",
        })

    return slots


def find_manual_open_slot(teacher, slot_date, slot_time, classroom=None):
    ensure_v282_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    params = [teacher, slot_date, slot_time]
    classroom_filter = ""
    if classroom:
        classroom_filter = "AND COALESCE(classroom, '') = ?"
        params.append(classroom)

    cursor.execute(f"""
    SELECT id
    FROM teacher_open_slots
    WHERE teacher = ?
    AND slot_date = ?
    AND slot_time = ?
    {classroom_filter}
    AND source = 'manual'
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, params)
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def mark_manual_open_slot_used(teacher, slot_date, slot_time, classroom=None, request_id=None):
    slot_id = find_manual_open_slot(teacher, slot_date, slot_time, classroom)
    if not slot_id:
        return False

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("""
    UPDATE teacher_open_slots
    SET active = 0,
        notes = COALESCE(notes, '') || ?,
        updated_at = ?
    WHERE id = ?
    """, (
        f" | used by reschedule #{request_id}" if request_id else " | used by reschedule",
        now,
        slot_id
    ))
    conn.commit()
    conn.close()
    return True


def get_open_slot_display_status(slot):
    if slot.get("source") != "manual":
        return "Available"

    notes = slot.get("notes", "") or ""
    if "used by reschedule" in notes:
        return "Used"
    if slot.get("active", 1) == 1:
        return "Available"
    return "Inactive"


def is_manual_slot_used(slot):
    return slot.get("source") == "manual" and "used by reschedule" in (slot.get("notes", "") or "")


def get_available_open_slots(teachers=None, include_inactive_manual=False):
    auto_slots = get_auto_open_slots(teachers=teachers)
    manual_slots = get_manual_open_slots(teachers=teachers)

    combined = []
    seen = set()

    for slot in auto_slots:
        key = (slot["teacher"], slot["slot_date"], slot["slot_time"])
        seen.add(key)
        combined.append(slot)

    for slot in manual_slots:
        if slot["active"] != 1 and not include_inactive_manual:
            continue
        key = (slot["teacher"], slot["slot_date"], slot["slot_time"])
        if key in seen and slot["active"] != 1:
            combined = [s for s in combined if (s["teacher"], s["slot_date"], s["slot_time"]) != key]
            continue
        if key not in seen:
            combined.append(slot)
            seen.add(key)

    combined.sort(key=lambda s: (s["slot_date"], s["slot_time"], s["teacher"]))
    return combined




# =========================
# V29 Message Center
# Unified threads, messages, and notifications
# =========================

def ensure_v29_schema():
    ensure_v282_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS message_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        student_name TEXT,
        parent_id INTEGER,
        teacher_name TEXT,
        thread_type TEXT,
        related_type TEXT,
        related_id INTEGER,
        status TEXT DEFAULT 'open',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER,
        sender_role TEXT,
        sender_name TEXT,
        recipient_role TEXT,
        body TEXT,
        channel TEXT DEFAULT 'in_app',
        read_at TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_role TEXT,
        user_key TEXT,
        title TEXT,
        body TEXT,
        link_url TEXT,
        read_at TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS message_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER,
        original_filename TEXT,
        stored_filename TEXT,
        mime_type TEXT,
        file_size INTEGER,
        created_at TEXT
    )
    """)

    os.makedirs(HMUSIC_UPLOAD_DIR, exist_ok=True)

    conn.commit()
    conn.close()


def get_or_create_message_thread(subject, student_name=None, parent_id=None, teacher_name=None, thread_type="general", related_type=None, related_id=None):
    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if related_type and related_id:
        cursor.execute("""
        SELECT id
        FROM message_threads
        WHERE related_type = ?
        AND related_id = ?
        LIMIT 1
        """, (related_type, related_id))
        existing = cursor.fetchone()

        if existing:
            conn.close()
            return existing[0]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    INSERT INTO message_threads (
        subject,
        student_name,
        parent_id,
        teacher_name,
        thread_type,
        related_type,
        related_id,
        status,
        created_at,
        updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        subject,
        student_name,
        parent_id,
        teacher_name,
        thread_type,
        related_type,
        related_id,
        "open",
        now,
        now
    ))

    thread_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return thread_id


def add_message(thread_id, sender_role, sender_name, recipient_role, body):
    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    INSERT INTO messages (
        thread_id,
        sender_role,
        sender_name,
        recipient_role,
        body,
        channel,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        thread_id,
        sender_role,
        sender_name,
        recipient_role,
        body,
        "in_app",
        now
    ))

    message_id = cursor.lastrowid

    cursor.execute("""
    UPDATE message_threads
    SET updated_at = ?
    WHERE id = ?
    """, (now, thread_id))

    conn.commit()
    conn.close()

    return message_id


def safe_upload_filename(filename):
    safe = ""
    for ch in filename:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe += ch
        else:
            safe += "_"
    return safe or "attachment"


def save_message_attachments(message_id, files):
    ensure_v29_schema()

    if not files:
        return

    os.makedirs(HMUSIC_UPLOAD_DIR, exist_ok=True)

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for file in files:
        if not file or not file.filename:
            continue

        original_filename = file.filename
        safe_name = safe_upload_filename(original_filename)
        stored_filename = f"{message_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
        file_path = os.path.join(HMUSIC_UPLOAD_DIR, stored_filename)
        file.save(file_path)
        file_size = os.path.getsize(file_path)

        cursor.execute("""
        INSERT INTO message_attachments (
            message_id,
            original_filename,
            stored_filename,
            mime_type,
            file_size,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            message_id,
            original_filename,
            stored_filename,
            file.mimetype,
            file_size,
            now
        ))

    conn.commit()
    conn.close()


def create_notification(user_role, user_key, title, body, link_url):
    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO notifications (
        user_role,
        user_key,
        title,
        body,
        link_url,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_role,
        user_key,
        title,
        body,
        link_url,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    conn.close()


def get_message_identity():
    if require_owner():
        return "owner", "owner"
    if require_parent():
        return "parent", str(session.get("parent_id"))
    if require_teacher():
        return "teacher", session.get("teacher_name")
    return None, None


def get_unread_message_count(viewer_role, viewer_key):
    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if viewer_role == "teacher":
        cursor.execute("""
        SELECT COUNT(*)
        FROM messages m
        JOIN message_threads t
            ON m.thread_id = t.id
        WHERE m.recipient_role = 'teacher'
        AND m.read_at IS NULL
        AND t.teacher_name = ?
        """, (viewer_key,))
    elif viewer_role == "parent":
        cursor.execute("""
        SELECT COUNT(*)
        FROM messages m
        JOIN message_threads t
            ON m.thread_id = t.id
        WHERE m.recipient_role = 'parent'
        AND m.read_at IS NULL
        AND t.parent_id = ?
        """, (viewer_key,))
    else:
        cursor.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE recipient_role = ?
        AND read_at IS NULL
        """, (viewer_role,))

    count = cursor.fetchone()[0] or 0
    conn.close()
    return count


def mark_message_thread_read(thread_id):
    viewer_role, viewer_key = get_message_identity()
    if not viewer_role:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE messages
    SET read_at = ?
    WHERE thread_id = ?
    AND recipient_role = ?
    AND read_at IS NULL
    """, (now, thread_id, viewer_role))

    cursor.execute("""
    UPDATE notifications
    SET read_at = ?
    WHERE link_url = ?
    AND user_role = ?
    AND user_key = ?
    AND read_at IS NULL
    """, (now, f"/message_thread/{thread_id}", viewer_role, viewer_key))

    conn.commit()
    conn.close()


def get_message_inbox_threads(viewer_role, viewer_key=None):
    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    where_sql = ""
    params = []

    if viewer_role == "parent":
        where_sql = "WHERE t.parent_id = ?"
        params.append(int(viewer_key))
    elif viewer_role == "teacher":
        where_sql = "WHERE t.teacher_name = ?"
        params.append(viewer_key)

    cursor.execute(f"""
    SELECT
        t.id,
        t.subject,
        t.student_name,
        COALESCE(p.parent_name, ''),
        COALESCE(t.teacher_name, ''),
        COALESCE(t.thread_type, 'general'),
        COALESCE(t.status, 'open'),
        COALESCE(t.updated_at, ''),
        COALESCE((
            SELECT body
            FROM messages lm
            WHERE lm.thread_id = t.id
            ORDER BY lm.id DESC
            LIMIT 1
        ), ''),
        COALESCE((
            SELECT COUNT(*)
            FROM messages um
            WHERE um.thread_id = t.id
            AND um.recipient_role = ?
            AND um.read_at IS NULL
        ), 0),
        COALESCE((
            SELECT COUNT(*)
            FROM message_attachments ma
            JOIN messages am
                ON ma.message_id = am.id
            WHERE am.thread_id = t.id
        ), 0)
    FROM message_threads t
    LEFT JOIN parent_profiles p
        ON t.parent_id = p.id
    {where_sql}
    ORDER BY t.updated_at DESC, t.id DESC
    """, [viewer_role] + params)

    rows = cursor.fetchall()
    conn.close()
    return rows


def render_message_inbox(title, back_href, back_label, rows_data, new_href=None, new_label=None, notifications_href=None):
    rows = ""
    for t in rows_data:
        unread_badge = f"<span class='badge unread'>{t[9]} unread</span>" if t[9] else "<span class='badge'>Read</span>"
        attachment_badge = f"<span class='badge'>{t[10]} files</span>" if t[10] else ""
        latest = t[8] or ""
        if len(latest) > 120:
            latest = latest[:117] + "..."

        rows += f"""
        <tr class="{'is-unread' if t[9] else ''}">
            <td><a href="/message_thread/{t[0]}">{t[1]}</a><div class="subtle">#{t[0]}</div></td>
            <td>{t[2] or ''}</td>
            <td>{t[3] or ''}</td>
            <td>{t[4] or ''}</td>
            <td><span class="badge type">{t[5]}</span></td>
            <td>{unread_badge} {attachment_badge}</td>
            <td>{t[7]}</td>
            <td>{latest}</td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='8'>No messages yet.</td></tr>"

    action_buttons = f'<a class="button" href="{back_href}">{back_label}</a>'
    if new_href and new_label:
        action_buttons += f' <a class="button" href="{new_href}">{new_label}</a>'
    if notifications_href:
        action_buttons += f' <a class="button" href="{notifications_href}">Notifications</a>'

    is_parent_app = back_href.startswith("/parent") or new_href == "/new_parent_message"
    bottom_nav_html = parent_bottom_nav("messages") if is_parent_app else ""
    page_padding = "calc(96px + env(safe-area-inset-bottom))" if is_parent_app else "40px"

    return f"""
    <html>
    <head>
        {parent_app_meta(title) if is_parent_app else f"<title>{title}</title>"}
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f7f7fb; margin:0; color:#111827; }}
            .container {{ background:white; min-height:100vh; padding:max(22px, env(safe-area-inset-top)) 18px {page_padding}; }}
            h1 {{ font-size:30px; line-height:1.08; margin:0 0 18px; }}
            .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }}
            a.button {{ display:inline-block; background:#4f46e5; color:white; padding:12px 14px; border-radius:8px; text-decoration:none; font-weight:bold; margin:0; }}
            table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; vertical-align:top; }}
            th {{ background:#eeeeff; }}
            a {{ color:#4f46e5; font-weight:bold; }}
            .subtle {{ color:#6b7280; font-size:12px; margin-top:4px; }}
            .badge {{ display:inline-block; padding:3px 8px; border-radius:999px; background:#eef2ff; color:#374151; font-size:12px; font-weight:bold; }}
            .badge.unread {{ background:#fee2e2; color:#991b1b; }}
            .badge.type {{ background:#e0f2fe; color:#075985; }}
            tr.is-unread td {{ background:#fff7ed; }}
            .parent-bottom-nav {{
                position: fixed; left: 0; right: 0; bottom: 0;
                display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
                padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
                background: rgba(255,255,255,.96); border-top: 1px solid #e5e7eb;
                box-shadow: 0 -4px 18px rgba(0,0,0,.08); z-index: 20;
            }}
            .parent-bottom-nav a {{ text-align:center; text-decoration:none; color:#6b7280; font-size:12px; font-weight:800; padding:9px 4px; border-radius:8px; }}
            .parent-bottom-nav a.active {{ color:#4f46e5; background:#eef2ff; }}
            @media (max-width:760px) {{
                table {{ display:block; overflow-x:auto; font-size:12px; }}
                .actions {{ display:grid; grid-template-columns:1fr; }}
                a.button {{ text-align:center; }}
            }}
            @media (min-width:900px) {{
                body {{ padding:32px; }}
                .container {{ min-height:auto; padding:32px; border-radius:16px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{title}</h1>
            <div class="actions">{action_buttons}</div>

            <table>
                <tr>
                    <th>Subject</th>
                    <th>Student</th>
                    <th>Parent</th>
                    <th>Teacher</th>
                    <th>Type</th>
                    <th>State</th>
                    <th>Updated</th>
                    <th>Latest</th>
                </tr>
                {rows}
            </table>
        </div>
        {bottom_nav_html}
    </body>
    </html>
    """


def user_can_view_thread(thread_id):
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT parent_id, teacher_name
    FROM message_threads
    WHERE id = ?
    """, (thread_id,))
    thread = cursor.fetchone()
    conn.close()

    if not thread:
        return False

    if require_owner():
        return True

    if require_parent() and session.get("parent_id") == thread[0]:
        return True

    if require_teacher() and session.get("teacher_name") == thread[1]:
        return True

    return False


def create_reschedule_message_event(request_id, event_type, body, parent_id=None, student_name=None, teacher_name=None):
    subject = f"Reschedule Request #{request_id}"
    if student_name:
        subject += f" - {student_name}"

    thread_id = get_or_create_message_thread(
        subject,
        student_name=student_name,
        parent_id=parent_id,
        teacher_name=teacher_name,
        thread_type="reschedule",
        related_type="reschedule_request",
        related_id=request_id
    )

    if event_type == "submitted":
        if require_teacher():
            add_message(thread_id, "teacher", session.get("teacher_name", "Teacher"), "owner", body)
            create_notification("owner", "owner", "New teacher reschedule request", body, f"/reschedule_request/{request_id}")
        else:
            add_message(thread_id, "parent", session.get("parent_name", "Parent"), "owner", body)
            create_notification("owner", "owner", "New reschedule request", body, f"/reschedule_request/{request_id}")
    elif event_type == "approved":
        recipient_role = "parent" if parent_id else "teacher"
        add_message(thread_id, "owner", "Owner", recipient_role, body)
        if parent_id:
            create_notification("parent", str(parent_id), "Reschedule approved", body, f"/message_thread/{thread_id}")
        if teacher_name:
            create_notification("teacher", teacher_name, "Reschedule approved", body, f"/message_thread/{thread_id}")
    elif event_type == "rejected":
        recipient_role = "parent" if parent_id else "teacher"
        add_message(thread_id, "owner", "Owner", recipient_role, body)
        if parent_id:
            create_notification("parent", str(parent_id), "Reschedule rejected", body, f"/message_thread/{thread_id}")
        if teacher_name:
            create_notification("teacher", teacher_name, "Reschedule rejected", body, f"/message_thread/{thread_id}")


@app.route("/messages")
def messages():
    if not require_owner():
        return redirect("/owner_login")

    rows = get_message_inbox_threads("owner", "owner")
    return render_message_inbox(
        "Message Center",
        "/",
        "Home",
        rows,
        notifications_href="/notifications"
    )


@app.route("/parent_messages")
def parent_messages():
    if not require_parent():
        return redirect("/parent_login")

    parent_id = session.get("parent_id")
    rows = get_message_inbox_threads("parent", str(parent_id))
    return render_message_inbox(
        "Parent Messages",
        "/parent_dashboard",
        "Back to Dashboard",
        rows,
        new_href="/new_parent_message",
        new_label="New Message to Teacher"
    )


@app.route("/new_parent_message", methods=["GET", "POST"])
def new_parent_message():
    if not require_parent():
        return redirect("/parent_login")

    ensure_v29_schema()

    parent_id = session.get("parent_id")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        teacher_name = request.form.get("teacher_name")
        body = request.form.get("body")
        files = request.files.getlist("attachments")

        if not parent_can_access_student(parent_id, student_name):
            conn.close()
            return "<h1>Permission denied</h1>"

        subject = f"Parent / Teacher Message - {student_name}"
        thread_id = get_or_create_message_thread(
            subject,
            student_name=student_name,
            parent_id=parent_id,
            teacher_name=teacher_name,
            thread_type="parent_teacher",
            related_type="parent_teacher",
            related_id=None
        )

        message_id = add_message(thread_id, "parent", session.get("parent_name", "Parent"), "teacher", body or "")
        save_message_attachments(message_id, files)
        create_notification("teacher", teacher_name, "New parent message", body or "Parent sent a message.", f"/message_thread/{thread_id}")

        conn.close()
        return redirect(f"/message_thread/{thread_id}")

    cursor.execute("""
    SELECT s.name, s.teacher
    FROM parent_students ps
    JOIN students s
        ON ps.student_name = s.name
    WHERE ps.parent_id = ?
    AND ps.active = 1
    ORDER BY s.name
    """, (parent_id,))
    linked_students = cursor.fetchall()

    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teachers = cursor.fetchall()
    conn.close()

    student_options = "".join([f'<option value="{s[0]}">{s[0]} | Primary Teacher: {s[1] or ""}</option>' for s in linked_students])
    teacher_options = "".join([f'<option value="{t[0]}">{t[0]}</option>' for t in teachers])

    return f"""
    <html>
    <head>
        {parent_app_meta("New Message")}
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f7f7fb; margin:0; color:#111827; }}
            .container {{ background:white; min-height:100vh; padding:max(22px, env(safe-area-inset-top)) 18px calc(96px + env(safe-area-inset-bottom)); max-width:760px; margin:0 auto; }}
            h1 {{ font-size:30px; line-height:1.08; margin:0 0 22px; }}
            input, select, textarea {{ width:100%; min-height:48px; padding:12px 14px; margin:8px 0 18px; font-size:16px; border:1px solid #d1d5db; border-radius:10px; }}
            textarea {{ min-height:130px; }}
            button, a.button {{ display:inline-block; background:#4f46e5; color:white; border:none; padding:12px 16px; border-radius:8px; font-weight:bold; text-decoration:none; min-height:48px; }}
            .form-actions {{ display:flex; gap:10px; flex-wrap:wrap; }}
            .parent-bottom-nav {{ position:fixed; left:0; right:0; bottom:0; display:grid; grid-template-columns:repeat(4,1fr); gap:4px; padding:8px 10px calc(8px + env(safe-area-inset-bottom)); background:rgba(255,255,255,.96); border-top:1px solid #e5e7eb; box-shadow:0 -4px 18px rgba(0,0,0,.08); z-index:20; }}
            .parent-bottom-nav a {{ text-align:center; text-decoration:none; color:#6b7280; font-size:12px; font-weight:800; padding:9px 4px; border-radius:8px; }}
            .parent-bottom-nav a.active {{ color:#4f46e5; background:#eef2ff; }}
            @media (max-width:760px) {{ .form-actions {{ display:grid; grid-template-columns:1fr 1fr; }} .form-actions button, .form-actions a {{ text-align:center; }} }}
            @media (min-width:900px) {{ body {{ padding:32px; }} .container {{ min-height:auto; padding:32px; border-radius:16px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>New Message to Teacher</h1>
            <form method="POST" enctype="multipart/form-data">
                Student:<br>
                <select name="student_name" required>{student_options}</select>

                Teacher:<br>
                <select name="teacher_name" required>{teacher_options}</select>

                Message:<br>
                <textarea name="body" rows="5" required></textarea>

                Attachments:<br>
                <input type="file" name="attachments" multiple accept="image/*,video/*,.pdf,.doc,.docx,.txt">

                <div class="form-actions">
                    <button type="submit">Send Message</button>
                    <a class="button" href="/parent_messages">Back</a>
                </div>
            </form>
        </div>
        {parent_bottom_nav("messages")}
    </body>
    </html>
    """


@app.route("/new_teacher_message", methods=["GET", "POST"])
def new_teacher_message():
    if not require_teacher():
        return redirect("/teacher_login")

    ensure_v29_schema()

    teacher_name = session.get("teacher_name")
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        parent_id = request.form.get("parent_id")
        body = request.form.get("body")
        files = request.files.getlist("attachments")

        cursor.execute("""
        SELECT id
        FROM schedule
        WHERE teacher = ?
        AND student_name = ?
        LIMIT 1
        """, (teacher_name, student_name))
        teaches_student = cursor.fetchone()

        if not teaches_student:
            conn.close()
            return "<h1>Permission denied</h1>"

        subject = f"Teacher / Parent Message - {student_name}"
        thread_id = get_or_create_message_thread(
            subject,
            student_name=student_name,
            parent_id=int(parent_id),
            teacher_name=teacher_name,
            thread_type="parent_teacher",
            related_type="parent_teacher",
            related_id=None
        )

        message_id = add_message(thread_id, "teacher", teacher_name, "parent", body or "")
        save_message_attachments(message_id, files)
        create_notification("parent", str(parent_id), "New teacher message", body or "Teacher sent a message.", f"/message_thread/{thread_id}")

        conn.close()
        return redirect(f"/message_thread/{thread_id}")

    cursor.execute("""
    SELECT DISTINCT s.student_name, ps.parent_id, p.parent_name
    FROM schedule s
    JOIN parent_students ps
        ON s.student_name = ps.student_name
        AND ps.active = 1
    JOIN parent_profiles p
        ON ps.parent_id = p.id
    WHERE s.teacher = ?
    ORDER BY s.student_name
    """, (teacher_name,))
    rows = cursor.fetchall()
    conn.close()

    options = "".join([f'<option value="{r[0]}|{r[1]}">{r[0]} | Parent: {r[2]}</option>' for r in rows])

    return f"""
    <html>
    <head>
        <title>New Message to Parent</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:760px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select, textarea {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
        <script>
            function splitStudentParent(value) {{
                const parts = value.split("|");
                document.getElementById("student_name").value = parts[0] || "";
                document.getElementById("parent_id").value = parts[1] || "";
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <h1>New Message to Parent</h1>
            <form method="POST" enctype="multipart/form-data">
                Student / Parent:<br>
                <select onchange="splitStudentParent(this.value)" required>
                    <option value="">Select student</option>
                    {options}
                </select>
                <input type="hidden" id="student_name" name="student_name">
                <input type="hidden" id="parent_id" name="parent_id">

                Message:<br>
                <textarea name="body" rows="5" required></textarea>

                Attachments:<br>
                <input type="file" name="attachments" multiple accept="image/*,video/*,.pdf,.doc,.docx,.txt">

                <button type="submit">Send Message</button>
                <a class="button" href="/teacher_messages">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/message_thread/<int:thread_id>", methods=["GET", "POST"])
def message_thread(thread_id):
    if not user_can_view_thread(thread_id):
        return "<h1>Permission denied</h1>"

    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, subject, student_name, thread_type, status, updated_at, parent_id, teacher_name
    FROM message_threads
    WHERE id = ?
    """, (thread_id,))
    thread_for_reply = cursor.fetchone()
    conn.close()

    if request.method == "POST":
        body = request.form.get("body")
        files = request.files.getlist("attachments")

        if body or any([f and f.filename for f in files]):
            if require_owner():
                sender_role = "owner"
                sender_name = "Owner"
                recipient_role = "parent"
                notify_role = "parent"
                notify_key = str(thread_for_reply[6]) if thread_for_reply and thread_for_reply[6] else None
            elif require_parent():
                sender_role = "parent"
                sender_name = session.get("parent_name", "Parent")
                recipient_role = "teacher" if thread_for_reply and thread_for_reply[7] else "owner"
                notify_role = "teacher" if thread_for_reply and thread_for_reply[7] else "owner"
                notify_key = thread_for_reply[7] if thread_for_reply and thread_for_reply[7] else "owner"
            else:
                sender_role = "teacher"
                sender_name = session.get("teacher_name", "Teacher")
                recipient_role = "parent" if thread_for_reply and thread_for_reply[6] else "owner"
                notify_role = "parent" if thread_for_reply and thread_for_reply[6] else "owner"
                notify_key = str(thread_for_reply[6]) if thread_for_reply and thread_for_reply[6] else "owner"

            message_id = add_message(thread_id, sender_role, sender_name, recipient_role, body or "")
            save_message_attachments(message_id, files)

            if notify_key:
                create_notification(notify_role, notify_key, "New message", body or "New attachment", f"/message_thread/{thread_id}")

        return redirect(f"/message_thread/{thread_id}")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, subject, student_name, thread_type, status, updated_at, parent_id
    FROM message_threads
    WHERE id = ?
    """, (thread_id,))
    thread = cursor.fetchone()

    cursor.execute("""
    SELECT id, sender_role, sender_name, recipient_role, body, created_at
    FROM messages
    WHERE thread_id = ?
    ORDER BY id ASC
    """, (thread_id,))
    message_rows = cursor.fetchall()

    message_ids = [str(m[0]) for m in message_rows]
    attachments_by_message = {}
    if message_ids:
        cursor.execute(f"""
        SELECT message_id, original_filename, stored_filename, mime_type
        FROM message_attachments
        WHERE message_id IN ({",".join(["?"] * len(message_ids))})
        ORDER BY id ASC
        """, message_ids)

        for a in cursor.fetchall():
            attachments_by_message.setdefault(a[0], []).append(a)

    conn.close()

    mark_message_thread_read(thread_id)

    messages_html = ""
    for m in message_rows:
        attachment_html = ""
        for a in attachments_by_message.get(m[0], []):
            file_url = f"/message_uploads/{a[2]}"
            mime_type = a[3] or ""
            if mime_type.startswith("image/"):
                attachment_html += f"<div class='attachment'><img src='{file_url}' style='max-width:360px; border-radius:8px;'></div>"
            elif mime_type.startswith("video/"):
                attachment_html += f"<div class='attachment'><video src='{file_url}' controls style='max-width:480px; border-radius:8px;'></video></div>"
            else:
                attachment_html += f"<div class='attachment'><a href='{file_url}'>{a[1]}</a></div>"

        messages_html += f"""
        <div class="message">
            <div class="meta">{m[5]} | {m[2]} ({m[1]}) to {m[3]}</div>
            <div class="body">{m[4]}</div>
            {attachment_html}
        </div>
        """

    if not messages_html:
        messages_html = "<p>No messages yet.</p>"

    if require_owner():
        back_link = "/messages"
    elif require_teacher():
        back_link = "/teacher_messages"
    else:
        back_link = "/parent_messages"

    is_parent_app = back_link == "/parent_messages"
    thread_head = parent_app_meta(thread[1]) if is_parent_app else f"<title>{thread[1]}</title>"
    bottom_nav_html = parent_bottom_nav("messages") if is_parent_app else ""
    page_padding = "calc(96px + env(safe-area-inset-bottom))" if is_parent_app else "40px"

    return f"""
    <html>
    <head>
        {thread_head}
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f7f7fb; margin:0; color:#111827; }}
            .container {{ background:white; min-height:100vh; padding:max(22px, env(safe-area-inset-top)) 18px {page_padding}; max-width:900px; margin:0 auto; }}
            h1 {{ font-size:28px; line-height:1.12; margin:0 0 10px; }}
            .message {{ border:1px solid #e5e7eb; border-radius:10px; padding:14px; margin:12px 0; background:#fafafa; overflow:hidden; }}
            .meta {{ color:#6b7280; font-size:13px; margin-bottom:8px; }}
            .body {{ font-size:15px; white-space:pre-wrap; }}
            textarea {{ width:100%; min-height:120px; padding:12px 14px; margin:12px 0; font-size:16px; border:1px solid #d1d5db; border-radius:10px; }}
            input[type=file] {{ width:100%; margin:8px 0 18px; }}
            button, a.button {{ display:inline-block; background:#4f46e5; color:white; border:none; padding:12px 14px; border-radius:8px; text-decoration:none; font-weight:bold; margin-right:8px; min-height:48px; }}
            .attachment img, .attachment video {{ max-width:100% !important; height:auto; }}
            .parent-bottom-nav {{ position:fixed; left:0; right:0; bottom:0; display:grid; grid-template-columns:repeat(4,1fr); gap:4px; padding:8px 10px calc(8px + env(safe-area-inset-bottom)); background:rgba(255,255,255,.96); border-top:1px solid #e5e7eb; box-shadow:0 -4px 18px rgba(0,0,0,.08); z-index:20; }}
            .parent-bottom-nav a {{ text-align:center; text-decoration:none; color:#6b7280; font-size:12px; font-weight:800; padding:9px 4px; border-radius:8px; }}
            .parent-bottom-nav a.active {{ color:#4f46e5; background:#eef2ff; }}
            @media (min-width:900px) {{ body {{ padding:32px; }} .container {{ min-height:auto; padding:32px; border-radius:16px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{thread[1]}</h1>
            <p>Student: {thread[2] or ''} | Type: {thread[3]} | Status: {thread[4]}</p>
            <a class="button" href="{back_link}">Back</a>

            {messages_html}

            <h2>Reply</h2>
            <form method="POST" enctype="multipart/form-data">
                <textarea name="body" rows="4"></textarea>
                Attachments:<br>
                <input type="file" name="attachments" multiple accept="image/*,video/*,.pdf,.doc,.docx,.txt"><br><br>
                <button type="submit">Send Reply</button>
            </form>
        </div>
        {bottom_nav_html}
    </body>
    </html>
    """




@app.route("/message_uploads/<filename>")
def message_upload(filename):
    if not (require_owner() or require_parent() or require_teacher()):
        return redirect("/owner_login")
    return send_from_directory(HMUSIC_UPLOAD_DIR, filename)


def schedule_has_conflict(teacher, classroom, lesson_date, lesson_time, exclude_schedule_id=None, duration=30):
    target_start = minutes_from_time_text(lesson_time)
    if target_start is None:
        return {"has_conflict": False, "message": ""}

    try:
        duration = int(duration or 30)
    except:
        duration = 30

    target_end = target_start + duration

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, student_name, teacher, classroom, lesson_time, duration, status
    FROM schedule
    WHERE lesson_date = ?
    AND id != ?
    AND (
        teacher = ?
        OR classroom = ?
    )
    """, (
        lesson_date,
        exclude_schedule_id or -1,
        teacher,
        classroom
    ))

    rows = cursor.fetchall()
    conn.close()

    for row in rows:
        status = row[6] or "scheduled"
        if str(status).startswith("cancel") or status in ("excused_24h", "teacher_cancelled"):
            continue

        row_start = minutes_from_time_text(row[4])
        if row_start is None:
            continue

        try:
            row_duration = int(row[5] or 30)
        except:
            row_duration = 30

        row_end = row_start + row_duration

        if max(target_start, row_start) < min(target_end, row_end):
            conflict_type = "teacher" if row[2] == teacher else "classroom"
            return {
                "has_conflict": True,
                "message": f"{conflict_type.title()} conflict with {row[1]} at {row[4]} in {row[3]}."
            }

    return {"has_conflict": False, "message": ""}


@app.route("/teacher_messages")
def teacher_messages():
    if not require_teacher():
        return redirect("/teacher_login")

    teacher_name = session.get("teacher_name")
    rows = get_message_inbox_threads("teacher", teacher_name)
    return render_message_inbox(
        "Teacher Messages",
        "/teacher_dashboard",
        "Back to Dashboard",
        rows,
        new_href="/new_teacher_message",
        new_label="New Message to Parent"
    )


@app.route("/teacher_reschedule", methods=["GET", "POST"])
def teacher_reschedule():
    if not require_teacher():
        return redirect("/teacher_login")

    ensure_v29_schema()

    teacher_name = session.get("teacher_name")

    if request.method == "POST":
        schedule_id = request.form.get("schedule_id")
        preferred_slot = request.form.get("preferred_slot")
        requested_date = request.form.get("requested_date")
        requested_time = request.form.get("requested_time")
        reason = request.form.get("reason")
        requested_teacher = None
        requested_classroom = None
        requested_slot_source = None

        if preferred_slot:
            slot_parts = preferred_slot.split("|")
            if len(slot_parts) >= 4:
                requested_teacher = slot_parts[0]
                requested_date = slot_parts[1]
                requested_time = slot_parts[2]
                requested_classroom = slot_parts[3]
                requested_slot_source = slot_parts[4] if len(slot_parts) >= 5 else None

        if not requested_date or not requested_time:
            return "<h1>Please choose an open slot or enter a backup requested date and time.</h1>"

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, student_name, lesson_date, lesson_time, teacher, classroom, status
        FROM schedule
        WHERE id = ?
        AND teacher = ?
        """, (schedule_id, teacher_name))
        lesson = cursor.fetchone()

        if not lesson:
            conn.close()
            return "<h1>Lesson not found or permission denied.</h1>"

        if lesson[6] not in (None, "", "scheduled"):
            conn.close()
            return "<h1>Only scheduled lessons can be rescheduled.</h1>"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO reschedule_requests (
            parent_id,
            student_name,
            original_schedule_id,
            original_date,
            original_time,
            original_teacher,
            original_classroom,
            requested_date,
            requested_time,
            requested_teacher,
            requested_classroom,
            requested_slot_source,
            reason,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            None,
            lesson[1],
            lesson[0],
            lesson[2],
            lesson[3],
            lesson[4],
            lesson[5],
            requested_date,
            requested_time,
            requested_teacher,
            requested_classroom,
            requested_slot_source,
            reason,
            "pending",
            now,
            now
        ))

        request_id = cursor.lastrowid
        conn.commit()
        conn.close()

        create_reschedule_message_event(
            request_id,
            "submitted",
            f"{teacher_name} requested a reschedule for {lesson[1]} from {lesson[2]} {lesson[3]} to {requested_date} {requested_time}. Reason: {reason or ''}",
            parent_id=None,
            student_name=lesson[1],
            teacher_name=teacher_name
        )

        return f"""
        <h1>Teacher Reschedule Request Submitted</h1>
        <p>Request #{request_id}</p>
        <p>Student: {lesson[1]}</p>
        <p>Requested Time: {requested_date} {requested_time}</p>
        <p><a href="/teacher_dashboard">Back to Teacher Dashboard</a></p>
        """

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT id, lesson_date, lesson_time, student_name, classroom, status
    FROM schedule
    WHERE teacher = ?
    AND lesson_date >= ?
    AND (status IS NULL OR status = '' OR status = 'scheduled')
    ORDER BY lesson_date, lesson_time
    """, (teacher_name, today))
    lessons = cursor.fetchall()
    conn.close()

    open_slots = get_available_open_slots(teachers=[teacher_name])

    lesson_options = ""
    for l in lessons:
        lesson_options += f"<option value='{l[0]}'>{l[1]} {l[2]} | {l[3]} | {l[4]}</option>"
    if not lesson_options:
        lesson_options = "<option value=''>No upcoming scheduled lessons</option>"

    open_slot_options = '<option value="">Use backup date/time instead</option>'
    for slot in open_slots:
        value = f"{slot['teacher']}|{slot['slot_date']}|{slot['slot_time']}|{slot['classroom']}|{slot['source']}"
        open_slot_options += f"<option value='{value}'>{slot['slot_date']} {slot['slot_time']} | {slot['classroom']} | {slot['source']}</option>"
    if not open_slot_options:
        open_slot_options = "<option value=''>No open slots found</option>"

    return f"""
    <html>
    <head>
        <title>Teacher Reschedule Request</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:900px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select, textarea {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Teacher Reschedule Request</h1>
            <form method="POST">
                Current Lesson:<br>
                <select name="schedule_id" required>{lesson_options}</select>

                Preferred Open Slot:<br>
                <select name="preferred_slot" required>{open_slot_options}</select>

                Backup Requested Date:<br>
                <input type="date" name="requested_date">

                Backup Requested Time:<br>
                <input type="time" name="requested_time">

                Reason:<br>
                <textarea name="reason" rows="4"></textarea>

                <button type="submit">Submit Request</button>
                <a class="button" href="/teacher_dashboard">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/notifications")
def notifications():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v29_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, title, body, link_url, read_at, created_at
    FROM notifications
    WHERE user_role = 'owner'
    ORDER BY id DESC
    LIMIT 50
    """)
    rows_data = cursor.fetchall()
    conn.close()

    rows = ""
    for n in rows_data:
        read_status = "Unread" if not n[4] else "Read"
        rows += f"""
        <tr>
            <td>{n[5]}</td>
            <td><a href="{n[3]}">{n[1]}</a></td>
            <td>{n[2]}</td>
            <td>{read_status}</td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='4'>No notifications.</td></tr>"

    return f"""
    <html>
    <head>
        <title>Notifications</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; }}
            th {{ background:#eeeeff; }}
            a {{ color:#5b5cff; font-weight:bold; }}
            a.button {{ display:inline-block; background:#5b5cff; color:white; padding:10px 14px; border-radius:8px; text-decoration:none; font-weight:bold; margin-right:8px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Notifications</h1>
            <a class="button" href="/messages">Message Center</a>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Title</th>
                    <th>Body</th>
                    <th>Status</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/parent_reschedule", methods=["GET", "POST"])
def parent_reschedule():
    if not require_parent():
        return redirect("/parent_login")

    ensure_v282_schema()

    parent_id = session.get("parent_id")
    student_name = session.get("parent_student_name")

    if not student_name:
        return redirect("/parent_dashboard")

    if parent_id and not parent_can_access_student(parent_id, student_name):
        return "<h1>Permission denied</h1>"

    if request.method == "POST":
        schedule_id = request.form.get("schedule_id")
        preferred_slot = request.form.get("preferred_slot")
        requested_date = request.form.get("requested_date")
        requested_time = request.form.get("requested_time")
        reason = request.form.get("reason")
        requested_teacher = None
        requested_classroom = None
        requested_slot_source = None

        if preferred_slot:
            slot_parts = preferred_slot.split("|")
            if len(slot_parts) >= 4:
                requested_teacher = slot_parts[0]
                requested_date = slot_parts[1]
                requested_time = slot_parts[2]
                requested_classroom = slot_parts[3]
                requested_slot_source = slot_parts[4] if len(slot_parts) >= 5 else None

        if not preferred_slot and (not requested_date or not requested_time):
            return "<h1>Please choose an open slot or enter a backup requested date and time.</h1>"

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, student_name, lesson_date, lesson_time, teacher, classroom, status
        FROM schedule
        WHERE id = ?
        """, (schedule_id,))

        lesson = cursor.fetchone()

        if not lesson:
            conn.close()
            return "<h1>Lesson not found</h1>"

        if lesson[1] != student_name:
            conn.close()
            return "<h1>Permission denied</h1>"

        if lesson[6] not in (None, "", "scheduled"):
            conn.close()
            return "<h1>Only scheduled lessons can be rescheduled.</h1>"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO reschedule_requests (
            parent_id,
            student_name,
            original_schedule_id,
            original_date,
            original_time,
            original_teacher,
            original_classroom,
            requested_date,
            requested_time,
            requested_teacher,
            requested_classroom,
            requested_slot_source,
            reason,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parent_id,
            student_name,
            lesson[0],
            lesson[2],
            lesson[3],
            lesson[4],
            lesson[5],
            requested_date,
            requested_time,
            requested_teacher,
            requested_classroom,
            requested_slot_source,
            reason,
            "pending",
            now,
            now
        ))

        request_id = cursor.lastrowid
        conn.commit()
        conn.close()

        log_parent_activity(
            parent_id,
            student_name,
            "reschedule_request",
            f"Parent requested reschedule for lesson #{schedule_id} from {lesson[2]} {lesson[3]} to {requested_date} {requested_time}.",
            schedule_id
        )

        create_reschedule_message_event(
            request_id,
            "submitted",
            f"{student_name} requested a reschedule from {lesson[2]} {lesson[3]} to {requested_date} {requested_time}. Reason: {reason or ''}",
            parent_id=parent_id,
            student_name=student_name,
            teacher_name=lesson[4]
        )

        return f"""
        <h1>Reschedule Request Submitted</h1>
        <p>Request #{request_id}</p>
        <p>Student: {student_name}</p>
        <p>Requested Time: {requested_date} {requested_time}</p>
        <p><a href="/parent_dashboard">Back to Parent Dashboard</a></p>
        """

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT id, lesson_date, lesson_time, teacher, classroom, status
    FROM schedule
    WHERE student_name = ?
    AND lesson_date >= ?
    AND (status IS NULL OR status = '' OR status = 'scheduled')
    ORDER BY lesson_date, lesson_time
    """, (student_name, today))
    lessons = cursor.fetchall()

    cursor.execute("""
    SELECT id, original_date, original_time, requested_date, requested_time, status, created_at
    FROM reschedule_requests
    WHERE student_name = ?
    AND parent_id = ?
    ORDER BY id DESC
    LIMIT 10
    """, (student_name, parent_id))
    requests = cursor.fetchall()

    open_slots = get_available_open_slots()

    conn.close()

    lesson_options = ""
    for l in lessons:
        lesson_options += f"""
        <option value="{l[0]}">{l[1]} {l[2]} | {l[3]} | {l[4]}</option>
        """

    if not lesson_options:
        lesson_options = '<option value="">No upcoming scheduled lessons</option>'

    open_slot_options = '<option value="">Use backup date/time instead</option>'
    for slot in open_slots:
        value = f"{slot['teacher']}|{slot['slot_date']}|{slot['slot_time']}|{slot['classroom']}|{slot['source']}"
        open_slot_options += f"""
        <option value="{value}">{slot['slot_date']} {slot['slot_time']} | {slot['teacher']} | {slot['classroom']} | {slot['source']}</option>
        """

    if len(open_slots) == 0:
        open_slot_options += '<option value="" disabled>No open slots found</option>'

    request_rows = ""
    for r in requests:
        request_rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]} {r[2]}</td>
            <td>{r[3]} {r[4]}</td>
            <td>{r[5]}</td>
            <td>{r[6]}</td>
        </tr>
        """

    if not request_rows:
        request_rows = "<tr><td colspan='5'>No reschedule requests yet.</td></tr>"

    return f"""
    <html>
    <head>
        {parent_app_meta("Request Reschedule")}
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f7f7fb; margin:0; color:#111827; }}
            .container {{ background:white; min-height:100vh; padding:max(22px, env(safe-area-inset-top)) 18px calc(96px + env(safe-area-inset-bottom)); max-width:900px; margin:0 auto; }}
            h1 {{ font-size:30px; line-height:1.08; margin:0 0 24px; }}
            input, select, textarea {{ width:100%; min-height:48px; padding:12px 14px; margin:8px 0 18px; font-size:16px; border:1px solid #d1d5db; border-radius:10px; }}
            textarea {{ min-height:120px; }}
            button, a.button {{ display:inline-block; background:#4f46e5; color:white; border:none; padding:12px 16px; border-radius:8px; font-weight:bold; text-decoration:none; min-height:48px; }}
            table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; }}
            th {{ background:#eeeeff; }}
            .form-actions {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
            .parent-bottom-nav {{
                position: fixed; left: 0; right: 0; bottom: 0;
                display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
                padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
                background: rgba(255,255,255,.96); border-top: 1px solid #e5e7eb;
                box-shadow: 0 -4px 18px rgba(0,0,0,.08); z-index: 20;
            }}
            .parent-bottom-nav a {{ text-align:center; text-decoration:none; color:#6b7280; font-size:12px; font-weight:800; padding:9px 4px; border-radius:8px; }}
            .parent-bottom-nav a.active {{ color:#4f46e5; background:#eef2ff; }}
            @media (max-width:760px) {{
                table {{ display:block; overflow-x:auto; font-size:12px; }}
                .form-actions {{ display:grid; grid-template-columns:1fr 1fr; }}
                .form-actions button, .form-actions a {{ text-align:center; }}
            }}
            @media (min-width:900px) {{
                body {{ padding:32px; }}
                .container {{ min-height:auto; padding:32px; border-radius:16px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Request Reschedule - {student_name}</h1>

            <form method="POST">
                Current Lesson:<br>
                <select name="schedule_id" required>
                    {lesson_options}
                </select>

                Preferred Open Slot:<br>
                <select name="preferred_slot">
                    {open_slot_options}
                </select>

                Backup Requested Date:<br>
                <input type="date" name="requested_date">

                Backup Requested Time:<br>
                <input type="time" name="requested_time">

                Reason:<br>
                <textarea name="reason" rows="4"></textarea>

                <div class="form-actions">
                    <button type="submit">Submit Request</button>
                    <a class="button" href="/parent_dashboard">Back</a>
                </div>
            </form>

            <h2>Recent Requests</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Original</th>
                    <th>Requested</th>
                    <th>Status</th>
                    <th>Created</th>
                </tr>
                {request_rows}
            </table>
        </div>
        {parent_bottom_nav("reschedule")}
    </body>
    </html>
    """




@app.route("/open_slots")
def open_slots():
    if not (require_owner() or require_teacher()):
        return redirect("/owner_login")

    ensure_v282_schema()

    teacher_filter = request.args.get("teacher")
    status_filter = request.args.get("status", "available")
    source_filter = request.args.get("source", "all")
    teachers = None

    if require_teacher() and not require_owner():
        teachers = [session.get("teacher_name")]
        teacher_filter = session.get("teacher_name")
    elif teacher_filter:
        teachers = [teacher_filter]

    slots = get_available_open_slots(teachers=teachers, include_inactive_manual=True)

    filtered_slots = []
    for slot in slots:
        display_status = get_open_slot_display_status(slot)
        source = slot.get("source", "auto_gap")
        if status_filter != "all" and display_status.lower() != status_filter:
            continue
        if source_filter != "all" and source != source_filter:
            continue
        filtered_slots.append(slot)

    summary = {"Available": 0, "Used": 0, "Inactive": 0, "auto_gap": 0, "manual": 0}
    for slot in slots:
        summary[get_open_slot_display_status(slot)] = summary.get(get_open_slot_display_status(slot), 0) + 1
        source = slot.get("source", "auto_gap")
        summary[source] = summary.get(source, 0) + 1

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teacher_rows = cursor.fetchall()
    conn.close()

    teacher_options = '<option value="">All Teachers</option>'
    for t in teacher_rows:
        selected = "selected" if teacher_filter == t[0] else ""
        teacher_options += f'<option value="{t[0]}" {selected}>{t[0]}</option>'

    status_options = ""
    for value, label in [("available", "Available"), ("used", "Used"), ("inactive", "Inactive"), ("all", "All")]:
        selected = "selected" if status_filter == value else ""
        status_options += f'<option value="{value}" {selected}>{label}</option>'

    source_options = ""
    for value, label in [("all", "All Sources"), ("manual", "Manual"), ("auto_gap", "Auto Gap")]:
        selected = "selected" if source_filter == value else ""
        source_options += f'<option value="{value}" {selected}>{label}</option>'

    rows = ""
    for slot in filtered_slots:
        display_status = get_open_slot_display_status(slot)
        status_class = display_status.lower()
        source = slot.get("source", "auto_gap")
        action = ""
        if source == "manual" and slot.get("id"):
            if display_status == "Used":
                action = "<span class='muted'>Locked</span>"
            elif display_status == "Available":
                action = f"""
                <form method="POST" action="/toggle_open_slot/{slot['id']}" style="display:inline;">
                    <button type="submit">Deactivate</button>
                </form>
                """
            else:
                action = f"""
                <form method="POST" action="/toggle_open_slot/{slot['id']}" style="display:inline;">
                    <button type="submit">Reactivate</button>
                </form>
                """
        else:
            action = "<span class='muted'>Auto</span>"

        rows += f"""
        <tr>
            <td>{slot['slot_date']}</td>
            <td>{slot['slot_time']}</td>
            <td>{slot['teacher']}</td>
            <td>{slot['classroom']}</td>
            <td><span class="badge source">{source}</span></td>
            <td><span class="badge {status_class}">{display_status}</span></td>
            <td>{slot.get('notes', '')}</td>
            <td>{action}</td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='8'>No open slots found.</td></tr>"

    add_link = "/add_open_slot"
    back_link = "/teacher_dashboard" if require_teacher() and not require_owner() else "/"

    return f"""
    <html>
    <head>
        <title>Open Slots</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; color:#111827; }}
            .container {{ background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            a.button, button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:9px 13px; border-radius:7px; text-decoration:none; font-weight:bold; margin-right:7px; cursor:pointer; }}
            table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; vertical-align:top; }}
            th {{ background:#eeeeff; }}
            select {{ padding:9px; font-size:14px; margin-right:8px; }}
            .summary {{ display:grid; grid-template-columns:repeat(5, 1fr); gap:12px; margin:18px 0; }}
            .summary-card {{ background:#f5f5ff; border:1px solid #ddd; border-radius:8px; padding:12px; }}
            .label {{ color:#6b7280; font-size:12px; }}
            .value {{ font-size:22px; font-weight:bold; margin-top:4px; }}
            .badge {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#eef2ff; font-size:12px; font-weight:bold; }}
            .badge.available {{ background:#dcfce7; color:#166534; }}
            .badge.used {{ background:#fee2e2; color:#991b1b; }}
            .badge.inactive {{ background:#e5e7eb; color:#374151; }}
            .badge.source {{ background:#e0f2fe; color:#075985; }}
            .muted {{ color:#6b7280; font-size:13px; }}
            @media (max-width: 760px) {{
                body {{ padding:14px; }}
                .summary {{ grid-template-columns:repeat(2, 1fr); }}
                table {{ font-size:12px; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Teacher Open Slots</h1>
            <p class="muted">Available slots are shown to parents during reschedule. Used manual slots are locked after approval. Auto gaps are generated between a teacher's first and last lesson of the day.</p>

            <a class="button" href="{back_link}">Back</a>
            <a class="button" href="{add_link}">Add Manual Slot</a>

            <div class="summary">
                <div class="summary-card"><div class="label">Available</div><div class="value">{summary.get('Available', 0)}</div></div>
                <div class="summary-card"><div class="label">Used</div><div class="value">{summary.get('Used', 0)}</div></div>
                <div class="summary-card"><div class="label">Inactive</div><div class="value">{summary.get('Inactive', 0)}</div></div>
                <div class="summary-card"><div class="label">Manual</div><div class="value">{summary.get('manual', 0)}</div></div>
                <div class="summary-card"><div class="label">Auto Gap</div><div class="value">{summary.get('auto_gap', 0)}</div></div>
            </div>

            <form method="GET" action="/open_slots" style="margin-top:18px;">
                Teacher:
                <select name="teacher">
                    {teacher_options}
                </select>
                Status:
                <select name="status">
                    {status_options}
                </select>
                Source:
                <select name="source">
                    {source_options}
                </select>
                <button type="submit">Filter</button>
            </form>

            <table>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Teacher</th>
                    <th>Room</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Notes</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_open_slot", methods=["GET", "POST"])
def add_open_slot():
    if not (require_owner() or require_teacher()):
        return redirect("/owner_login")

    ensure_v282_schema()

    fixed_teacher = None
    if require_teacher() and not require_owner():
        fixed_teacher = session.get("teacher_name")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        teacher = fixed_teacher or request.form.get("teacher")
        slot_date = request.form.get("slot_date")
        slot_time = request.form.get("slot_time")
        classroom = request.form.get("classroom")
        notes = request.form.get("notes")

        if not teacher or not slot_date or not slot_time or not classroom:
            conn.close()
            return "<h1>Teacher, date, time, and classroom are required.</h1>"

        cursor.execute("""
        SELECT id, active, notes
        FROM teacher_open_slots
        WHERE teacher = ?
        AND slot_date = ?
        AND slot_time = ?
        AND classroom = ?
        AND source = 'manual'
        ORDER BY id DESC
        LIMIT 1
        """, (teacher, slot_date, slot_time, classroom))
        existing_slot = cursor.fetchone()

        if existing_slot:
            conn.close()
            return "<h1>This manual open slot already exists.</h1><p><a href='/open_slots?status=all'>Back to Open Slots</a></p>"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        created_by = "owner" if require_owner() else f"teacher:{fixed_teacher}"

        cursor.execute("""
        INSERT INTO teacher_open_slots (
            teacher,
            slot_date,
            slot_time,
            classroom,
            source,
            active,
            notes,
            created_by,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            teacher,
            slot_date,
            slot_time,
            classroom,
            "manual",
            1,
            notes,
            created_by,
            now,
            now
        ))

        conn.commit()
        conn.close()
        return redirect(request.referrer or "/open_slots")

    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teacher_rows = cursor.fetchall()
    cursor.execute("SELECT room_name FROM classrooms ORDER BY room_name")
    classroom_rows = cursor.fetchall()
    conn.close()

    if fixed_teacher:
        teacher_input = f"""
        Teacher:<br>
        <input name="teacher" value="{fixed_teacher}" disabled>
        """
    else:
        teacher_options = "".join([f'<option value="{t[0]}">{t[0]}</option>' for t in teacher_rows])
        teacher_input = f"""
        Teacher:<br>
        <select name="teacher">{teacher_options}</select>
        """

    classroom_options = "".join([f'<option value="{c[0]}">{c[0]}</option>' for c in classroom_rows])
    today = date.today().strftime("%Y-%m-%d")

    return f"""
    <html>
    <head>
        <title>Add Open Slot</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:700px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            input, select, textarea {{ width:100%; padding:10px; margin:8px 0 18px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Add Manual Open Slot</h1>
            <form method="POST">
                {teacher_input}

                Date:<br>
                <input type="date" name="slot_date" value="{today}" required>

                Time:<br>
                <input type="time" name="slot_time" required>

                Classroom:<br>
                <select name="classroom">{classroom_options}</select>

                Notes:<br>
                <textarea name="notes" rows="4"></textarea>

                <button type="submit">Add Slot</button>
                <a class="button" href="/open_slots">Back</a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route("/toggle_open_slot/<int:slot_id>", methods=["POST"])
def toggle_open_slot(slot_id):
    if not (require_owner() or require_teacher()):
        return redirect("/owner_login")

    ensure_v282_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT teacher, active, notes
    FROM teacher_open_slots
    WHERE id = ?
    """, (slot_id,))
    slot = cursor.fetchone()

    if not slot:
        conn.close()
        return "<h1>Open slot not found</h1>"

    if require_teacher() and not require_owner() and slot[0] != session.get("teacher_name"):
        conn.close()
        return "<h1>Permission denied</h1>"

    if "used by reschedule" in (slot[2] or ""):
        conn.close()
        return "<h1>Used open slots are locked and cannot be reactivated.</h1>"

    new_active = 0 if slot[1] == 1 else 1

    cursor.execute("""
    UPDATE teacher_open_slots
    SET active = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        new_active,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        slot_id
    ))

    conn.commit()
    conn.close()

    return redirect("/open_slots")


@app.route("/owner_reschedule_requests")
def owner_reschedule_requests():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v28_schema()

    status_filter = request.args.get("status", "pending")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if status_filter == "all":
        cursor.execute("""
        SELECT id, student_name, original_date, original_time, requested_date, requested_time, status, created_at
        FROM reschedule_requests
        ORDER BY id DESC
        """)
    else:
        cursor.execute("""
        SELECT id, student_name, original_date, original_time, requested_date, requested_time, status, created_at
        FROM reschedule_requests
        WHERE status = ?
        ORDER BY id DESC
        """, (status_filter,))

    requests_data = cursor.fetchall()
    conn.close()

    rows = ""
    for r in requests_data:
        rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>{r[2]} {r[3]}</td>
            <td>{r[4]} {r[5]}</td>
            <td>{r[6]}</td>
            <td>{r[7]}</td>
            <td><a href="/reschedule_request/{r[0]}">Review</a></td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='7'>No reschedule requests found.</td></tr>"

    return f"""
    <html>
    <head>
        <title>Reschedule Requests</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            a.button {{ display:inline-block; background:#5b5cff; color:white; padding:10px 14px; border-radius:8px; text-decoration:none; font-weight:bold; margin-right:8px; }}
            table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
            th, td {{ padding:10px; border-bottom:1px solid #eee; text-align:left; }}
            th {{ background:#eeeeff; }}
            a {{ color:#5b5cff; font-weight:bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Reschedule Requests</h1>
            <a class="button" href="/">Home</a>
            <a class="button" href="/owner_reschedule_requests?status=pending">Pending</a>
            <a class="button" href="/owner_reschedule_requests?status=approved">Approved</a>
            <a class="button" href="/owner_reschedule_requests?status=rejected">Rejected</a>
            <a class="button" href="/owner_reschedule_requests?status=all">All</a>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Student</th>
                    <th>Original</th>
                    <th>Requested</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/reschedule_request/<int:request_id>")
def reschedule_request_detail(request_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v28_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        parent_id,
        student_name,
        original_schedule_id,
        original_date,
        original_time,
        original_teacher,
        original_classroom,
        requested_date,
        requested_time,
        reason,
        status,
        owner_note,
        reviewed_by,
        reviewed_at,
        created_at,
        requested_teacher,
        requested_classroom,
        requested_slot_source,
        approved_teacher,
        approved_classroom
    FROM reschedule_requests
    WHERE id = ?
    """, (request_id,))
    r = cursor.fetchone()
    conn.close()

    if not r:
        return "<h1>Reschedule request not found</h1>"

    conn2 = sqlite3.connect("hmusic.db")
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teacher_rows = cursor2.fetchall()
    conn2.close()

    teacher_options = ""
    requested_teacher = r[16] or r[6]
    requested_classroom = r[17] or r[7]
    requested_slot_source = r[18] or "backup"

    for t in teacher_rows:
        selected = "selected" if t[0] == requested_teacher else ""
        teacher_options += f'<option value="{t[0]}" {selected}>{t[0]}</option>'

    pending_actions = ""
    if r[11] == "pending":
        pending_actions = f"""
        <h2>Approve</h2>
        <form method="POST" action="/approve_reschedule/{r[0]}">
            Actual Teacher:<br>
            <select name="approved_teacher">
                {teacher_options}
            </select>

            Approved Date:<br>
            <input type="date" name="approved_date" value="{r[8]}" required>

            Approved Time:<br>
            <input type="time" name="approved_time" value="{r[9]}" required>

            Approved Room:<br>
            <input name="approved_classroom" value="{requested_classroom or ''}" required>

            Owner Note:<br>
            <textarea name="owner_note" rows="3"></textarea>

            <button type="submit">Approve and Update Schedule</button>
        </form>

        <h2>Reject</h2>
        <form method="POST" action="/reject_reschedule/{r[0]}">
            Reject Reason:<br>
            <textarea name="owner_note" rows="3" required></textarea>
            <button class="danger" type="submit">Reject Request</button>
        </form>
        """

    return f"""
    <html>
    <head>
        <title>Review Reschedule Request</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f7f7fb; padding:40px; }}
            .container {{ background:white; padding:30px; border-radius:12px; max-width:820px; box-shadow:0 2px 10px rgba(0,0,0,0.08); }}
            .grid {{ display:grid; grid-template-columns:repeat(2, 1fr); gap:14px; margin:18px 0; }}
            .card {{ background:#f5f5ff; border:1px solid #ddd; border-radius:10px; padding:16px; }}
            .label {{ color:#6b7280; font-size:13px; }}
            .value {{ font-size:20px; font-weight:bold; margin-top:6px; }}
            input, textarea {{ width:100%; padding:10px; margin:8px 0 16px; font-size:15px; }}
            button, a.button {{ display:inline-block; background:#5b5cff; color:white; border:none; padding:10px 16px; border-radius:6px; font-weight:bold; text-decoration:none; margin-right:8px; }}
            .danger {{ background:#dc2626; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Reschedule Request #{r[0]}</h1>
            <a class="button" href="/owner_reschedule_requests">Back</a>

            <div class="grid">
                <div class="card"><div class="label">Student</div><div class="value">{r[2]}</div></div>
                <div class="card"><div class="label">Status</div><div class="value">{r[11]}</div></div>
                <div class="card"><div class="label">Original</div><div class="value">{r[4]} {r[5]}</div></div>
                <div class="card"><div class="label">Requested</div><div class="value">{r[8]} {r[9]}</div></div>
                <div class="card"><div class="label">Original Teacher</div><div class="value">{r[6]}</div></div>
                <div class="card"><div class="label">Original Room</div><div class="value">{r[7]}</div></div>
                <div class="card"><div class="label">Preferred Teacher</div><div class="value">{requested_teacher or ''}</div></div>
                <div class="card"><div class="label">Preferred Room</div><div class="value">{requested_classroom or ''}</div></div>
                <div class="card"><div class="label">Slot Source</div><div class="value">{requested_slot_source}</div></div>
            </div>

            <p><b>Reason:</b> {r[10] or ''}</p>
            <p><b>Owner Note:</b> {r[12] or ''}</p>
            <p><b>Reviewed:</b> {r[13] or ''} {r[14] or ''}</p>

            {pending_actions}
        </div>
    </body>
    </html>
    """


@app.route("/approve_reschedule/<int:request_id>", methods=["POST"])
def approve_reschedule(request_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v28_schema()

    approved_teacher = request.form.get("approved_teacher")
    approved_date = request.form.get("approved_date")
    approved_time = request.form.get("approved_time")
    approved_classroom = request.form.get("approved_classroom")
    owner_note = request.form.get("owner_note")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        rr.id,
        rr.parent_id,
        rr.student_name,
        rr.original_schedule_id,
        rr.status,
        rr.original_teacher,
        rr.original_classroom,
        COALESCE(s.duration, 30),
        rr.requested_teacher,
        rr.requested_classroom,
        rr.requested_slot_source
    FROM reschedule_requests rr
    LEFT JOIN schedule s
        ON rr.original_schedule_id = s.id
    WHERE rr.id = ?
    """, (request_id,))
    r = cursor.fetchone()

    if not r:
        conn.close()
        return "<h1>Reschedule request not found</h1>"

    if r[4] != "pending":
        conn.close()
        return "<h1>This request has already been reviewed.</h1>"

    actual_teacher = approved_teacher or r[8] or r[5]
    actual_classroom = approved_classroom or r[9] or r[6]

    if not approved_date or not approved_time or not actual_teacher or not actual_classroom:
        conn.close()
        return "<h1>Approved teacher, date, time, and room are required.</h1>"

    conflict = schedule_has_conflict(
        actual_teacher,
        actual_classroom,
        approved_date,
        approved_time,
        exclude_schedule_id=r[3],
        duration=r[7]
    )

    if conflict["has_conflict"]:
        conn.close()
        return f"""
        <h1>Cannot Approve Reschedule</h1>
        <p>{conflict["message"]}</p>
        <p><a href="/reschedule_request/{request_id}">Back to Request</a></p>
        """

    cursor.execute("""
    UPDATE schedule
    SET teacher = ?,
        lesson_date = ?,
        lesson_time = ?,
        classroom = ?,
        status = 'scheduled'
    WHERE id = ?
    """, (
        actual_teacher,
        approved_date,
        approved_time,
        actual_classroom,
        r[3]
    ))

    cursor.execute("""
    UPDATE reschedule_requests
    SET requested_date = ?,
        requested_time = ?,
        status = 'approved',
        owner_note = ?,
        approved_teacher = ?,
        approved_classroom = ?,
        reviewed_by = ?,
        reviewed_at = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        approved_date,
        approved_time,
        owner_note,
        actual_teacher,
        actual_classroom,
        "owner",
        now,
        now,
        request_id
    ))

    conn.commit()
    conn.close()

    if r[10] == "manual":
        mark_manual_open_slot_used(actual_teacher, approved_date, approved_time, actual_classroom, request_id)

    log_parent_activity(
        r[1],
        r[2],
        "reschedule_approved",
        f"Owner approved reschedule request #{request_id}; teacher {actual_teacher}; room {actual_classroom}; new time {approved_date} {approved_time}.",
        r[3]
    )

    create_reschedule_message_event(
        request_id,
        "approved",
        f"Your reschedule request was approved. Teacher: {actual_teacher}. Room: {actual_classroom}. New lesson time: {approved_date} {approved_time}. {owner_note or ''}",
        parent_id=r[1],
        student_name=r[2],
        teacher_name=actual_teacher
    )

    return redirect(f"/reschedule_request/{request_id}")


@app.route("/reject_reschedule/<int:request_id>", methods=["POST"])
def reject_reschedule(request_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v28_schema()

    owner_note = request.form.get("owner_note")
    if not owner_note or not owner_note.strip():
        return "<h1>Reject reason is required.</h1>"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, parent_id, student_name, original_schedule_id, status, original_teacher
    FROM reschedule_requests
    WHERE id = ?
    """, (request_id,))
    r = cursor.fetchone()

    if not r:
        conn.close()
        return "<h1>Reschedule request not found</h1>"

    if r[4] != "pending":
        conn.close()
        return "<h1>This request has already been reviewed.</h1>"

    cursor.execute("""
    UPDATE reschedule_requests
    SET status = 'rejected',
        owner_note = ?,
        reviewed_by = ?,
        reviewed_at = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        owner_note,
        "owner",
        now,
        now,
        request_id
    ))

    conn.commit()
    conn.close()

    log_parent_activity(
        r[1],
        r[2],
        "reschedule_rejected",
        f"Owner rejected reschedule request #{request_id}.",
        r[3]
    )

    create_reschedule_message_event(
        request_id,
        "rejected",
        f"Your reschedule request was rejected. {owner_note or ''}",
        parent_id=r[1],
        student_name=r[2],
        teacher_name=r[5]
    )

    return redirect(f"/reschedule_request/{request_id}")


@app.route("/parent_login", methods=["GET", "POST"])
def parent_login():
    ensure_v27_schema()

    if request.method == "POST":
        parent_email = request.form.get("parent_email")
        password = request.form.get("password")
        student_name = request.form.get("student_name")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        if parent_email and password:
            cursor.execute("""
            SELECT id, parent_name, email
            FROM parent_profiles
            WHERE lower(email) = lower(?)
            AND password = ?
            AND active = 1
            """, (parent_email, password))

            parent = cursor.fetchone()

            if parent:
                cursor.execute("""
                SELECT student_name
                FROM parent_students
                WHERE parent_id = ?
                AND active = 1
                ORDER BY student_name
                LIMIT 1
                """, (parent[0],))

                linked_student = cursor.fetchone()
                conn.close()

                session.clear()
                session["parent_id"] = parent[0]
                session["parent_name"] = parent[1]
                session["parent_email"] = parent[2]

                if linked_student:
                    session["parent_student_name"] = linked_student[0]

                return redirect("/parent_dashboard")

        if student_name and parent_email:
            cursor.execute("""
            SELECT name, parent_email
            FROM students
            WHERE name = ?
            AND parent_email = ?
            """, (student_name, parent_email))

            student = cursor.fetchone()

            if student:
                cursor.execute("""
                SELECT id, parent_name, email
                FROM parent_profiles
                WHERE email = ?
                """, (parent_email,))

                parent = cursor.fetchone()
                conn.close()

                session.clear()

                if parent:
                    session["parent_id"] = parent[0]
                    session["parent_name"] = parent[1]
                    session["parent_email"] = parent[2]

                session["parent_student_name"] = student[0]
                return redirect("/parent_dashboard")

        conn.close()

        return f"""
        <html>
        <head>
            {parent_app_meta("Login Failed")}
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    background: #f7f7fb;
                    color: #111827;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                }}
                .container {{
                    min-height: 100vh;
                    max-width: 520px;
                    margin: 0 auto;
                    background: white;
                    padding: max(32px, env(safe-area-inset-top)) 22px max(32px, env(safe-area-inset-bottom));
                }}
                .brand-mark {{
                    width: 56px;
                    height: 56px;
                    border-radius: 16px;
                    margin-bottom: 18px;
                    background: #4f46e5;
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 30px;
                    font-weight: 900;
                }}
                h1 {{ font-size: 32px; margin: 0 0 12px; }}
                p {{ color: #6b7280; line-height: 1.5; }}
                a.button {{
                    display: inline-block;
                    background: #4f46e5;
                    color: white;
                    padding: 12px 16px;
                    border-radius: 8px;
                    text-decoration: none;
                    font-weight: 800;
                    margin-top: 12px;
                }}
                @media (min-width: 760px) {{
                    body {{ padding: 40px; }}
                    .container {{
                        min-height: auto;
                        padding: 34px;
                        border-radius: 16px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="brand-mark">H</div>
                <h1>Login failed</h1>
                <p>Please check the parent email and password, then try again.</p>
                <a class="button" href="/parent_login">Back to Login</a>
            </div>
        </body>
        </html>
        """

    return """
    <html>
    <head>
        """ + parent_app_meta("H-Music Parent Login") + """
        <style>
            * {
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f7f7fb;
                margin: 0;
                color: #111827;
            }
            .container {
                background: white;
                min-height: 100vh;
                padding: max(28px, env(safe-area-inset-top)) 22px max(28px, env(safe-area-inset-bottom));
                max-width: 520px;
                margin: 0 auto;
            }
            .brand {
                margin: 30px 0 28px;
            }
            .brand-mark {
                width: 56px;
                height: 56px;
                border-radius: 16px;
                margin-bottom: 18px;
                background: #4f46e5;
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 30px;
                font-weight: 900;
            }
            h1 {
                font-size: 34px;
                line-height: 1.05;
                margin: 0;
            }
            h3 {
                margin-top: 0;
            }
            input {
                width: 100%;
                min-height: 48px;
                padding: 12px 14px;
                margin: 8px 0 18px;
                font-size: 16px;
                border: 1px solid #d1d5db;
                border-radius: 10px;
            }
            button {
                background: #4f46e5;
                color: white;
                border: none;
                min-height: 48px;
                padding: 12px 18px;
                border-radius: 10px;
                font-weight: bold;
                font-size: 16px;
                width: 100%;
            }
            .section {
                border-top: 1px solid #eee;
                margin-top: 28px;
                padding-top: 24px;
            }
            details.section summary {
                cursor: pointer;
                color: #6b7280;
                font-size: 14px;
                font-weight: 700;
                list-style: none;
            }
            details.section summary::-webkit-details-marker {
                display: none;
            }
            details.section summary::after {
                content: " +";
            }
            details.section[open] summary::after {
                content: " -";
            }
            .hint {
                color: #6b7280;
                font-size: 14px;
                line-height: 1.5;
            }
            .subtitle {
                color: #4b5563;
                font-size: 16px;
                line-height: 1.55;
                margin: 12px 0 22px;
            }
            .install-link {
                margin: 0 0 20px;
            }
            a {
                color: #4f46e5;
                font-weight: bold;
            }
            @media (min-width: 760px) {
                body {
                    padding: 40px;
                }
                .container {
                    min-height: auto;
                    padding: 34px;
                    border-radius: 16px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                }
                button {
                    width: auto;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="brand">
                <div class="brand-mark">H</div>
                <h1>H-Music</h1>
                <p class="hint">Parent App</p>
            </div>
            <p class="subtitle">Access your child's lessons, messages, reschedule requests, and account history.</p>
            <p class="install-link"><a href="/app_install">Install on phone</a></p>

            <form method="POST">
                Parent Email:<br>
                <input name="parent_email" required>

                Password:<br>
                <input type="password" name="password" required>

                <button type="submit">Login</button>
            </form>

            <details class="section">
                <summary>Legacy login</summary>
                <form method="POST">
                    Student Name:<br>
                    <input name="student_name">

                    Parent Email:<br>
                    <input name="parent_email">

                    <button type="submit">Login with Student</button>
                </form>
            </details>

            <br>
        </div>
    </body>
    </html>
    """


@app.route("/parent_dashboard")
def parent_dashboard():
    if not require_parent():
        return redirect("/parent_login")

    ensure_v27_schema()

    parent_id = session.get("parent_id")
    unread_messages = get_unread_message_count("parent", parent_id) if parent_id else 0
    message_label = f"Messages ({unread_messages})" if unread_messages else "Messages"
    linked_students = get_parent_students(parent_id) if parent_id else []

    requested_student = request.args.get("student_name")
    current_student = session.get("parent_student_name")

    if requested_student and parent_can_access_student(parent_id, requested_student):
        current_student = requested_student
        session["parent_student_name"] = current_student

    if not current_student and linked_students:
        current_student = linked_students[0][0]
        session["parent_student_name"] = current_student

    if not current_student:
        return """
        <h1>No linked student found</h1>
        <p>Please ask the owner to link this parent profile to a student.</p>
        <p><a href="/parent_logout">Logout</a></p>
        """

    if parent_id and not parent_can_access_student(parent_id, current_student):
        session.pop("parent_student_name", None)
        return redirect("/parent_dashboard")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, teacher, parent_email, lessons_left
    FROM students
    WHERE name = ?
    """, (current_student,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        session.clear()
        return redirect("/parent_login")

    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT lesson_date, lesson_time, teacher, classroom, status
    FROM schedule
    WHERE student_name = ?
    AND lesson_date >= ?
    AND (status IS NULL OR status='scheduled')
    ORDER BY lesson_date, lesson_time
    LIMIT 10
    """, (current_student, today))
    upcoming_lessons = cursor.fetchall()

    cursor.execute("""
    SELECT lesson_date, lesson_content, performance, homework
    FROM lessons
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 10
    """, (current_student,))
    lesson_history = cursor.fetchall()

    cursor.execute("""
    SELECT id, amount, status, invoice_type, created_at
    FROM invoices
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 10
    """, (current_student,))
    invoices = cursor.fetchall()

    cursor.execute("""
    SELECT payment_date, amount, lessons_added, payment_method
    FROM payments
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 10
    """, (current_student,))
    payments = cursor.fetchall()

    cursor.execute("""
    SELECT entry_type, amount, description, created_at
    FROM student_ledger
    WHERE student_name = ?
    ORDER BY id DESC
    LIMIT 10
    """, (current_student,))
    ledger_entries = cursor.fetchall()

    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM student_ledger
    WHERE student_name = ?
    """, (current_student,))
    balance = cursor.fetchone()[0]

    activity_entries = []
    if parent_id:
        cursor.execute("""
        SELECT student_name, action_type, description, created_at
        FROM parent_activity_logs
        WHERE parent_id = ?
        ORDER BY id DESC
        LIMIT 10
        """, (parent_id,))
        activity_entries = cursor.fetchall()

    conn.close()

    student_tabs = ""
    if linked_students:
        for linked in linked_students:
            active = "active" if linked[0] == current_student else ""
            student_tabs += f"""
            <a class="student-tab {active}" href="/parent_dashboard?student_name={linked[0]}">{linked[0]}</a>
            """

    upcoming_rows = ""
    for l in upcoming_lessons:
        upcoming_rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td>{l[1]}</td>
            <td>{l[2]}</td>
            <td>{l[3]}</td>
            <td>{l[4] or "scheduled"}</td>
        </tr>
        """

    if not upcoming_rows:
        upcoming_rows = "<tr><td colspan='5'>No upcoming lessons.</td></tr>"

    lesson_rows = ""
    for l in lesson_history:
        lesson_rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td>{l[1]}</td>
            <td>{l[2]}</td>
            <td>{l[3]}</td>
        </tr>
        """

    if not lesson_rows:
        lesson_rows = "<tr><td colspan='4'>No lesson history.</td></tr>"

    invoice_rows = ""
    for inv in invoices:
        action = "Paid"
        if inv[2] != "paid":
            action = "Pending"

        invoice_rows += f"""
        <tr>
            <td>{inv[0]}</td>
            <td>${inv[1]}</td>
            <td>{inv[2]}</td>
            <td>{inv[3]}</td>
            <td>{inv[4]}</td>
            <td>{action}</td>
        </tr>
        """

    if not invoice_rows:
        invoice_rows = "<tr><td colspan='6'>No invoices.</td></tr>"

    payment_rows = ""
    for p in payments:
        payment_rows += f"""
        <tr>
            <td>{p[0]}</td>
            <td>${p[1]}</td>
            <td>{p[2]}</td>
            <td>{p[3]}</td>
        </tr>
        """

    if not payment_rows:
        payment_rows = "<tr><td colspan='4'>No payments.</td></tr>"

    ledger_rows = ""
    for e in ledger_entries:
        ledger_rows += f"""
        <tr>
            <td>{e[3]}</td>
            <td>{e[0]}</td>
            <td>${e[1]}</td>
            <td>{e[2]}</td>
        </tr>
        """

    if not ledger_rows:
        ledger_rows = "<tr><td colspan='4'>No ledger entries.</td></tr>"

    activity_rows = ""
    for a in activity_entries:
        activity_rows += f"""
        <tr>
            <td>{a[3]}</td>
            <td>{a[0]}</td>
            <td>{a[1]}</td>
            <td>{a[2]}</td>
        </tr>
        """

    if not activity_rows:
        activity_rows = "<tr><td colspan='4'>No parent activity yet.</td></tr>"

    return f"""
    <html>
    <head>
        {parent_app_meta("H-Music Parent App")}
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f7f7fb;
                margin: 0;
                color: #111827;
            }}
            .container {{
                background: white;
                min-height: 100vh;
                padding: max(22px, env(safe-area-inset-top)) 18px calc(96px + env(safe-area-inset-bottom));
                max-width: 1180px;
                margin: 0 auto;
            }}
            .top {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 16px;
                margin-bottom: 18px;
            }}
            .top h1 {{
                font-size: 32px;
                line-height: 1.05;
                margin: 0 0 8px;
            }}
            .top p {{
                margin: 0;
                color: #6b7280;
            }}
            .top-links {{
                display: flex;
                gap: 10px;
                align-items: center;
            }}
            .student-tabs {{
                margin: 18px 0 10px;
                white-space: nowrap;
                overflow-x: auto;
                padding-bottom: 4px;
            }}
            .student-tab {{
                display: inline-block;
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 999px;
                margin-right: 8px;
                text-decoration: none;
                color: #111827;
                font-weight: bold;
            }}
            .student-tab.active {{
                background: #4f46e5;
                color: white;
                border-color: #4f46e5;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin: 25px 0;
            }}
            .card {{
                background: #f5f5ff;
                padding: 18px;
                border-radius: 8px;
                border: 1px solid #ddd;
            }}
            .label {{
                color: #666;
                font-size: 14px;
            }}
            .value {{
                font-size: 24px;
                font-weight: bold;
                margin-top: 8px;
                overflow-wrap: anywhere;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0 35px;
            }}
            th {{
                background: #eeeeff;
                padding: 10px;
                border: 1px solid #ddd;
            }}
            td {{
                padding: 10px;
                border: 1px solid #ddd;
            }}
            .actions {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin: 20px 0 30px;
            }}
            a.button {{
                display: inline-block;
                background: #4f46e5;
                color: white;
                padding: 10px 16px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
            }}
            button.install-button {{
                background: #111827;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 12px;
                font-weight: 800;
            }}
            a {{
                color: #4f46e5;
                font-weight: bold;
            }}
            .parent-bottom-nav {{
                position: fixed;
                left: 0;
                right: 0;
                bottom: 0;
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 4px;
                padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
                background: rgba(255, 255, 255, 0.96);
                border-top: 1px solid #e5e7eb;
                box-shadow: 0 -4px 18px rgba(0,0,0,0.08);
                z-index: 20;
            }}
            .parent-bottom-nav a {{
                text-align: center;
                text-decoration: none;
                color: #6b7280;
                font-size: 12px;
                font-weight: 800;
                padding: 9px 4px;
                border-radius: 8px;
            }}
            .parent-bottom-nav a.active {{
                color: #4f46e5;
                background: #eef2ff;
            }}
            @media (max-width: 760px) {{
                .top {{
                    align-items: flex-start;
                }}
                .cards {{
                    grid-template-columns: 1fr 1fr;
                    gap: 10px;
                    margin: 18px 0;
                }}
                .card {{
                    padding: 14px;
                }}
                .card:nth-child(4) {{
                    grid-column: 1 / -1;
                }}
                .value {{
                    font-size: 20px;
                }}
                table {{
                    display: block;
                    overflow-x: auto;
                    font-size: 12px;
                }}
                .actions {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                }}
                a.button {{
                    text-align: center;
                    margin: 0;
                }}
            }}
            @media (min-width: 900px) {{
                body {{
                    padding: 32px;
                }}
                .container {{
                    min-height: auto;
                    border-radius: 16px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                    padding: 32px;
                }}
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <div class="top">
                <div>
                    <h1>Parent Pro - {student[0]}</h1>
                    <p>Welcome, {session.get("parent_name", "Parent")}</p>
                </div>
                <div class="top-links">
                    <button class="install-button" data-install-app hidden onclick="installParentApp()">Install App</button>
                    <a href="/app_install">App Help</a>
                    <a href="/parent_logout">Logout</a>
                </div>
            </div>

            <div class="student-tabs">
                {student_tabs}
            </div>

            <div class="cards">
                <div class="card">
                    <div class="label">Teacher</div>
                    <div class="value">{student[1]}</div>
                </div>

                <div class="card">
                    <div class="label">Lessons Left</div>
                    <div class="value">{student[3]}</div>
                </div>

                <div class="card">
                    <div class="label">Ledger Balance</div>
                    <div class="value">${balance}</div>
                </div>

                <div class="card">
                    <div class="label">Parent Email</div>
                    <div class="value" style="font-size:15px;">{student[2]}</div>
                </div>
            </div>

            <div class="actions">
                <a class="button" href="/parent_cancel">Cancel Lesson</a>
                <a class="button" href="/parent_reschedule">Reschedule Lesson</a>
                <a class="button" href="/parent_messages">{message_label}</a>
                <a class="button" href="/parent_profile">Parent Profile</a>
                <a class="button" href="/student_ledger/{student[0]}">Full Ledger</a>
            </div>

            <h2>Upcoming Lessons</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Teacher</th>
                    <th>Room</th>
                    <th>Status</th>
                </tr>
                {upcoming_rows}
            </table>

            <h2>Invoices</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Type</th>
                    <th>Created</th>
                    <th>Action</th>
                </tr>
                {invoice_rows}
            </table>

            <h2>Payments</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Lessons Added</th>
                    <th>Method</th>
                </tr>
                {payment_rows}
            </table>

            <h2>Recent Ledger</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Description</th>
                </tr>
                {ledger_rows}
            </table>

            <h2>Parent Activity</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Student</th>
                    <th>Action</th>
                    <th>Description</th>
                </tr>
                {activity_rows}
            </table>

            <h2>Lesson History</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Lesson Content</th>
                    <th>Performance</th>
                    <th>Homework</th>
                </tr>
                {lesson_rows}
            </table>

        </div>
        {parent_bottom_nav("home")}
    </body>
    </html>
    """


@app.route("/parent_profile", methods=["GET", "POST"])
def parent_profile():
    if not require_parent():
        return redirect("/parent_login")

    ensure_v27_schema()

    parent_id = session.get("parent_id")

    if not parent_id:
        return """
        <h1>Legacy Parent Session</h1>
        <p>Please log in with a Parent Pro account to edit parent profile details.</p>
        <p><a href="/parent_dashboard">Back to Parent Dashboard</a></p>
        """

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        password = request.form.get("password")

        cursor.execute("""
        UPDATE parent_profiles
        SET parent_name = ?,
            phone = ?,
            password = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            parent_name,
            phone,
            password,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            parent_id
        ))

        conn.commit()
        conn.close()

        session["parent_name"] = parent_name
        log_parent_activity(parent_id, session.get("parent_student_name"), "profile_update", "Parent profile updated.")

        return redirect("/parent_profile")

    cursor.execute("""
    SELECT parent_name, email, phone, password
    FROM parent_profiles
    WHERE id = ?
    """, (parent_id,))

    profile = cursor.fetchone()

    cursor.execute("""
    SELECT student_name, relationship
    FROM parent_students
    WHERE parent_id = ?
    AND active = 1
    ORDER BY student_name
    """, (parent_id,))

    linked = cursor.fetchall()
    conn.close()

    linked_rows = ""
    for item in linked:
        linked_rows += f"<tr><td>{item[0]}</td><td>{item[1]}</td></tr>"

    if not linked_rows:
        linked_rows = "<tr><td colspan='2'>No linked students.</td></tr>"

    return f"""
    <html>
    <head>
        {parent_app_meta("Parent Profile")}
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f7f7fb;
                margin: 0;
                color: #111827;
            }}
            .container {{
                background: white;
                padding: max(22px, env(safe-area-inset-top)) 18px calc(96px + env(safe-area-inset-bottom));
                min-height: 100vh;
                max-width: 760px;
                margin: 0 auto;
            }}
            h1 {{
                font-size: 30px;
                margin: 0 0 22px;
            }}
            input {{
                width: 100%;
                min-height: 48px;
                padding: 12px 14px;
                margin: 8px 0 18px;
                font-size: 16px;
                border: 1px solid #d1d5db;
                border-radius: 10px;
            }}
            button, a.button {{
                display: inline-block;
                background: #4f46e5;
                color: white;
                border: none;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: bold;
                text-decoration: none;
                min-height: 48px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 14px;
            }}
            th, td {{
                padding: 10px;
                border: 1px solid #ddd;
                text-align: left;
            }}
            th {{
                background: #eeeeff;
            }}
            .form-actions {{
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }}
            .parent-bottom-nav {{
                position: fixed;
                left: 0;
                right: 0;
                bottom: 0;
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 4px;
                padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
                background: rgba(255, 255, 255, 0.96);
                border-top: 1px solid #e5e7eb;
                box-shadow: 0 -4px 18px rgba(0,0,0,0.08);
                z-index: 20;
            }}
            .parent-bottom-nav a {{
                text-align: center;
                text-decoration: none;
                color: #6b7280;
                font-size: 12px;
                font-weight: 800;
                padding: 9px 4px;
                border-radius: 8px;
            }}
            .parent-bottom-nav a.active {{
                color: #4f46e5;
                background: #eef2ff;
            }}
            @media (max-width: 760px) {{
                table {{
                    display: block;
                    overflow-x: auto;
                    font-size: 12px;
                }}
                .form-actions {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                }}
                .form-actions button,
                .form-actions a {{
                    text-align: center;
                }}
            }}
            @media (min-width: 900px) {{
                body {{
                    padding: 32px;
                }}
                .container {{
                    min-height: auto;
                    padding: 32px;
                    border-radius: 16px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Parent Profile</h1>

            <form method="POST">
                Parent Name:<br>
                <input name="parent_name" value="{profile[0] or ''}">

                Email:<br>
                <input value="{profile[1] or ''}" disabled>

                Phone:<br>
                <input name="phone" value="{profile[2] or ''}">

                Password:<br>
                <input name="password" value="{profile[3] or ''}">

                <div class="form-actions">
                    <button type="submit">Save Profile</button>
                    <a class="button" href="/parent_dashboard">Back</a>
                </div>
            </form>

            <h2>Linked Students</h2>
            <table>
                <tr>
                    <th>Student</th>
                    <th>Relationship</th>
                </tr>
                {linked_rows}
            </table>
        </div>
        {parent_bottom_nav("profile")}
    </body>
    </html>
    """


@app.route("/parent_logout")
def parent_logout():
    session.pop("parent_id", None)
    session.pop("parent_name", None)
    session.pop("parent_email", None)
    session.pop("parent_student_name", None)
    return redirect("/parent_login")

@app.route("/executive_dashboard")
def executive_dashboard():

    if not require_owner():
        return redirect("/owner_login")

    selected_month = request.args.get("month")

    if not selected_month:
        selected_month = date.today().strftime("%Y-%m")

    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("SELECT key, value FROM settings")
    settings = {row[0]: row[1] for row in cursor.fetchall()}

    lesson_rate = float(settings.get("default_lesson_rate", 50))

    # Core student metrics
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM students
    WHERE lessons_left > 0
    """)
    active_students = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM students
    WHERE lessons_left <= 2
    """)
    low_balance_count = cursor.fetchone()[0] or 0

    # Revenue from payments
    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM payments
    WHERE payment_date LIKE ?
    """, (selected_month + "%",))
    payment_revenue = cursor.fetchone()[0] or 0

    # Unpaid invoices
    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM invoices
    WHERE status = 'unpaid'
    """)
    unpaid_invoice_total = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM invoices
    WHERE status = 'unpaid'
    """)
    unpaid_invoice_count = cursor.fetchone()[0] or 0

    # Today metrics
    cursor.execute("""
    SELECT COUNT(*)
    FROM schedule
    WHERE lesson_date = ?
    """, (today,))
    today_lessons = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM schedule
    WHERE lesson_date = ?
    AND status = 'present'
    """, (today,))
    today_completed = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT COUNT(*)
    FROM schedule
    WHERE lesson_date = ?
    AND status IN ('no_show', 'cancel_3h', 'cancel_12h', 'cancel_24h')
    """, (today,))
    today_issue_count = cursor.fetchone()[0] or 0

    # Monthly payroll / margin by teacher
    cursor.execute("""
    SELECT
        s.teacher,
        COALESCE(SUM(s.charge_lessons), 0),
        COALESCE(t.hourly_rate, 30)
    FROM schedule s
    LEFT JOIN teachers t
        ON s.teacher = t.teacher_name
    WHERE s.status IN ('present', 'no_show', 'cancel_3h', 'cancel_12h', 'cancel_24h')
    AND s.lesson_date LIKE ?
    GROUP BY s.teacher, t.hourly_rate
    ORDER BY s.teacher
    """, (selected_month + "%",))

    teacher_rows = cursor.fetchall()

    total_units = 0
    total_revenue = 0
    total_payroll = 0

    teacher_html = ""

    for row in teacher_rows:
        teacher = row[0]
        units = row[1] or 0
        teacher_rate = row[2] or 30

        revenue = units * lesson_rate
        payroll = units * teacher_rate
        margin = revenue - payroll
        margin_pct = 0
        if revenue > 0:
            margin_pct = round((margin / revenue) * 100, 1)

        total_units += units
        total_revenue += revenue
        total_payroll += payroll

        teacher_html += f"""
        <tr>
            <td><a href="/payroll/{teacher}?month={selected_month}">{teacher}</a></td>
            <td>{units}</td>
            <td>${teacher_rate}</td>
            <td>${revenue}</td>
            <td>${payroll}</td>
            <td>${margin}</td>
            <td>{margin_pct}%</td>
        </tr>
        """

    if not teacher_html:
        teacher_html = "<tr><td colspan='7'>No payroll data for this month.</td></tr>"

    total_margin = total_revenue - total_payroll
    total_margin_pct = 0
    if total_revenue > 0:
        total_margin_pct = round((total_margin / total_revenue) * 100, 1)

    # Low balance students
    cursor.execute("""
    SELECT name, lessons_left, parent_email
    FROM students
    WHERE lessons_left <= 2
    ORDER BY lessons_left ASC
    LIMIT 10
    """)
    low_students = cursor.fetchall()

    low_students_html = ""
    for s in low_students:
        low_students_html += f"""
        <tr>
            <td><a href="/student/{s[0]}">{s[0]}</a></td>
            <td>{s[1]}</td>
            <td>{s[2]}</td>
        </tr>
        """

    if not low_students_html:
        low_students_html = "<tr><td colspan='3'>No low balance students.</td></tr>"

    # Unpaid invoice table
    cursor.execute("""
    SELECT id, student_name, amount, invoice_type, created_at
    FROM invoices
    WHERE status = 'unpaid'
    ORDER BY id DESC
    LIMIT 10
    """)
    unpaid_invoices = cursor.fetchall()

    unpaid_html = ""
    for inv in unpaid_invoices:
        unpaid_html += f"""
        <tr>
            <td>{inv[0]}</td>
            <td><a href="/student/{inv[1]}">{inv[1]}</a></td>
            <td>${inv[2]}</td>
            <td>{inv[3]}</td>
            <td>{inv[4]}</td>
            <td><a href="/pay_invoice/{inv[0]}">Mark Paid</a></td>
        </tr>
        """

    if not unpaid_html:
        unpaid_html = "<tr><td colspan='6'>No unpaid invoices.</td></tr>"

    # Today's schedule
    cursor.execute("""
    SELECT lesson_time, student_name, teacher, classroom, status
    FROM schedule
    WHERE lesson_date = ?
    ORDER BY lesson_time
    """, (today,))
    today_schedule = cursor.fetchall()

    today_rows = ""
    for l in today_schedule:
        today_rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td><a href="/student/{l[1]}">{l[1]}</a></td>
            <td>{l[2]}</td>
            <td>{l[3]}</td>
            <td>{l[4] or "scheduled"}</td>
        </tr>
        """

    if not today_rows:
        today_rows = "<tr><td colspan='5'>No lessons today.</td></tr>"

    conn.close()

    return f"""
    <html>
    <head>
        <title>Executive Dashboard Pro</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                max-width: 1250px;
                margin: auto;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
            }}
            .header p {{
                color: #666;
                margin-top: 6px;
            }}
            .card-grid {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin-bottom: 25px;
            }}
            .card {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                border: 1px solid #e5e7eb;
            }}
            .label {{
                color: #666;
                font-size: 14px;
            }}
            .value {{
                font-size: 28px;
                font-weight: bold;
                margin-top: 8px;
            }}
            .sub {{
                color: #777;
                font-size: 13px;
                margin-top: 5px;
            }}
            .section {{
                background: white;
                padding: 25px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                margin-bottom: 25px;
            }}
            .two-col {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}
            th {{
                background: #eeeeff;
                padding: 10px;
                border: 1px solid #ddd;
            }}
            td {{
                padding: 10px;
                border: 1px solid #ddd;
            }}
            input, button {{
                padding: 8px;
                font-size: 14px;
            }}
            button {{
                background: #5b5cff;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            a.button {{
                display: inline-block;
                margin-right: 10px;
                background: #5b5cff;
                color: white;
                padding: 10px 16px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: bold;
            }}
            a {{
                color: #5b5cff;
                font-weight: bold;
            }}
            .danger {{
                color: #b00020;
            }}
            .good {{
                color: #137333;
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <div class="header">
                <div>
                    <h1>Executive Dashboard Pro</h1>
                    <p>Owner command center for H-Music operations</p>
                </div>

                <div>
                    <a class="button" href="/">Home</a>
                    <a class="button" href="/payroll?month={selected_month}">Payroll</a>
                    <a class="button" href="/invoices">Invoices</a>
                    <a class="button" href="/calendar">Calendar</a>
                </div>
            </div>

            <form method="GET">
                Month:
                <input type="month" name="month" value="{selected_month}">
                <button type="submit">View</button>
            </form>

            <h2>Business Snapshot</h2>
            <div class="card-grid">
                <div class="card">
                    <div class="label">Total Students</div>
                    <div class="value">{total_students}</div>
                    <div class="sub">All students in CRM</div>
                </div>

                <div class="card">
                    <div class="label">Active Students</div>
                    <div class="value">{active_students}</div>
                    <div class="sub">Lessons left above 0</div>
                </div>

                <div class="card">
                    <div class="label">Need Renewal</div>
                    <div class="value danger">{low_balance_count}</div>
                    <div class="sub">Students with ≤ 2 lessons</div>
                </div>

                <div class="card">
                    <div class="label">Unpaid Invoices</div>
                    <div class="value danger">{unpaid_invoice_count}</div>
                    <div class="sub">${unpaid_invoice_total} outstanding</div>
                </div>
            </div>

            <h2>Monthly Finance</h2>
            <div class="card-grid">
                <div class="card">
                    <div class="label">Payment Revenue</div>
                    <div class="value">${payment_revenue}</div>
                    <div class="sub">Actual received this month</div>
                </div>

                <div class="card">
                    <div class="label">Earned Revenue</div>
                    <div class="value">${total_revenue}</div>
                    <div class="sub">Based on completed/charged units</div>
                </div>

                <div class="card">
                    <div class="label">Payroll</div>
                    <div class="value">${total_payroll}</div>
                    <div class="sub">Estimated teacher pay</div>
                </div>

                <div class="card">
                    <div class="label">Gross Margin</div>
                    <div class="value good">${total_margin}</div>
                    <div class="sub">{total_margin_pct}% margin</div>
                </div>
            </div>

            <h2>Today</h2>
            <div class="card-grid">
                <div class="card">
                    <div class="label">Today's Lessons</div>
                    <div class="value">{today_lessons}</div>
                </div>

                <div class="card">
                    <div class="label">Completed Today</div>
                    <div class="value">{today_completed}</div>
                </div>

                <div class="card">
                    <div class="label">Today's Issues</div>
                    <div class="value danger">{today_issue_count}</div>
                    <div class="sub">No shows / late cancels</div>
                </div>

                <div class="card">
                    <div class="label">Paid Lesson Units</div>
                    <div class="value">{total_units}</div>
                    <div class="sub">Selected month</div>
                </div>
            </div>

            <div class="section">
                <h2>Teacher Profitability</h2>
                <table>
                    <tr>
                        <th>Teacher</th>
                        <th>Units</th>
                        <th>Teacher Rate</th>
                        <th>Earned Revenue</th>
                        <th>Payroll</th>
                        <th>Margin</th>
                        <th>Margin %</th>
                    </tr>
                    {teacher_html}
                </table>
            </div>

            <div class="section">
                <h2>Today's Schedule</h2>
                <table>
                    <tr>
                        <th>Time</th>
                        <th>Student</th>
                        <th>Teacher</th>
                        <th>Room</th>
                        <th>Status</th>
                    </tr>
                    {today_rows}
                </table>
            </div>

            <div class="two-col">
                <div class="section">
                    <h2>Action Required: Low Lesson Balance</h2>
                    <table>
                        <tr>
                            <th>Student</th>
                            <th>Lessons Left</th>
                            <th>Parent Email</th>
                        </tr>
                        {low_students_html}
                    </table>
                </div>

                <div class="section">
                    <h2>Action Required: Unpaid Invoices</h2>
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>Student</th>
                            <th>Amount</th>
                            <th>Type</th>
                            <th>Action</th>
                        </tr>
                        {unpaid_html}
                    </table>
                </div>
            </div>

        </div>
    </body>
    </html>
    """
@app.route("/owner_dashboard")
def owner_dashboard():
    if not require_owner():
        return redirect("/owner_login")
    return redirect("/")


@app.route("/owner_login", methods=["GET", "POST"])
def owner_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        SELECT username, role, display_name
        FROM users
        WHERE username = ?
        AND password = ?
        AND role = 'owner'
        """, (username, password))

        user = cursor.fetchone()
        conn.close()

        if user:
            session.clear()
            session["user_role"] = user[1]
            session["username"] = user[0]
            session["display_name"] = user[2]
            return redirect("/executive_dashboard")

        return """
        <h2>Login Failed</h2>
        <p>Please check your username and password.</p>
        <a href="/owner_login">Try Again</a>
        """

    return """
    <h1>Owner Login</h1>

    <form method="POST">
        Username:<br>
        <input name="username"><br><br>

        Password:<br>
        <input type="password" name="password"><br><br>

        <button type="submit">Login</button>
    </form>
    """


@app.route("/owner_logout")
def owner_logout():
    session.clear()
    return redirect("/owner_login")

def ensure_v145_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS renewal_email_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        parent_email TEXT,
        lessons_left REAL,
        sent_at TEXT,
        status TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sub_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER,
        teacher_name TEXT,
        student_name TEXT,
        lesson_date TEXT,
        lesson_time TEXT,
        classroom TEXT,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        substitute_teacher TEXT,
        created_at TEXT,
        assigned_at TEXT
    )
    """)

    conn.commit()
    conn.close()


@app.route("/v145_setup")
def v145_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v145_schema()

    return """
    <h1>V14.5 Setup Complete</h1>
    <p>Renewal Email + Sub Request tables are ready.</p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/renewal_emails")
def renewal_emails():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v145_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, parent_email, lessons_left
    FROM students
    WHERE lessons_left <=2
    ORDER BY lessons_left ASC
    """)

    students = cursor.fetchall()
    conn.close()

    rows = ""

    for s in students:
        rows += f"""
        <tr>
            <td><a href="/student/{s[0]}">{s[0]}</a></td>
            <td>{s[1]}</td>
            <td>{s[2]}</td>
            <td>
                <a href="/send_renewal_email/{s[0]}">
                    Send Renewal Email
                </a>
            </td>
        </tr>
        """

    return f"""
    <h1>Auto Renewal Email Queue</h1>
    <p>Students with 2 or fewer lessons left.</p>

    <table border="1" cellpadding="8">
        <tr>
            <th>Student</th>
            <th>Parent Email</th>
            <th>Lessons Left</th>
            <th>Action</th>
        </tr>
        {rows}
    </table>

    <br>
    <a href="/">Back Home</a>
    <a href="/executive_dashboard">Executive Dashboard</a>
    """


@app.route("/send_renewal_email/<student_name>")
def send_renewal_email(student_name):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v145_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, parent_email, lessons_left
    FROM students
    WHERE name = ?
    """, (student_name,))

    student = cursor.fetchone()

    if not student:
        conn.close()
        return "<h1>Student not found</h1>"

    name = student[0]
    parent_email = student[1]
    lessons_left = student[2]

    email_text = f"""
Dear Parent,

This is a friendly reminder that {name} currently has {lessons_left} lesson(s) remaining.

To avoid any interruption in scheduling, please renew the lesson package when convenient.

Thank you,
H-Music
"""

    msg = EmailMessage()
    msg["Subject"] = f"{name}'s Lesson Package Renewal Reminder"
    msg["From"] = "huangzhenwei606@gmail.com"
    msg["To"] = parent_email
    msg.set_content(email_text)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            "huangzhenwei606@gmail.com",
            os.getenv("GMAIL_APP_PASSWORD")
        )
        smtp.send_message(msg)

    cursor.execute("""
    INSERT INTO renewal_email_logs (
        student_name,
        parent_email,
        lessons_left,
        sent_at,
        status
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        parent_email,
        lessons_left,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sent"
    ))

    conn.commit()
    conn.close()

    return f"""
    <h1>Renewal Email Sent</h1>
    <p>Student: {name}</p>
    <p>To: {parent_email}</p>
    <pre>{email_text}</pre>
    <p><a href="/renewal_emails">Back to Renewal Queue</a></p>
    """


@app.route("/teacher_sub_request", methods=["GET", "POST"])
def teacher_sub_request():
    if not require_teacher():
        return redirect("/teacher_login")

    ensure_v145_schema()

    teacher_name = session.get("teacher_name")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        schedule_id = request.form.get("schedule_id")
        reason = request.form.get("reason")

        cursor.execute("""
        SELECT id, student_name, lesson_date, lesson_time, classroom
        FROM schedule
        WHERE id = ?
        AND teacher = ?
        """, (schedule_id, teacher_name))

        lesson = cursor.fetchone()

        if not lesson:
            conn.close()
            return "<h1>Lesson not found</h1>"

        cursor.execute("""
        INSERT INTO sub_requests (
            schedule_id,
            teacher_name,
            student_name,
            lesson_date,
            lesson_time,
            classroom,
            reason,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lesson[0],
            teacher_name,
            lesson[1],
            lesson[2],
            lesson[3],
            lesson[4],
            reason,
            "pending",
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        conn.commit()
        conn.close()

        return """
        <h1>Sub Request Submitted</h1>
        <p>Owner will review and assign a substitute teacher.</p>
        <p><a href="/teacher_dashboard">Back to Teacher Dashboard</a></p>
        """

    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT id, lesson_date, lesson_time, student_name, classroom
    FROM schedule
    WHERE teacher = ?
    AND lesson_date >= ?
    ORDER BY lesson_date, lesson_time
    LIMIT 30
    """, (teacher_name, today))

    lessons = cursor.fetchall()
    conn.close()

    rows = ""

    for l in lessons:
        rows += f"""
        <form method="POST" style="border:1px solid #ddd; padding:15px; margin:12px 0;">
            <p><b>{l[1]} {l[2]}</b></p>
            <p>Student: {l[3]}</p>
            <p>Room: {l[4]}</p>

            <input type="hidden" name="schedule_id" value="{l[0]}">

            Reason:<br>
            <input name="reason" style="width:300px;"><br><br>

            <button type="submit">Request Substitute</button>
        </form>
        """

    return f"""
    <h1>Teacher Sub Request</h1>
    <p>Teacher: {teacher_name}</p>

    {rows}

    <p><a href="/teacher_dashboard">Back to Teacher Dashboard</a></p>
    """


@app.route("/owner_sub_requests")
def owner_sub_requests():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v145_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)
    teachers = cursor.fetchall()

    teacher_options = ""
    for t in teachers:
        teacher_options += f"<option value='{t[0]}'>{t[0]}</option>"

    cursor.execute("""
    SELECT
        id,
        teacher_name,
        student_name,
        lesson_date,
        lesson_time,
        classroom,
        reason,
        status,
        substitute_teacher
    FROM sub_requests
    ORDER BY id DESC
    """)

    requests = cursor.fetchall()
    conn.close()

    rows = ""

    for r in requests:
        assign_form = ""

        if r[7] == "pending":
            assign_form = f"""
            <form method="POST" action="/assign_sub_request/{r[0]}">
                <select name="substitute_teacher">
                    {teacher_options}
                </select>
                <button type="submit">Assign</button>
            </form>
            """
        else:
            assign_form = f"Assigned to {r[8]}"

        rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td>{r[5]}</td>
            <td>{r[6]}</td>
            <td>{r[7]}</td>
            <td>{assign_form}</td>
        </tr>
        """

    return f"""
    <h1>Owner Sub Requests</h1>

    <table border="1" cellpadding="8">
        <tr>
            <th>ID</th>
            <th>Original Teacher</th>
            <th>Student</th>
            <th>Date</th>
            <th>Time</th>
            <th>Room</th>
            <th>Reason</th>
            <th>Status</th>
            <th>Assign</th>
        </tr>
        {rows}
    </table>

    <br>
    <a href="/">Back Home</a>
    <a href="/executive_dashboard">Executive Dashboard</a>
    """


@app.route("/assign_sub_request/<int:request_id>", methods=["POST"])
def assign_sub_request(request_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v145_schema()

    substitute_teacher = request.form.get("substitute_teacher")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT schedule_id
    FROM sub_requests
    WHERE id = ?
    """, (request_id,))

    result = cursor.fetchone()

    if not result:
        conn.close()
        return "<h1>Sub request not found</h1>"

    schedule_id = result[0]

    cursor.execute("""
    UPDATE schedule
    SET teacher = ?
    WHERE id = ?
    """, (substitute_teacher, schedule_id))

    cursor.execute("""
    UPDATE sub_requests
    SET status = ?,
        substitute_teacher = ?,
        assigned_at = ?
    WHERE id = ?
    """, (
        "assigned",
        substitute_teacher,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request_id
    ))

    conn.commit()
    conn.close()

    return redirect("/owner_sub_requests")

# =========================
# V17 Inquiry CRM - FULL
# =========================

def ensure_v17_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        parent_name TEXT,
        parent_email TEXT,
        phone TEXT,
        age TEXT,
        instrument TEXT,
        source TEXT,
        status TEXT DEFAULT 'Inquiry',
        trial_date TEXT,
        trial_time TEXT,
        trial_teacher TEXT,
        notes TEXT,
        converted_student_name TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


@app.route("/v17_setup")
def v17_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v17_schema()

    return """
    <h1>V17 Inquiry CRM Setup Complete</h1>
    <p>Inquiry CRM tables are ready.</p>
    <p><a href="/inquiries">Go to Inquiry CRM</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/inquiries")
def inquiries():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v17_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    statuses = [
        "Inquiry",
        "Trial Scheduled",
        "Trial Completed",
        "Active Student",
        "Inactive"
    ]

    counts = {}

    for status in statuses:
        cursor.execute("""
        SELECT COUNT(*)
        FROM inquiries
        WHERE status = ?
        """, (status,))
        counts[status] = cursor.fetchone()[0]

    cursor.execute("""
    SELECT
        id,
        student_name,
        parent_name,
        phone,
        age,
        instrument,
        source,
        status,
        trial_date,
        trial_teacher,
        created_at
    FROM inquiries
    ORDER BY id DESC
    """)

    rows_data = cursor.fetchall()

    cursor.execute("""
    SELECT COUNT(*)
    FROM inquiries
    """)
    total_inquiries = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COUNT(*)
    FROM inquiries
    WHERE status IN ('Trial Scheduled', 'Trial Completed', 'Active Student')
    """)
    total_trials = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COUNT(*)
    FROM inquiries
    WHERE status = 'Active Student'
    """)
    total_active = cursor.fetchone()[0]

    inquiry_to_trial = 0
    trial_to_active = 0
    overall_conversion = 0

    if total_inquiries > 0:
        inquiry_to_trial = round(total_trials * 100 / total_inquiries, 1)
        overall_conversion = round(total_active * 100 / total_inquiries, 1)

    if total_trials > 0:
        trial_to_active = round(total_active * 100 / total_trials, 1)

    cursor.execute("""
    SELECT
        trial_teacher,
        COUNT(*) as trials,
        SUM(CASE WHEN status = 'Active Student' THEN 1 ELSE 0 END) as converted
    FROM inquiries
    WHERE trial_teacher IS NOT NULL
    AND trial_teacher != ''
    GROUP BY trial_teacher
    ORDER BY trials DESC
    """)

    teacher_rows = cursor.fetchall()

    cursor.execute("""
    SELECT source, COUNT(*)
    FROM inquiries
    GROUP BY source
    ORDER BY COUNT(*) DESC
    """)

    source_rows = cursor.fetchall()

    conn.close()

    cards = ""

    for status in statuses:
        cards += f"""
        <div class="card">
            <div class="label">{status}</div>
            <div class="value">{counts[status]}</div>
        </div>
        """

    rows = ""

    for r in rows_data:
        rows += f"""
        <tr>
            <td><a href="/inquiry/{r[0]}">{r[1]}</a></td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td>{r[5]}</td>
            <td>{r[6]}</td>
            <td><span class="status">{r[7]}</span></td>
            <td>{r[8] or ''}</td>
            <td>{r[9] or ''}</td>
            <td>{r[10]}</td>
        </tr>
        """

    teacher_html = ""

    for t in teacher_rows:
        teacher = t[0]
        trials = t[1] or 0
        converted = t[2] or 0
        rate = 0

        if trials > 0:
            rate = round(converted * 100 / trials, 1)

        teacher_html += f"""
        <tr>
            <td>{teacher}</td>
            <td>{trials}</td>
            <td>{converted}</td>
            <td>{rate}%</td>
        </tr>
        """

    source_html = ""

    for s in source_rows:
        source_html += f"""
        <tr>
            <td>{s[0]}</td>
            <td>{s[1]}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Inquiry CRM</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
                background: #f7f8fc;
                margin: 0;
                color: #111827;
            }}

            .container {{
                max-width: 1300px;
                margin: 0 auto;
                padding: 30px;
            }}

            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }}

            h1 {{
                margin: 0;
                font-size: 30px;
            }}

            .button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 10px;
                text-decoration: none;
                font-weight: 700;
                margin-left: 8px;
            }}

            .cards {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 14px;
                margin-bottom: 20px;
            }}

            .card {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 18px;
            }}

            .label {{
                color: #6b7280;
                font-size: 13px;
                margin-bottom: 8px;
            }}

            .value {{
                font-size: 30px;
                font-weight: 850;
            }}

            .section {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 20px;
                margin-bottom: 20px;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
            }}

            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
                font-size: 14px;
            }}

            th {{
                background: #fafafa;
                font-size: 12px;
                text-transform: uppercase;
                color: #6b7280;
            }}

            .analytics {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 14px;
            }}

            .status {{
                background: #f1efff;
                color: #4f46e5;
                padding: 4px 8px;
                border-radius: 999px;
                font-size: 12px;
                font-weight: 700;
            }}

            @media (max-width: 800px) {{
                .cards,
                .analytics {{
                    grid-template-columns: repeat(2, 1fr);
                }}

                .container {{
                    padding: 14px;
                }}

                table {{
                    font-size: 12px;
                }}
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <div class="header">
                <div>
                    <h1>Inquiry CRM</h1>
                    <p>Inquiry → Trial → Active Student</p>
                </div>

                <div>
                    <a class="button" href="/">Home</a>
                    <a class="button" href="/add_inquiry">Add Inquiry</a>
                </div>
            </div>

            <div class="cards">
                {cards}
            </div>

            <div class="analytics">
                <div class="card">
                    <div class="label">Inquiry → Trial</div>
                    <div class="value">{inquiry_to_trial}%</div>
                </div>

                <div class="card">
                    <div class="label">Trial → Active</div>
                    <div class="value">{trial_to_active}%</div>
                </div>

                <div class="card">
                    <div class="label">Overall Conversion</div>
                    <div class="value">{overall_conversion}%</div>
                </div>
            </div>

            <br>

            <div class="section">
                <h2>Inquiry List</h2>

                <table>
                    <tr>
                        <th>Student</th>
                        <th>Parent</th>
                        <th>Phone</th>
                        <th>Age</th>
                        <th>Instrument</th>
                        <th>Source</th>
                        <th>Status</th>
                        <th>Trial Date</th>
                        <th>Teacher</th>
                        <th>Created</th>
                    </tr>
                    {rows}
                </table>
            </div>

            <div class="section">
                <h2>Teacher Conversion Ranking</h2>

                <table>
                    <tr>
                        <th>Teacher</th>
                        <th>Trials</th>
                        <th>Converted</th>
                        <th>Conversion Rate</th>
                    </tr>
                    {teacher_html}
                </table>
            </div>

            <div class="section">
                <h2>Inquiry Sources</h2>

                <table>
                    <tr>
                        <th>Source</th>
                        <th>Count</th>
                    </tr>
                    {source_html}
                </table>
            </div>

        </div>
    </body>
    </html>
    """


@app.route("/add_inquiry", methods=["GET", "POST"])
def add_inquiry():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v17_schema()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        parent_name = request.form.get("parent_name")
        parent_email = request.form.get("parent_email")
        phone = request.form.get("phone")
        age = request.form.get("age")
        instrument = request.form.get("instrument")
        source = request.form.get("source")
        notes = request.form.get("notes")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO inquiries (
            student_name,
            parent_name,
            parent_email,
            phone,
            age,
            instrument,
            source,
            status,
            notes,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_name,
            parent_name,
            parent_email,
            phone,
            age,
            instrument,
            source,
            "Inquiry",
            notes,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        inquiry_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return redirect(f"/inquiry/{inquiry_id}")

    return """
    <h1>Add Inquiry</h1>

    <form method="POST">

        Student Name:<br>
        <input name="student_name" required><br><br>

        Parent Name:<br>
        <input name="parent_name"><br><br>

        Parent Email:<br>
        <input name="parent_email"><br><br>

        Phone:<br>
        <input name="phone"><br><br>

        Age:<br>
        <input name="age"><br><br>

        Instrument:<br>
        <select name="instrument">
            <option value="Piano">Piano</option>
            <option value="Voice">Voice</option>
            <option value="Guitar">Guitar</option>
            <option value="Violin">Violin</option>
            <option value="Drums">Drums</option>
            <option value="Music Theory">Music Theory</option>
            <option value="Other">Other</option>
        </select><br><br>

        Source:<br>
        <select name="source">
            <option value="Google">Google</option>
            <option value="Referral">Referral</option>
            <option value="Website">Website</option>
            <option value="Wechat">Wechat</option>
            <option value="Walk-in">Walk-in</option>
            <option value="Instagram">Instagram</option>
            <option value="Facebook">Facebook</option>
            <option value="Other">Other</option>
        </select><br><br>

        Notes:<br>
        <textarea name="notes" rows="5" cols="50"></textarea><br><br>

        <button type="submit">Save Inquiry</button>

    </form>

    <br>
    <a href="/inquiries">Back to Inquiry CRM</a>
    """


@app.route("/inquiry/<int:inquiry_id>")
def inquiry_detail(inquiry_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v17_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        parent_name,
        parent_email,
        phone,
        age,
        instrument,
        source,
        status,
        trial_date,
        trial_time,
        trial_teacher,
        notes,
        converted_student_name,
        created_at,
        updated_at
    FROM inquiries
    WHERE id = ?
    """, (inquiry_id,))

    inquiry = cursor.fetchone()

    if not inquiry:
        conn.close()
        return "<h1>Inquiry not found</h1>"

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)

    teachers = cursor.fetchall()
    conn.close()

    teacher_options = ""

    for t in teachers:
        selected = ""
        if inquiry[11] == t[0]:
            selected = "selected"

        teacher_options += f"""
        <option value="{t[0]}" {selected}>{t[0]}</option>
        """

    status_options = ""

    statuses = [
        "Inquiry",
        "Trial Scheduled",
        "Trial Completed",
        "Active Student",
        "Inactive"
    ]

    for s in statuses:
        selected = ""
        if inquiry[8] == s:
            selected = "selected"

        status_options += f"""
        <option value="{s}" {selected}>{s}</option>
        """

    convert_button = ""

    if inquiry[8] != "Active Student":
        convert_button = f"""
        <form method="POST" action="/convert_inquiry_to_student/{inquiry_id}">
            <button type="submit" style="background:#16a34a;color:white;padding:10px 14px;border:none;border-radius:8px;">
                Convert to Active Student
            </button>
        </form>
        """

    return f"""
    <h1>Inquiry Detail</h1>

    <p><a href="/inquiries">Back to Inquiry CRM</a></p>

    <h2>{inquiry[1]}</h2>

    <p><b>Parent:</b> {inquiry[2]}</p>
    <p><b>Email:</b> {inquiry[3]}</p>
    <p><b>Phone:</b> {inquiry[4]}</p>
    <p><b>Age:</b> {inquiry[5]}</p>
    <p><b>Instrument:</b> {inquiry[6]}</p>
    <p><b>Source:</b> {inquiry[7]}</p>
    <p><b>Status:</b> {inquiry[8]}</p>
    <p><b>Created:</b> {inquiry[14]}</p>

    <hr>

    <h2>Edit Inquiry</h2>

    <form method="POST" action="/update_inquiry/{inquiry_id}">

        Student Name:<br>
        <input name="student_name" value="{inquiry[1] or ''}"><br><br>

        Parent Name:<br>
        <input name="parent_name" value="{inquiry[2] or ''}"><br><br>

        Parent Email:<br>
        <input name="parent_email" value="{inquiry[3] or ''}"><br><br>

        Phone:<br>
        <input name="phone" value="{inquiry[4] or ''}"><br><br>

        Age:<br>
        <input name="age" value="{inquiry[5] or ''}"><br><br>

        Instrument:<br>
        <input name="instrument" value="{inquiry[6] or ''}"><br><br>

        Source:<br>
        <input name="source" value="{inquiry[7] or ''}"><br><br>

        Status:<br>
        <select name="status">
            {status_options}
        </select><br><br>

        Trial Date:<br>
        <input type="date" name="trial_date" value="{inquiry[9] or ''}"><br><br>

        Trial Time:<br>
        <input type="time" name="trial_time" value="{inquiry[10] or ''}"><br><br>

        Trial Teacher:<br>
        <select name="trial_teacher">
            <option value="">Select Teacher</option>
            {teacher_options}
        </select><br><br>

        Notes:<br>
        <textarea name="notes" rows="6" cols="60">{inquiry[12] or ''}</textarea><br><br>

        <button type="submit">Update Inquiry</button>

    </form>

    <hr>

    <h2>Convert</h2>

    {convert_button}
    """


@app.route("/update_inquiry/<int:inquiry_id>", methods=["POST"])
def update_inquiry(inquiry_id):

    student_name = request.form.get("student_name")
    parent_email = request.form.get("parent_email")
    phone = request.form.get("phone")
    source = request.form.get("source")
    status = request.form.get("status")

    trial_date = request.form.get("trial_date")
    trial_time = request.form.get("trial_time")
    trial_teacher = request.form.get("trial_teacher")

    notes = request.form.get("notes")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE inquiries
    SET
        student_name=?,
        parent_email=?,
        phone=?,
        source=?,
        status=?,
        trial_date=?,
        trial_time=?,
        trial_teacher=?,
        notes=?
    WHERE id=?
    """, (
        student_name,
        parent_email,
        phone,
        source,
        status,
        trial_date,
        trial_time,
        trial_teacher,
        notes,
        inquiry_id
    ))

    # Trial → Calendar
    if trial_date and trial_time and trial_teacher:

        cursor.execute("""
        SELECT id
        FROM schedule
        WHERE student_name=?
        AND lesson_date=?
        AND lesson_time=?
        """, (
            student_name,
            trial_date,
            trial_time
        ))

        existing = cursor.fetchone()

        if not existing:

            try:

                cursor.execute("""
                INSERT INTO schedule (
                    student_name,
                    teacher,
                    lesson_date,
                    lesson_time,
                    classroom,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    student_name,
                    trial_teacher,
                    trial_date,
                    trial_time,
                    "Trial Room",
                    "scheduled"
                ))

            except Exception as e:
                print("Trial Calendar Error:", e)

    conn.commit()
    conn.close()

    return redirect(f"/inquiry/{inquiry_id}")


@app.route("/convert_inquiry_to_student/<int:inquiry_id>", methods=["POST"])
def convert_inquiry_to_student(inquiry_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v17_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        student_name,
        parent_email,
        trial_teacher,
        instrument
    FROM inquiries
    WHERE id = ?
    """, (inquiry_id,))

    inquiry = cursor.fetchone()

    if not inquiry:
        conn.close()
        return "<h1>Inquiry not found</h1>"

    student_name = inquiry[0]
    parent_email = inquiry[1]
    teacher = inquiry[2] or "Unassigned"

    cursor.execute("""
    INSERT OR IGNORE INTO students (
        name,
        teacher,
        parent_email,
        lessons_left
    )
    VALUES (?, ?, ?, ?)
    """, (
        student_name,
        teacher,
        parent_email,
        0
    ))

    cursor.execute("""
    UPDATE inquiries
    SET status = ?,
        converted_student_name = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        "Active Student",
        student_name,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        inquiry_id
    ))

    conn.commit()
    conn.close()

    return redirect(f"/student/{student_name}")

# =========================
# V18 Core Data Model Upgrade
# Course Types + Pricing Rules
# =========================

def calculate_course_amount(billing_method, rate, duration_minutes):
    try:
        rate = float(rate or 0)
        duration_minutes = float(duration_minutes or 0)
    except:
        return 0

    if billing_method == "Hourly":
        return round(rate * duration_minutes / 60, 2)

    return round(rate, 2)


def ensure_v18_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS course_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        duration INTEGER,
        student_billing_method TEXT,
        student_price REAL,
        teacher_billing_method TEXT,
        teacher_pay REAL,
        is_group INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    def add_column_if_missing(table_name, column_name, column_sql):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]

        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    add_column_if_missing("schedule", "course_type_id", "course_type_id INTEGER")
    add_column_if_missing("schedule", "course_type_name", "course_type_name TEXT")
    add_column_if_missing("schedule", "duration", "duration INTEGER")
    add_column_if_missing("schedule", "student_billing_method", "student_billing_method TEXT")
    add_column_if_missing("schedule", "student_price", "student_price REAL")
    add_column_if_missing("schedule", "teacher_billing_method", "teacher_billing_method TEXT")
    add_column_if_missing("schedule", "teacher_pay", "teacher_pay REAL")
    add_column_if_missing("schedule", "student_charge_amount", "student_charge_amount REAL")
    add_column_if_missing("schedule", "teacher_pay_amount", "teacher_pay_amount REAL")
    add_column_if_missing("schedule", "is_group", "is_group INTEGER DEFAULT 0")
    add_column_if_missing("schedule", "status", "status TEXT DEFAULT 'scheduled'")
    add_column_if_missing("schedule", "charge_lessons", "charge_lessons REAL DEFAULT 0")
    add_column_if_missing("schedule", "location", "location TEXT")

    cursor.execute("SELECT COUNT(*) FROM course_types")
    existing_count = cursor.fetchone()[0]

    if existing_count == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        preset_courses = [
            ("Private Lesson", 30, "Per Lesson", 55, "Per Lesson", 40, 0, 1, now, now),
            ("Private Lesson", 45, "Per Lesson", 82.5, "Per Lesson", 60, 0, 1, now, now),
            ("Private Lesson", 60, "Per Lesson", 110, "Per Lesson", 80, 0, 1, now, now),
            ("Group Class", 50, "Per Lesson", 35, "Hourly", 60, 1, 1, now, now),
            ("Trial Class", 30, "Per Lesson", 0, "Per Lesson", 25, 0, 1, now, now),
            ("Custom Program", 60, "Hourly", 120, "Hourly", 70, 0, 1, now, now),
        ]

        cursor.executemany("""
        INSERT INTO course_types (
            name,
            duration,
            student_billing_method,
            student_price,
            teacher_billing_method,
            teacher_pay,
            is_group,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, preset_courses)

    conn.commit()
    conn.close()


@app.route("/v18_setup")
def v18_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18_schema()

    return """
    <h1>V18 Setup Complete</h1>
    <p>Course Types and Schedule pricing fields are ready.</p>
    <p><a href="/course_types">Manage Course Types</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/course_types")
def course_types():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        name,
        duration,
        student_billing_method,
        student_price,
        teacher_billing_method,
        teacher_pay,
        is_group,
        active
    FROM course_types
    ORDER BY active DESC, name, duration
    """)

    courses = cursor.fetchall()
    conn.close()

    rows = ""

    for c in courses:
        group_label = "Group" if c[7] == 1 else "Private/Single"
        active_label = "Active" if c[8] == 1 else "Inactive"

        student_example = calculate_course_amount(c[3], c[4], c[2])
        teacher_example = calculate_course_amount(c[5], c[6], c[2])

        rows += f"""
        <tr>
            <td>{c[0]}</td>
            <td><b>{c[1]}</b></td>
            <td>{c[2]} mins</td>
            <td>{c[3]}</td>
            <td>${c[4]}</td>
            <td>${student_example}</td>
            <td>{c[5]}</td>
            <td>${c[6]}</td>
            <td>${teacher_example}</td>
            <td>{group_label}</td>
            <td>{active_label}</td>
            <td>
                <a href="/edit_course_type/{c[0]}">Edit</a>
            </td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Course Types</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Course Types</h1>
            <p>Owner can define duration, student price, teacher pay, and billing method.</p>

            <a class="button" href="/">Home</a>
            <a class="button" href="/add_course_type">Add Course Type</a>
            <a class="button" href="/add_schedule">Add Schedule</a>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Duration</th>
                    <th>Student Billing</th>
                    <th>Student Rate</th>
                    <th>Student Charge</th>
                    <th>Teacher Billing</th>
                    <th>Teacher Rate</th>
                    <th>Teacher Pay</th>
                    <th>Class Type</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_course_type", methods=["GET", "POST"])
def add_course_type():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18_schema()

    if request.method == "POST":
        name = request.form.get("name")
        duration = request.form.get("duration")
        student_billing_method = request.form.get("student_billing_method")
        student_price = request.form.get("student_price")
        teacher_billing_method = request.form.get("teacher_billing_method")
        teacher_pay = request.form.get("teacher_pay")
        is_group = request.form.get("is_group")
        active = request.form.get("active")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        conn = sqlite3.connect("hmusic.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO course_types (
            name,
            duration,
            student_billing_method,
            student_price,
            teacher_billing_method,
            teacher_pay,
            is_group,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            duration,
            student_billing_method,
            student_price,
            teacher_billing_method,
            teacher_pay,
            int(is_group or 0),
            int(active or 1),
            now,
            now
        ))

        conn.commit()
        conn.close()

        return redirect("/course_types")

    return """
    <h1>Add Course Type</h1>

    <form method="POST">

        Course Name:<br>
        <input name="name" placeholder="Private Lesson / Group Class / Custom Program" required><br><br>

        Duration Minutes:<br>
        <input type="number" name="duration" value="45" required><br><br>

        Student Billing Method:<br>
        <select name="student_billing_method">
            <option value="Per Lesson">Per Lesson</option>
            <option value="Hourly">Hourly</option>
        </select><br><br>

        Student Price / Rate:<br>
        <input type="number" step="0.01" name="student_price" value="0"><br><br>

        Teacher Billing Method:<br>
        <select name="teacher_billing_method">
            <option value="Per Lesson">Per Lesson</option>
            <option value="Hourly">Hourly</option>
        </select><br><br>

        Teacher Pay / Rate:<br>
        <input type="number" step="0.01" name="teacher_pay" value="0"><br><br>

        Is Group Class?<br>
        <select name="is_group">
            <option value="0">No</option>
            <option value="1">Yes</option>
        </select><br><br>

        Active?<br>
        <select name="active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
        </select><br><br>

        <button type="submit">Save Course Type</button>

    </form>

    <br>
    <a href="/course_types">Back to Course Types</a>
    """


@app.route("/edit_course_type/<int:course_id>", methods=["GET", "POST"])
def edit_course_type(course_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name")
        duration = request.form.get("duration")
        student_billing_method = request.form.get("student_billing_method")
        student_price = request.form.get("student_price")
        teacher_billing_method = request.form.get("teacher_billing_method")
        teacher_pay = request.form.get("teacher_pay")
        is_group = request.form.get("is_group")
        active = request.form.get("active")

        cursor.execute("""
        UPDATE course_types
        SET name = ?,
            duration = ?,
            student_billing_method = ?,
            student_price = ?,
            teacher_billing_method = ?,
            teacher_pay = ?,
            is_group = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            name,
            duration,
            student_billing_method,
            student_price,
            teacher_billing_method,
            teacher_pay,
            int(is_group or 0),
            int(active or 1),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            course_id
        ))

        conn.commit()
        conn.close()

        return redirect("/course_types")

    cursor.execute("""
    SELECT
        id,
        name,
        duration,
        student_billing_method,
        student_price,
        teacher_billing_method,
        teacher_pay,
        is_group,
        active
    FROM course_types
    WHERE id = ?
    """, (course_id,))

    c = cursor.fetchone()
    conn.close()

    if not c:
        return "<h1>Course Type not found</h1>"

    def selected(value, current):
        return "selected" if value == current else ""

    return f"""
    <h1>Edit Course Type</h1>

    <form method="POST">

        Course Name:<br>
        <input name="name" value="{c[1]}" required><br><br>

        Duration Minutes:<br>
        <input type="number" name="duration" value="{c[2]}" required><br><br>

        Student Billing Method:<br>
        <select name="student_billing_method">
            <option value="Per Lesson" {selected("Per Lesson", c[3])}>Per Lesson</option>
            <option value="Hourly" {selected("Hourly", c[3])}>Hourly</option>
        </select><br><br>

        Student Price / Rate:<br>
        <input type="number" step="0.01" name="student_price" value="{c[4]}"><br><br>

        Teacher Billing Method:<br>
        <select name="teacher_billing_method">
            <option value="Per Lesson" {selected("Per Lesson", c[5])}>Per Lesson</option>
            <option value="Hourly" {selected("Hourly", c[5])}>Hourly</option>
        </select><br><br>

        Teacher Pay / Rate:<br>
        <input type="number" step="0.01" name="teacher_pay" value="{c[6]}"><br><br>

        Is Group Class?<br>
        <select name="is_group">
            <option value="0" {selected(0, c[7])}>No</option>
            <option value="1" {selected(1, c[7])}>Yes</option>
        </select><br><br>

        Active?<br>
        <select name="active">
            <option value="1" {selected(1, c[8])}>Active</option>
            <option value="0" {selected(0, c[8])}>Inactive</option>
        </select><br><br>

        <button type="submit">Update Course Type</button>

    </form>

    <br>
    <a href="/course_types">Back to Course Types</a>
    """
# =========================
# V18-B Rate Override System
# =========================

def ensure_v18b_schema():
    ensure_v18_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teacher_course_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_name TEXT,
        course_type_id INTEGER,
        teacher_billing_method TEXT,
        teacher_pay REAL,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_course_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        course_type_id INTEGER,
        student_billing_method TEXT,
        student_price REAL,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_effective_course_pricing(student_name, teacher_name, course_type_id):
    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        name,
        duration,
        student_billing_method,
        student_price,
        teacher_billing_method,
        teacher_pay,
        is_group
    FROM course_types
    WHERE id = ?
    """, (course_type_id,))

    course = cursor.fetchone()

    if not course:
        conn.close()
        return None

    course_id = course[0]
    course_name = course[1]
    duration = course[2]

    student_billing_method = course[3]
    student_price = course[4]

    teacher_billing_method = course[5]
    teacher_pay = course[6]

    is_group = course[7]

    # Student override
    cursor.execute("""
    SELECT student_billing_method, student_price
    FROM student_course_rates
    WHERE student_name = ?
    AND course_type_id = ?
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, (student_name, course_type_id))

    student_override = cursor.fetchone()

    if student_override:
        student_billing_method = student_override[0]
        student_price = student_override[1]

    # Teacher override
    cursor.execute("""
    SELECT teacher_billing_method, teacher_pay
    FROM teacher_course_rates
    WHERE teacher_name = ?
    AND course_type_id = ?
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, (teacher_name, course_type_id))

    teacher_override = cursor.fetchone()

    if teacher_override:
        teacher_billing_method = teacher_override[0]
        teacher_pay = teacher_override[1]

    student_charge_amount = calculate_course_amount(
        student_billing_method,
        student_price,
        duration
    )

    teacher_pay_amount = calculate_course_amount(
        teacher_billing_method,
        teacher_pay,
        duration
    )

    conn.close()

    return {
        "course_id": course_id,
        "course_name": course_name,
        "duration": duration,
        "student_billing_method": student_billing_method,
        "student_price": student_price,
        "teacher_billing_method": teacher_billing_method,
        "teacher_pay": teacher_pay,
        "student_charge_amount": student_charge_amount,
        "teacher_pay_amount": teacher_pay_amount,
        "is_group": is_group
    }


@app.route("/v18b_setup")
def v18b_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18b_schema()

    return """
    <h1>V18-B Setup Complete</h1>
    <p>Teacher Course Rates and Student Course Rates are ready.</p>
    <p><a href="/rate_overrides">Rate Overrides</a></p>
    <p><a href="/course_types">Course Types</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/rate_overrides")
def rate_overrides():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        t.id,
        t.teacher_name,
        c.name,
        c.duration,
        t.teacher_billing_method,
        t.teacher_pay,
        t.active
    FROM teacher_course_rates t
    LEFT JOIN course_types c
        ON t.course_type_id = c.id
    ORDER BY t.teacher_name, c.name, c.duration
    """)

    teacher_rates = cursor.fetchall()

    cursor.execute("""
    SELECT
        s.id,
        s.student_name,
        c.name,
        c.duration,
        s.student_billing_method,
        s.student_price,
        s.active
    FROM student_course_rates s
    LEFT JOIN course_types c
        ON s.course_type_id = c.id
    ORDER BY s.student_name, c.name, c.duration
    """)

    student_rates = cursor.fetchall()

    conn.close()

    teacher_rows = ""

    for r in teacher_rates:
        active = "Active" if r[6] == 1 else "Inactive"

        teacher_rows += f"""
        <tr>
            <td>{r[1]}</td>
            <td>{r[2]} - {r[3]} mins</td>
            <td>{r[4]}</td>
            <td>${r[5]}</td>
            <td>{active}</td>
        </tr>
        """

    student_rows = ""

    for r in student_rates:
        active = "Active" if r[6] == 1 else "Inactive"

        student_rows += f"""
        <tr>
            <td>{r[1]}</td>
            <td>{r[2]} - {r[3]} mins</td>
            <td>{r[4]}</td>
            <td>${r[5]}</td>
            <td>{active}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Rate Overrides</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                margin-bottom: 24px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Rate Overrides</h1>

            <a class="button" href="/">Home</a>
            <a class="button" href="/course_types">Course Types</a>
            <a class="button" href="/add_teacher_course_rate">Add Teacher Rate</a>
            <a class="button" href="/add_student_course_rate">Add Student Rate</a>
        </div>

        <div class="container">
            <h2>Teacher Course Rates</h2>

            <table>
                <tr>
                    <th>Teacher</th>
                    <th>Course</th>
                    <th>Billing Method</th>
                    <th>Teacher Pay / Rate</th>
                    <th>Status</th>
                </tr>
                {teacher_rows}
            </table>
        </div>

        <div class="container">
            <h2>Student Course Rates</h2>

            <table>
                <tr>
                    <th>Student</th>
                    <th>Course</th>
                    <th>Billing Method</th>
                    <th>Student Price / Rate</th>
                    <th>Status</th>
                </tr>
                {student_rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_teacher_course_rate", methods=["GET", "POST"])
def add_teacher_course_rate():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name")
        course_type_id = request.form.get("course_type_id")
        teacher_billing_method = request.form.get("teacher_billing_method")
        teacher_pay = request.form.get("teacher_pay")
        active = request.form.get("active")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO teacher_course_rates (
            teacher_name,
            course_type_id,
            teacher_billing_method,
            teacher_pay,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            teacher_name,
            course_type_id,
            teacher_billing_method,
            teacher_pay,
            int(active or 1),
            now,
            now
        ))

        conn.commit()
        conn.close()

        return redirect("/rate_overrides")

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)
    teachers = cursor.fetchall()

    cursor.execute("""
    SELECT id, name, duration
    FROM course_types
    WHERE active = 1
    ORDER BY name, duration
    """)
    courses = cursor.fetchall()

    conn.close()

    teacher_options = ""
    for t in teachers:
        teacher_options += f"<option value='{t[0]}'>{t[0]}</option>"

    course_options = ""
    for c in courses:
        course_options += f"<option value='{c[0]}'>{c[1]} - {c[2]} mins</option>"

    return f"""
    <h1>Add Teacher Course Rate</h1>

    <form method="POST">

        Teacher:<br>
        <select name="teacher_name">
            {teacher_options}
        </select><br><br>

        Course:<br>
        <select name="course_type_id">
            {course_options}
        </select><br><br>

        Teacher Billing Method:<br>
        <select name="teacher_billing_method">
            <option value="Per Lesson">Per Lesson</option>
            <option value="Hourly">Hourly</option>
        </select><br><br>

        Teacher Pay / Rate:<br>
        <input type="number" step="0.01" name="teacher_pay" required><br><br>

        Active:<br>
        <select name="active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
        </select><br><br>

        <button type="submit">Save Teacher Rate</button>

    </form>

    <p><a href="/rate_overrides">Back to Rate Overrides</a></p>
    """


@app.route("/add_student_course_rate", methods=["GET", "POST"])
def add_student_course_rate():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        course_type_id = request.form.get("course_type_id")
        student_billing_method = request.form.get("student_billing_method")
        student_price = request.form.get("student_price")
        active = request.form.get("active")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO student_course_rates (
            student_name,
            course_type_id,
            student_billing_method,
            student_price,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            student_name,
            course_type_id,
            student_billing_method,
            student_price,
            int(active or 1),
            now,
            now
        ))

        conn.commit()
        conn.close()

        return redirect("/rate_overrides")

    cursor.execute("""
    SELECT name
    FROM students
    ORDER BY name
    """)
    students = cursor.fetchall()

    cursor.execute("""
    SELECT id, name, duration
    FROM course_types
    WHERE active = 1
    ORDER BY name, duration
    """)
    courses = cursor.fetchall()

    conn.close()

    student_options = ""
    for s in students:
        student_options += f"<option value='{s[0]}'>{s[0]}</option>"

    course_options = ""
    for c in courses:
        course_options += f"<option value='{c[0]}'>{c[1]} - {c[2]} mins</option>"

    return f"""
    <h1>Add Student Course Rate</h1>

    <form method="POST">

        Student:<br>
        <select name="student_name">
            {student_options}
        </select><br><br>

        Course:<br>
        <select name="course_type_id">
            {course_options}
        </select><br><br>

        Student Billing Method:<br>
        <select name="student_billing_method">
            <option value="Per Lesson">Per Lesson</option>
            <option value="Hourly">Hourly</option>
        </select><br><br>

        Student Price / Rate:<br>
        <input type="number" step="0.01" name="student_price" required><br><br>

        Active:<br>
        <select name="active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
        </select><br><br>

        <button type="submit">Save Student Rate</button>

    </form>

    <p><a href="/rate_overrides">Back to Rate Overrides</a></p>
    """

# =========================
# V18-C/D/E Teacher Rate Card + Pricing Engine + Payroll Auto
# =========================

def ensure_v18c_schema():
    ensure_v18b_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teacher_rate_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_name TEXT,
        billing_method TEXT,
        rate REAL,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_teacher_rate_card(teacher_name):
    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT billing_method, rate
    FROM teacher_rate_cards
    WHERE teacher_name = ?
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, (teacher_name,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            "billing_method": result[0],
            "rate": result[1]
        }

    return None


def get_final_pricing(student_name, teacher_name, course_type_id):
    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        name,
        duration,
        student_billing_method,
        student_price,
        teacher_billing_method,
        teacher_pay,
        is_group
    FROM course_types
    WHERE id = ?
    """, (course_type_id,))

    course = cursor.fetchone()

    if not course:
        conn.close()
        return None

    course_id = course[0]
    course_name = course[1]
    duration = course[2]

    student_billing_method = course[3]
    student_price = course[4]

    teacher_billing_method = course[5]
    teacher_pay = course[6]

    is_group = course[7]

    # Student price override
    cursor.execute("""
    SELECT student_billing_method, student_price
    FROM student_course_rates
    WHERE student_name = ?
    AND course_type_id = ?
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, (student_name, course_type_id))

    student_override = cursor.fetchone()

    if student_override:
        student_billing_method = student_override[0]
        student_price = student_override[1]

    # Teacher Rate Card override
    cursor.execute("""
    SELECT billing_method, rate
    FROM teacher_rate_cards
    WHERE teacher_name = ?
    AND active = 1
    ORDER BY id DESC
    LIMIT 1
    """, (teacher_name,))

    teacher_rate_card = cursor.fetchone()

    if teacher_rate_card:
        teacher_billing_method = teacher_rate_card[0]
        teacher_pay = teacher_rate_card[1]

    student_charge_amount = calculate_course_amount(
        student_billing_method,
        student_price,
        duration
    )

    teacher_pay_amount = calculate_course_amount(
        teacher_billing_method,
        teacher_pay,
        duration
    )

    conn.close()

    return {
        "course_id": course_id,
        "course_name": course_name,
        "duration": duration,
        "student_billing_method": student_billing_method,
        "student_price": student_price,
        "teacher_billing_method": teacher_billing_method,
        "teacher_pay": teacher_pay,
        "student_charge_amount": student_charge_amount,
        "teacher_pay_amount": teacher_pay_amount,
        "is_group": is_group
    }


@app.route("/v18c_setup")
def v18c_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18c_schema()

    return """
    <h1>V18-C/D/E Setup Complete</h1>
    <p>Teacher Rate Card + Pricing Engine + Payroll Auto fields are ready.</p>
    <p><a href="/teacher_rate_cards">Teacher Rate Cards</a></p>
    <p><a href="/rate_overrides">Student Rate Overrides</a></p>
    <p><a href="/course_types">Course Types</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/teacher_rate_cards")
def teacher_rate_cards():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        teacher_name,
        billing_method,
        rate,
        active,
        created_at
    FROM teacher_rate_cards
    ORDER BY teacher_name, id DESC
    """)

    cards = cursor.fetchall()
    conn.close()

    rows = ""

    for c in cards:
        active = "Active" if c[4] == 1 else "Inactive"

        rows += f"""
        <tr>
            <td>{c[0]}</td>
            <td>{c[1]}</td>
            <td>{c[2]}</td>
            <td>${c[3]}</td>
            <td>{active}</td>
            <td>{c[5]}</td>
            <td><a href="/edit_teacher_rate_card/{c[0]}">Edit</a></td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Teacher Rate Cards</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Teacher Rate Cards</h1>
            <p>Teacher default pay rule. This overrides Course Type teacher pay.</p>

            <a class="button" href="/">Home</a>
            <a class="button" href="/add_teacher_rate_card">Add Teacher Rate Card</a>
            <a class="button" href="/course_types">Course Types</a>
            <a class="button" href="/rate_overrides">Student Rate Overrides</a>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Teacher</th>
                    <th>Billing Method</th>
                    <th>Rate</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/add_teacher_rate_card", methods=["GET", "POST"])
def add_teacher_rate_card():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name")
        billing_method = request.form.get("billing_method")
        rate = request.form.get("rate")
        active = request.form.get("active")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO teacher_rate_cards (
            teacher_name,
            billing_method,
            rate,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            teacher_name,
            billing_method,
            rate,
            int(active or 1),
            now,
            now
        ))

        conn.commit()
        conn.close()

        return redirect("/teacher_rate_cards")

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)
    teachers = cursor.fetchall()
    conn.close()

    teacher_options = ""

    for t in teachers:
        teacher_options += f"<option value='{t[0]}'>{t[0]}</option>"

    return f"""
    <h1>Add Teacher Rate Card</h1>

    <form method="POST">

        Teacher:<br>
        <select name="teacher_name">
            {teacher_options}
        </select><br><br>

        Billing Method:<br>
        <select name="billing_method">
            <option value="Hourly">Hourly</option>
            <option value="Per Lesson">Per Lesson</option>
        </select><br><br>

        Rate:<br>
        <input type="number" step="0.01" name="rate" required><br><br>

        Active:<br>
        <select name="active">
            <option value="1">Active</option>
            <option value="0">Inactive</option>
        </select><br><br>

        <button type="submit">Save Teacher Rate Card</button>

    </form>

    <p><a href="/teacher_rate_cards">Back to Teacher Rate Cards</a></p>
    """


@app.route("/edit_teacher_rate_card/<int:card_id>", methods=["GET", "POST"])
def edit_teacher_rate_card(card_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name")
        billing_method = request.form.get("billing_method")
        rate = request.form.get("rate")
        active = request.form.get("active")

        cursor.execute("""
        UPDATE teacher_rate_cards
        SET teacher_name = ?,
            billing_method = ?,
            rate = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            teacher_name,
            billing_method,
            rate,
            int(active or 1),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            card_id
        ))

        conn.commit()
        conn.close()

        return redirect("/teacher_rate_cards")

    cursor.execute("""
    SELECT id, teacher_name, billing_method, rate, active
    FROM teacher_rate_cards
    WHERE id = ?
    """, (card_id,))

    card = cursor.fetchone()

    cursor.execute("""
    SELECT teacher_name
    FROM teachers
    ORDER BY teacher_name
    """)
    teachers = cursor.fetchall()

    conn.close()

    if not card:
        return "<h1>Teacher Rate Card not found</h1>"

    teacher_options = ""
    for t in teachers:
        selected = "selected" if t[0] == card[1] else ""
        teacher_options += f"<option value='{t[0]}' {selected}>{t[0]}</option>"

    def selected_option(value, current):
        return "selected" if value == current else ""

    return f"""
    <h1>Edit Teacher Rate Card</h1>

    <form method="POST">

        Teacher:<br>
        <select name="teacher_name">
            {teacher_options}
        </select><br><br>

        Billing Method:<br>
        <select name="billing_method">
            <option value="Hourly" {selected_option("Hourly", card[2])}>Hourly</option>
            <option value="Per Lesson" {selected_option("Per Lesson", card[2])}>Per Lesson</option>
        </select><br><br>

        Rate:<br>
        <input type="number" step="0.01" name="rate" value="{card[3]}" required><br><br>

        Active:<br>
        <select name="active">
            <option value="1" {selected_option(1, card[4])}>Active</option>
            <option value="0" {selected_option(0, card[4])}>Inactive</option>
        </select><br><br>

        <button type="submit">Update Teacher Rate Card</button>

    </form>

    <p><a href="/teacher_rate_cards">Back to Teacher Rate Cards</a></p>
    """
# =========================
# V19 Enrollment Engine
# =========================

def calculate_discounted_price(base_price, discount_type, discount_value):
    try:
        base_price = float(base_price or 0)
        discount_value = float(discount_value or 0)
    except:
        return 0

    if discount_type == "Fixed":
        return max(round(base_price - discount_value, 2), 0)

    if discount_type == "Percent":
        return max(round(base_price * (1 - discount_value / 100), 2), 0)

    return round(base_price, 2)


def ensure_v19_schema():
    ensure_v18c_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        course_type_id INTEGER,
        course_type_name TEXT,
        teacher_name TEXT,
        duration INTEGER,

        student_billing_method TEXT,
        base_price REAL,
        discount_type TEXT DEFAULT 'None',
        discount_value REAL DEFAULT 0,
        final_price REAL,

        teacher_billing_method TEXT,
        teacher_rate REAL,
        teacher_pay_amount REAL,

        lessons_left REAL DEFAULT 0,
        status TEXT DEFAULT 'active',

        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    def add_column_if_missing(table_name, column_name, column_sql):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    add_column_if_missing("schedule", "enrollment_id", "enrollment_id INTEGER")
    add_column_if_missing("schedule", "final_price", "final_price REAL")

    conn.commit()
    conn.close()


@app.route("/v19_setup")
def v19_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    return """
    <h1>V19 Enrollment Engine Setup Complete</h1>
    <p>Enrollment table and schedule enrollment fields are ready.</p>
    <p><a href="/enrollments">Enrollment Dashboard</a></p>
    <p><a href="/add_enrollment">Add Enrollment</a></p>
    <p><a href="/">Back Ho
    me</a></p>
    """

@app.route("/enrollments")
def enrollments():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        course_type_name,
        teacher_name,
        duration,
        final_price,
        teacher_pay_amount,
        lessons_left,
        status
    FROM enrollments
    ORDER BY student_name, status, id DESC
    """)

    rows_data = cursor.fetchall()

    cursor.execute("""
    SELECT COUNT(*)
    FROM enrollments
    WHERE status = 'active'
    """)
    active_count = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COUNT(*)
    FROM enrollments
    WHERE lessons_left <= 2
    AND status = 'active'
    """)
    renewal_count = cursor.fetchone()[0]

    conn.close()

    rows = ""

    for r in rows_data:
        rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td><a href="/student/{r[1]}">{r[1]}</a></td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]} mins</td>
            <td>${r[5]}</td>
            <td>${r[6]}</td>
            <td>{r[7]}</td>
            <td>{r[8]}</td>
            <td>
                <a href="/enrollment/{r[0]}">View</a>
                |
                <a href="/enrollment_payment/{r[0]}">Payment</a>
                |
                <a href="/add_enrollment_schedule/{r[0]}">Schedule</a>
            </td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Enrollments</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 16px;
                margin-bottom: 20px;
            }}
            .card {{
                background: #f8f8ff;
                padding: 18px;
                border-radius: 12px;
            }}
            .value {{
                font-size: 30px;
                font-weight: bold;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
            td a {{
                color: #635bff;
                font-weight: bold;
                text-decoration: none;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Enrollment Dashboard</h1>

            <a class="button" href="/">Home</a>
            <a class="button" href="/add_enrollment">New Enrollment</a>
            <a class="button" href="/enrollment_renewals">Renewals</a>
            <a class="button" href="/enrollment_payments">Payments</a>

            <div class="cards">
                <div class="card">
                    <div>Active Enrollments</div>
                    <div class="value">{active_count}</div>
                </div>

                <div class="card">
                    <div>Need Renewal</div>
                    <div class="value">{renewal_count}</div>
                </div>
            </div>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Student</th>
                    <th>Course</th>
                    <th>Teacher</th>
                    <th>Duration</th>
                    <th>Student Price</th>
                    <th>Teacher Pay</th>
                    <th>Lessons Left</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """

@app.route("/add_enrollment", methods=["GET", "POST"])
def add_enrollment():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v211_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        student_name = request.form.get("student_name")
        course_type_id = request.form.get("course_type_id")
        teacher_name = request.form.get("teacher_name")
        discount_type = request.form.get("discount_type")
        discount_value = request.form.get("discount_value")
        package_amount = float(request.form.get("package_amount") or 0)
        package_lessons = float(request.form.get("package_lessons") or 0)
        start_date = request.form.get("start_date")
        status = request.form.get("status")
        notes = request.form.get("notes")

        pricing = get_final_pricing(student_name, teacher_name, course_type_id)

        if not pricing:
            conn.close()
            return "<h1>Pricing not found</h1>"

        base_price = pricing["student_charge_amount"]

        final_price = calculate_discounted_price(
            base_price,
            discount_type,
            discount_value
        )

        teacher_pay_amount = pricing["teacher_pay_amount"]
        profit_per_lesson = final_price - teacher_pay_amount

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("""
        INSERT INTO enrollments (
            student_name,
            course_type_id,
            course_type_name,
            teacher_name,
            duration,

            student_billing_method,
            base_price,
            discount_type,
            discount_value,
            final_price,

            teacher_billing_method,
            teacher_rate,
            teacher_pay_amount,

            lessons_left,
            status,
            notes,
            start_date,
            package_amount,
            package_lessons,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_name,
            pricing["course_id"],
            pricing["course_name"],
            teacher_name,
            pricing["duration"],

            pricing["student_billing_method"],
            base_price,
            discount_type,
            float(discount_value or 0),
            final_price,

            pricing["teacher_billing_method"],
            pricing["teacher_pay"],
            teacher_pay_amount,

            package_lessons,
            status,
            notes,
            start_date,
            package_amount,
            package_lessons,
            now,
            now
        ))

        enrollment_id = cursor.lastrowid

        if package_amount > 0:
            cursor.execute("""
            INSERT INTO payments (
                student_name,
                amount,
                lessons_added,
                payment_method,
                payment_date,
                enrollment_id,
                course_type_name,
                teacher_name,
                package_name,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                student_name,
                package_amount,
                package_lessons,
                "Not Recorded",
                start_date,
                enrollment_id,
                pricing["course_name"],
                teacher_name,
                f"{package_lessons} Lesson Package",
                "Initial enrollment payment"
            ))

        conn.commit()
        conn.close()

        return redirect(f"/enrollment/{enrollment_id}")

    today = date.today().strftime("%Y-%m-%d")

    cursor.execute("SELECT name FROM students ORDER BY name")
    students = cursor.fetchall()

    cursor.execute("SELECT teacher_name FROM teachers ORDER BY teacher_name")
    teachers = cursor.fetchall()

    cursor.execute("""
    SELECT id, name, duration
    FROM course_types
    WHERE active = 1
    ORDER BY name, duration
    """)
    courses = cursor.fetchall()

    conn.close()

    student_options = "".join([f"<option value='{s[0]}'>{s[0]}</option>" for s in students])
    teacher_options = "".join([f"<option value='{t[0]}'>{t[0]}</option>" for t in teachers])
    course_options = "".join([f"<option value='{c[0]}'>{c[1]} - {c[2]} mins</option>" for c in courses])

    return f"""
    <html>
    <head>
        <title>New Enrollment</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                max-width: 760px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            input, select, textarea {{
                width: 100%;
                padding: 9px;
                margin-top: 6px;
                margin-bottom: 16px;
                font-size: 14px;
            }}
            button {{
                background: #635bff;
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 8px;
                font-weight: bold;
            }}
            .hint {{
                color: #6b7280;
                font-size: 13px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>New Enrollment</h1>
            <p><a href="/enrollments">Back to Enrollments</a></p>

            <form method="POST">

                Student:<br>
                <select name="student_name">
                    {student_options}
                </select>

                Course:<br>
                <select name="course_type_id">
                    {course_options}
                </select>

                Teacher:<br>
                <select name="teacher_name">
                    {teacher_options}
                </select>

                Discount Type:<br>
                <select name="discount_type">
                    <option value="None">None</option>
                    <option value="Fixed">Fixed Amount Off</option>
                    <option value="Percent">Percent Off</option>
                </select>

                Discount Value:<br>
                <input type="number" step="0.01" name="discount_value" value="0">

                Package Amount:<br>
                <input type="number" step="0.01" name="package_amount" value="0">
                <div class="hint">Example: 1200 for a 10-lesson package.</div><br>

                Package Lessons:<br>
                <input type="number" step="0.5" name="package_lessons" value="10">

                Start Date:<br>
                <input type="date" name="start_date" value="{today}">

                Status:<br>
                <select name="status">
                    <option value="present">Present</option>
                    <option value="no_show">No Show</option>
                    <option value="cancel_3h">Cancel &lt; 3h</option>
                    <option value="cancel_12h">Cancel &lt; 12h</option>
                    <option value="cancel_24h">Cancel &lt; 24h</option>
                    <option value="excused_24h">Cancel &gt; 24h</option>
                    <option value="teacher_cancelled">Teacher Cancel</option>
                    <option value="makeup">Makeup</option>
                </select>

                Notes:<br>
                <textarea name="notes" rows="4"></textarea>

                <button type="submit">Create Enrollment</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.route("/enrollment/<int:enrollment_id>")
def enrollment_detail(enrollment_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        course_type_name,
        teacher_name,
        duration,
        student_billing_method,
        base_price,
        discount_type,
        discount_value,
        final_price,
        teacher_billing_method,
        teacher_rate,
        teacher_pay_amount,
        lessons_left,
        status,
        notes,
        start_date,
        package_amount,
        package_lessons
    FROM enrollments
    WHERE id = ?
    """, (enrollment_id,))

    e = cursor.fetchone()

    if not e:
        conn.close()
        return "<h1>Enrollment not found</h1>"

    # Payments summary
    cursor.execute("""
    SELECT
        COALESCE(SUM(amount), 0),
        COALESCE(SUM(lessons_added), 0)
    FROM payments
    WHERE enrollment_id = ?
    """, (enrollment_id,))
    payment_summary = cursor.fetchone()

    total_paid = payment_summary[0] or 0
    total_lessons_purchased = payment_summary[1] or 0

    # Lesson financial summary
    cursor.execute("""
    SELECT
        COALESCE(SUM(charge_lessons), 0),
        COALESCE(SUM(revenue_amount), 0),
        COALESCE(SUM(payroll_amount), 0),
        COALESCE(SUM(profit_amount), 0)
    FROM schedule
    WHERE enrollment_id = ?
    """, (enrollment_id,))
    financial_summary = cursor.fetchone()

    lessons_used = financial_summary[0] or 0
    revenue_earned = financial_summary[1] or 0
    teacher_cost = financial_summary[2] or 0
    profit_earned = financial_summary[3] or 0

    package_value = e[17] or 0
    outstanding_balance = round(package_value - total_paid, 2)
    utilization = 0
    if total_lessons_purchased:
        utilization = round((lessons_used / total_lessons_purchased) * 100, 1)

    # Recent payments
    cursor.execute("""
    SELECT
        amount,
        lessons_added,
        payment_method,
        payment_date,
        package_name
    FROM payments
    WHERE enrollment_id = ?
    ORDER BY id DESC
    LIMIT 10
    """, (enrollment_id,))
    payments = cursor.fetchall()

    # Recent lessons
    cursor.execute("""
    SELECT
        lesson_date,
        lesson_time,
        classroom,
        status,
        charge_lessons,
        revenue_amount,
        payroll_amount,
        profit_amount
    FROM schedule
    WHERE enrollment_id = ?
    ORDER BY lesson_date DESC, lesson_time DESC
    LIMIT 15
    """, (enrollment_id,))
    lessons = cursor.fetchall()

    conn.close()

    payment_rows = ""
    for p in payments:
        payment_rows += f"""
        <tr>
            <td>${p[0]}</td>
            <td>{p[1]}</td>
            <td>{p[2]}</td>
            <td>{p[3]}</td>
            <td>{p[4]}</td>
        </tr>
        """

    if payment_rows == "":
        payment_rows = "<tr><td colspan='5'>No payments yet.</td></tr>"

    lesson_rows = ""
    ledger_rows = ""

    for l in lessons:
        lesson_rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td>{l[1]}</td>
            <td>{l[2]}</td>
            <td>{l[3]}</td>
            <td>{l[4] or 0}</td>
            <td>${l[5] or 0}</td>
            <td>${l[6] or 0}</td>
            <td>${l[7] or 0}</td>
        </tr>
        """

        ledger_rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td>{l[3]}</td>
            <td>-{l[4] or 0} lesson</td>
            <td>Revenue ${l[5] or 0} / Payroll ${l[6] or 0} / Profit ${l[7] or 0}</td>
        </tr>
        """

    if lesson_rows == "":
        lesson_rows = "<tr><td colspan='8'>No scheduled lessons yet.</td></tr>"

    if ledger_rows == "":
        ledger_rows = "<tr><td colspan='4'>No ledger events yet.</td></tr>"

    # Add payment events to ledger
    for p in payments:
        ledger_rows += f"""
        <tr>
            <td>{p[3]}</td>
            <td>Payment</td>
            <td>+{p[1]} lessons</td>
            <td>${p[0]} / {p[4]}</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Enrollment Detail</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .actions {{
                margin-bottom: 24px;
            }}
            .actions a {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 16px;
                margin: 20px 0;
            }}
            .card {{
                background: #f8f8ff;
                padding: 18px;
                border-radius: 12px;
            }}
            .label {{
                color: #6b7280;
                font-size: 13px;
            }}
            .value {{
                font-size: 24px;
                font-weight: bold;
                margin-top: 6px;
            }}
            h3 {{
                margin-top: 32px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
                margin-bottom: 24px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #f0f0ff;
            }}
            .muted {{
                color: #6b7280;
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <h1>Enrollment Detail</h1>
            <h2>{e[1]} - {e[2]}</h2>

            <div class="actions">
                <a href="/enrollments">Back</a>
                <a href="/enrollment_payment/{e[0]}">Payment</a>
                <a href="/add_enrollment_schedule/{e[0]}">Schedule</a>
                <a href="/edit_enrollment/{e[0]}">Edit</a>
            </div>

            <h3>Overview</h3>

            <div class="grid">
                <div class="card">
                    <div class="label">Student</div>
                    <div class="value">{e[1]}</div>
                </div>

                <div class="card">
                    <div class="label">Teacher</div>
                    <div class="value">{e[3]}</div>
                </div>

                <div class="card">
                    <div class="label">Course</div>
                    <div class="value">{e[2]}</div>
                </div>

                <div class="card">
                    <div class="label">Status</div>
                    <div class="value">{e[14]}</div>
                </div>

                <div class="card">
                    <div class="label">Price / Lesson</div>
                    <div class="value">${e[9]}</div>
                </div>

                <div class="card">
                    <div class="label">Teacher Pay / Lesson</div>
                    <div class="value">${e[12]}</div>
                </div>

                <div class="card">
                    <div class="label">Profit / Lesson</div>
                    <div class="value">${round((e[9] or 0) - (e[12] or 0), 2)}</div>
                </div>

                <div class="card">
                    <div class="label">Lessons Left</div>
                    <div class="value">{e[13]}</div>
                </div>
            </div>

            <h3>Financial Summary</h3>

            <div class="card">
                <div class="label">Package Value</div>
                <div class="value">${package_value}</div>
            </div>

                <div class="card">
                    <div class="label">Lessons Purchased</div>
                    <div class="value">{total_lessons_purchased}</div>
                </div>

                <div class="card">
                    <div class="label">Lessons Used</div>
                    <div class="value">{lessons_used}</div>
                </div>

                <div class="card">
                    <div class="label">Utilization</div>
                    <div class="value">{utilization}%</div>
                </div>

                <div class="card">
                    <div class="label">Revenue Earned</div>
                    <div class="value">${revenue_earned}</div>
                </div>

                <div class="card">
                    <div class="label">Teacher Cost</div>
                    <div class="value">${teacher_cost}</div>
                </div>

                <div class="card">
                    <div class="label">Profit Earned</div>
                    <div class="value">${profit_earned}</div>
                </div>

                <div class="card">
                    <div class="label">Outstanding Balance</div>
                    <div class="value">${outstanding_balance}</div>
                </div>
            </div>

            <h3>Pricing Details</h3>
            <p><b>Billing:</b> {e[5]}</p>
            <p><b>Base Price:</b> ${e[6]}</p>
            <p><b>Discount:</b> {e[7]} {e[8]}</p>
            <p><b>Start Date:</b> {e[16]}</p>
            <p><b>Notes:</b> {e[15] or ""}</p>

            <h3>Recent Lessons</h3>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Room</th>
                    <th>Status</th>
                    <th>Charged Units</th>
                    <th>Revenue</th>
                    <th>Payroll</th>
                    <th>Profit</th>
                </tr>
                {lesson_rows}
            </table>

            <h3>Recent Payments</h3>
            <table>
                <tr>
                    <th>Amount</th>
                    <th>Lessons Added</th>
                    <th>Method</th>
                    <th>Date</th>
                    <th>Package</th>
                </tr>
                {payment_rows}
            </table>

            <h3>Enrollment Ledger</h3>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Event</th>
                    <th>Lesson Change</th>
                    <th>Details</th>
                </tr>
                {ledger_rows}
            </table>

        </div>
    </body>
    </html>
    """

@app.route("/edit_enrollment/<int:enrollment_id>", methods=["GET", "POST"])
def edit_enrollment(enrollment_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        discount_type = request.form.get("discount_type")
        discount_value = request.form.get("discount_value")
        lessons_left = request.form.get("lessons_left")
        status = request.form.get("status")
        notes = request.form.get("notes")

        cursor.execute("""
        SELECT base_price
        FROM enrollments
        WHERE id = ?
        """, (enrollment_id,))

        result = cursor.fetchone()

        if not result:
            conn.close()
            return "<h1>Enrollment not found</h1>"

        base_price = result[0]

        final_price = calculate_discounted_price(
            base_price,
            discount_type,
            discount_value
        )

        cursor.execute("""
        UPDATE enrollments
        SET discount_type = ?,
            discount_value = ?,
            final_price = ?,
            lessons_left = ?,
            status = ?,
            notes = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            discount_type,
            float(discount_value or 0),
            final_price,
            float(lessons_left or 0),
            status,
            notes,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            enrollment_id
        ))

        conn.commit()
        conn.close()

        return redirect(f"/enrollment/{enrollment_id}")

    cursor.execute("""
    SELECT
        discount_type,
        discount_value,
        lessons_left,
        status,
        notes
    FROM enrollments
    WHERE id = ?
    """, (enrollment_id,))

    e = cursor.fetchone()
    conn.close()

    if not e:
        return "<h1>Enrollment not found</h1>"

    def selected(value, current):
        return "selected" if value == current else ""

    return f"""
    <h1>Edit Enrollment</h1>

    <form method="POST">

        Discount Type:<br>
        <select name="discount_type">
            <option value="None" {selected("None", e[0])}>None</option>
            <option value="Fixed" {selected("Fixed", e[0])}>Fixed Amount Off</option>
            <option value="Percent" {selected("Percent", e[0])}>Percent Off</option>
        </select><br><br>

        Discount Value:<br>
        <input type="number" step="0.01" name="discount_value" value="{e[1]}"><br><br>

        Lessons Left:<br>
        <input type="number" step="0.5" name="lessons_left" value="{e[2]}"><br><br>

        Status:<br>
        <select name="status">
            <option value="active" {selected("active", e[3])}>Active</option>
            <option value="paused" {selected("paused", e[3])}>Paused</option>
            <option value="inactive" {selected("inactive", e[3])}>Inactive</option>
        </select><br><br>

        Notes:<br>
        <textarea name="notes" rows="4" cols="50">{e[4] or ""}</textarea><br><br>

        <button type="submit">Update Enrollment</button>

    </form>

    <p><a href="/enrollment/{enrollment_id}">Back to Enrollment</a></p>
    """


@app.route("/add_enrollment_lessons/<int:enrollment_id>", methods=["GET", "POST"])
def add_enrollment_lessons(enrollment_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        lessons_added = float(request.form.get("lessons_added") or 0)

        cursor.execute("""
        UPDATE enrollments
        SET lessons_left = lessons_left + ?,
            updated_at = ?
        WHERE id = ?
        """, (
            lessons_added,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            enrollment_id
        ))

        conn.commit()
        conn.close()

        return redirect(f"/enrollment/{enrollment_id}")

    conn.close()

    return f"""
    <h1>Add Lessons / Package</h1>

    <form method="POST">
        Lessons Added:<br>
        <input type="number" step="0.5" name="lessons_added" value="10"><br><br>

        <button type="submit">Add Lessons</button>
    </form>

    <p><a href="/enrollment/{enrollment_id}">Back to Enrollment</a></p>
    """


@app.route("/add_enrollment_schedule/<int:enrollment_id>", methods=["GET", "POST"])
def add_enrollment_schedule(enrollment_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        course_type_id,
        course_type_name,
        teacher_name,
        duration,
        student_billing_method,
        final_price,
        teacher_billing_method,
        teacher_rate,
        teacher_pay_amount
    FROM enrollments
    WHERE id = ?
    """, (enrollment_id,))

    e = cursor.fetchone()

    if not e:
        conn.close()
        return "<h1>Enrollment not found</h1>"

    cursor.execute("""
    SELECT room_name
    FROM classrooms
    ORDER BY room_name
    """)

    rooms = cursor.fetchall()

    if request.method == "POST":
        classroom = request.form.get("classroom")
        weekday = request.form.get("weekday")
        lesson_time = request.form.get("lesson_time")
        schedule_type = request.form.get("schedule_type")
        package_type = request.form.get("package_type")
        start_date = request.form.get("start_date")

        if schedule_type == "one_time":
            number_of_lessons = 1
        elif package_type == "10":
            number_of_lessons = 10
        elif package_type == "12":
            number_of_lessons = 12
        else:
            number_of_lessons = 24

        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")

        generated_count = 0

        for i in range(number_of_lessons):
            if schedule_type == "weekly":
                lesson_date_obj = start_date_obj + timedelta(days=7 * i)
            else:
                lesson_date_obj = start_date_obj

            lesson_date = lesson_date_obj.strftime("%Y-%m-%d")

            cursor.execute("""
            INSERT INTO schedule (
                enrollment_id,
                student_name,
                teacher,
                classroom,
                weekday,
                lesson_time,
                schedule_type,
                package_type,
                start_date,
                lesson_date,

                course_type_id,
                course_type_name,
                duration,
                student_billing_method,
                student_price,
                teacher_billing_method,
                teacher_pay,
                student_charge_amount,
                teacher_pay_amount,
                final_price,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                e[0],
                e[1],
                e[4],
                classroom,
                weekday,
                lesson_time,
                schedule_type,
                package_type,
                start_date,
                lesson_date,

                e[2],
                e[3],
                e[5],
                e[6],
                e[7],
                e[8],
                e[9],
                e[7],
                e[10],
                e[7],
                "scheduled"
            ))

            generated_count += 1

        conn.commit()
        conn.close()

        return f"""
        <h1>Enrollment Schedule Generated!</h1>

        <p>{generated_count} lesson(s) created.</p>
        <p>Student: {e[1]}</p>
        <p>Course: {e[3]}</p>
        <p>Teacher: {e[4]}</p>
        <p>Duration: {e[5]} mins</p>
        <p>Student Price: ${e[7]}</p>
        <p>Teacher Pay: ${e[10]}</p>

        <p><a href="/enrollment/{enrollment_id}">Back to Enrollment</a></p>
        <p><a href="/calendar">Calendar</a></p>
        """

    room_options = ""
    for r in rooms:
        room_options += f"<option value='{r[0]}'>{r[0]}</option>"

    conn.close()

    return f"""
    <h1>Schedule Enrollment</h1>

    <h2>{e[1]} - {e[3]}</h2>

    <p>Teacher: {e[4]}</p>
    <p>Duration: {e[5]} mins</p>
    <p>Student Price: ${e[7]}</p>
    <p>Teacher Pay: ${e[10]}</p>

    <form method="POST">

        Room:<br>
        <select name="classroom">
            {room_options}
        </select><br><br>

        Day of Week:<br>
        <select name="weekday">
            <option value="Monday">Monday</option>
            <option value="Tuesday">Tuesday</option>
            <option value="Wednesday">Wednesday</option>
            <option value="Thursday">Thursday</option>
            <option value="Friday">Friday</option>
            <option value="Saturday">Saturday</option>
            <option value="Sunday">Sunday</option>
        </select><br><br>

        Time:<br>
        <input type="time" name="lesson_time" required><br><br>

        Schedule Type:<br>
        <select name="schedule_type">
            <option value="one_time">One Time</option>
            <option value="weekly">Weekly</option>
        </select><br><br>

        Package:<br>
        <select name="package_type">
            <option value="10">10 Lessons</option>
            <option value="12">12 Lessons</option>
            <option value="unlimited">Unlimited</option>
        </select><br><br>

        Start Date:<br>
        <input type="date" name="start_date" required><br><br>

        <button type="submit">Generate Schedule</button>

    </form>

    <p><a href="/enrollment/{enrollment_id}">Back to Enrollment</a></p>
    """
# =========================
# V20-A Enrollment Renewals
# =========================

@app.route("/enrollment_renewals")
def enrollment_renewals():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        course_type_name,
        teacher_name,
        duration,
        final_price,
        lessons_left,
        status
    FROM enrollments
    WHERE lessons_left <= 2
    AND status = 'active'
    ORDER BY lessons_left ASC, student_name ASC
    """)

    renewals = cursor.fetchall()
    conn.close()

    rows = ""

    for r in renewals:
        rows += f"""
        <tr>
            <td><a href="/enrollment/{r[0]}">{r[0]}</a></td>
            <td><a href="/student/{r[1]}">{r[1]}</a></td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]} mins</td>
            <td>${r[5]}</td>
            <td style="color:red;font-weight:bold;">{r[6]}</td>
            <td>{r[7]}</td>
            <td>
                <a href="/add_enrollment_lessons/{r[0]}">Add Lessons</a>
            </td>
        </tr>
        """

    if rows == "":
        rows = """
        <tr>
            <td colspan="9">No enrollments need renewal.</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Enrollment Renewals</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}

            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}

            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}

            th {{
                background: #f0f0ff;
            }}

            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Enrollment Renewals</h1>
            <p>Only active enrollments with 2 or fewer lessons left.</p>

            <a class="button" href="/">Home</a>
            <a class="button" href="/enrollments">Enrollments</a>
            <a class="button" href="/add_enrollment">Add Enrollment</a>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Student</th>
                    <th>Course</th>
                    <th>Teacher</th>
                    <th>Duration</th>
                    <th>Price</th>
                    <th>Lessons Left</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """

# =========================
# V21 Package / Payment Engine
# Enrollment-Based Payment
# =========================

def ensure_v21_schema():
    ensure_v19_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    def add_column_if_missing(table_name, column_name, column_sql):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    add_column_if_missing("payments", "enrollment_id", "enrollment_id INTEGER")
    add_column_if_missing("payments", "course_type_name", "course_type_name TEXT")
    add_column_if_missing("payments", "teacher_name", "teacher_name TEXT")
    add_column_if_missing("payments", "package_name", "package_name TEXT")
    add_column_if_missing("payments", "notes", "notes TEXT")

    conn.commit()
    conn.close()


@app.route("/v21_setup")
def v21_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v21_schema()

    return """
    <h1>V21 Package / Payment Engine Setup Complete</h1>
    <p>Enrollment-based payment fields are ready.</p>
    <p><a href="/enrollment_payments">Enrollment Payments</a></p>
    <p><a href="/enrollments">Enrollments</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/enrollment_payments")
def enrollment_payments():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v21_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        p.id,
        p.student_name,
        p.course_type_name,
        p.teacher_name,
        p.amount,
        p.lessons_added,
        p.payment_method,
        p.payment_date,
        p.package_name,
        p.enrollment_id
    FROM payments p
    WHERE p.enrollment_id IS NOT NULL
    ORDER BY p.id DESC
    LIMIT 100
    """)

    payments = cursor.fetchall()
    conn.close()

    rows = ""

    for p in payments:
        rows += f"""
        <tr>
            <td>{p[0]}</td>
            <td>{p[1]}</td>
            <td>{p[2]}</td>
            <td>{p[3]}</td>
            <td>${p[4]}</td>
            <td>{p[5]}</td>
            <td>{p[6]}</td>
            <td>{p[7]}</td>
            <td>{p[8]}</td>
            <td><a href="/enrollment/{p[9]}">Enrollment</a></td>
        </tr>
        """

    if rows == "":
        rows = """
        <tr>
            <td colspan="10">No enrollment payments yet.</td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Enrollment Payments</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Enrollment Payments</h1>

            <a class="button" href="/">Home</a>
            <a class="button" href="/enrollments">Enrollments</a>
            <a class="button" href="/enrollment_renewals">Enrollment Renewals</a>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Student</th>
                    <th>Course</th>
                    <th>Teacher</th>
                    <th>Amount</th>
                    <th>Lessons Added</th>
                    <th>Method</th>
                    <th>Date</th>
                    <th>Package</th>
                    <th>Link</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/enrollment_payment/<int:enrollment_id>", methods=["GET", "POST"])
def enrollment_payment(enrollment_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v21_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        student_name,
        course_type_name,
        teacher_name,
        duration,
        final_price,
        lessons_left
    FROM enrollments
    WHERE id = ?
    """, (enrollment_id,))

    e = cursor.fetchone()

    if not e:
        conn.close()
        return "<h1>Enrollment not found</h1>"

    if request.method == "POST":
        amount = float(request.form.get("amount") or 0)
        lessons_added = float(request.form.get("lessons_added") or 0)
        payment_method = request.form.get("payment_method")
        payment_date = request.form.get("payment_date")
        package_name = request.form.get("package_name")
        notes = request.form.get("notes")

        cursor.execute("""
        INSERT INTO payments (
            student_name,
            amount,
            lessons_added,
            payment_method,
            payment_date,
            enrollment_id,
            course_type_name,
            teacher_name,
            package_name,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            e[1],
            amount,
            lessons_added,
            payment_method,
            payment_date,
            enrollment_id,
            e[2],
            e[3],
            package_name,
            notes
        ))

        payment_id = cursor.lastrowid

        cursor.execute("""
        UPDATE enrollments
        SET lessons_left = lessons_left + ?,
            updated_at = ?
        WHERE id = ?
        """, (
            lessons_added,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            enrollment_id
        ))

        cursor.execute("""
        INSERT INTO student_ledger (
            student_name,
            entry_type,
            amount,
            description,
            related_invoice_id,
            related_payment_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            e[1],
            "enrollment_payment",
            amount,
            f"Payment for {e[2]} / Enrollment #{enrollment_id} / +{lessons_added} lessons",
            None,
            payment_id,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        conn.commit()
        conn.close()

        return redirect(f"/enrollment/{enrollment_id}")

    today = date.today().strftime("%Y-%m-%d")
    suggested_amount = round((e[5] or 0) * 10, 2)

    conn.close()

    return f"""
    <h1>Enrollment Payment</h1>

    <h2>{e[1]} - {e[2]}</h2>

    <p>Teacher: {e[3]}</p>
    <p>Duration: {e[4]} mins</p>
    <p>Price per lesson: ${e[5]}</p>
    <p>Current Lessons Left: {e[6]}</p>

    <form method="POST">

        Package Name:<br>
        <input name="package_name" value="10 Lesson Package"><br><br>

        Amount:<br>
        <input type="number" step="0.01" name="amount" value="{suggested_amount}"><br><br>

        Lessons Added:<br>
        <input type="number" step="0.5" name="lessons_added" value="10"><br><br>

        Payment Method:<br>
        <select name="payment_method">
            <option value="Zelle">Zelle</option>
            <option value="Cash">Cash</option>
            <option value="Check">Check</option>
            <option value="Credit Card">Credit Card</option>
            <option value="Venmo">Venmo</option>
            <option value="Other">Other</option>
        </select><br><br>

        Payment Date:<br>
        <input type="date" name="payment_date" value="{today}"><br><br>

        Notes:<br>
        <textarea name="notes" rows="4" cols="50"></textarea><br><br>

        <button type="submit">Record Payment + Add Lessons</button>

    </form>

    <p><a href="/enrollment/{enrollment_id}">Back to Enrollment</a></p>
    <p><a href="/enrollments">Back to Enrollments</a></p>
    """

def ensure_v211_schema():
    ensure_v21_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    def add_column_if_missing(table_name, column_name, column_sql):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    add_column_if_missing("enrollments", "start_date", "start_date TEXT")
    add_column_if_missing("enrollments", "package_amount", "package_amount REAL DEFAULT 0")
    add_column_if_missing("enrollments", "package_lessons", "package_lessons REAL DEFAULT 0")

    conn.commit()
    conn.close()

    # =========================
# V25 Business Rules Engine
# Lesson Status Rules
# =========================

def ensure_v25_schema():
    ensure_v21_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lesson_status_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status_code TEXT UNIQUE,
        status_label TEXT,
        student_charge_units REAL,
        teacher_pay_units REAL,
        counts_as_revenue INTEGER DEFAULT 1,
        counts_as_payroll INTEGER DEFAULT 1,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    default_rules = [
        ("present", "Present", 1.0, 1.0, 1, 1),
        ("no_show", "No Show", 1.0, 1.0, 1, 1),
        ("cancel_3h", "Cancel < 3h", 1.0, 1.0, 1, 1),
        ("cancel_12h", "Cancel < 12h", 0.75, 0.75, 1, 1),
        ("cancel_24h", "Cancel < 24h", 0.5, 0.5, 1, 1),
        ("excused_24h", "Cancel > 24h", 0.0, 0.0, 0, 0),
        ("teacher_cancelled", "Teacher Cancel", 0.0, 0.0, 0, 0),
        ("makeup", "Makeup", 0.0, 0.0, 0, 0),
    ]

    for rule in default_rules:
        cursor.execute("""
        INSERT OR IGNORE INTO lesson_status_rules (
            status_code,
            status_label,
            student_charge_units,
            teacher_pay_units,
            counts_as_revenue,
            counts_as_payroll,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rule[0],
            rule[1],
            rule[2],
            rule[3],
            rule[4],
            rule[5],
            1,
            now,
            now
        ))

    def add_column_if_missing(table_name, column_name, column_sql):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    add_column_if_missing("schedule", "student_charge_units", "student_charge_units REAL DEFAULT 0")
    add_column_if_missing("schedule", "teacher_pay_units", "teacher_pay_units REAL DEFAULT 0")
    add_column_if_missing("schedule", "revenue_amount", "revenue_amount REAL DEFAULT 0")
    add_column_if_missing("schedule", "payroll_amount", "payroll_amount REAL DEFAULT 0")
    add_column_if_missing("schedule", "profit_amount", "profit_amount REAL DEFAULT 0")

    conn.commit()
    conn.close()


def get_lesson_status_rule(status_code):
    ensure_v25_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        status_code,
        status_label,
        student_charge_units,
        teacher_pay_units,
        counts_as_revenue,
        counts_as_payroll
    FROM lesson_status_rules
    WHERE status_code = ?
    AND active = 1
    """, (status_code,))

    rule = cursor.fetchone()
    conn.close()

    if not rule:
        return {
            "status_code": status_code,
            "status_label": status_code,
            "student_charge_units": 0,
            "teacher_pay_units": 0,
            "counts_as_revenue": 0,
            "counts_as_payroll": 0
        }

    return {
        "status_code": rule[0],
        "status_label": rule[1],
        "student_charge_units": rule[2],
        "teacher_pay_units": rule[3],
        "counts_as_revenue": rule[4],
        "counts_as_payroll": rule[5]
    }


@app.route("/v25_setup")
def v25_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v25_schema()

    return """
    <h1>V25 Business Rules Engine Setup Complete</h1>
    <p>Lesson Status Rules are ready.</p>
    <p><a href="/lesson_status_rules">Lesson Status Rules</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/lesson_status_rules")
def lesson_status_rules():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v25_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        status_code,
        status_label,
        student_charge_units,
        teacher_pay_units,
        counts_as_revenue,
        counts_as_payroll,
        active
    FROM lesson_status_rules
    ORDER BY id
    """)

    rules = cursor.fetchall()
    conn.close()

    rows = ""

    for r in rules:
        revenue = "Yes" if r[5] == 1 else "No"
        payroll = "Yes" if r[6] == 1 else "No"
        active = "Active" if r[7] == 1 else "Inactive"

        rows += f"""
        <tr>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td>{revenue}</td>
            <td>{payroll}</td>
            <td>{active}</td>
            <td><a href="/edit_lesson_status_rule/{r[0]}">Edit</a></td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Lesson Status Rules</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Lesson Status Rules</h1>
            <p>Owner can control student charge units and teacher pay units for each lesson status.</p>

            <a class="button" href="/">Home</a>
            <a class="button" href="/enrollments">Enrollments</a>
            <a class="button" href="/teacher_dashboard">Teacher Dashboard</a>

            <table>
                <tr>
                    <th>Status Code</th>
                    <th>Status Label</th>
                    <th>Student Charge Units</th>
                    <th>Teacher Pay Units</th>
                    <th>Counts Revenue</th>
                    <th>Counts Payroll</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/edit_lesson_status_rule/<int:rule_id>", methods=["GET", "POST"])
def edit_lesson_status_rule(rule_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v25_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        status_label = request.form.get("status_label")
        student_charge_units = request.form.get("student_charge_units")
        teacher_pay_units = request.form.get("teacher_pay_units")
        counts_as_revenue = request.form.get("counts_as_revenue")
        counts_as_payroll = request.form.get("counts_as_payroll")
        active = request.form.get("active")

        cursor.execute("""
        UPDATE lesson_status_rules
        SET status_label = ?,
            student_charge_units = ?,
            teacher_pay_units = ?,
            counts_as_revenue = ?,
            counts_as_payroll = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            status_label,
            float(student_charge_units or 0),
            float(teacher_pay_units or 0),
            int(counts_as_revenue or 0),
            int(counts_as_payroll or 0),
            int(active or 1),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            rule_id
        ))

        conn.commit()
        conn.close()

        return redirect("/lesson_status_rules")

    cursor.execute("""
    SELECT
        id,
        status_code,
        status_label,
        student_charge_units,
        teacher_pay_units,
        counts_as_revenue,
        counts_as_payroll,
        active
    FROM lesson_status_rules
    WHERE id = ?
    """, (rule_id,))

    r = cursor.fetchone()
    conn.close()

    if not r:
        return "<h1>Rule not found</h1>"

    def selected(value, current):
        return "selected" if value == current else ""

    return f"""
    <h1>Edit Lesson Status Rule</h1>

    <p>Status Code: <b>{r[1]}</b></p>

    <form method="POST">

        Status Label:<br>
        <input name="status_label" value="{r[2]}"><br><br>

        Student Charge Units:<br>
        <input type="number" step="0.25" name="student_charge_units" value="{r[3]}"><br><br>

        Teacher Pay Units:<br>
        <input type="number" step="0.25" name="teacher_pay_units" value="{r[4]}"><br><br>

        Counts as Revenue?<br>
        <select name="counts_as_revenue">
            <option value="1" {selected(1, r[5])}>Yes</option>
            <option value="0" {selected(0, r[5])}>No</option>
        </select><br><br>

        Counts as Payroll?<br>
        <select name="counts_as_payroll">
            <option value="1" {selected(1, r[6])}>Yes</option>
            <option value="0" {selected(0, r[6])}>No</option>
        </select><br><br>

        Active?<br>
        <select name="active">
            <option value="1" {selected(1, r[7])}>Active</option>
            <option value="0" {selected(0, r[7])}>Inactive</option>
        </select><br><br>

        <button type="submit">Update Rule</button>

    </form>

    <p><a href="/lesson_status_rules">Back to Rules</a></p>
    """
# =========================
# V25.2 Owner Business Rules Settings
# =========================

def ensure_v252_schema():
    ensure_v25_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT UNIQUE,
        rule_label TEXT,
        student_charge_percent REAL DEFAULT 100,
        teacher_pay_percent REAL DEFAULT 100,
        deduct_lesson INTEGER DEFAULT 1,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    default_rules = [
        ("present", "Present", 100, 100, 1),
        ("no_show", "No Show", 100, 100, 1),
        ("cancel_3h", "Cancel < 3h", 100, 100, 1),
        ("cancel_12h", "Cancel < 12h", 100, 75, 1),
        ("cancel_24h", "Cancel < 24h", 50, 50, 0),
        ("excused_24h", "Cancel > 24h", 0, 0, 0),
        ("teacher_cancelled", "Teacher Cancel", 0, 0, 0),
        ("makeup", "Makeup", 0, 100, 0),
    ]

    for r in default_rules:
        cursor.execute("""
        INSERT OR IGNORE INTO business_rules (
            rule_name,
            rule_label,
            student_charge_percent,
            teacher_pay_percent,
            deduct_lesson,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            1,
            now,
            now
        ))

    conn.commit()
    conn.close()


def get_business_rule(status):
    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        rule_name,
        rule_label,
        student_charge_percent,
        teacher_pay_percent,
        deduct_lesson
    FROM business_rules
    WHERE rule_name = ?
    AND active = 1
    """, (status,))

    r = cursor.fetchone()
    conn.close()

    if not r:
        return {
            "rule_name": status,
            "rule_label": status,
            "student_charge_percent": 0,
            "teacher_pay_percent": 0,
            "deduct_lesson": 0
        }

    return {
        "rule_name": r[0],
        "rule_label": r[1],
        "student_charge_percent": r[2],
        "teacher_pay_percent": r[3],
        "deduct_lesson": r[4]
    }


@app.route("/v252_setup")
def v252_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v252_schema()

    return """
    <h1>V25.2 Setup Complete</h1>
    <p>Owner Business Rules are ready.</p>
    <p><a href="/business_rules">Business Rules</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/business_rules")
def business_rules():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        id,
        rule_name,
        rule_label,
        student_charge_percent,
        teacher_pay_percent,
        deduct_lesson,
        active
    FROM business_rules
    ORDER BY id
    """)

    rules = cursor.fetchall()
    conn.close()

    rows = ""

    for r in rules:
        deduct = "Yes" if r[5] == 1 else "No"
        active = "Active" if r[6] == 1 else "Inactive"

        rows += f"""
        <tr>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td>{r[3]}%</td>
            <td>{r[4]}%</td>
            <td>{deduct}</td>
            <td>{active}</td>
            <td><a href="/edit_business_rule/{r[0]}">Edit</a></td>
        </tr>
        """

    return f"""
    <html>
    <head>
        <title>Business Rules</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Business Rules</h1>
            <p>Owner can edit student charge, teacher pay, and lesson deduction rules.</p>

            <a class="button" href="/">Home</a>
            <a class="button" href="/lesson_status_rules">Lesson Status Rules</a>
            <a class="button" href="/teacher_dashboard">Teacher Dashboard</a>

            <table>
                <tr>
                    <th>Rule Name</th>
                    <th>Label</th>
                    <th>Student Charge</th>
                    <th>Teacher Pay</th>
                    <th>Deduct Lesson?</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/edit_business_rule/<int:rule_id>", methods=["GET", "POST"])
def edit_business_rule(rule_id):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    if request.method == "POST":
        rule_label = request.form.get("rule_label")
        student_charge_percent = request.form.get("student_charge_percent")
        teacher_pay_percent = request.form.get("teacher_pay_percent")
        deduct_lesson = request.form.get("deduct_lesson")
        active = request.form.get("active")

        cursor.execute("""
        UPDATE business_rules
        SET rule_label = ?,
            student_charge_percent = ?,
            teacher_pay_percent = ?,
            deduct_lesson = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """, (
            rule_label,
            float(student_charge_percent or 0),
            float(teacher_pay_percent or 0),
            int(deduct_lesson or 0),
            int(active or 1),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            rule_id
        ))

        conn.commit()
        conn.close()

        return redirect("/business_rules")

    cursor.execute("""
    SELECT
        id,
        rule_name,
        rule_label,
        student_charge_percent,
        teacher_pay_percent,
        deduct_lesson,
        active
    FROM business_rules
    WHERE id = ?
    """, (rule_id,))

    r = cursor.fetchone()
    conn.close()

    if not r:
        return "<h1>Business Rule not found</h1>"

    def selected(value, current):
        return "selected" if value == current else ""

    return f"""
    <h1>Edit Business Rule</h1>

    <p><b>Rule:</b> {r[1]}</p>

    <form method="POST">

        Label:<br>
        <input name="rule_label" value="{r[2]}"><br><br>

        Student Charge Percent:<br>
        <input type="number" step="1" name="student_charge_percent" value="{r[3]}"><br><br>

        Teacher Pay Percent:<br>
        <input type="number" step="1" name="teacher_pay_percent" value="{r[4]}"><br><br>

        Deduct Lesson?<br>
        <select name="deduct_lesson">
            <option value="1" {selected(1, r[5])}>Yes</option>
            <option value="0" {selected(0, r[5])}>No</option>
        </select><br><br>

        Active?<br>
        <select name="active">
            <option value="1" {selected(1, r[6])}>Active</option>
            <option value="0" {selected(0, r[6])}>Inactive</option>
        </select><br><br>

        <button type="submit">Update Business Rule</button>

    </form>

    <p><a href="/business_rules">Back to Business Rules</a></p>
    """
# =========================
# V26 Payroll Engine Final
# =========================

def ensure_v26_schema():
    ensure_v252_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payroll_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT UNIQUE,
        locked INTEGER DEFAULT 0,
        locked_at TEXT,
        locked_by TEXT
    )
    """)

    conn.commit()
    conn.close()


def is_payroll_locked(month):
    ensure_v26_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT locked
    FROM payroll_periods
    WHERE month = ?
    """, (month,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return False

    return row[0] == 1


@app.route("/v26_setup")
def v26_setup():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    return """
    <h1>V26 Payroll Engine Setup Complete</h1>
    <p>Payroll periods are ready.</p>
    <p><a href="/payroll">Go to Payroll</a></p>
    <p><a href="/">Back Home</a></p>
    """


@app.route("/payroll")
def payroll():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    month = request.args.get("month") or date.today().strftime("%Y-%m")
    locked = is_payroll_locked(month)

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        teacher,
        COUNT(id),
        COALESCE(SUM(teacher_pay_units), 0),
        COALESCE(SUM(revenue_amount), 0),
        COALESCE(SUM(payroll_amount), 0),
        COALESCE(SUM(profit_amount), 0)
    FROM schedule
    WHERE substr(lesson_date, 1, 7) = ?
    GROUP BY teacher
    ORDER BY teacher
    """, (month,))

    rows_data = cursor.fetchall()

    cursor.execute("""
    SELECT
        COALESCE(SUM(revenue_amount), 0),
        COALESCE(SUM(payroll_amount), 0),
        COALESCE(SUM(profit_amount), 0),
        COALESCE(SUM(teacher_pay_units), 0),
        COUNT(id)
    FROM schedule
    WHERE substr(lesson_date, 1, 7) = ?
    """, (month,))

    totals = cursor.fetchone()
    conn.close()

    total_revenue = totals[0] or 0
    total_payroll = totals[1] or 0
    total_profit = totals[2] or 0
    total_units = totals[3] or 0
    total_lessons = totals[4] or 0

    rows = ""

    for r in rows_data:
        teacher = r[0]
        lesson_count = r[1] or 0
        paid_units = r[2] or 0
        revenue = r[3] or 0
        payroll_amount = r[4] or 0
        profit = r[5] or 0

        rows += f"""
        <tr>
            <td><a href="/payroll/{teacher}?month={month}">{teacher}</a></td>
            <td>{lesson_count}</td>
            <td>{paid_units}</td>
            <td>${revenue}</td>
            <td>${payroll_amount}</td>
            <td>${profit}</td>
        </tr>
        """

    if rows == "":
        rows = "<tr><td colspan='6'>No payroll records for this month.</td></tr>"

    lock_button = ""
    if locked:
        lock_button = "<span class='locked'>Payroll Locked</span>"
    else:
        lock_button = f"""
        <form method="POST" action="/lock_payroll/{month}" style="display:inline;">
            <button type="submit">Lock Payroll</button>
        </form>
        """

    return f"""
    <html>
    <head>
        <title>Payroll</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 14px;
                margin: 22px 0;
            }}
            .card {{
                background: #f8f8ff;
                padding: 16px;
                border-radius: 12px;
            }}
            .label {{
                color: #6b7280;
                font-size: 13px;
            }}
            .value {{
                font-size: 22px;
                font-weight: bold;
                margin-top: 6px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button, button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                border: none;
                margin-right: 8px;
                cursor: pointer;
            }}
            .locked {{
                display: inline-block;
                background: #16a34a;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                font-weight: bold;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Teacher Payroll</h1>

            <form method="GET" action="/payroll">
                Month:
                <input type="month" name="month" value="{month}">
                <button type="submit">View</button>
            </form>

            <br>

            <a class="button" href="/">Home</a>
            <a class="button" href="/payroll_audit?month={month}">Payroll Audit</a>
            <a class="button" href="/export_payroll_csv?month={month}">Export CSV</a>
            {lock_button}

            <div class="cards">
                <div class="card">
                    <div class="label">Lesson Records</div>
                    <div class="value">{total_lessons}</div>
                </div>

                <div class="card">
                    <div class="label">Paid Units</div>
                    <div class="value">{total_units}</div>
                </div>

                <div class="card">
                    <div class="label">Revenue</div>
                    <div class="value">${total_revenue}</div>
                </div>

                <div class="card">
                    <div class="label">Payroll</div>
                    <div class="value">${total_payroll}</div>
                </div>

                <div class="card">
                    <div class="label">Profit</div>
                    <div class="value">${total_profit}</div>
                </div>
            </div>

            <table>
                <tr>
                    <th>Teacher</th>
                    <th>Lesson Records</th>
                    <th>Paid Units</th>
                    <th>Revenue</th>
                    <th>Payroll</th>
                    <th>Profit</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/payroll/<teacher_name>")
def payroll_teacher_detail(teacher_name):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    month = request.args.get("month") or date.today().strftime("%Y-%m")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        COALESCE(SUM(revenue_amount), 0),
        COALESCE(SUM(payroll_amount), 0),
        COALESCE(SUM(profit_amount), 0),
        COALESCE(SUM(teacher_pay_units), 0),
        COUNT(id)
    FROM schedule
    WHERE teacher = ?
    AND substr(lesson_date, 1, 7) = ?
    """, (teacher_name, month))

    totals = cursor.fetchone()

    total_revenue = totals[0] or 0
    total_payroll = totals[1] or 0
    total_profit = totals[2] or 0
    total_units = totals[3] or 0
    total_lessons = totals[4] or 0

    cursor.execute("""
    SELECT
        lesson_date,
        lesson_time,
        student_name,
        status,
        teacher_pay_units,
        revenue_amount,
        payroll_amount,
        profit_amount
    FROM schedule
    WHERE teacher = ?
    AND substr(lesson_date, 1, 7) = ?
    ORDER BY lesson_date, lesson_time
    """, (teacher_name, month))

    lessons = cursor.fetchall()
    conn.close()

    rows = ""

    for l in lessons:
        rows += f"""
        <tr>
            <td>{l[0]}</td>
            <td>{l[1]}</td>
            <td>{l[2]}</td>
            <td>{l[3]}</td>
            <td>{l[4] or 0}</td>
            <td>${l[5] or 0}</td>
            <td>${l[6] or 0}</td>
            <td>${l[7] or 0}</td>
        </tr>
        """

    if rows == "":
        rows = "<tr><td colspan='8'>No payroll records.</td></tr>"

    return f"""
    <html>
    <head>
        <title>{teacher_name} Payroll Detail</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 14px;
                margin: 22px 0;
            }}
            .card {{
                background: #f8f8ff;
                padding: 16px;
                border-radius: 12px;
            }}
            .label {{
                color: #6b7280;
                font-size: 13px;
            }}
            .value {{
                font-size: 22px;
                font-weight: bold;
                margin-top: 6px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>{teacher_name} Payroll Detail</h1>
            <p>Month: {month}</p>

            <a class="button" href="/payroll?month={month}">Back to Payroll</a>
            <a class="button" href="/">Home</a>

            <div class="cards">
                <div class="card">
                    <div class="label">Lesson Records</div>
                    <div class="value">{total_lessons}</div>
                </div>

                <div class="card">
                    <div class="label">Paid Units</div>
                    <div class="value">{total_units}</div>
                </div>

                <div class="card">
                    <div class="label">Revenue</div>
                    <div class="value">${total_revenue}</div>
                </div>

                <div class="card">
                    <div class="label">Payroll</div>
                    <div class="value">${total_payroll}</div>
                </div>

                <div class="card">
                    <div class="label">Profit</div>
                    <div class="value">${total_profit}</div>
                </div>
            </div>

            <table>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Student</th>
                    <th>Status</th>
                    <th>Paid Units</th>
                    <th>Revenue</th>
                    <th>Payroll</th>
                    <th>Profit</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/payroll_audit")
def payroll_audit():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    month = request.args.get("month") or date.today().strftime("%Y-%m")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        lesson_date,
        lesson_time,
        teacher,
        student_name,
        status,
        charge_lessons,
        teacher_pay_units,
        revenue_amount,
        payroll_amount,
        profit_amount
    FROM schedule
    WHERE substr(lesson_date, 1, 7) = ?
    ORDER BY lesson_date DESC, lesson_time DESC
    """, (month,))

    records = cursor.fetchall()
    conn.close()

    rows = ""

    for r in records:
        rows += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
            <td>{r[3]}</td>
            <td>{r[4]}</td>
            <td>{r[5] or 0}</td>
            <td>{r[6] or 0}</td>
            <td>${r[7] or 0}</td>
            <td>${r[8] or 0}</td>
            <td>${r[9] or 0}</td>
        </tr>
        """

    if rows == "":
        rows = "<tr><td colspan='10'>No audit records.</td></tr>"

    return f"""
    <html>
    <head>
        <title>Payroll Audit</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f7fb;
                padding: 40px;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                border-bottom: 1px solid #eee;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #f0f0ff;
            }}
            a.button {{
                display: inline-block;
                background: #635bff;
                color: white;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-right: 8px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>Payroll Audit</h1>

            <form method="GET" action="/payroll_audit">
                Month:
                <input type="month" name="month" value="{month}">
                <button type="submit">View</button>
            </form>

            <br>

            <a class="button" href="/payroll?month={month}">Back to Payroll</a>
            <a class="button" href="/">Home</a>

            <table>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Teacher</th>
                    <th>Student</th>
                    <th>Status</th>
                    <th>Student Units</th>
                    <th>Teacher Units</th>
                    <th>Revenue</th>
                    <th>Payroll</th>
                    <th>Profit</th>
                </tr>
                {rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.route("/lock_payroll/<month>", methods=["POST"])
def lock_payroll(month):
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
    INSERT INTO payroll_periods (
        month,
        locked,
        locked_at,
        locked_by
    )
    VALUES (?, ?, ?, ?)
    ON CONFLICT(month) DO UPDATE SET
        locked = 1,
        locked_at = excluded.locked_at,
        locked_by = excluded.locked_by
    """, (
        month,
        1,
        now,
        "owner"
    ))

    conn.commit()
    conn.close()

    return redirect(f"/payroll?month={month}")


@app.route("/export_payroll_csv")
def export_payroll_csv():
    if not require_owner():
        return redirect("/owner_login")

    ensure_v26_schema()

    month = request.args.get("month") or date.today().strftime("%Y-%m")

    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        teacher,
        COUNT(id),
        COALESCE(SUM(teacher_pay_units), 0),
        COALESCE(SUM(revenue_amount), 0),
        COALESCE(SUM(payroll_amount), 0),
        COALESCE(SUM(profit_amount), 0)
    FROM schedule
    WHERE substr(lesson_date, 1, 7) = ?
    GROUP BY teacher
    ORDER BY teacher
    """, (month,))

    rows = cursor.fetchall()
    conn.close()

    csv_text = "Teacher,Lesson Records,Paid Units,Revenue,Payroll,Profit\n"

    for r in rows:
        csv_text += f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}\n"

    return Response(
        csv_text,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=payroll_{month}.csv"
        }
    )


_production_schema_ready = False


def ensure_base_schema():
    conn = sqlite3.connect("hmusic.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        teacher TEXT,
        parent_name TEXT,
        parent_email TEXT,
        lessons_left INTEGER DEFAULT 0,
        free_cancel_used INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        teacher TEXT,
        lesson_date TEXT,
        lesson_time TEXT,
        classroom TEXT,
        location TEXT,
        notes TEXT,
        schedule_type TEXT,
        total_lessons INTEGER,
        weekday TEXT,
        package_type TEXT,
        start_date TEXT,
        status TEXT DEFAULT 'scheduled',
        charge_lessons REAL DEFAULT 0,
        cancellation_reason TEXT,
        cancelled_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        amount REAL,
        lessons_added INTEGER,
        payment_method TEXT,
        payment_date TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        schedule_id INTEGER,
        charge_lessons REAL,
        amount REAL,
        status TEXT,
        invoice_type TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        lesson_content TEXT,
        performance TEXT,
        homework TEXT,
        lesson_date TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT,
        entry_type TEXT,
        amount REAL,
        description TEXT,
        related_invoice_id INTEGER,
        related_payment_id INTEGER,
        created_at TEXT,
        related_schedule_id INTEGER
    )
    """)

    conn.commit()
    conn.close()


def ensure_production_schema():
    global _production_schema_ready
    if _production_schema_ready:
        return

    ensure_base_schema()
    ensure_teacher_management_schema()
    ensure_v26_schema()
    ensure_v27_schema()
    ensure_v29_schema()
    ensure_v145_schema()

    _production_schema_ready = True


@app.before_request
def prepare_database_for_request():
    ensure_production_schema()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
