"""A lesson-scoped parent composer using the existing message delivery pipeline."""
import re
from flask import abort, jsonify, request


def register_calendar_parent_message(app, api):
    def owner():
        if not api['require_owner']():
            abort(403)

    def context(sid):
        api['ensure_v29_schema']()
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            cur = conn.cursor()
            cur.execute('SELECT student_name,teacher,lesson_date,lesson_time,COALESCE(is_group,0) FROM schedule WHERE id=?', (sid,))
            lesson = cur.fetchone()
            if not lesson:
                abort(404)
            names = [lesson[0]] if lesson[0] else []
            if lesson[4]:
                roster = api['calendar_group_roster'](cur, sid, api['calendar_lesson_row'](cur, sid))
                names = sorted({r['student_name'] for r in roster if r.get('student_name')})
            recipients = []
            for name in names:
                cur.execute('''SELECT p.id,p.parent_name,p.email,p.phone FROM parent_students ps
                    JOIN parent_profiles p ON p.id=ps.parent_id
                    WHERE ps.student_name=? AND COALESCE(ps.active,1)=1 AND COALESCE(p.active,1)=1 ORDER BY p.id''', (name,))
                for pid, parent, email, phone in cur.fetchall():
                    recipients.append(dict(id=pid, name=parent or 'Parent', email=email or '', phone=phone or '', student=name))
            return dict(student=lesson[0] or 'Group lesson', teacher=lesson[1], date=lesson[2], time=lesson[3]), recipients
        finally:
            conn.close()

    @app.get('/api/calendar-parent-message/<int:sid>')
    def calendar_parent_message_context(sid):
        owner()
        lesson, parents = context(sid)
        return jsonify(ok=True, lesson=lesson, parents=parents,
                       email_ready=bool(api['smtp_config_status']()[0]), sms_ready=bool(api['sms_config_status']()[0]))

    @app.post('/api/calendar-parent-message/<int:sid>')
    def calendar_parent_message_send(sid):
        owner()
        payload = request.get_json(silent=True) or {}
        lesson, parents = context(sid)
        body = str(payload.get('body') or '').strip()
        channels = payload.get('channels')
        if not body or len(body) > 10000:
            return jsonify(ok=False, error='Enter a message (up to 10,000 characters).'), 400
        if not isinstance(channels, list) or any(c not in ('email', 'sms') for c in channels):
            return jsonify(ok=False, error='Choose Email and/or Mobile SMS.'), 400
        recipient = next((p for p in parents if str(p['id']) == str(payload.get('parent_id')) and p['student'] == payload.get('student')), None)
        if not recipient:
            return jsonify(ok=False, error='This parent is no longer linked to this student. Reopen the composer.'), 409
        api['validate_message_channels'](api, 'parent', recipient['id'], channels)
        token = str(payload.get('token') or '')
        if not re.fullmatch(r'[a-f0-9-]{32,36}', token):
            return jsonify(ok=False, error='Reopen the composer before sending.'), 400
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            cur = conn.cursor()
            cur.execute('CREATE TABLE IF NOT EXISTS calendar_parent_message_submissions (token TEXT PRIMARY KEY, schedule_id INTEGER, parent_id INTEGER, thread_id INTEGER)')
            cur.execute('INSERT OR IGNORE INTO calendar_parent_message_submissions(token,schedule_id,parent_id) VALUES(?,?,?)', (token,sid,recipient['id']))
            claimed = cur.rowcount == 1
            cur.execute('SELECT schedule_id,parent_id,thread_id FROM calendar_parent_message_submissions WHERE token=?', (token,))
            prior = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
        if not claimed:
            if prior[:2] == (sid,recipient['id']) and prior[2]:
                return jsonify(ok=True, message='Already saved. Review delivery in the conversation.', thread_url=f'/message_thread/{prior[2]}')
            return jsonify(ok=False, error='This send was already submitted. Check Messages before sending again.'), 409
        subject = f"Message about {recipient['student']} · {lesson['date']}"
        tid = api['get_or_create_message_thread'](subject, student_name=recipient['student'], parent_id=recipient['id'], teacher_name=None, thread_type='owner_parent')
        mid = api['add_message'](tid, 'owner', 'Manager', 'parent', body)
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            conn.execute('UPDATE calendar_parent_message_submissions SET thread_id=? WHERE token=?', (tid,token))
            conn.commit()
        finally:
            conn.close()
        # Once saved, never invite a blind resend on a notification/provider error.
        try:
            api['create_notification']('parent', str(recipient['id']), 'New message from H-Music', body,
                f'/message_thread/{tid}', related_type='message', related_id=mid, send_email_now=True, delivery_channels=channels)
            status = 'Saved in the parent app. ' + ('Delivery details are available in the conversation.' if channels else 'No Email/SMS selected.')
        except Exception:
            status = 'Saved in the parent app. Notification delivery needs review in the conversation; do not resend.'
        return jsonify(ok=True, message=status, thread_url=f'/message_thread/{tid}')

    @app.after_request
    def calendar_parent_message_assets(response):
        if request.path.startswith('/api/calendar-parent-message/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.endpoint == 'calendar' and response.status_code == 200 and response.mimetype == 'text/html' and api['require_owner']():
            assets = '<link rel="stylesheet" href="/static/calendar_parent_message.css?v=1"><script defer src="/static/calendar_parent_message.js?v=1"></script>'
            response.set_data(response.get_data(as_text=True).replace('</head>', assets + '</head>', 1))
        return response
