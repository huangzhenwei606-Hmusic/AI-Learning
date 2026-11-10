"""School communications workspace; teacher identity and owner authority stay separate."""
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
import json
import re
import threading
from urllib.parse import urlsplit

from flask import abort, redirect, request, session, Response, send_from_directory

PERMISSIONS = {
    'inbox': 'Read school inbox', 'reply': 'Reply to families',
    'broadcast': 'Send school messages', 'publish': 'Publish courses and events',
    'push': 'Send push notifications', 'approval': 'Owner approval required',
}
DEFAULT_PERMISSIONS = {key: True for key in PERMISSIONS if key != 'approval'}

# Public family journeys never inherit the current staff session's navigation.
PUBLIC_FAMILY_PATHS = re.compile(
    r'^/(?:group-classes|group-registration|enrollment-order|trial-enrollment|trial|trial_form|trial_request|registration)(?:/|$)'
)


def ensure_schema(conn):
    statements = [
        '''CREATE TABLE IF NOT EXISTS director_access (
            user_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0,
            permissions TEXT NOT NULL, updated_by TEXT, updated_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS school_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL, image_url TEXT, signup_url TEXT,
            event_details TEXT, author_id INTEGER NOT NULL, status TEXT NOT NULL,
            recipients TEXT NOT NULL, push_requested INTEGER DEFAULT 0,
            created_at TEXT, published_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS school_deliveries (
            post_id INTEGER NOT NULL, parent_id INTEGER NOT NULL, thread_id INTEGER,
            push_state TEXT DEFAULT 'not_requested', PRIMARY KEY(post_id, parent_id))''',
        '''CREATE TABLE IF NOT EXISTS school_thread_state (
            thread_id INTEGER PRIMARY KEY, handled INTEGER DEFAULT 0,
            last_read_id INTEGER DEFAULT 0, updated_by TEXT)''',
        '''CREATE TABLE IF NOT EXISTS school_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT,
            target TEXT, details TEXT, created_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS director_migrations (name TEXT PRIMARY KEY)''',
    ]
    for sql in statements:
        conn.execute(sql)
    # One-time grant to the existing teacher account only. Never re-grant after revocation.
    if not conn.execute("SELECT 1 FROM director_migrations WHERE name='xueyang_v1'").fetchone():
        matches = conn.execute('''SELECT u.id FROM users u JOIN teachers t
            ON t.teacher_name=u.linked_teacher_name
            WHERE u.role='teacher' AND LOWER(TRIM(t.teacher_name))='xueyang wang'
            AND COALESCE(t.active,1)=1''').fetchall()
        if len(matches) == 1:
            conn.execute('''INSERT OR IGNORE INTO director_access
                (user_id,enabled,permissions,updated_by,updated_at) VALUES (?,1,?,?,?)''',
                (matches[0][0], json.dumps(DEFAULT_PERMISSIONS), 'owner-authorized setup', now()))
            conn.execute('INSERT OR IGNORE INTO director_migrations(name) VALUES (?)', ('xueyang_v1',))
            conn.execute('''INSERT INTO school_audit(actor,action,target,details,created_at)
                VALUES (?,?,?,?,?)''', ('owner-authorized setup','grant',str(matches[0][0]),
                                      json.dumps(DEFAULT_PERMISSIONS),now()))
    conn.commit()


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def safe_url(value):
    value = (value or '').strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if parsed.scheme not in ('https', 'http') or not parsed.netloc:
        abort(400, 'Use an http or https URL.')
    return value


def register_director_portal(app, api):
    lock = threading.RLock()
    ready = False

    @contextmanager
    def db():
        nonlocal ready
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            with lock:
                if not ready:
                    ensure_schema(conn)
                    ready = True
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def teacher_account(conn):
        return conn.execute('''SELECT u.id,u.linked_teacher_name FROM users u
            JOIN teachers t ON t.teacher_name=u.linked_teacher_name
            WHERE u.username=? AND u.role='teacher' AND COALESCE(t.active,1)=1''',
            (session.get('username'),)).fetchone()

    def permissions(conn):
        user = teacher_account(conn)
        if not user:
            return None, {}
        access = conn.execute('SELECT enabled,permissions FROM director_access WHERE user_id=?', (user[0],)).fetchone()
        return user, json.loads(access[1]) if access and access[0] else {}

    def authorize(permission=None):
        if api['require_owner']():
            return 0
        if session.get('user_role') != 'director' or session.get('must_change_password'):
            abort(403)
        with db() as conn:
            user, grants = permissions(conn)
        if not user or not grants or (permission and not grants.get(permission)):
            abort(403)
        return user[0]

    def audit(conn, action, target, details=''):
        conn.execute('''INSERT INTO school_audit(actor,action,target,details,created_at)
            VALUES (?,?,?,?,?)''', (session.get('username','owner'), action, str(target), details, now()))

    def page(title, content):
        owner = api['require_owner']()
        navigation = '<a href="/director">School office</a> <a href="/director/inbox">Inbox</a> <a href="/director/compose">New message / announcement</a>'
        if owner:
            navigation += ' <a href="/owner/directors">Director permissions</a> <a href="/">Owner home</a>'
        if session.get('user_role') == 'parent':
            navigation = '<a href="/parent_dashboard">Parent home</a> <a href="/parent_messages">Messages</a> <a href="/school/announcements">Courses &amp; events</a>'
        return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{escape(title)} · H-Music</title><style>
        *{{box-sizing:border-box}}body{{font:16px system-ui;background:#f3f5fa;color:#172338;margin:0}}
        main{{max-width:1000px;margin:32px auto;padding:24px}}nav{{display:flex;gap:18px;flex-wrap:wrap}}
        a{{color:#4149a5}}section,article{{background:white;padding:24px;border-radius:16px;margin:20px 0;border:1px solid #e0e5f0}}
        label{{display:block;margin:12px 0}}input:not([type=checkbox]),textarea,select{{width:100%;padding:12px;border:1px solid #bac4d6;border-radius:8px;font:inherit}}
        textarea{{min-height:180px}}button{{background:#454abb;color:white;border:0;padding:12px 18px;border-radius:8px;cursor:pointer;margin:8px 8px 0 0}}
        .body{{white-space:pre-wrap;overflow-wrap:anywhere}}.muted{{color:#64748b}}img{{max-width:100%;max-height:400px;border-radius:12px}}
        </style></head><body><main><nav>{navigation}</nav><h1>{escape(title)}</h1>{content}</main></body></html>'''

    @app.before_request
    def restrict_director_surface():
        if session.get('user_role') != 'director':
            return
        with db() as conn:
            user, grants = permissions(conn)
        if not user or not grants:
            session['user_role'] = 'teacher'
            if user:
                session['teacher_name'] = user[1]
            else:
                session.clear()
            return redirect('/teacher_dashboard' if user else '/teacher_login')
        allowed = ('/director', '/role/switch', '/teacher_logout', '/static/', '/favicon', '/hmusic-icon')
        if not request.path.startswith(allowed):
            abort(403, 'Switch to Teacher to use teacher tools.')

    @app.after_request
    def add_workspace_navigation(response):
        if PUBLIC_FAMILY_PATHS.match(request.path):
            return response
        if response.status_code != 200 or not response.content_type.startswith('text/html'):
            return response
        role = session.get('user_role')
        nav = ''
        if role == 'owner':
            nav = '<a href="/owner/directors">Director permissions</a> · <a href="/director">School office</a>'
        elif role in ('teacher', 'director'):
            with db() as conn:
                user, grants = permissions(conn)
            if user and grants and not session.get('must_change_password'):
                target = 'teacher' if role == 'director' else 'director'
                token = escape(api['hmusic_csrf_token']())
                nav = f'<form method="POST" action="/role/switch"><input type="hidden" name="_csrf_token" value="{token}"><input type="hidden" name="role" value="{target}"><button>Switch to {target.title()}</button></form>'
        elif role == 'parent':
            nav = '<a href="/school/announcements">School courses &amp; events</a>'
        if nav:
            html = response.get_data(as_text=True)
            marker = '<div style="padding:12px 20px;background:#eef0fb;color:#172338">' + nav + '</div>'
            if re.search(r'<body\b[^>]*>',html,re.IGNORECASE):
                html = re.sub(r'(<body\b[^>]*>)',lambda m: m.group(1)+marker,html,count=1,flags=re.IGNORECASE)
            else:
                html = marker + html
            response.set_data(html)
        return response

    @app.post('/role/switch')
    def switch_school_role():
        if session.get('user_role') not in ('teacher','director') or session.get('must_change_password'):
            abort(403)
        with db() as conn:
            user, grants = permissions(conn)
        target = request.form.get('role')
        if not user or target not in ('teacher','director') or (target == 'director' and not grants):
            abort(403)
        session['user_role'] = target
        if target == 'teacher':
            session['teacher_name'] = user[1]
        else:
            session.pop('teacher_name', None)
        return redirect('/director' if target == 'director' else '/teacher_dashboard')

    @app.route('/owner/directors', methods=['GET','POST'])
    def owner_directors():
        if not api['require_owner']():
            abort(403)
        with db() as conn:
            if request.method == 'POST':
                user_id = request.form.get('user_id', type=int)
                user = conn.execute("SELECT id FROM users WHERE id=? AND role='teacher'", (user_id,)).fetchone()
                if not user:
                    abort(400)
                grants = {key: request.form.get(key) == '1' for key in PERMISSIONS}
                enabled = int(request.form.get('enabled') == '1')
                conn.execute('''INSERT INTO director_access(user_id,enabled,permissions,updated_by,updated_at)
                    VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,
                    permissions=excluded.permissions,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                    (user_id,enabled,json.dumps(grants),session.get('username'),now()))
                audit(conn, 'permissions', user_id, json.dumps({'enabled': enabled, **grants}))
            rows = conn.execute('''SELECT u.id,u.display_name,u.linked_teacher_name,u.username,
                COALESCE(d.enabled,0),d.permissions FROM users u LEFT JOIN director_access d ON d.user_id=u.id
                WHERE u.role='teacher' ORDER BY u.linked_teacher_name''').fetchall()
            audit_rows = conn.execute('SELECT actor,action,target,created_at FROM school_audit ORDER BY id DESC LIMIT 30').fetchall()
        forms = ''
        for uid, name, teacher, username, enabled, raw in rows:
            grants = json.loads(raw) if raw else DEFAULT_PERMISSIONS
            checks = ''.join(f'<label><input type="checkbox" name="{key}" value="1" {"checked" if grants.get(key) else ""}> {label}</label>' for key,label in PERMISSIONS.items())
            forms += f'''<section><h2>{escape(teacher or name or username)}</h2><p>{escape(username or '')}</p>
            <form method="POST"><input type="hidden" name="user_id" value="{uid}">
            <label><input type="checkbox" name="enabled" value="1" {'checked' if enabled else ''}> Enable Director identity</label>
            {checks}<button>Save permissions</button></form></section>'''
        history = ''.join('<p>'+escape(' · '.join(str(x or '') for x in row))+'</p>' for row in audit_rows)
        return page('Director permissions', '<p>Teacher access is preserved. Revocation takes effect on the next request.</p>'+forms+'<section><h2>Recent activity</h2>'+history+'</section>')

    def audience(conn, form):
        mode = form.get('audience','all')
        value = (form.get('audience_value') or '').strip()
        if mode == 'selected':
            ids = form.getlist('parent_ids')
            if not ids or any(not str(x).isdigit() for x in ids):
                abort(400, 'Select at least one family.')
            rows = conn.execute('SELECT id FROM parent_profiles WHERE active=1 AND id IN ('+','.join('?' for _ in ids)+')', ids).fetchall()
        elif mode == 'all':
            rows = conn.execute('SELECT id FROM parent_profiles WHERE active=1').fetchall()
        elif mode in ('teacher','course','classroom') and value:
            column = {'teacher':'teacher','course':'course_type_name','classroom':'classroom'}[mode]
            rows = conn.execute(f'''SELECT DISTINCT p.id FROM parent_profiles p
                JOIN parent_students ps ON ps.parent_id=p.id AND ps.active=1
                JOIN schedule s ON s.student_name=ps.student_name
                WHERE p.active=1 AND s.{column}=? AND s.lesson_date>=?
                AND COALESCE(s.status,'scheduled') NOT IN ('cancelled','canceled','deleted')''',
                (value,datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat())).fetchall()
        else:
            abort(400, 'Choose a valid audience and filter value.')
        ids = sorted({r[0] for r in rows})
        if not ids:
            abort(400, 'No active families match this audience.')
        return ids

    @app.get('/director')
    def director_home():
        authorize()
        with db() as conn:
            rows = conn.execute('SELECT id,title,kind,status FROM school_posts ORDER BY id DESC LIMIT 100').fetchall()
        cards = ''.join(f'<article><a href="/director/posts/{r[0]}">{escape(r[1])}</a><p>{escape(r[2])} · {escape(r[3])}</p></article>' for r in rows)
        return page('H-Music School Office', '<p>Private family conversations, school messages, courses and events.</p>'+cards)

    @app.route('/director/compose', methods=['GET','POST'])
    def school_compose():
        authorize()
        if not api['require_owner']():
            with db() as conn:
                _, grants = permissions(conn)
            if not (grants.get('broadcast') or grants.get('publish')):
                abort(403)
        if request.method == 'POST':
            kind = request.form.get('kind')
            authorize('broadcast' if kind == 'message' else 'publish')
            if kind not in ('message','course','new_class','event'):
                abort(400)
            title = (request.form.get('title') or '').strip()
            body = (request.form.get('body') or '').strip()
            if not title or not body or len(title)>200 or len(body)>20000:
                abort(400, 'A title (up to 200 characters) and message (up to 20,000) are required.')
            push = int(request.form.get('push') == '1')
            if push:
                authorize('push')
            with db() as conn:
                ids = audience(conn, request.form)
                author = teacher_account(conn) if not api['require_owner']() else None
                cur = conn.execute('''INSERT INTO school_posts(kind,title,body,image_url,signup_url,event_details,
                    author_id,status,recipients,push_requested,created_at) VALUES (?,?,?,?,?,?,?,'draft',?,?,?)''',
                    (kind,title,body,safe_url(request.form.get('image_url')),safe_url(request.form.get('signup_url')),
                     (request.form.get('event_details') or '')[:2000],author[0] if author else 0,json.dumps(ids),push,now()))
                post_id = cur.lastrowid
                audit(conn,'draft',post_id)
            return redirect(f'/director/posts/{post_id}')
        with db() as conn:
            parents = conn.execute('SELECT id,parent_name FROM parent_profiles WHERE active=1 ORDER BY parent_name').fetchall()
            filters = {}
            for key,column in [('teacher','teacher'),('course','course_type_name'),('classroom','classroom')]:
                filters[key] = [r[0] for r in conn.execute(f'SELECT DISTINCT {column} FROM schedule WHERE {column} IS NOT NULL ORDER BY {column}').fetchall()]
        choices = ''.join(f'<label><input type="checkbox" name="parent_ids" value="{p[0]}"> {escape(p[1] or "Family")}</label>' for p in parents)
        hints = ''.join(f'<p>{key.title()}: {escape(", ".join(values))}</p>' for key,values in filters.items())
        return page('Compose school update', f'''<section><form method="POST">
        <label>Type<select name="kind"><option value="message">School message</option><option value="course">Course</option><option value="new_class">New class</option><option value="event">Event</option></select></label>
        <label>Title<input name="title" maxlength="200" required></label><label>Message<textarea name="body" maxlength="20000" required></textarea></label>
        <label>Date, time and location<input name="event_details"></label><label>Image URL<input name="image_url" type="url"></label>
        <label>Registration link<input name="signup_url" type="url"></label>
        <label>Audience<select name="audience"><option value="all">All active families</option><option value="selected">Selected families below</option><option value="teacher">Teacher (upcoming lessons)</option><option value="course">Course (upcoming lessons)</option><option value="classroom">Classroom (upcoming lessons)</option></select></label>
        <label>Exact filter value<input name="audience_value"></label><details><summary>Available filters</summary>{hints}</details>
        <details><summary>Select individual families</summary>{choices}</details>
        <label><input type="checkbox" name="push" value="1"> Request push notification</label>
        <button>Save draft &amp; preview</button></form></section>''')

    def post_record(conn, post_id):
        row = conn.execute('''SELECT id,kind,title,body,image_url,signup_url,event_details,author_id,
            status,recipients,push_requested FROM school_posts WHERE id=?''', (post_id,)).fetchone()
        if not row:
            abort(404)
        return row

    def post_content(row):
        image = f'<img src="{escape(row[4],quote=True)}" alt="School update">' if row[4] else ''
        link = f'<p><a rel="noopener" href="{escape(row[5],quote=True)}">Registration / more information</a></p>' if row[5] else ''
        return f'<article><h2>{escape(row[2])}</h2>{image}<p>{escape(row[6] or "")}</p><div class="body">{escape(row[3])}</div>{link}</article>'

    def dispatch_push(post_id):
        with db() as conn:
            row = post_record(conn,post_id)
            deliveries = conn.execute("SELECT parent_id,thread_id FROM school_deliveries WHERE post_id=? AND push_state IN ('pending','failed')",(post_id,)).fetchall()
        for parent_id, thread_id in deliveries:
            url = f'/message_thread/{thread_id}' if row[1] == 'message' else f'/school/announcements/{post_id}'
            try:
                queued = api['queue_notification_delivery']('parent',str(parent_id),row[2],row[3][:500],url,
                    'push',related_type='school_post',related_id=post_id)
                state = 'queued' if queued else 'unavailable'
            except Exception:
                app.logger.exception('School update push queue failed')
                state = 'failed'
            with db() as conn:
                conn.execute('UPDATE school_deliveries SET push_state=? WHERE post_id=? AND parent_id=?',(state,post_id,parent_id))

    @app.route('/director/posts/<int:post_id>', methods=['GET','POST'])
    def school_post(post_id):
        authorize()
        with db() as conn:
            row = post_record(conn,post_id)
            user, grants = permissions(conn) if not api['require_owner']() else (None,{})
            owner = api['require_owner']()
            can_edit = owner or (user and row[7] == user[0])
            if not can_edit and row[8] != 'published':
                abort(403)
        if request.method == 'POST':
            authorize('broadcast' if row[1] == 'message' else 'publish')
            if not can_edit:
                abort(403)
            action = request.form.get('action')
            if row[10] and action in ('submit','publish','retry'):
                authorize('push')
            if action not in ('submit','publish','retry','delete','save'):
                abort(400)
            with lock, db() as conn:
                row = post_record(conn,post_id)
                if action == 'save':
                    if row[8] not in ('draft','pending'):
                        abort(409)
                    title = (request.form.get('title') or '').strip()
                    body = (request.form.get('body') or '').strip()
                    if not title or not body or len(title)>200 or len(body)>20000:
                        abort(400)
                    conn.execute("UPDATE school_posts SET title=?,body=?,status='draft' WHERE id=?",(title,body,post_id))
                    audit(conn,'edit',post_id)
                    return redirect(f'/director/posts/{post_id}')
                if action == 'delete':
                    if row[8] not in ('draft','pending'):
                        abort(409)
                    conn.execute("UPDATE school_posts SET status='discarded' WHERE id=?",(post_id,))
                    audit(conn,'discard',post_id)
                    return redirect('/director')
                if action == 'submit':
                    if row[8] != 'draft':
                        abort(409)
                    conn.execute("UPDATE school_posts SET status='pending' WHERE id=?",(post_id,))
                    audit(conn,'submit',post_id)
                elif action == 'publish':
                    if not owner and grants.get('approval'):
                        abort(403, 'Owner approval required.')
                    if row[8] not in ('draft','pending','published'):
                        abort(409)
                    if row[8] != 'published':
                        # Conditional claim protects against duplicate publish across processes.
                        claimed = conn.execute("UPDATE school_posts SET status='publishing' WHERE id=? AND status IN ('draft','pending')",(post_id,))
                        if claimed.rowcount != 1:
                            abort(409)
                        for parent_id in json.loads(row[9]):
                            active = conn.execute('SELECT parent_name FROM parent_profiles WHERE id=? AND active=1',(parent_id,)).fetchone()
                            if not active:
                                continue
                            thread_id = None
                            if row[1] == 'message':
                                cur = conn.execute('''INSERT INTO message_threads(subject,parent_id,thread_type,is_group,
                                    owner_observer,related_type,related_id,status,created_at,updated_at)
                                    VALUES (?,?,'school',0,1,'school_post',?,'open',?,?)''',(row[2],parent_id,post_id,now(),now()))
                                thread_id = cur.lastrowid
                                api['sync_thread_default_participants'](conn.cursor(),thread_id,parent_id,None,owner_observer=1)
                                conn.execute('''INSERT INTO messages(thread_id,sender_role,sender_name,recipient_role,body,channel,created_at)
                                    VALUES (?,'owner','H-Music School Office','participants',?,'in_app',?)''',(thread_id,'\n\n'.join(value for value in (row[3],row[6],row[4],row[5]) if value),now()))
                            conn.execute('INSERT INTO school_deliveries(post_id,parent_id,thread_id,push_state) VALUES (?,?,?,?)',
                                (post_id,parent_id,thread_id,'pending' if row[10] else 'not_requested'))
                            url = f'/message_thread/{thread_id}' if thread_id else f'/school/announcements/{post_id}'
                            conn.execute('''INSERT INTO notifications(user_role,user_key,title,body,link_url,related_type,related_id,created_at)
                                VALUES ('parent',?,?,?,?, 'school_post',?,?)''',(str(parent_id),row[2],row[3][:500],url,post_id,now()))
                        conn.execute("UPDATE school_posts SET status='published',published_at=? WHERE id=?",(now(),post_id))
                        audit(conn,'publish',post_id)
                elif row[8] != 'published':
                    abort(409)
            if action in ('publish','retry') and row[10]:
                dispatch_push(post_id)
            return redirect(f'/director/posts/{post_id}')
        with db() as conn:
            names = []
            for pid in json.loads(row[9]):
                p = conn.execute('SELECT parent_name FROM parent_profiles WHERE id=?',(pid,)).fetchone()
                names.append(p[0] or str(pid) if p else str(pid))
            states = conn.execute('SELECT push_state,COUNT(*) FROM school_deliveries WHERE post_id=? GROUP BY push_state',(post_id,)).fetchall()
        controls = ''
        if can_edit and row[8] in ('draft','pending'):
            controls = f'<form method="POST"><label>Title<input name="title" value="{escape(row[2],quote=True)}" maxlength="200"></label><label>Message<textarea name="body" maxlength="20000">{escape(row[3])}</textarea></label><button name="action" value="save">Save changes &amp; preview again</button></form>'
            controls += '<form method="POST"><button name="action" value="submit">Submit for Owner review</button>'
            if owner or not grants.get('approval'):
                controls += '<button name="action" value="publish">Confirm publish / send</button>'
            controls += '<button name="action" value="delete">Discard draft</button></form>'
        elif can_edit and row[8] == 'published' and row[10]:
            controls = f'<form method="POST"><label>Title<input name="title" value="{escape(row[2],quote=True)}" maxlength="200"></label><label>Message<textarea name="body" maxlength="20000">{escape(row[3])}</textarea></label><button name="action" value="save">Save changes &amp; preview again</button></form>'
            controls += '<form method="POST"><button name="action" value="retry">Retry failed push queue requests</button></form>'
        status = escape(', '.join(f'{key}: {count}' for key,count in states))
        return page('Preview school update', f'<p>Status: {escape(row[8])} · Push requested: {bool(row[10])}</p>'+post_content(row)+
            f'<section><h2>Recipients ({len(names)})</h2><p>{escape(", ".join(names))}</p><p>Each family receives a private copy. Inactive families are skipped at publication.</p><p>{status}</p><p>Queued means added to the existing notification queue. Phone lock-screen delivery requires a connected push provider; the current CRM has in-app notifications only.</p>{controls}</section>')

    @app.get('/director/inbox')
    def school_inbox():
        authorize('inbox')
        with db() as conn:
            rows = conn.execute('''SELECT t.id,t.subject,p.parent_name,COALESCE(s.handled,0),
                (SELECT COUNT(*) FROM messages m WHERE m.thread_id=t.id AND m.sender_role='parent'
                 AND m.id>COALESCE(s.last_read_id,0)) FROM message_threads t
                JOIN parent_profiles p ON p.id=t.parent_id
                LEFT JOIN school_thread_state s ON s.thread_id=t.id
                WHERE (t.thread_type='parent_director' OR EXISTS (SELECT 1 FROM school_deliveries d WHERE d.thread_id=t.id)) ORDER BY t.updated_at DESC,t.id DESC''').fetchall()
        cards = ''.join(f'<article><a href="/director/inbox/{r[0]}">{escape(r[1])}</a><p>{escape(r[2] or "Family")} · {"Handled" if r[3] and not r[4] else "Needs attention"} · {r[4]} new replies</p></article>' for r in rows)
        return page('School inbox', cards or '<p>No school conversations yet.</p>')

    @app.route('/director/inbox/<int:thread_id>', methods=['GET','POST'])
    def school_conversation(thread_id):
        authorize('inbox')
        with db() as conn:
            thread = conn.execute('''SELECT t.subject FROM message_threads t WHERE t.id=? AND t.parent_id IS NOT NULL
                AND (t.thread_type='parent_director' OR EXISTS (SELECT 1 FROM school_deliveries d WHERE d.thread_id=t.id))''',(thread_id,)).fetchone()
            if not thread:
                abort(404)
            if request.method == 'POST':
                action = request.form.get('action')
                if action == 'reply':
                    authorize('reply')
                    body = (request.form.get('body') or '').strip()
                    if not body or len(body)>20000:
                        abort(400)
                    conn.execute('''INSERT INTO messages(thread_id,sender_role,sender_name,recipient_role,body,channel,created_at)
                        VALUES (?,'owner','H-Music School Office','participants',?,'in_app',?)''',(thread_id,body,now()))
                    conn.execute('UPDATE message_threads SET updated_at=? WHERE id=?',(now(),thread_id))
                    parent_id = conn.execute('SELECT parent_id FROM message_threads WHERE id=?',(thread_id,)).fetchone()[0]
                    conn.execute('''INSERT INTO notifications(user_role,user_key,title,body,link_url,created_at)
                        VALUES ('parent',?,'School office reply',?,?,?)''',(str(parent_id),body[:500],f'/message_thread/{thread_id}',now()))
                    audit(conn,'reply',thread_id)
                elif action != 'handled':
                    abort(400)
                max_id = conn.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE thread_id=?',(thread_id,)).fetchone()[0]
                conn.execute('''INSERT INTO school_thread_state(thread_id,handled,last_read_id,updated_by)
                    VALUES (?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET handled=excluded.handled,
                    last_read_id=excluded.last_read_id,updated_by=excluded.updated_by''',
                    (thread_id,int(action=='handled'),max_id,session.get('username')))
                audit(conn,action,thread_id)
                return redirect(f'/director/inbox/{thread_id}')
            messages = conn.execute('SELECT sender_name,body FROM messages WHERE thread_id=? ORDER BY id',(thread_id,)).fetchall()
            attachments = conn.execute('''SELECT a.id,a.original_filename FROM message_attachments a
                JOIN messages m ON m.id=a.message_id WHERE m.thread_id=? ORDER BY a.id''',(thread_id,)).fetchall()
        content = ''.join(f'<article><strong>{escape(m[0] or "Family")}</strong><p class="body">{escape(m[1] or "")}</p></article>' for m in messages)
        content += ''.join(f'<p><a href="/director/attachments/{a[0]}">{escape(a[1] or "Attachment")}</a></p>' for a in attachments)
        content += '<section><form method="POST"><textarea name="body" placeholder="Reply as H-Music School Office"></textarea><button name="action" value="reply">Send reply</button><button name="action" value="handled">Mark handled</button></form></section>'
        return page(thread[0],content)

    @app.get('/school/announcements')
    @app.get('/school/announcements/<int:post_id>')
    def family_announcements(post_id=None):
        if session.get('user_role') != 'parent' or not session.get('parent_id'):
            abort(403)
        with db() as conn:
            rows = conn.execute('''SELECT p.id FROM school_posts p JOIN school_deliveries d ON d.post_id=p.id
                WHERE d.parent_id=? AND p.status='published' AND p.kind!='message' ORDER BY p.id DESC''',
                (session['parent_id'],)).fetchall()
            ids = [r[0] for r in rows]
            if post_id is not None and post_id not in ids:
                abort(404)
            posts = [post_record(conn,pid) for pid in ([post_id] if post_id else ids)]
        content = ''.join(post_content(row) for row in posts) or '<p>No school announcements yet.</p>'
        return page('School courses & events', '<a href="/parent_dashboard">Parent home</a>'+content)

    @app.get('/director/attachments/<int:attachment_id>')
    def school_attachment(attachment_id):
        authorize('inbox')
        with db() as conn:
            attachment = conn.execute('''SELECT a.stored_filename,a.original_filename,a.mime_type
                FROM message_attachments a JOIN messages m ON m.id=a.message_id
                JOIN message_threads t ON t.id=m.thread_id WHERE a.id=? AND t.parent_id IS NOT NULL
                AND (t.thread_type='parent_director' OR EXISTS (SELECT 1 FROM school_deliveries d WHERE d.thread_id=t.id))''',(attachment_id,)).fetchone()
            if not attachment:
                abort(404)
            # Deployment supports database-backed attachments as well as disk/object storage.
            if 'get_message_upload_s3_config' in api:
                encoded = conn.execute('SELECT content_base64 FROM message_attachments WHERE id=?',(attachment_id,)).fetchone()[0]
                if encoded:
                    import base64
                    response = Response(base64.b64decode(encoded),mimetype=attachment[2])
                    response.headers.set('Content-Disposition','attachment',filename=attachment[1])
                    response.headers['X-Content-Type-Options'] = 'nosniff'
                    response.headers['Cache-Control'] = 'private, no-store'
                    return response
                config = api['get_message_upload_s3_config']()
                if config:
                    key = api['message_upload_s3_key'](config,attachment[0])
                    client = api['message_upload_s3_client'](config)
                    return redirect(client.generate_presigned_url('get_object',Params={'Bucket':config['bucket'],'Key':key},ExpiresIn=300))
        return send_from_directory(api['HMUSIC_UPLOAD_DIR'],attachment[0],as_attachment=True,download_name=attachment[1])
