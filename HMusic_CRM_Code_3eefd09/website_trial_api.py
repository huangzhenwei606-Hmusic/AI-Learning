"""Public school-site intake. No parent-session privileges or client-supplied recipients."""
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

PATH = '/api/website/trial'
ORIGINS = {'https://www.hmusicandart.com', 'https://hmusicandart.com', 'https://hmusic-website.onrender.com'}
DESTINATION = 'info@h-musicandarts.com'


def register_website_trial_api(app, services, db_path='hmusic.db'):
    def connect():
        return sqlite3.connect(db_path, timeout=10)

    def schema(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS website_trial_submissions (
            request_key TEXT PRIMARY KEY, client_hash TEXT NOT NULL,
            created_at TEXT NOT NULL, inquiry_id INTEGER, notification_id INTEGER
        )''')
        conn.commit()

    @app.after_request
    def website_cors(response):
        if request.path == PATH:
            response.headers['Cache-Control'] = 'no-store'
            response.vary.add('Origin')
            if request.headers.get('Origin') in ORIGINS:
                response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
                response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    @app.route(PATH, methods=['POST', 'OPTIONS'])
    def website_trial_submit():
        if request.headers.get('Origin') not in ORIGINS:
            return jsonify(error='origin_not_allowed'), 403
        if request.method == 'OPTIONS':
            return '', 204
        if (request.content_length or 0) > 12000:
            return jsonify(error='request_too_large'), 413
        if not request.is_json:
            return jsonify(error='json_required'), 415
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='invalid_request'), 400
        # Quietly refuse bot honeypot submissions without writing or emailing.
        if body.get('website'):
            return jsonify(error='invalid_request'), 400
        limits = {'parent': 100, 'email': 150, 'student': 80, 'age': 5,
                  'program': 100, 'location': 80, 'notes': 1500}
        values = {}
        for field, limit in limits.items():
            value = body.get(field, '')
            if not isinstance(value, str) or len(value) > limit:
                return jsonify(error='invalid_field', field=field), 400
            values[field] = value.strip()
        if any(not values[k] for k in limits):
            return jsonify(error='missing_fields'), 400
        if not re.fullmatch(r'[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]+', values['email']):
            return jsonify(error='invalid_email'), 400
        if any('\n' in values[k] or '\r' in values[k] for k in ['student', 'parent', 'email']):
            return jsonify(error='invalid_name'), 400
        try:
            age = float(values['age'])
            if not 1 <= age <= 100:
                raise ValueError()
        except ValueError:
            return jsonify(error='invalid_age'), 400
        key = body.get('request_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{20,80}', key):
            return jsonify(error='invalid_request_key'), 400
        data = {
            'student_name': values['student'], 'parent_name': values['parent'],
            'parent_email': values['email'], 'age': values['age'],
            'program_interest': values['program'], 'trial_location': values['location'],
            'notes': values['notes'], 'preferred_times': values['notes'],
            'trial_duration': '30 mins', 'trial_fee': '$30',
            'source': 'H-Music & Art Website', 'lead_temperature': 'Warm',
        }
        now = datetime.now(timezone.utc)
        # X-Forwarded-For is not accepted here: clients must not choose the rate-limit key.
        client_hash = hashlib.sha256(((request.remote_addr or 'unknown') + '|' + values['email'].casefold()).encode()).hexdigest()
        conn = connect()
        try:
            schema(conn)
            existing = conn.execute('SELECT inquiry_id FROM website_trial_submissions WHERE request_key = ?', (key,)).fetchone()
            if existing:
                return (jsonify(ok=True, request_id=existing[0]), 200) if existing[0] else (jsonify(error='processing'), 409)
            count = conn.execute('SELECT COUNT(*) FROM website_trial_submissions WHERE client_hash = ? AND created_at > ?',
                                 (client_hash, (now-timedelta(hours=1)).isoformat())).fetchone()[0]
            if count >= 10:
                return jsonify(error='too_many_requests'), 429
            inserted = conn.execute('INSERT INTO website_trial_submissions (request_key, client_hash, created_at) VALUES (?, ?, ?) ON CONFLICT(request_key) DO NOTHING',
                                    (key, client_hash, now.isoformat()))
            conn.commit()
            if inserted.rowcount != 1:
                return jsonify(error='processing'), 409
            try:
                inquiry_id = services['v35_insert_trial_lead'](data, public=True)
            except Exception:
                conn.execute('DELETE FROM website_trial_submissions WHERE request_key = ? AND inquiry_id IS NULL', (key,))
                conn.commit()
                app.logger.exception('Website intake could not save request')
                return jsonify(error='save_failed'), 503
            conn.execute('UPDATE website_trial_submissions SET inquiry_id = ? WHERE request_key = ?', (inquiry_id, key))
            conn.commit()
            try:
                message = '\n'.join([
                    'New trial request submitted through www.hmusicandart.com',
                    f'Request #{inquiry_id}', f"Parent: {values['parent']}",
                    f"Email: {values['email']}", f"Student: {values['student']}",
                    f"Age: {values['age']}", f"Program: {values['program']}",
                    f"Location preference: {values['location']}", 'Trial: $30 / 30 minutes',
                    'Instrument, experience and preferred times:', values['notes'],
                    'This is a request, not a confirmed booking or payment.',
                ])
                queue_id = services['queue_direct_delivery']('email', DESTINATION,
                    f"Website trial request #{inquiry_id} — {values['student']}", message,
                    f'https://hmusic-crm.onrender.com/inquiry/{inquiry_id}',
                    related_type='website_trial', related_id=inquiry_id)
                conn.execute('UPDATE website_trial_submissions SET notification_id = ? WHERE request_key = ?', (queue_id, key))
                conn.commit()
                if queue_id:
                    services['send_queued_email_now'](queue_id)
            except Exception:
                # Intake remains in CRM even if SMTP is temporarily unavailable.
                app.logger.exception('Website intake saved; email notification needs review for inquiry %s', inquiry_id)
            return jsonify(ok=True, request_id=inquiry_id), 201
        finally:
            conn.close()
