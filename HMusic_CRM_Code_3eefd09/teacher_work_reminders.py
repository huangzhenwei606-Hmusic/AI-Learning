"""Manager-initiated teacher SMS/email reminders with immutable previews and send claims."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import secrets
import threading
from zoneinfo import ZoneInfo
from flask import abort, make_response, redirect, render_template_string, request, url_for

LA = ZoneInfo('America/Los_Angeles')
UTC = timezone.utc
KINDS = {'new_lesson': 'New lesson', 'time_change': 'Schedule changed', 'work_reminder': 'Work reminder'}


def register_teacher_work_reminders(app, api):
    lock = threading.Lock()
    ready = False

    def fail(code, text):
        abort(make_response(render_template_string(ERROR, error=text), code))

    def owner():
        if not api['require_owner']():
            fail(403, 'Manager login required')

    @contextmanager
    def db():
        nonlocal ready
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            with lock:
                if not ready:
                    conn.cursor().execute('''CREATE TABLE IF NOT EXISTS teacher_work_reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE,
                        teacher_id INTEGER NOT NULL, kind TEXT NOT NULL, snapshot TEXT NOT NULL,
                        payload TEXT NOT NULL, results TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL, sent_at TEXT
                    )''')
                    conn.commit()
                    ready = True
            yield conn, conn.cursor()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def teachers(cursor):
        cursor.execute("SELECT id,teacher_name,COALESCE(email,''),COALESCE(phone,'') FROM teachers WHERE COALESCE(active,1)=1 ORDER BY teacher_name")
        return [dict(id=r[0], name=r[1], email=r[2], phone=r[3]) for r in cursor.fetchall()]

    def teacher(cursor, tid):
        person = next((t for t in teachers(cursor) if t['id'] == tid), None)
        if not person:
            fail(400, 'Choose an active teacher')
        return person

    def lesson(cursor, sid, name, row=None):
        if row is None:
            cursor.execute('''SELECT id,student_name,teacher,lesson_date,lesson_time,duration,
                COALESCE(location,''),COALESCE(classroom,''),COALESCE(status,'scheduled'),
                COALESCE(course_type_name,''),COALESCE(is_group,0) FROM schedule WHERE id=?''', (sid,))
            row = cursor.fetchone()
        r = row
        if not r or r[2] != name:
            fail(400, 'A lesson does not belong to the selected teacher')
        try:
            start = datetime.fromisoformat(str(r[3])+'T'+str(r[4])).replace(tzinfo=LA)
        except (ValueError, TypeError):
            fail(400, 'The lesson needs a valid date and time')
        if r[8] != 'scheduled' or start <= datetime.now(LA):
            fail(409, 'Choose an upcoming scheduled lesson')
        student = r[1] or 'Group lesson'
        if r[10]:
            cursor.execute("SELECT student_name FROM group_schedule_students WHERE schedule_id=? AND COALESCE(attendance_status,'scheduled')='scheduled' ORDER BY student_name", (sid,))
            student = ', '.join(str(row[0]) for row in cursor.fetchall() if row[0]) or student
        end = start + timedelta(minutes=int(r[5] or 30))
        return dict(id=r[0], student=student, teacher=name, date=str(r[3]), time=str(r[4]),
                    duration=int(r[5] or 30), location=r[6], room=r[7], course=r[9],
                    display=start.strftime('%a %b %d, %Y · %I:%M %p')+'–'+end.strftime('%I:%M %p %Z'))

    def destinations(person, channels):
        result = {}
        for channel in channels:
            if channel == 'sms':
                dest = api['hmusic_normalize_sms_phone'](person['phone'])
                configured = api['sms_config_status']()[0]
            elif channel == 'email':
                dest = person['email'].strip()
                configured = api['smtp_config_status']()[0]
                if not api['hmusic_is_real_email'](dest):
                    dest = None
            else:
                fail(400, 'Choose SMS, email, or both')
            if not dest:
                fail(400, f"{person['name']} needs a valid {'mobile number' if channel == 'sms' else 'email address'} in Teachers before sending")
            if not configured:
                fail(503, f"{'SMS' if channel == 'sms' else 'Email'} service is not configured. Choose another channel or contact the manager.")
            result[channel] = dest
        return result

    @app.route('/manager/teacher-work-reminders', methods=['GET', 'POST'])
    def teacher_work_reminders():
        owner()
        try:
            tid = int(request.values.get('teacher_id') or 0)
        except ValueError:
            fail(400, 'Choose a valid teacher')
        if request.method == 'POST':
            kind = request.form.get('kind', '')
            channels = sorted(set(request.form.getlist('channels')))
            if kind not in KINDS or not channels or len(channels)>2:
                fail(400, 'Choose a reminder type and at least one delivery channel')
            try:
                ids = sorted(set(int(x) for x in request.form.getlist('lesson_ids')))
            except ValueError:
                fail(400, 'Choose valid lessons')
            if not 1 <= len(ids) <= 20 or (kind == 'time_change' and len(ids) != 1):
                fail(400, 'Select 1–20 lessons. A time-change reminder must have exactly one lesson.')
            note = request.form.get('note', '').strip()
            if len(note)>500:
                fail(400, 'Keep the manager note to 500 characters or fewer')
            previous = None
            if kind == 'time_change':
                try:
                    previous = datetime.fromisoformat(request.form.get('old_date','')+'T'+request.form.get('old_time','')).replace(tzinfo=LA)
                except ValueError:
                    fail(400, 'Enter the previous lesson date and time for the change notice')
            now = datetime.now(UTC)
            with db() as (_, cursor):
                person = teacher(cursor, tid)
                contact = destinations(person, channels)
                lessons = [lesson(cursor, sid, person['name']) for sid in ids]
                if previous and previous == datetime.fromisoformat(lessons[0]['date']+'T'+lessons[0]['time']).replace(tzinfo=LA):
                    fail(400, 'Previous time and new time are the same')
                body = 'Hi '+person['name']+',\n'
                if previous:
                    body += 'Previous time (provided by manager): '+previous.strftime('%a %b %d, %Y · %I:%M %p %Z')+'\n'
                for item in lessons:
                    body += '\nStudent: '+item['student']+'\n'+('New time: ' if previous else 'Time: ')+item['display']+'\nCourse: '+(item['course'] or 'Lesson')+' · '+str(item['duration'])+' min\nLocation: '+(item['location'] or 'H-Music Studio')+' · '+(item['room'] or 'Room TBD')+'\n'
                if note:
                    body += '\nManager note: '+note+'\n'
                body += '\nPlease review your teacher calendar.'
                title = KINDS[kind]
                payload = {c: dict(destination=d, title=title, body=body+('\nReply STOP to opt out.' if c=='sms' else '')) for c,d in contact.items()}
                if 'sms' in payload and len('H-Music: '+title+'\n'+payload['sms']['body'])>1500:
                    fail(400, 'SMS is too long. Select fewer lessons or use email.')
                token = secrets.token_urlsafe(32)
                snapshot = dict(teacher=person, lessons=lessons, channels=channels)
                cursor.execute('''INSERT INTO teacher_work_reminders(token,teacher_id,kind,snapshot,payload,created_at,expires_at)
                    VALUES(?,?,?,?,?,?,?)''', (token,tid,kind,json.dumps(snapshot,sort_keys=True),json.dumps(payload,sort_keys=True),now.isoformat(),(now+timedelta(minutes=15)).isoformat()))
            return redirect(url_for('teacher_work_reminder_review',token=token))

        start = request.args.get('start') or datetime.now(LA).date().isoformat()
        end = request.args.get('end') or (datetime.now(LA).date()+timedelta(days=45)).isoformat()
        try:
            if datetime.fromisoformat(start)>datetime.fromisoformat(end):
                raise ValueError()
        except ValueError:
            fail(400, 'Choose a valid date range')
        with db() as (_, cursor):
            people = teachers(cursor)
            person = teacher(cursor, tid) if tid else None
            lessons = []
            if person:
                cursor.execute("SELECT id,student_name,teacher,lesson_date,lesson_time,duration,COALESCE(location,''),COALESCE(classroom,''),COALESCE(status,'scheduled'),COALESCE(course_type_name,''),COALESCE(is_group,0) FROM schedule WHERE teacher=? AND lesson_date>=? AND lesson_date<=? AND COALESCE(status,'scheduled')='scheduled' ORDER BY lesson_date,lesson_time,id LIMIT 501",(person['name'],start,end))
                for row in cursor.fetchall():
                    # Past lessons today are omitted rather than blocking the list.
                    try:
                        lessons.append(lesson(cursor,row[0],person['name'],row))
                    except Exception as exc:
                        if getattr(exc,'code',None) != 409:
                            raise
                lessons = lessons[:500]
            cursor.execute("SELECT kind,status,results,created_at FROM teacher_work_reminders WHERE teacher_id=? AND status!='draft' ORDER BY id DESC LIMIT 20",(tid,))
            history=[dict(kind=KINDS.get(r[0],r[0]),status=r[1],results=json.loads(r[2]),created=r[3]) for r in cursor.fetchall()]
        return render_template_string(PAGE,people=people,person=person,lessons=lessons,history=history,start=start,end=end,kinds=KINDS,
                                      sms_ready=api['sms_config_status']()[0],email_ready=api['smtp_config_status']()[0])

    @app.route('/manager/teacher-work-reminders/review/<token>',methods=['GET','POST'])
    def teacher_work_reminder_review(token):
        owner()
        with db() as (conn,cursor):
            cursor.execute('SELECT id,teacher_id,snapshot,payload,status,expires_at,results FROM teacher_work_reminders WHERE token=?',(token,))
            row=cursor.fetchone()
            if not row:
                fail(404,'Preview not found')
            rid,tid,snapshot,payload,status,expires,results=row
            snapshot,payload,results=json.loads(snapshot),json.loads(payload),json.loads(results)
            if request.method=='POST' and status=='draft':
                if datetime.fromisoformat(expires)<=datetime.now(UTC):
                    fail(409,'Preview expired. Create a new preview.')
                current_teacher=teacher(cursor,tid)
                current_lessons=[lesson(cursor,x['id'],current_teacher['name']) for x in snapshot['lessons']]
                if current_teacher!=snapshot['teacher'] or current_lessons!=snapshot['lessons']:
                    fail(409,'The lesson or teacher contact changed. Create a new preview before sending.')
                destinations(current_teacher,snapshot['channels'])
                # Lock the teacher to serialize duplicate drafts as well as repeated clicks.
                cursor.execute('UPDATE teachers SET id=id WHERE id=?',(tid,))
                cutoff=(datetime.now(UTC)-timedelta(minutes=10)).isoformat()
                cursor.execute("SELECT payload,results,status FROM teacher_work_reminders WHERE teacher_id=? AND status IN ('sending','sent','partial','unconfirmed') AND sent_at>=? AND id!=?",(tid,cutoff,rid))
                for old_payload,old_results,old_status in cursor.fetchall():
                    old_payload,old_results=json.loads(old_payload),json.loads(old_results)
                    for channel,item in payload.items():
                        if old_payload.get(channel)==item and (old_status=='sending' or old_results.get(channel,{}).get('status') in ('accepted','unconfirmed')):
                            fail(409,'This reminder was recently submitted for '+channel+'. Check recent history or choose another channel.')
                cursor.execute("UPDATE teacher_work_reminders SET status='sending',sent_at=? WHERE id=? AND status='draft'",(datetime.now(UTC).isoformat(),rid))
                if cursor.rowcount!=1:
                    fail(409,'This reminder is already being sent')
                conn.commit()
                status='sending'
                for channel,item in payload.items():
                    try:
                        sent,detail=api['send_sms_delivery' if channel=='sms' else 'send_email_delivery'](item['destination'],item['title'],item['body'],'')
                        state='accepted' if sent else 'failed'
                    except Exception:
                        state,detail='unconfirmed','Delivery outcome unknown. Check the provider before sending again.'
                    results[channel]=dict(status=state,detail=str(detail)[:1000])
                    cursor.execute('UPDATE teacher_work_reminders SET results=? WHERE id=?',(json.dumps(results),rid))
                    conn.commit()
                status='sent' if all(r['status']=='accepted' for r in results.values()) else 'partial' if any(r['status']=='accepted' for r in results.values()) else 'unconfirmed'
                cursor.execute('UPDATE teacher_work_reminders SET status=? WHERE id=?',(status,rid))
        return render_template_string(REVIEW,token=token,person=snapshot['teacher'],payload=payload,status=status,results=results)

    @app.after_request
    def teacher_reminder_button(response):
        if request.endpoint in ('teacher_work_reminders','teacher_work_reminder_review'):
            response.headers['Cache-Control']='no-store'
        if request.endpoint in ('calendar','teachers','parent_booking_request_review') and response.status_code==200 and response.mimetype=='text/html' and api['require_owner']():
            html=response.get_data(as_text=True)
            button='<div style="padding:10px 20px;background:#eef4ff"><a style="display:inline-block;padding:10px 16px;background:#1f6fb8;color:white;border-radius:8px;text-decoration:none;font-weight:700" href="/manager/teacher-work-reminders">Send teacher work reminder · SMS / email</a></div>'
            import re
            response.set_data(re.sub(r'(<body\b[^>]*>)',lambda m:m.group(1)+button,html,count=1,flags=re.I))
        return response


STYLE='''<style>*{box-sizing:border-box}body{font:15px system-ui;background:#f6f7fb;color:#172235;margin:0;padding:24px}.wrap{max-width:1000px;margin:auto}.card{background:white;border:1px solid #dce2ea;border-radius:14px;padding:24px;margin-bottom:18px}h1{margin-top:0}label{display:block;margin:12px 0 5px}input,select,textarea{font:inherit;padding:10px;border:1px solid #cbd2dd;border-radius:8px;max-width:100%}select,textarea{width:100%}input[type=checkbox]{width:auto}button,.button{display:inline-block;font:inherit;font-weight:700;padding:11px 16px;background:#1f6fb8;color:white;border:0;border-radius:8px;text-decoration:none;cursor:pointer}button:disabled{opacity:.5}pre{white-space:pre-wrap;font:inherit;background:#f3f6fa;padding:16px;border-radius:8px}.muted{color:#5d6c80}.lesson{display:block;padding:10px;background:#f5f7fb;border-radius:8px}.row{display:flex;gap:16px;flex-wrap:wrap}.error{color:#a12020}fieldset{border:1px solid #dce2ea;border-radius:8px;margin:16px 0}a{color:#155d9e}</style>'''
ERROR='<!doctype html><html><head><title>Teacher work reminder</title>'+STYLE+'</head><body><main class="wrap card"><h1>Cannot send reminder</h1><p role="alert">{{error}}</p><a href="/manager/teacher-work-reminders">Back to teacher reminders</a></main></body></html>'
PAGE='''<!doctype html><html><head><title>Teacher work reminders</title>'''+STYLE+'''</head><body><main class="wrap"><section class="card"><h1>Teacher work reminders</h1><p>Send a new-lesson, changed-time or work reminder directly to a teacher by SMS or email.</p><a href="/calendar">Back to calendar</a><form method="get"><label for="teacher_id">Teacher</label><select name="teacher_id" id="teacher_id" required><option value="">Select teacher</option>{% for t in people %}<option value="{{t.id}}" {% if person and person.id==t.id %}selected{% endif %}>{{t.name}}</option>{% endfor %}</select><div class="row"><label>From <input type="date" name="start" value="{{start}}" required></label><label>Through <input type="date" name="end" value="{{end}}" required></label></div><button>Load lessons</button></form></section>
{% if person %}<form class="card" method="post"><input type="hidden" name="teacher_id" value="{{person.id}}"><h2>Reminder for {{person.name}}</h2><p>Mobile: {{person.phone or 'Missing — add it in Teachers'}}<br>Email: {{person.email or 'Missing — add it in Teachers'}}</p><label for="kind">Reminder type</label><select id="kind" name="kind" required><option value="">Choose reminder type</option>{% for k,v in kinds.items() %}<option value="{{k}}">{{v}}</option>{% endfor %}</select><fieldset><legend>Delivery channel</legend><label><input type="checkbox" name="channels" value="sms" {% if not sms_ready or not person.phone %}disabled{% endif %}> Mobile SMS {% if not sms_ready %}— service not configured{% endif %}</label><label><input type="checkbox" name="channels" value="email" {% if not email_ready or not person.email %}disabled{% endif %}> Email {% if not email_ready %}— service not configured{% endif %}</label></fieldset><fieldset><legend>Upcoming lessons · select up to 20</legend>{% for l in lessons %}<label class="lesson"><input type="checkbox" name="lesson_ids" value="{{l.id}}"> {{l.student}} · {{l.display}}<br>{{l.course}} · {{l.location}} · {{l.room}}</label>{% else %}<p>No upcoming scheduled lessons in this range.</p>{% endfor %}</fieldset><fieldset id="previous-time" hidden><legend>Previous time · Pacific time</legend><p class="muted">Select exactly one lesson above. Its current calendar time is the new time. Enter the original time below; it is not inferred from the calendar.</p><div class="row"><label>Previous date <input type="date" name="old_date"></label><label>Previous time <input type="time" name="old_time"></label></div></fieldset><label for="note">Manager note · optional</label><textarea name="note" id="note" maxlength="500" rows="3"></textarea><p>Preview the teacher, destination and exact message before sending. This reminder does not edit the schedule or billing.</p><button {% if not lessons %}disabled{% endif %}>Preview reminder</button></form><section class="card"><h2>Recent sends</h2>{% for h in history %}<p>{{h.created}} · {{h.kind}} · {{h.status}}</p>{% for c,r in h.results.items() %}<p>{{c}}: {{r.status}} — {{r.detail}}</p>{% endfor %}{% else %}<p>No reminders sent yet.</p>{% endfor %}</section>{% endif %}</main><script>const kind=document.getElementById('kind');if(kind){function updatePrevious(){const changed=kind.value==='time_change';const fields=document.getElementById('previous-time');fields.hidden=!changed;for(const input of fields.querySelectorAll('input'))input.required=changed;}kind.addEventListener('change',updatePrevious);updatePrevious();}</script></body></html>'''
REVIEW='''<!doctype html><html><head><title>Review teacher reminder</title>'''+STYLE+'''</head><body><main class="wrap card"><h1>Teacher work reminder · {{person.name}}</h1><p role="status">Status: {{status}}</p>{% for channel,item in payload.items() %}<h2>{{'Mobile SMS' if channel=='sms' else 'Email'}} → {{item.destination}}</h2><p>Subject: {{item.title}}</p><pre>{% if channel=='sms' %}H-Music: {{item.title}}\n{% endif %}{{item.body}}</pre>{% if channel in results %}<p>{{results[channel].status}} — {{results[channel].detail}}</p>{% endif %}{% endfor %}{% if status=='draft' %}<form method="post"><button>Send reminder now</button></form><p>SMS acceptance confirms submission to the provider, not handset delivery.</p>{% elif status=='sending' %}<p>Sending is in progress or the previous attempt needs review. Do not resend until you check the result.</p>{% endif %}<p><a href="/manager/teacher-work-reminders?teacher_id={{person.id}}">Back to teacher reminders</a> · <a href="/calendar">Calendar</a></p></main></body></html>'''
