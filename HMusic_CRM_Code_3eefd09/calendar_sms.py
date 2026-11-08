"""Explicit owner-selected SMS reminders, with preview snapshots and send claims."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import re
import secrets
import threading

from flask import abort, jsonify, make_response, request

LA = ZoneInfo('America/Los_Angeles')
UTC = timezone.utc


def register_calendar_sms(app, api):
    lock = threading.Lock()
    ready = False

    def fail(code, message):
        abort(make_response(jsonify(ok=False, error=message), code))

    def owner():
        if not api['require_owner']():
            fail(403, 'Manager login required')

    @contextmanager
    def database():
        nonlocal ready
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            with lock:
                if not ready:
                    api['ensure_calendar_lesson_panel_schema']()
                    api['ensure_parent_portal_feature_schema']()
                    conn.cursor().execute('''CREATE TABLE IF NOT EXISTS calendar_sms_reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token TEXT NOT NULL UNIQUE,
                        schedule_id INTEGER NOT NULL,
                        parent_id INTEGER NOT NULL,
                        destination TEXT NOT NULL,
                        body TEXT NOT NULL,
                        snapshot TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'draft',
                        provider_response TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        sent_at TEXT
                    )''')
                    conn.cursor().execute('CREATE INDEX IF NOT EXISTS calendar_sms_lesson ON calendar_sms_reminders(schedule_id, id)')
                    conn.commit()
                    ready = True
            yield conn, conn.cursor()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def context(cursor, sid):
        cursor.execute('''SELECT student_name,teacher,lesson_date,lesson_time,duration,
            location,classroom,COALESCE(status,'scheduled'),COALESCE(is_group,0)
            FROM schedule WHERE id=?''', (sid,))
        row = cursor.fetchone()
        if not row:
            fail(404, 'Lesson not found')
        student, teacher, day, time, duration, location, room, status, group = row
        try:
            start = datetime.fromisoformat(str(day) + 'T' + str(time)).replace(tzinfo=LA)
            end = start + timedelta(minutes=int(duration or 30))
        except (ValueError, TypeError):
            fail(400, 'This lesson needs a valid date and time before sending a reminder')
        if status != 'scheduled' or start <= datetime.now(LA):
            fail(409, 'Only upcoming scheduled lessons can receive a reminder')
        students = [student] if student else []
        if group:
            roster = api['calendar_group_roster'](cursor, sid, api['calendar_lesson_row'](cursor, sid))
            students = [r['student_name'] for r in roster if r.get('attendance_status', 'scheduled') == 'scheduled']
        info = dict(student=student or 'Group lesson', teacher=teacher or 'TBD', date=str(day),
                    time=start.strftime('%I:%M %p') + '–' + end.strftime('%I:%M %p %Z'),
                    location=location or 'H-Music Studio', room=room or 'TBD', students=sorted(set(students)))
        return info

    def parents(cursor, info):
        if not info['students']:
            return []
        marks = ','.join('?' for _ in info['students'])
        cursor.execute(f'''SELECT DISTINCT p.id,p.parent_name,p.phone,ps.student_name,
                COALESCE(pref.lesson_reminders,1)
            FROM parent_profiles p JOIN parent_students ps ON ps.parent_id=p.id
            LEFT JOIN parent_notification_preferences pref ON pref.parent_id=p.id
            WHERE ps.student_name IN ({marks}) AND ps.active=1 AND COALESCE(p.active,1)=1
            ORDER BY p.id,ps.student_name''', tuple(info['students']))
        people = {}
        for pid, name, phone, student, allowed in cursor.fetchall():
            normalized = api['hmusic_normalize_sms_phone'](phone)
            person = people.setdefault(pid, dict(id=pid, name=name or 'Parent', phone=normalized or str(phone or ''),
                available=bool(normalized) and bool(allowed), reason='' if normalized and allowed else
                'Lesson reminders opted out' if not allowed else 'Missing or invalid mobile number', students=[]))
            person['students'].append(student)
        return list(people.values())

    def message(info, person, note):
        text = ('Hi ' + person['name'] + ',\nLesson reminder for ' + ', '.join(person['students']) +
            '\nDate: ' + info['date'] + '\nTime: ' + info['time'] + '\nTeacher: ' + info['teacher'] +
            '\nLocation: ' + info['location'] + '\nRoom: ' + info['room'])
        if note:
            text += '\n' + note
        # This is exactly the prefix used by the existing SMS transport.
        return 'H-Music: Lesson reminder\n' + text + '\nReply STOP to opt out.'

    @app.get('/api/calendar-sms/lessons')
    def calendar_sms_lessons():
        owner()
        month = request.args.get('month', datetime.now(LA).strftime('%Y-%m'))
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            fail(400, 'Choose a calendar month')
        try:
            first = datetime.strptime(month, '%Y-%m').date()
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        except ValueError:
            fail(400, 'Choose a valid calendar month')
        teacher = request.args.get('teacher', '').strip()
        student = api['hmusic_clean_student_picker_value'](request.args.get('student', ''))
        with database() as (_, cursor):
            sql = "SELECT id,student_name,teacher,lesson_date,lesson_time FROM schedule WHERE lesson_date>=? AND lesson_date<? AND COALESCE(status,'scheduled')='scheduled'"
            args = [max(str(first), datetime.now(LA).date().isoformat()), str(last)]
            if teacher:
                sql += ' AND teacher=?'; args.append(teacher)
            if student:
                sql += ' AND (student_name=? OR id IN (SELECT schedule_id FROM group_schedule_students WHERE student_name=?))'
                args.extend([student, student])
            cursor.execute(sql + ' ORDER BY lesson_date,lesson_time,id LIMIT 501', tuple(args))
            result = []
            for sid, name, teacher_name, day, time in cursor.fetchall():
                try:
                    future = datetime.fromisoformat(str(day)+'T'+str(time)).replace(tzinfo=LA) > datetime.now(LA)
                except ValueError:
                    continue
                if future:
                    result.append(dict(id=sid, label=f'{day} {time} · {name or "Group lesson"} · {teacher_name or "TBD"}'))
        return jsonify(ok=True, lessons=result[:500], truncated=len(result)>500)

    @app.get('/api/calendar-sms/lesson/<int:sid>')
    def calendar_sms_lesson(sid):
        owner()
        with database() as (_, cursor):
            info = context(cursor, sid)
            people = parents(cursor, info)
            cursor.execute("SELECT parent_id,destination,status,provider_response,created_at FROM calendar_sms_reminders WHERE schedule_id=? AND status!='draft' ORDER BY id DESC LIMIT 30", (sid,))
            history = [dict(parent_id=r[0], phone=r[1], status=r[2], detail=r[3], created_at=r[4]) for r in cursor.fetchall()]
        available, _ = api['sms_config_status']()
        return jsonify(ok=True, lesson=info, parents=people, sms_ready=available, history=history)

    @app.post('/api/calendar-sms/lesson/<int:sid>/preview')
    def calendar_sms_preview(sid):
        owner()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            fail(400, 'Expected a JSON object')
        ids, note = data.get('parent_ids'), data.get('note', '')
        if not isinstance(ids, list) or not ids or len(ids)>20 or any(type(pid) is not int for pid in ids):
            fail(400, 'Select between 1 and 20 parents')
        if not isinstance(note, str) or len(note)>400:
            fail(400, 'Additional note must be 400 characters or fewer')
        available, _ = api['sms_config_status']()
        if not available:
            fail(503, 'SMS service is not configured. Contact the manager.')
        now = datetime.now(UTC)
        with database() as (_, cursor):
            info = context(cursor, sid)
            people = {p['id']:p for p in parents(cursor, info) if p['available']}
            if not set(ids)<=people.keys():
                fail(400, 'A selected parent is unlinked, opted out or has no valid mobile number')
            # One message per phone, even when two parent profiles share it.
            by_phone = {}
            for pid in sorted(set(ids)):
                p = people[pid]
                if p['phone'] in by_phone:
                    prior = by_phone[p['phone']]
                    prior['students'] = sorted(set(prior['students'] + p['students']))
                else:
                    by_phone[p['phone']] = dict(p, students=list(p['students']))
            previews = []
            for p in by_phone.values():
                text = message(info, p, note.strip())
                if len(text)>1500:
                    fail(400, 'Message is too long; shorten the note or reduce recipients')
                recipient_snapshot = [people[pid] for pid in sorted(set(ids)) if people[pid]['phone'] == p['phone']]
                token = secrets.token_urlsafe(32)
                cursor.execute('''INSERT INTO calendar_sms_reminders
                    (token,schedule_id,parent_id,destination,body,snapshot,status,created_at,expires_at)
                    VALUES (?,?,?,?,?,?,'draft',?,?)''', (token, sid, p['id'], p['phone'], text,
                    json.dumps(dict(lesson=info, parents=recipient_snapshot), sort_keys=True), now.isoformat(), (now+timedelta(minutes=15)).isoformat()))
                previews.append(dict(token=token, name=p['name'], phone=p['phone'], body=text))
        return jsonify(ok=True, previews=previews)

    @app.post('/api/calendar-sms/send/<token>')
    def calendar_sms_send(token):
        owner()
        with database() as (conn, cursor):
            cursor.execute('SELECT id,schedule_id,parent_id,destination,body,snapshot,status,expires_at,provider_response FROM calendar_sms_reminders WHERE token=?', (token,))
            row = cursor.fetchone()
            if not row:
                fail(404, 'Preview not found. Review the reminder again.')
            rid, sid, pid, phone, body, snapshot, status, expires, detail = row
            if status != 'draft':
                return jsonify(ok=True, status=status, detail=detail, phone=phone)
            if datetime.fromisoformat(expires) <= datetime.now(UTC):
                fail(409, 'Preview expired. Review the reminder again.')
            info = context(cursor, sid)
            expected = json.loads(snapshot)
            current_people = {p['id']:p for p in parents(cursor, info)}
            current = [current_people.get(p['id']) for p in expected['parents']]
            if (info != expected['lesson'] or current != expected['parents']
                    or any(not p or not p['available'] or p['phone'] != phone for p in current)):
                fail(409, 'Lesson or recipient details changed. Review the reminder again.')
            available, _ = api['sms_config_status']()
            if not available:
                fail(503, 'SMS service is not configured')
            # Serialize sends for this lesson, then block rapid duplicate previews.
            cursor.execute('UPDATE schedule SET id=id WHERE id=?', (sid,))
            cutoff = (datetime.now(UTC)-timedelta(minutes=10)).isoformat()
            cursor.execute("SELECT id FROM calendar_sms_reminders WHERE schedule_id=? AND destination=? AND body=? AND status IN ('sending','accepted','unconfirmed') AND COALESCE(sent_at,created_at)>=? AND id!=?", (sid, phone, body, cutoff, rid))
            if cursor.fetchone():
                fail(409, 'This reminder was recently submitted for this phone. Check history before sending again.')
            cursor.execute("UPDATE calendar_sms_reminders SET status='sending',sent_at=? WHERE id=? AND status='draft'", (datetime.now(UTC).isoformat(), rid))
            if cursor.rowcount != 1:
                fail(409, 'This reminder is already being sent')
            conn.commit()
        try:
            # Prefix is already visible in the preview; pass only the remaining body.
            accepted, detail = api['send_sms_delivery'](phone, 'Lesson reminder', body.split('\n',1)[1], '')
        except Exception:
            accepted, detail = False, 'Outcome unknown. Check SMS provider records before sending another reminder.'
        state = 'accepted' if accepted else 'unconfirmed'
        with database() as (_, cursor):
            cursor.execute('UPDATE calendar_sms_reminders SET status=?,provider_response=?,sent_at=? WHERE id=?',
                (state, str(detail)[:1000], datetime.now(UTC).isoformat(), rid))
        return jsonify(ok=True, status=state, phone=phone, detail=str(detail))

    @app.after_request
    def calendar_sms_assets(response):
        if request.path.startswith('/api/calendar-sms/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.endpoint == 'calendar' and response.status_code == 200 and response.mimetype == 'text/html' and api['require_owner']():
            html = response.get_data(as_text=True)
            assets = '<link rel="stylesheet" href="/static/calendar_sms.css?v=1"><script defer src="/static/calendar_sms.js?v=1"></script>'
            response.set_data(html.replace('</head>', assets+'</head>', 1))
        return response
