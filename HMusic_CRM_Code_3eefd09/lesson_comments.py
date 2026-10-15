"""Private, per-lesson staff conversations shared by owners and assigned teachers."""
from contextlib import contextmanager
from datetime import datetime, timezone
import threading

from flask import abort, jsonify, make_response, request, session


def ensure_schema(conn):
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS lesson_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL,
        parent_id INTEGER,
        author_key TEXT NOT NULL,
        author_name TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        edited_at TEXT,
        revision INTEGER NOT NULL DEFAULT 1
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS lesson_comment_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL,
        comment_id INTEGER NOT NULL
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS lesson_comment_reads (
        schedule_id INTEGER NOT NULL,
        user_key TEXT NOT NULL,
        last_event_id INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (schedule_id, user_key)
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS lesson_comments_schedule ON lesson_comments (schedule_id, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS lesson_comment_events_schedule ON lesson_comment_events (schedule_id, id)")
    conn.commit()


def install_lesson_comments(app, api):
    lock = threading.Lock()
    ready = False

    def fail(code, description):
        abort(make_response(jsonify(ok=False, error=description), code))

    def json_body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            fail(400, description='Expected a JSON object')
        return data

    def identity():
        if api['require_owner']():
            return 'owner', 'Owner'
        if session.get('user_role') == 'teacher' and session.get('teacher_name'):
            name = str(session['teacher_name']).strip()
            return 'teacher:' + name.casefold(), name
        fail(401, description='Staff login required')

    @contextmanager
    def database():
        nonlocal ready
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            with lock:
                if not ready:
                    ensure_schema(conn)
                    ready = True
            yield conn, conn.cursor()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def authorize(cursor, schedule_id, user_key, write=False):
        if write:
            # Serialize changes for this lesson so event IDs have commit order.
            # Never change attendance, credits, or recurring-series configuration.
            cursor.execute('UPDATE schedule SET id = id WHERE id = ?', (schedule_id,))
        cursor.execute('SELECT student_name, teacher, lesson_date, lesson_time, duration FROM schedule WHERE id = ?', (schedule_id,))
        row = cursor.fetchone()
        if not row:
            fail(404, description='Lesson not found')
        if user_key != 'owner' and not api['hmusic_teacher_name_matches'](row[1], session.get('teacher_name')):
            fail(403, description='Only this lesson\'s teacher and the owner can view its comments')
        return {'id': schedule_id, 'student': row[0] or 'Lesson', 'teacher': row[1] or '',
                'date': row[2] or '', 'time': row[3] or '', 'duration': row[4] or 30}

    def body_text(data):
        body = data.get('body')
        if not isinstance(body, str) or not body.strip():
            fail(400, description='Enter a comment')
        if len(body) > 5000:
            fail(400, description='Comments may contain up to 5,000 characters')
        return body.strip()

    def event_id(cursor, schedule_id):
        cursor.execute('SELECT COALESCE(MAX(id), 0) FROM lesson_comment_events WHERE schedule_id = ?', (schedule_id,))
        return int(cursor.fetchone()[0])

    @app.route('/api/lesson-comments/summary')
    def lesson_comments_summary():
        user_key, _ = identity()
        raw_ids = request.args.get('ids', '')
        try:
            ids = list(dict.fromkeys(int(value) for value in raw_ids.split(',') if value))
        except ValueError:
            fail(400, description='Invalid lesson IDs')
        if len(ids) > 300 or any(value < 1 for value in ids):
            fail(400, description='Request up to 300 lessons at a time')
        if not ids:
            return {'ok': True, 'lessons': {}}
        placeholders = ','.join('?' for _ in ids)
        with database() as (_, cursor):
            cursor.execute(f'SELECT id, teacher FROM schedule WHERE id IN ({placeholders})', ids)
            allowed = [row[0] for row in cursor.fetchall() if user_key == 'owner' or api['hmusic_teacher_name_matches'](row[1], session.get('teacher_name'))]
            result = {}
            if allowed:
                placeholders = ','.join('?' for _ in allowed)
                cursor.execute(f"""SELECT s.id,
                    (SELECT COUNT(*) FROM lesson_comments c WHERE c.schedule_id = s.id),
                    (SELECT COALESCE(MAX(e.id),0) FROM lesson_comment_events e WHERE e.schedule_id = s.id),
                    COALESCE(r.last_event_id,0)
                    FROM schedule s LEFT JOIN lesson_comment_reads r
                    ON r.schedule_id = s.id AND r.user_key = ?
                    WHERE s.id IN ({placeholders})""", [user_key] + allowed)
                result = {str(row[0]): {'count': int(row[1]), 'unread': row[2] > row[3]} for row in cursor.fetchall()}
        return {'ok': True, 'lessons': result}

    @app.route('/api/lesson-comments/<int:schedule_id>', methods=['GET', 'POST'])
    def lesson_comments_thread(schedule_id):
        user_key, name = identity()
        with database() as (_, cursor):
            lesson = authorize(cursor, schedule_id, user_key, write=request.method == 'POST')
            if request.method == 'POST':
                data = json_body()
                body = body_text(data)
                parent_id = data.get('parent_id')
                if parent_id is not None:
                    if type(parent_id) is not int:
                        fail(400, description='Invalid reply')
                    cursor.execute('SELECT id, parent_id FROM lesson_comments WHERE id = ? AND schedule_id = ?', (parent_id, schedule_id))
                    parent = cursor.fetchone()
                    if not parent:
                        fail(400, description='Reply must belong to this lesson')
                    parent_id = parent[1] or parent[0]
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute('INSERT INTO lesson_comments (schedule_id,parent_id,author_key,author_name,body,created_at) VALUES (?,?,?,?,?,?)',
                               (schedule_id, parent_id, user_key, name, body, now))
                comment_id = cursor.lastrowid
                cursor.execute('INSERT INTO lesson_comment_events (schedule_id,comment_id) VALUES (?,?)', (schedule_id, comment_id))
                return {'ok': True, 'id': comment_id}, 201
            # Capture the read boundary BEFORE loading content. A concurrent new
            # comment/edit can remain unread, but can never be accidentally hidden.
            boundary = event_id(cursor, schedule_id)
            cursor.execute('SELECT id,parent_id,author_name,body,created_at,edited_at,revision,author_key FROM lesson_comments WHERE schedule_id = ? ORDER BY id', (schedule_id,))
            comments = [{'id': r[0], 'parent_id': r[1], 'author': r[2], 'body': r[3],
                         'created_at': r[4], 'edited_at': r[5], 'revision': r[6], 'can_edit': r[7] == user_key}
                        for r in cursor.fetchall()]
            return {'ok': True, 'lesson': lesson, 'comments': comments, 'event_id': boundary}

    @app.route('/api/lesson-comments/<int:schedule_id>/<int:comment_id>', methods=['PATCH'])
    def lesson_comments_edit(schedule_id, comment_id):
        user_key, _ = identity()
        data = json_body()
        body = body_text(data)
        with database() as (_, cursor):
            authorize(cursor, schedule_id, user_key, write=True)
            cursor.execute('SELECT author_key, revision FROM lesson_comments WHERE id = ? AND schedule_id = ?', (comment_id, schedule_id))
            row = cursor.fetchone()
            if not row:
                fail(404, description='Comment not found')
            if row[0] != user_key:
                fail(403, description='You can only edit your own comments')
            if data.get('revision') != row[1]:
                fail(409, description='This comment changed. Refresh the conversation before editing again.')
            cursor.execute('UPDATE lesson_comments SET body = ?, edited_at = ?, revision = revision + 1 WHERE id = ?',
                           (body, datetime.now(timezone.utc).isoformat(), comment_id))
            cursor.execute('INSERT INTO lesson_comment_events (schedule_id,comment_id) VALUES (?,?)', (schedule_id, comment_id))
        return {'ok': True}

    @app.route('/api/lesson-comments/<int:schedule_id>/read', methods=['POST'])
    def lesson_comments_read(schedule_id):
        user_key, _ = identity()
        boundary = (json_body()).get('event_id')
        if type(boundary) is not int or boundary < 0:
            fail(400, description='Invalid read marker')
        with database() as (_, cursor):
            authorize(cursor, schedule_id, user_key)
            boundary = min(boundary, event_id(cursor, schedule_id))
            cursor.execute("""INSERT INTO lesson_comment_reads (schedule_id,user_key,last_event_id) VALUES (?,?,?)
                ON CONFLICT (schedule_id,user_key) DO UPDATE SET last_event_id =
                CASE WHEN lesson_comment_reads.last_event_id > excluded.last_event_id
                THEN lesson_comment_reads.last_event_id ELSE excluded.last_event_id END""", (schedule_id, user_key, boundary))
        return {'ok': True}

    @app.after_request
    def lesson_comments_response(response):
        if request.path.startswith('/api/lesson-comments'):
            if response.status_code >= 400 and not response.is_json:
                # Keep errors usable by both browser and native clients.
                from werkzeug.exceptions import default_exceptions
                code = response.status_code
                message = default_exceptions.get(code)
                response = jsonify(ok=False, error=(message.description if message else 'Unable to load comments'))
                response.status_code = code
            response.headers['Cache-Control'] = 'no-store'
        if (request.endpoint in {'calendar', 'teacher_dashboard'} and response.status_code == 200
                and response.mimetype == 'text/html' and (api['require_owner']() or session.get('user_role') == 'teacher')):
            html = response.get_data(as_text=True)
            assets = '<link rel="stylesheet" href="/static/lesson_comments.css?v=1"><script defer src="/static/lesson_comments.js?v=1"></script>'
            html = html.replace('</head>', assets + '</head>', 1) if '</head>' in html else html + assets
            response.set_data(html)
        return response
