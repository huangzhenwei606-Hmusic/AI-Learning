"""Website group applications, manager review, and payment-backed roster admission.

Class sessions reference existing calendar lessons so dates and cancellations stay
in sync. All admission writes share a transaction; an application never grants
credits. The existing invoice settlement remains the only credit-granting path.
"""
import base64
import io
import warnings
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Response, Blueprint, abort, redirect, render_template, request, session, url_for

ACTIVE = ('review', 'waitlist', 'reserved', 'enrolled')


def now():
    return datetime.now(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None).isoformat(timespec='seconds')


def rows(cur):
    keys = [x[0] for x in cur.description]
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def one(cur):
    data = rows(cur)
    return data[0] if data else None


def ensure_schema(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS group_offerings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        description TEXT NOT NULL, age_range TEXT NOT NULL, policy TEXT NOT NULL,
        capacity INTEGER NOT NULL, tuition_cents INTEGER NOT NULL,
        published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS group_offering_sessions (
        offering_id INTEGER NOT NULL, schedule_id INTEGER NOT NULL UNIQUE,
        PRIMARY KEY(offering_id,schedule_id))''',
        '''CREATE TABLE IF NOT EXISTS group_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, offering_id INTEGER NOT NULL,
        student_name TEXT NOT NULL, birth_date TEXT NOT NULL, experience TEXT NOT NULL,
        parent_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
        status TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE,
        receipt_hash TEXT NOT NULL UNIQUE, policy_snapshot TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reserved_until TEXT,
        student_id INTEGER, enrollment_id INTEGER, invoice_id INTEGER, inquiry_id INTEGER)''',
        '''CREATE TABLE IF NOT EXISTS group_offering_images (offering_id INTEGER PRIMARY KEY, image_data TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS group_application_limits (bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL)''',
        '''CREATE INDEX IF NOT EXISTS idx_group_apps_offering ON group_applications(offering_id,status)''',
    ):
        conn.execute(sql)
    conn.commit()


def get_sessions(cur, offering_id):
    cur.execute('''SELECT s.id,s.lesson_date,s.lesson_time,s.duration,s.teacher,s.classroom,s.location,
        s.course_type_id,s.course_type_name,s.status,s.group_name,s.room_id,s.location_id
        FROM group_offering_sessions gs JOIN schedule s ON s.id=gs.schedule_id
        WHERE gs.offering_id=? ORDER BY s.lesson_date,s.lesson_time,s.id''', (offering_id,))
    return rows(cur)


def get_offering(cur, oid):
    cur.execute('SELECT * FROM group_offerings WHERE id=?', (oid,))
    item = one(cur)
    if item:
        cur.execute('SELECT COUNT(*) FROM group_offering_sessions WHERE offering_id=?',(oid,))
        item['session_count']=cur.fetchone()[0]
        cur.execute('SELECT updated_at FROM group_offering_images WHERE offering_id=?',(oid,))
        image=cur.fetchone()
        item['image_url'] = '/group-class-image/'+str(oid)+'?v='+image[0] if image else ''
        item['sessions'] = get_sessions(cur, oid)
        item['available_sessions'] = [s for s in item['sessions'] if str(s['status']).lower() == 'scheduled']
        item['teachers']=list(dict.fromkeys(s['teacher'] for s in item['sessions']))
        item['tuition'] = f"{item['tuition_cents']/100:.2f}"
    return item


def payment_status(cur, application):
    if not application.get('invoice_id'):
        return 'Not invoiced'
    cur.execute('SELECT status FROM invoices WHERE id=?', (application['invoice_id'],))
    r = cur.fetchone()
    return r[0] if r else 'Invoice missing'


def session_roster_names(cur, sid):
    cur.execute('SELECT student_name FROM group_schedule_students WHERE schedule_id=? ORDER BY id',(sid,))
    names=[r[0] for r in cur.fetchall()]
    if names:return names
    cur.execute('SELECT group_student_names,student_name FROM schedule WHERE id=?',(sid,))
    legacy=cur.fetchone()
    if not legacy:return []
    names=[n.strip() for n in (legacy[0] or '').split(',') if n.strip()]
    if not names and legacy[1]:
        cur.execute('SELECT name FROM students WHERE name=?',(legacy[1],))
        real_student=cur.fetchone()
        if real_student:names=[real_student[0]]
    return list(dict.fromkeys(names))


def class_roster_names(cur, oid):
    cur.execute('SELECT schedule_id FROM group_offering_sessions WHERE offering_id=?',(oid,))
    session_ids=[r[0] for r in cur.fetchall()]
    return {name.strip().lower() for sid in session_ids for name in session_roster_names(cur,sid)}


def occupied(cur, oid, exclude=None):
    """Count actual calendar participants plus live reservations, once per child."""
    names = class_roster_names(cur,oid)
    cur.execute('''SELECT a.id,a.student_name,a.status,a.reserved_until,i.status
        FROM group_applications a LEFT JOIN invoices i ON i.id=a.invoice_id
        WHERE a.offering_id=? AND a.status IN ('reserved','enrolled')''', (oid,))
    for aid, name, state, expires, paid in cur.fetchall():
        if aid == exclude:
            continue
        if state == 'enrolled' or paid in {'paid','payment_processing','stripe_processing','square_processing'} or (expires and expires > now()):
            names.add(name.strip().lower())
    return len(names)


def lock_offering(cur, oid):
    # SQLite BEGIN IMMEDIATE and PostgreSQL's row lock serialize the final seat.
    cur.execute('UPDATE group_offerings SET capacity=capacity WHERE id=?', (oid,))
    if cur.rowcount != 1:
        raise ValueError('Class not found.')


def valid_sessions(cur, offering):
    ss = offering['available_sessions']
    if not ss or len(ss) != len(offering['sessions']) or len(ss)!=offering['session_count']:
        raise ValueError('A class session was cancelled. Review the class dates before accepting enrollment.')
    if any(s['lesson_date']+'T'+s['lesson_time']+':00' <= now() for s in ss):
        raise ValueError('This class has already started. Create a remaining-session offering before enrolling a new student.')
    if len({(s['course_type_id'], s['duration']) for s in ss}) != 1:
        raise ValueError('Class course type or duration has changed. Review the calendar sessions.')
    return ss


def approve(cur, aid, student_choice, api):
    cur.execute('SELECT * FROM group_applications WHERE id=?', (aid,))
    a = one(cur)
    if not a:
        raise ValueError('Application not found.')
    lock_offering(cur, a['offering_id'])
    cur.execute('SELECT * FROM group_applications WHERE id=?', (aid,))
    a = one(cur)
    o = get_offering(cur, a['offering_id'])
    if a['status'] == 'enrolled':
        return
    if a['status'] not in ACTIVE:
        raise ValueError('This application is closed.')
    ss = valid_sessions(cur, o)
    if occupied(cur, o['id'], aid) >= o['capacity']:
        raise ValueError('This class is full. Keep this student on the waitlist.')
    if a['invoice_id']:
        cur.execute("UPDATE group_applications SET status='reserved',reserved_until=?,updated_at=? WHERE id=?",
                    ((datetime.fromisoformat(now())+timedelta(hours=48)).isoformat(), now(), aid))
        return
    if student_choice == 'new':
        cur.execute('SELECT id FROM students WHERE lower(trim(name))=lower(trim(?))', (a['student_name'],))
        if cur.fetchone():
            raise ValueError('A student with this name exists. Select their existing profile or use a unique profile name.')
        cur.execute('''INSERT INTO students(name,teacher,parent_name,parent_email,parent_phone,lessons_left)
            VALUES (?,?,?,?,?,0)''', (a['student_name'], ss[0]['teacher'], a['parent_name'], a['email'], a['phone']))
        sid = cur.lastrowid
        name = a['student_name']
    else:
        try:
            sid = int(student_choice)
        except (TypeError, ValueError):
            raise ValueError('Choose an existing student or explicitly create a new profile.')
        cur.execute('SELECT name FROM students WHERE id=?', (sid,))
        student = cur.fetchone()
        if not student:
            raise ValueError('Student profile not found.')
        name = student[0]
    cur.execute("SELECT id FROM group_applications WHERE offering_id=? AND student_id=? AND id<>? AND status IN ('reserved','enrolled')", (o['id'],sid,aid))
    if cur.fetchone():
        raise ValueError('This student already has an approved application for this class.')
    if name.strip().lower() in class_roster_names(cur,o['id']):
        raise ValueError('This student is already on the class roster. Do not create another invoice.')
    # Only a manager explicitly approving this application may establish family access.
    cur.execute('SELECT id FROM parent_profiles WHERE lower(email)=lower(?)', (a['email'],))
    parents = cur.fetchall()
    if len(parents) > 1:
        raise ValueError('Duplicate parent accounts found; review the family first.')
    if parents:
        pid = parents[0][0]
        cur.execute('SELECT active FROM parent_profiles WHERE id=?',(pid,))
        if cur.fetchone()[0] == 0:
            raise ValueError('This parent account is inactive. Review family access before approving.')
    else:
        cur.execute('''INSERT INTO parent_profiles(parent_name,email,phone,password,password_hash,
            must_change_password,active,created_at,updated_at) VALUES (?,?,?,'',?,1,1,?,?)''',
            (a['parent_name'], a['email'], a['phone'], api['hmusic_password_hash'](secrets.token_urlsafe(32)), now(), now()))
        pid = cur.lastrowid
    cur.execute('SELECT id FROM parent_students WHERE parent_id=? AND student_name=?', (pid, name))
    link = cur.fetchone()
    if link:
        cur.execute('UPDATE parent_students SET active=1 WHERE id=?', (link[0],))
    else:
        cur.execute('''INSERT INTO parent_students(parent_id,student_name,relationship,active,created_at)
            VALUES (?,?,'Parent',1,?)''', (pid, name, now()))
    # Never reuse or overwrite another course wallet, or pre-grant its credits.
    per_lesson = o['tuition_cents']/100/len(ss)
    cur.execute('''INSERT INTO enrollments(student_name,course_type_id,course_type_name,teacher_name,
        duration,student_billing_method,base_price,final_price,lessons_left,status,notes,
        package_amount,package_lessons,auto_renew_enabled,start_date,created_at,updated_at)
        VALUES (?,?,?,?,?,'Per Lesson',?,?,0,'pending',?,?,?,0,?,?,?)''',
        (name, ss[0]['course_type_id'], ss[0]['course_type_name'], ss[0]['teacher'],ss[0]['duration'],
         per_lesson,per_lesson,f"Group enrollment #{aid}: {o['title']}",o['tuition_cents']/100,len(ss),ss[0]['lesson_date'],now(),now()))
    eid = cur.lastrowid
    invoice = api['create_enrollment_invoice'](cur, eid, 'initial_tuition',
                  f"Group class: {o['title']} | Application #{aid} | {len(ss)} lessons", grant_credit_on_payment=True, attach_pending_charges=False)
    cur.execute("""UPDATE invoices SET coverage_title=?,coverage_class=?,coverage_start=?,coverage_note=? WHERE id=?""",
        (o['title'],f"{ss[0]['course_type_name']} · {ss[0]['duration']} minutes · {' & '.join(o['teachers'])}",
         ss[0]['lesson_date'],"Class dates (Pacific time):\n"+"\n".join(
             f"{s['lesson_date']} {s['lesson_time']} · {s['teacher']} · {s['location'] or ''} {s['classroom']}" for s in ss)
             +"\n"+o['description'],invoice))
    cur.execute("UPDATE group_applications SET student_id=?,student_name=?,enrollment_id=?,invoice_id=?,status='reserved',reserved_until=?,updated_at=? WHERE id=?",
        (sid,name,eid,invoice,(datetime.fromisoformat(now())+timedelta(hours=48)).isoformat(),now(),aid))


def confirm(cur, aid):
    cur.execute('SELECT * FROM group_applications WHERE id=?', (aid,))
    a = one(cur)
    if not a:
        raise ValueError('Application not found.')
    lock_offering(cur, a['offering_id'])
    cur.execute('SELECT * FROM group_applications WHERE id=?', (aid,))
    a = one(cur)
    if a['status'] == 'enrolled':
        return
    if a['status'] != 'reserved' or payment_status(cur, a) != 'paid':
        raise ValueError('Confirm admission only after the invoice is marked paid. Use Billing to verify Zelle or bank settlement.')
    o = get_offering(cur, a['offering_id'])
    ss = valid_sessions(cur, o)
    if occupied(cur, o['id'], aid) >= o['capacity']:
        raise ValueError('Class is full. Review this paid application before admission.')
    cur.execute("UPDATE enrollments SET status='active',updated_at=? WHERE id=?", (now(), a['enrollment_id']))
    for s in ss:
        # Materialize a legacy roster only when it has no structured rows yet.
        # Otherwise adding its first new member would hide existing children.
        previous_names=session_roster_names(cur,s['id'])
        cur.execute('SELECT COUNT(*) FROM group_schedule_students WHERE schedule_id=?',(s['id'],))
        if not cur.fetchone()[0]:
            for previous in previous_names:
                cur.execute("SELECT COALESCE(parent_name,'') FROM students WHERE name=?",(previous,))
                parent=cur.fetchone()
                cur.execute("""INSERT INTO group_schedule_students(schedule_id,student_name,parent_name,credit_units,
                    billing_rule,billing_status,attendance_status,attendance_credit_applied,created_at,updated_at)
                    VALUES (?,?,?,1,'existing_credits','planned','scheduled',0,?,?)""",
                    (s['id'],previous,parent[0] if parent else '',now(),now()))
        cur.execute('SELECT id FROM group_schedule_students WHERE schedule_id=? AND student_name=?', (s['id'],a['student_name']))
        if not cur.fetchone():
            cur.execute('''INSERT INTO group_schedule_students(schedule_id,student_name,parent_name,
                credit_units,student_rate,billing_rule,billing_status,attendance_status,
                attendance_credit_applied,attendance_enrollment_id,created_at,updated_at)
                VALUES (?,?,?,1,?,'existing_credits','planned','scheduled',0,?,?,?)''',
                (s['id'],a['student_name'],a['parent_name'],o['tuition_cents']/100/len(ss),a['enrollment_id'],now(),now()))
        cur.execute('SELECT student_name FROM group_schedule_students WHERE schedule_id=? ORDER BY id', (s['id'],))
        names = [r[0] for r in cur.fetchall()]
        cur.execute('UPDATE schedule SET group_student_names=?,group_size=?,owner_calendar_updated_at=? WHERE id=?',
                    (', '.join(names),len(names),now(),s['id']))
    cur.execute("UPDATE group_applications SET status='enrolled',updated_at=? WHERE id=?", (now(),aid))
    if a['inquiry_id']:
        cur.execute("UPDATE inquiries SET status='Active',converted_student_name=?,converted_enrollment_id=?,updated_at=? WHERE id=?",
                    (a['student_name'],a['enrollment_id'],now(),a['inquiry_id']))


def schedule_version(offering):
    return hashlib.sha256(json.dumps(offering['sessions'],sort_keys=True,default=str).encode()).hexdigest()


def validate_schedule_plan(cur, oid, data):
    if not isinstance(data,list) or not 1<=len(data)<=100:
        raise ValueError('Select between 1 and 100 class dates.')
    offering=get_offering(cur,oid)
    if not offering:raise ValueError('Class not found.')
    if offering['published']:raise ValueError('Close registration before editing the class calendar.')
    cur.execute('SELECT COUNT(*) FROM group_applications WHERE offering_id=?',(oid,))
    if cur.fetchone()[0]:raise ValueError('This class already has applications. Manage changes through Calendar to preserve enrollment records.')
    existing={x['id']:x for x in offering['sessions']}
    if offering['session_count']!=len(existing):raise ValueError('A linked calendar lesson is missing. Review the class first.')
    for sid,lesson in existing.items():
        if str(lesson['status']).lower()!='scheduled' or session_roster_names(cur,sid):
            raise ValueError('Only upcoming empty Scheduled class sessions can be changed here. Use Calendar for existing student lessons.')
        if lesson['lesson_date']+'T'+lesson['lesson_time']+':00'<=now():
            raise ValueError('Past class sessions cannot be changed here.')
    plan=[];dates=set();ids=set()
    for item in data:
        if not isinstance(item,dict):raise ValueError('Invalid class date.')
        try:
            day=str(item['date']);time=str(item['time']);sid=int(item.get('id') or 0)
            moment=datetime.strptime(day+' '+time,'%Y-%m-%d %H:%M')
            if moment.strftime('%Y-%m-%d %H:%M')!=day+' '+time or moment.isoformat()<=now():raise ValueError()
            room_id=int(item['room_id']);course_id=int(item['course_id']);teacher=str(item['teacher']).strip()
        except (ValueError,TypeError,KeyError):raise ValueError('Each selected date needs a future date, time, teacher, course and location/room.')
        if day in dates or (sid and sid in ids):raise ValueError('Select each class date only once.')
        if sid and sid not in existing:raise ValueError('A lesson does not belong to this class.')
        dates.add(day);ids.add(sid)
        cur.execute('SELECT teacher_name FROM teachers WHERE teacher_name=? AND active=1',(teacher,))
        if not cur.fetchone():raise ValueError('Choose an active teacher.')
        cur.execute('SELECT id,name,duration FROM course_types WHERE id=? AND is_group=1 AND active=1',(course_id,))
        course=cur.fetchone()
        if not course or not 1<=int(course[2] or 0)<=240:raise ValueError('Choose an active group course with a valid duration.')
        cur.execute("""SELECT r.room_name,r.location_id,l.location_name FROM studio_rooms r JOIN studio_locations l ON l.id=r.location_id
            WHERE r.id=? AND r.active=1 AND l.active=1""",(room_id,));room=cur.fetchone()
        if not room:raise ValueError('Choose an active location and room.')
        if moment.hour*60+moment.minute+int(course[2])>1440:raise ValueError('A class must finish before midnight.')
        plan.append(dict(id=sid,date=day,time=time,teacher=teacher,room_id=room_id,classroom=room[0],location_id=room[1],location=room[2],course_id=course_id,course_name=course[1],duration=int(course[2])))
    if len({(x['course_id'],x['duration']) for x in plan})!=1:raise ValueError('Use the same course and duration for this class package.')
    return offering,plan


def prepare_class_image(upload):
    if not upload or not upload.filename:
        raise ValueError('Choose a PNG, JPEG or WebP image.')
    data=upload.read(4*1024*1024+1)
    if len(data)>4*1024*1024:
        raise ValueError('Image exceeds 4 MB. Choose a smaller file.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>20000000:
                    raise ValueError('Use a PNG, JPEG or WebP image under 20 megapixels.')
                source.load()
                image=ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1600,1600))
                output=io.BytesIO(); image.save(output,format='JPEG',quality=85)
                return base64.b64encode(output.getvalue()).decode('ascii')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValueError('This file could not be read as a valid image.')


def register_group_enrollment(app, api):
    bp = Blueprint('group_enrollment', __name__, template_folder='templates')

    @contextmanager
    def db(write=False):
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            ensure_schema(conn)
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn
            if write:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def owner():
        if not api['require_owner']():
            abort(403)

    def page(template, **kw):
        result = app.make_response(render_template('group_enrollment/'+template, **kw))
        result.headers['Cache-Control'] = 'no-store'
        result.headers['Referrer-Policy'] = 'no-referrer'
        result.headers['X-Robots-Tag'] = 'noindex'
        return result

    @app.before_request
    def protect_group_intake_conversion():
        if request.method!='POST' or request.endpoint!='convert_inquiry_to_student' or not api['require_owner']():
            return None
        with db() as conn:
            cur=conn.cursor()
            cur.execute('SELECT id FROM group_applications WHERE inquiry_id=?',((request.view_args or {}).get('inquiry_id'),))
            application=cur.fetchone()
        if application:
            return redirect('/group-enrollments#application-'+str(application[0]),code=303)
        return None

    @bp.route('/group-classes')
    def catalog():
        with db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id FROM group_offerings WHERE published=1 ORDER BY id DESC')
            offerings = [get_offering(cur, r[0]) for r in cur.fetchall()]
            offerings = [o for o in offerings if o['available_sessions'] and len(o['available_sessions'])==o['session_count'] and o['sessions'][0]['lesson_date']+'T'+o['sessions'][0]['lesson_time']+':00'>now()]
            for o in offerings:
                o['remaining'] = max(0,o['capacity']-occupied(cur,o['id']))
        return page('catalog.html', offerings=offerings)

    @bp.route('/group-classes/<int:oid>/apply', methods=['GET','POST'])
    def apply(oid):
        error = ''
        if request.method == 'GET':
            session['group_request_key'] = secrets.token_urlsafe(24)
        try:
            with db(write=request.method=='POST') as conn:
                cur = conn.cursor()
                o = get_offering(cur, oid)
                preview=request.method=='GET' and request.args.get('preview')=='1' and api['require_owner']()
                if not o or (not o['published'] and not preview):
                    abort(404)
                o['remaining'] = max(0,o['capacity']-occupied(cur,oid))
                if request.method == 'POST':
                    if len(request.form) > 20 or request.content_length and request.content_length > 16000:
                        abort(413)
                    token = request.form.get('request_key','')
                    if not token or token != session.get('group_request_key'):
                        raise ValueError('This form expired. Reload the page and try again.')
                    raw = {k:request.form.get(k,'').strip() for k in ('student_name','birth_date','experience','parent_name','email','phone')}
                    if any(len(v)>1500 for v in raw.values()) or any(not raw[k] for k in ('student_name','parent_name','email','phone','birth_date')):
                        raise ValueError('Please complete the required student and parent information.')
                    if any('\n' in raw[k] or '\r' in raw[k] for k in ('student_name','parent_name','email','phone')) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',raw['email']):
                        raise ValueError('Enter a valid email and single-line contact details.')
                    if len(re.sub(r'\D','',raw['phone'])) < 10 or len(raw['student_name'])>100:
                        raise ValueError('Please enter a valid phone number and student name.')
                    birth = datetime.strptime(raw['birth_date'],'%Y-%m-%d')
                    today=datetime.fromisoformat(now()).date()
                    age=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))
                    if not '1900-01-01' <= raw['birth_date'] <= now()[:10]:
                        raise ValueError('Enter a valid birth date.')
                    if request.form.get('website') or request.form.get('policy_ack') != 'yes':
                        raise ValueError('Please read and acknowledge the class policy.')
                    # Receipt token is deterministic within this browser's one-time form,
                    # so retries return the same private receipt, without duplicate leads.
                    receipt = hashlib.sha256((token+app.secret_key).encode()).hexdigest()
                    digest = hashlib.sha256(receipt.encode()).hexdigest()
                    lock_offering(cur,oid)
                    cur.execute('SELECT id FROM group_applications WHERE request_key=?', (token,))
                    if cur.fetchone():
                        return redirect(url_for('group_enrollment.receipt', token=receipt),code=303)
                    cur.execute('''SELECT id FROM group_applications WHERE offering_id=?
                        AND lower(trim(student_name))=lower(?) AND lower(email)=lower(?)
                        AND status IN ('review','waitlist','reserved','enrolled')''',(oid,raw['student_name'],raw['email']))
                    if cur.fetchone():
                        raise ValueError('An application for this child and class already exists. Contact info@h-musicandarts.com for an update.')
                    cur.execute('SELECT COUNT(*) FROM group_applications WHERE email=? AND created_at>?',
                                (raw['email'].lower(),(datetime.fromisoformat(now())-timedelta(hours=1)).isoformat()))
                    if cur.fetchone()[0]>=10:
                        abort(429)
                    bucket = hashlib.sha256((str(request.remote_addr)+app.secret_key).encode()).hexdigest()+now()[:13]
                    cur.execute('INSERT OR IGNORE INTO group_application_limits(bucket,hits) VALUES (?,0)',(bucket,))
                    cur.execute('UPDATE group_application_limits SET hits=hits+1 WHERE bucket=?',(bucket,))
                    cur.execute('SELECT hits FROM group_application_limits WHERE bucket=?',(bucket,))
                    if cur.fetchone()[0]>60:
                        abort(429)
                    valid_sessions(cur,o)
                    state = 'waitlist' if occupied(cur,oid)>=o['capacity'] else 'review'
                    cur.execute('''INSERT INTO inquiries(student_name,parent_name,parent_email,phone,age,
                        program_interest,source,status,trial_status,follow_up_status,notes,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,'Website Group Enrollment','Registration Submitted','Registration','Needs Review',?,?,?)''',
                        (raw['student_name'],raw['parent_name'],raw['email'].lower(),raw['phone'],str(age),
                         'Group Class: '+o['title'],f"Group class application. Review at /group-enrollments. Class #{oid}",now(),now()))
                    inquiry = cur.lastrowid
                    cur.execute('''INSERT INTO group_applications(offering_id,student_name,birth_date,experience,
                        parent_name,email,phone,status,request_key,receipt_hash,policy_snapshot,created_at,updated_at,inquiry_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (oid,raw['student_name'],raw['birth_date'],raw['experience'],raw['parent_name'],raw['email'].lower(),raw['phone'],
                         state,token,digest,json.dumps({'policy':o['policy'],'tuition_cents':o['tuition_cents'],
                         'sessions':o['sessions']},ensure_ascii=False),now(),now(),inquiry))
                    return redirect(url_for('group_enrollment.receipt',token=receipt),code=303)
        except ValueError as exc:
            error = str(exc) if 'does not match format' not in str(exc) else 'Enter a valid birth date.'
        return page('apply.html', offering=o,error=error,values=request.form,
                    request_key=session.get('group_request_key',''))

    @bp.get('/group-registration/<token>')
    def receipt(token):
        if not re.fullmatch(r'[a-f0-9]{64}',token):
            abort(404)
        with db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM group_applications WHERE receipt_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
            a = one(cur)
            if not a:
                abort(404)
            o = get_offering(cur,a['offering_id'])
            paid = payment_status(cur,a)
        return page('receipt.html',application=a,offering=o,payment=paid)

    @bp.get('/group-class-image/<int:oid>')
    def class_image(oid):
        with db() as conn:
            cur=conn.cursor();o=get_offering(cur,oid)
            if not o or (not o['published'] and not api['require_owner']()):abort(404)
            cur.execute('SELECT image_data FROM group_offering_images WHERE offering_id=?',(oid,))
            data=cur.fetchone()
            if not data:abort(404)
        response=Response(base64.b64decode(data[0]),mimetype='image/jpeg')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='private, no-store'
        return response

    @bp.route('/group-class-admin/<int:oid>/schedule',methods=['GET','POST'])
    def schedule_editor(oid):
        owner();error='';submitted=None
        # Native schema helpers can write, so run them before the scheduling transaction.
        for name in ('ensure_teacher_management_schema','ensure_location_room_schema','ensure_v18c_schema'):
            if name in api:api[name]()
        try:
            if request.method=='POST':
                try:submitted=json.loads(request.form.get('sessions','[]'))
                except (ValueError,TypeError):raise ValueError('Invalid calendar selection.')
                with db() as conn:
                    o,plan=validate_schedule_plan(conn.cursor(),oid,submitted)
                pricing={}
                for item in plan:
                    key=(item['teacher'],item['course_id'])
                    if key not in pricing:
                        pricing[key]=api['get_final_pricing']('',item['teacher'],item['course_id'],class_size=o['capacity'])
                    if not pricing[key]:raise ValueError('Course pricing is not configured. Complete the course settings first.')
                with db(write=True) as conn:
                    cur=conn.cursor();lock_offering(cur,oid)
                    o,plan=validate_schedule_plan(cur,oid,submitted)
                    if request.form.get('version')!=schedule_version(o):raise ValueError('The class calendar changed in another window. Reload before saving.')
                    kept={item['id'] for item in plan if item['id']}
                    for old in o['sessions']:
                        if old['id'] not in kept:
                            cur.execute("UPDATE schedule SET status='cancelled',charge_lessons=0,owner_calendar_updated_at=? WHERE id=?",(now(),old['id']))
                            cur.execute('DELETE FROM group_offering_sessions WHERE offering_id=? AND schedule_id=?',(oid,old['id']))
                    for item in plan:
                        rate=pricing[(item['teacher'],item['course_id'])]
                        fields=dict(student_name=o['title'],lesson_date=item['date'],lesson_time=item['time'],teacher=item['teacher'],classroom=item['classroom'],duration=item['duration'],course_type_id=item['course_id'],course_type_name=item['course_name'],student_billing_method=rate['student_billing_method'],student_price=rate['student_price'],teacher_billing_method=rate['teacher_billing_method'],teacher_pay=rate['teacher_pay'],student_charge_amount=rate['student_charge_amount'],teacher_pay_amount=rate['teacher_pay_amount'],is_group=1,group_size=0,group_name=o['title'],group_student_names='',room_id=item['room_id'],location_id=item['location_id'],location=item['location'],charge_lessons=0,owner_calendar_updated_at=now())
                        if item['id']:
                            cur.execute('UPDATE schedule SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',tuple(fields.values())+(item['id'],))
                        else:
                            fields.update(status='scheduled',schedule_type='one_time',notes='Group offering #'+str(oid)+'; enrollment pending.')
                            cur.execute('INSERT INTO schedule('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(fields.values()))
                            cur.execute('INSERT INTO group_offering_sessions(offering_id,schedule_id) VALUES (?,?)',(oid,cur.lastrowid))
                session['group_schedule_saved_id']=oid
                return redirect('/group-class-admin',code=303)
        except (ValueError,TypeError) as exc:error=str(exc)
        with db() as conn:
            cur=conn.cursor();o=get_offering(cur,oid)
            if not o:abort(404)
            cur.execute('SELECT teacher_name FROM teachers WHERE active=1 ORDER BY teacher_name');teachers=[r[0] for r in cur.fetchall()]
            cur.execute('SELECT id,name,duration FROM course_types WHERE is_group=1 AND active=1 ORDER BY duration,name');courses=rows(cur)
            cur.execute("""SELECT r.id,r.room_name,l.location_name FROM studio_rooms r JOIN studio_locations l ON l.id=r.location_id
                WHERE r.active=1 AND l.active=1 ORDER BY l.location_name,r.room_name""");rooms=rows(cur)
        initial=[dict(id=x['id'],date=x['lesson_date'],time=x['lesson_time'],teacher=x['teacher'],room_id=x['room_id'],course_id=x['course_type_id']) for x in o['sessions']]
        return page('schedule.html',offering=o,initial=submitted if isinstance(submitted,list) else initial,teachers=teachers,courses=courses,rooms=rooms,version=schedule_version(o),error=error)

    @bp.route('/group-class-admin',methods=['GET','POST'])
    def manage():
        owner()
        error = ''
        try:
            with db(write=request.method=='POST') as conn:
                cur = conn.cursor()
                if request.method == 'POST':
                    if request.form.get('action')=='image':
                        oid=int(request.form.get('id','0'));lock_offering(cur,oid)
                        data=prepare_class_image(request.files.get('class_image'))
                        cur.execute('DELETE FROM group_offering_images WHERE offering_id=?',(oid,))
                        cur.execute('INSERT INTO group_offering_images(offering_id,image_data,updated_at) VALUES (?,?,?)',(oid,data,now()))
                        return redirect('/group-class-admin',code=303)
                    if request.form.get('action')=='visibility':
                        if request.form.get('published')=='1':
                            candidate=get_offering(cur,int(request.form['id']))
                            if not candidate:raise ValueError('Class not found.')
                            valid_sessions(cur,candidate)
                        cur.execute('UPDATE group_offerings SET published=? WHERE id=?',
                                    (1 if request.form.get('published')=='1' else 0,int(request.form['id'])))
                        return redirect('/group-class-admin',code=303)
                    edit_id=int(request.form.get('offering_id') or 0)
                    if edit_id:
                        lock_offering(cur,edit_id)
                        cur.execute('SELECT COUNT(*) FROM group_applications WHERE offering_id=?',(edit_id,))
                        if cur.fetchone()[0]:raise ValueError('This class has applications. Review enrollment before changing terms.')
                        if get_offering(cur,edit_id)['published']:raise ValueError('Close registration before editing this draft.')
                    title=request.form.get('title','').strip(); policy=request.form.get('policy','').strip()
                    capacity=int(request.form.get('capacity','0'))
                    amount=Decimal(request.form.get('tuition','0'))
                    if not amount.is_finite() or amount<=0 or amount>100000 or amount.as_tuple().exponent < -2:
                        raise ValueError('Tuition must be a positive dollar amount with at most two decimal places.')
                    if not title or len(title)>150 or not policy or not 1<=capacity<=100:
                        raise ValueError('Enter a title, policy and capacity between 1 and 100.')
                    selected=sorted(set(int(x) for x in request.form.getlist('schedule_ids')))
                    if len(selected)>100:
                        raise ValueError('Select at most 100 group calendar sessions.')
                    ss=[]
                    for sid in selected:
                        cur.execute('''SELECT id,teacher,course_type_id,duration,lesson_date,status
                            FROM schedule WHERE id=? AND is_group=1''',(sid,))
                        r=one(cur)
                        if not r or r['lesson_date']<now()[:10] or str(r['status']).lower() != 'scheduled':
                            raise ValueError('Select upcoming, uncancelled group sessions.')
                        cur.execute('SELECT offering_id FROM group_offering_sessions WHERE schedule_id=?',(sid,))
                        linked=cur.fetchone()
                        if linked and linked[0]!=edit_id:
                            raise ValueError('A selected session already belongs to another offering.')
                        ss.append(r)
                    if ss and (len({(s['course_type_id'],s['duration']) for s in ss})!=1 or not ss[0]['course_type_id']):
                        raise ValueError('All sessions must use the same group course type and duration; each session keeps its actual teacher.')
                    values=(title,request.form.get('description','')[:3000],request.form.get('age_range','')[:100],policy[:5000],capacity,int(amount*100))
                    if edit_id:
                        oid=edit_id
                        cur.execute('UPDATE group_offerings SET title=?,description=?,age_range=?,policy=?,capacity=?,tuition_cents=? WHERE id=?',values+(oid,))
                        cur.execute('DELETE FROM group_offering_sessions WHERE offering_id=?',(oid,))
                    else:
                        cur.execute("""INSERT INTO group_offerings(title,description,age_range,policy,capacity,
                            tuition_cents,published,created_at) VALUES (?,?,?,?,?,?,0,?)""",values+(now(),))
                        oid=cur.lastrowid
                    for sid in selected:
                        cur.execute('INSERT INTO group_offering_sessions(offering_id,schedule_id) VALUES (?,?)',(oid,sid))
                    if occupied(cur,oid)>capacity:
                        raise ValueError('Capacity is smaller than the existing calendar roster.')
                    return redirect('/group-class-admin',code=303)
        except (ValueError,InvalidOperation) as exc:
            error=str(exc)
        with db() as conn:
            cur=conn.cursor();cur.execute('SELECT id FROM group_offerings ORDER BY id DESC')
            offerings=[get_offering(cur,r[0]) for r in cur.fetchall()]
            for o in offerings:o['remaining']=max(0,o['capacity']-occupied(cur,o['id']))
            cur.execute('''SELECT s.id,s.lesson_date,s.lesson_time,s.duration,s.teacher,s.group_name,s.course_type_name,s.classroom,s.location
                FROM schedule s LEFT JOIN group_offering_sessions gs ON gs.schedule_id=s.id
                WHERE s.is_group=1 AND s.lesson_date>=? AND gs.schedule_id IS NULL
                AND lower(s.status)='scheduled'
                ORDER BY s.teacher,s.group_name,s.lesson_date,s.lesson_time LIMIT 400''',(now()[:10],))
            choices=rows(cur)
        saved_id=session.pop('group_schedule_saved_id',None)
        saved=next((o for o in offerings if o['id']==saved_id),None)
        warnings=[]
        if saved:
            for lesson in saved['sessions']:
                conflict=api['schedule_has_conflict'](lesson['teacher'],lesson['classroom'],lesson['lesson_date'],lesson['lesson_time'],exclude_schedule_id=lesson['id'],duration=lesson['duration'],room_id=lesson['room_id'],location_id=lesson['location_id'],location=lesson['location'])
                if conflict.get('has_conflict'):
                    warnings.append(lesson['lesson_date']+': '+conflict.get('message','Teacher or room overlap.'))
        editing=next((o for o in offerings if str(o['id'])==request.args.get('edit')),None)
        return page('manage.html',offerings=offerings,choices=choices,editing=editing,saved=saved,warnings=warnings,error=error)

    @bp.route('/group-enrollments',methods=['GET','POST'])
    def review():
        owner();error=''
        try:
            if request.method=='POST':
                with db(write=True) as conn:
                    cur=conn.cursor();aid=int(request.form.get('id','0'));action=request.form.get('action')
                    if action=='approve':approve(cur,aid,request.form.get('student_id'),api)
                    elif action=='confirm':confirm(cur,aid)
                    elif action in ('waitlist','cancel'):
                        cur.execute('SELECT * FROM group_applications WHERE id=?',(aid,));a=one(cur)
                        if not a:raise ValueError('Application not found.')
                        lock_offering(cur,a['offering_id'])
                        if a['invoice_id'] or a['status']=='enrolled':
                            raise ValueError('This application has a linked invoice. Review payment or revoke checkout in Billing before closing it.')
                        cur.execute('UPDATE group_applications SET status=?,updated_at=? WHERE id=?',
                                    ('waitlist' if action=='waitlist' else 'cancelled',now(),aid))
                    else:raise ValueError('Unknown action.')
                return redirect('/group-enrollments',code=303)
        except ValueError as exc:error=str(exc)
        with db() as conn:
            cur=conn.cursor();cur.execute('''SELECT a.*,o.title FROM group_applications a
                JOIN group_offerings o ON o.id=a.offering_id ORDER BY a.id DESC LIMIT 500''');applications=rows(cur)
            for a in applications:a['payment']=payment_status(cur,a)
            cur.execute('SELECT id,name FROM students ORDER BY name');students=rows(cur)
        return page('review.html',applications=applications,students=students,error=error)

    app.register_blueprint(bp)
