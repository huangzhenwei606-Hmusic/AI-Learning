"""Capture saved schedule changes transactionally and ask the manager before delivery."""
from datetime import datetime,timedelta,timezone
import json
import secrets
from zoneinfo import ZoneInfo
from flask import g,request,session,render_template_string

LA=ZoneInfo('America/Los_Angeles')
UTC=timezone.utc
FIELDS=('id','student','teacher','date','time','duration','location','room','status','course','is_group')
SELECT="id,COALESCE(student_name,''),COALESCE(teacher,''),lesson_date,lesson_time,COALESCE(duration,30),COALESCE(location,''),COALESCE(classroom,''),COALESCE(status,'scheduled'),COALESCE(course_type_name,''),COALESCE(is_group,0)"


def register_teacher_schedule_changes(app,api):
    work=app.extensions['teacher_work_reminders']
    fail=work['fail']

    def schema(cursor):
        cursor.execute('''CREATE TABLE IF NOT EXISTS teacher_schedule_change_batches (
            token TEXT PRIMARY KEY, changes TEXT NOT NULL, previews TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)''')

    def capture(cursor,ids):
        if not api['require_owner']():return {}
        ids=list(dict.fromkeys(int(x) for x in ids if x))
        result={}
        postgres=api.get('using_postgres',lambda:False)()
        if ids and not postgres and not getattr(getattr(cursor,'connection',None),'in_transaction',True):
            cursor.execute('BEGIN IMMEDIATE')
        for start in range(0,len(ids),200):
            chunk=ids[start:start+200]
            cursor.execute('SELECT '+SELECT+' FROM schedule WHERE id IN ('+','.join('?' for _ in chunk)+') ORDER BY id'+(' FOR UPDATE' if postgres else ''),tuple(chunk))
            for row in cursor.fetchall():
                item=dict(zip(FIELDS,row));item['date']=str(item['date']);item['time']=str(item['time'])
                result[int(item['id'])]=item
        return result

    def record(cursor,before,new_ids=()):
        if not api['require_owner']():return None
        after=capture(cursor,list(before)+list(new_ids));changes=[]
        for sid,current in after.items():
            old=before.get(sid)
            if old and all(old.get(k)==current.get(k) for k in ('teacher','date','time','duration','location','room','course','student')):continue
            try:upcoming=datetime.fromisoformat(current['date']+'T'+current['time']).replace(tzinfo=LA)>datetime.now(LA)
            except (ValueError,TypeError):upcoming=False
            if current['status']!='scheduled' or not upcoming or not current['teacher']:continue
            kind='new_lesson' if not old else 'time_change' if (old['date'],old['time'])!=(current['date'],current['time']) else 'work_reminder'
            changes.append(dict(before=old,after=current,kind=kind))
        if not changes:return None
        changes.sort(key=lambda c:(c['after']['date'],c['after']['time'],c['after']['id']))
        schema(cursor);token=secrets.token_urlsafe(32)
        cursor.execute('INSERT INTO teacher_schedule_change_batches(token,changes,created_at) VALUES(?,?,?)',(token,json.dumps(changes,sort_keys=True),datetime.now(UTC).isoformat()))
        urls=getattr(g,'teacher_work_urls',[]);urls.append('/manager/teacher-work-reminders/saved/'+token);g.teacher_work_urls=urls
        return token

    def original_time(item):
        dt=datetime.fromisoformat(item['date']+'T'+item['time']).replace(tzinfo=LA)
        return dt.strftime('%a %b %d, %Y · %I:%M %p %Z')

    def contact_profile(cursor,name):
        people=[p for p in work['teachers'](cursor) if p['name']==name]
        if not people:fail(400,'No active teacher profile for '+name)
        with_contact=[p for p in people if p['email'].strip() or api['hmusic_normalize_sms_phone'](p['phone'])]
        candidates=with_contact or people
        if len({(p['email'].strip().lower(),api['hmusic_normalize_sms_phone'](p['phone'])) for p in candidates})>1:
            fail(409,'There are multiple different active contact profiles for '+name+'. Update Teachers to one current contact profile before sending.')
        return work['teacher'](cursor,max(candidates,key=lambda p:p['id'])['id'])

    def prepare(cursor,changes):
        groups={}
        for change in changes:groups.setdefault(change['after']['teacher'],[]).append(change)
        previews=[]
        for name,items in groups.items():
            # A later edit invalidates this entire saved-change notification.
            current=capture(cursor,[i['after']['id'] for i in items])
            if any(current.get(i['after']['id'])!=i['after'] for i in items):
                fail(409,'The lesson changed again. Use the reminder from the latest save.')
            person=contact_profile(cursor,name)
            lessons=[work['lesson'](cursor,i['after']['id'],name) for i in items]
            kind='new_lesson' if all(i['kind']=='new_lesson' for i in items) else 'time_change' if any(i['kind']=='time_change' for i in items) else 'work_reminder'
            title={'new_lesson':'New lesson','time_change':'Schedule changed','work_reminder':'Work reminder'}[kind]
            def message(limit=None):
                body='Hi '+name+',\n'
                for i,l in zip(items[:limit] if limit else items,lessons[:limit] if limit else lessons):
                    body+='\nStudent: '+l['student']+'\n'
                    if i['before']:
                        body+='Previous time: '+original_time(i['before'])+'\nNew time: '+l['display']+'\n'
                    else:body+='New lesson: '+l['display']+'\n'
                    body+='Course: '+(l['course'] or 'Lesson')+' · '+str(l['duration'])+' min\nLocation: '+(l['location'] or 'H-Music Studio')+' · '+(l['room'] or 'Room TBD')+'\n'
                if limit and len(items)>limit:body+='\nAlso applies to '+str(len(items)-limit)+' additional saved lesson(s). Review the teacher calendar for all dates.\n'
                return body+'\nPlease review your teacher calendar.'
            bodies={'email':message(),'sms':message(2)+'\nReply STOP to opt out.'}
            payload={};reasons={}
            for channel in ('sms','email'):
                valid=api['hmusic_normalize_sms_phone'](person['phone']) if channel=='sms' else api['hmusic_is_real_email'](person['email'])
                configured=api['sms_config_status' if channel=='sms' else 'smtp_config_status']()[0]
                if not valid:reasons[channel]='Add a valid '+('mobile number' if channel=='sms' else 'email address')+' in Teachers';continue
                if not configured:reasons[channel]='Delivery service is not configured';continue
                if channel=='sms' and len('H-Music: '+title+'\n'+bodies[channel])>1500:reasons[channel]='Message too long for SMS; choose email';continue
                dest=work['destinations'](person,[channel])[channel]
                payload[channel]=dict(destination=dest,title=title,body=bodies[channel])
            now=datetime.now(UTC);draft=secrets.token_urlsafe(32)
            snapshot=dict(teacher=person,lessons=lessons,channels=sorted(payload),saved_changes=items)
            cursor.execute('''INSERT INTO teacher_work_reminders(token,teacher_id,kind,snapshot,payload,created_at,expires_at) VALUES(?,?,?,?,?,?,?)''',(draft,person['id'],kind,json.dumps(snapshot,sort_keys=True),json.dumps(payload,sort_keys=True),now.isoformat(),(now+timedelta(minutes=15)).isoformat()))
            previews.append(dict(token=draft,name=name,reasons=reasons))
        return previews

    @app.route('/manager/teacher-work-reminders/saved/<token>',methods=['GET','POST'])
    def teacher_saved_schedule_reminder(token):
        if not api['require_owner']():fail(403,'Manager login required')
        with work['db']() as (_,cursor):
            schema(cursor)
            cursor.execute('UPDATE teacher_schedule_change_batches SET token=token WHERE token=?',(token,))
            cursor.execute('SELECT changes,previews FROM teacher_schedule_change_batches WHERE token=?',(token,));row=cursor.fetchone()
            if not row:fail(404,'Saved lesson changes not found')
            changes,previews=json.loads(row[0]),json.loads(row[1])
            if not previews:
                previews=prepare(cursor,changes)
                cursor.execute('UPDATE teacher_schedule_change_batches SET previews=? WHERE token=?',(json.dumps(previews),token))
        results=[]
        if request.method=='POST':
            chosen=[(p,request.form.getlist('channels_'+p['token'])) for p in previews]
            if not any(channels for _,channels in chosen):fail(400,'Choose SMS or email for at least one teacher')
            # Validate every selected draft before making the first external send.
            with work['db']() as (_,cursor):
                for p,channels in chosen:
                    if not channels:continue
                    cursor.execute('SELECT snapshot,payload,status,expires_at FROM teacher_work_reminders WHERE token=?',(p['token'],));r=cursor.fetchone()
                    snap,payload,status,expires=json.loads(r[0]),json.loads(r[1]),r[2],r[3]
                    if status!='draft':continue
                    if datetime.fromisoformat(expires)<=datetime.now(UTC):fail(409,'Preview expired; open a fresh reminder')
                    if not set(channels)<=set(payload):fail(400,'Choose an available delivery channel')
                    person=work['teacher'](cursor,snap['teacher']['id'])
                    lessons=[work['lesson'](cursor,l['id'],person['name']) for l in snap['lessons']]
                    if person!={k:v for k,v in snap['teacher'].items() if k!='label'} or lessons!=snap['lessons']:fail(409,'Lesson or contact details changed. Review the latest saved reminder.')
                    work['destinations'](person,channels)
            for p,channels in chosen:
                if channels:results.append(work['dispatch'](p['token'],send=True,channels=channels))
        cards=[]
        for p in previews:
            cards.append(dict(**p,**{k:v for k,v in work['dispatch'](p['token']).items() if k!='token'}))
        from teacher_work_reminders import STYLE
        return render_template_string(SAVED_PAGE,style=STYLE,cards=cards,submitted=bool(results))

    @app.after_request
    def saved_teacher_reminders(response):
        if not api['require_owner']():return response
        urls=getattr(g,'teacher_work_urls',[])
        if response.status_code in (301,302,303,307,308) and urls:
            session['teacher_work_pending']=urls
        elif response.is_json and response.status_code<300 and urls:
            data=response.get_json(silent=True)
            if isinstance(data,dict) and data.get('ok'):
                data['teacher_work_reminders']=urls;response.set_data(app.json.dumps(data))
        elif response.status_code==200 and response.mimetype=='text/html' and request.endpoint!='teacher_saved_schedule_reminder':
            if request.method=='GET':urls=urls+session.pop('teacher_work_pending',[])
            if request.endpoint in ('calendar','add_schedule','parent_booking_request_review','reschedule_request_detail') or urls:
                assets='<script src="/static/teacher_save_prompt.js?v=1" defer></script>'
                if urls:assets+='<script>document.addEventListener("DOMContentLoaded",()=>window.HMusicTeacherWorkReminderPrompt('+json.dumps(urls).replace('<','\\u003c')+'));</script>'
                html=response.get_data(as_text=True);response.set_data(html.replace('</body>',assets+'</body>',1))
        return response

    # Run after workspace wrapping so redirect-backed popups are not discarded.
    handlers=app.after_request_funcs[None];handlers.insert(0,handlers.pop())
    app.extensions['teacher_schedule_changes']=dict(capture=capture,record=record)


SAVED_PAGE='''<!doctype html><html><head><title>Lesson saved · notify teacher</title>{{style|safe}}<style>pre{max-height:360px;overflow:auto}.choice{display:inline-block;margin-right:20px}</style></head><body><main class="wrap"><section class="card"><h1>Lesson saved · notify teacher</h1><p>The schedule is saved. Previous and new times below were captured automatically from the calendar. Choose channels and confirm to send.</p><form method="post">{% for c in cards %}<section class="card"><h2>{{c.person.name}}</h2><p>Status: {{c.status}}</p><div class="preview-grid">{% for channel in ['sms','email'] %}<section>{% if channel in c.payload %}<label class="choice"><input type="checkbox" name="channels_{{c.token}}" value="{{channel}}" {% if c.status!='draft' %}disabled{% endif %}> {{'Mobile SMS' if channel=='sms' else 'Email'}} → {{c.payload[channel].destination}}</label><p>Subject: {{c.payload[channel].title}}</p><pre>{% if channel=='sms' %}H-Music: {{c.payload[channel].title}}\n{% endif %}{{c.payload[channel].body}}</pre>{% else %}<p>{{channel}} unavailable: {{c.reasons.get(channel,'Not selected for this send')}}</p>{% endif %}{% if channel in c.results %}<p>{{c.results[channel].status}} — {{c.results[channel].detail}}</p>{% endif %}</section>{% endfor %}</div></section>{% endfor %}{% if not submitted and cards|selectattr('status','equalto','draft')|list %}<button>Confirm and send</button>{% endif %}</form><p><button type="button" onclick="window.parent.postMessage({type:'hmusic-teacher-reminder-close'},location.origin)">{{'Done' if submitted else 'Not now · close'}}</button></p><a href="/calendar">Calendar</a></section></main></body></html>'''
