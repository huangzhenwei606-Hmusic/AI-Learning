"""Opt-in trial -> parent choice -> owner approval -> paid enrollment saga.
Uses the existing admissions quote/checkout and Studio durable notification outbox.
No historical family is activated by installation; no card data enters this module.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from flask import Blueprint, request, redirect, render_template_string, abort
from itsdangerous import URLSafeSerializer, BadSignature
from admissions import ensure_schema as admissions_schema, catalog, quote, sync_order, digest
from studio_operations import LA, stamp, pack, record, conflict_check, checked_date, minutes, fingerprint

ROOT = '/studio-enrollment'
STAGES = {'draft':'待配置','offered':'等家长选试听时间','selected':'等校长审核','trial':'等待试听完成','followup':'试听后跟进','payment':'待缴费','paid':'已付款待排课','attention':'需要校长处理','enrolled':'报名及排课完成','paused':'已暂停'}

def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS studio_enrollment_windows (
      id INTEGER PRIMARY KEY AUTOINCREMENT,teacher_id TEXT NOT NULL,course_type_id INTEGER NOT NULL,
      date_from TEXT NOT NULL,date_until TEXT NOT NULL,weekdays TEXT NOT NULL,start_time TEXT NOT NULL,
      end_time TEXT NOT NULL,classroom TEXT NOT NULL,location TEXT NOT NULL,active INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS studio_enrollment_journeys (
      id INTEGER PRIMARY KEY AUTOINCREMENT,inquiry_id INTEGER NOT NULL UNIQUE,nonce TEXT NOT NULL,
      stage TEXT NOT NULL,enabled INTEGER NOT NULL,source TEXT NOT NULL,channels TEXT NOT NULL,
      candidates TEXT NOT NULL,selected TEXT NOT NULL,plans TEXT NOT NULL,trial_schedule_id INTEGER,
      ended_at TEXT,followup_due TEXT,order_id TEXT,result TEXT NOT NULL,error TEXT NOT NULL,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
    c.commit()


def lock(c):
    # Same lock as Studio operations; works with SQLite's write lock and PG UPDATE row locks.
    c.execute("INSERT OR IGNORE INTO studio_leases VALUES ('write','','')")
    c.execute("UPDATE studio_leases SET owner='enrollment' WHERE id='write'")


def local(value):
    d=datetime.fromisoformat(str(value))
    return d.replace(tzinfo=LA) if d.tzinfo is None else d.astimezone(LA)


class Journey:
    def __init__(self, operations, api, secret):
        self.ops=operations; self.api=api; self.ready=False
        self.signer=URLSafeSerializer(secret,salt='hmusic-trial-enrollment-v1')
    def db(self):
        if not self.ready:
            for key in ('ensure_teacher_time_off_schema','ensure_guardian_billing_schema','ensure_v321_schema'):
                if key in self.api:self.api[key]()
            self.ready=True
        c=self.ops.db(); admissions_schema(c); schema(c); return c
    def get(self,c,jid):
        j=record(c,'SELECT * FROM studio_enrollment_journeys WHERE id=?',(int(jid),))
        if not j: raise ValueError('流程不存在')
        return j
    def identity(self,c,j):
        i=record(c,'SELECT * FROM inquiries WHERE id=?',(j['inquiry_id'],));source=json.loads(j['source'])
        if not i or any(str(i.get(k) or '').strip().casefold()!=str(source.get(k) or '').strip().casefold() for k in ('student_name','parent_email','phone')):
            raise ValueError('家庭身份或联系方式已改变，需重新核实')
        return i
    def path(self,j):return '/trial-enrollment/'+self.signer.dumps([j['id'],j['nonce']])
    def public(self,c,token):
        try:
            jid,nonce=self.signer.loads(token);j=self.get(c,jid)
        except (BadSignature,ValueError,TypeError):abort(404)
        if nonce!=j['nonce'] or not j['enabled']:abort(404)
        if datetime.now(timezone.utc)-datetime.fromisoformat(j['created_at'])>timedelta(days=60):abort(410)
        return j
    def notify(self,c,j,key,title,body,path=None,teacher=None,owner=False,**extra):
        p={'journey_id':j['id'],'journey_kind':key,'target_kind':'inquiry','target_id':j['inquiry_id'],
           'channels':['push'] if owner else ['email','push'] if teacher else json.loads(j['channels']),
           'title':title,'body':body,**extra}
        if teacher:p['teacher']=teacher
        if owner:p['owner']=True
        if path:p['journey_path']=path
        self.ops.task(c,f"enrollment:{j['id']}:{key}",f"enrollment:{j['id']}",p)
    def owner_notice(self,c,j,key,body):
        self.notify(c,j,'owner:'+key,'试听报名待处理',body,ROOT,owner=True)
    def set_stage(self,c,jid,stage,**fields):
        fields={**fields,'stage':stage,'updated_at':stamp()}
        allowed={'stage','enabled','candidates','selected','plans','trial_schedule_id','ended_at','followup_due','order_id','result','error','updated_at'}
        if not set(fields)<=allowed:raise ValueError('字段无效')
        c.execute('UPDATE studio_enrollment_journeys SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),jid))
    def create(self,inquiry_id,channels):
        if not channels or any(x not in ('email','sms') for x in channels):raise ValueError('选择邮件或短信')
        c=self.db()
        try:
            lock(c);i=record(c,'SELECT * FROM inquiries WHERE id=?',(int(inquiry_id),))
            if not i or i.get('converted_student_name'):raise ValueError('选择未转为正式学生的咨询')
            if not i.get('parent_email') or '@' not in i['parent_email']:raise ValueError('报名付款需要已核实的家长邮箱')
            existing=record(c,'SELECT id FROM studio_enrollment_journeys WHERE inquiry_id=?',(i['id'],))
            if existing:return existing['id']
            source=pack({k:i.get(k) for k in ('source','student_name','parent_name','parent_email','phone','notes','created_at')})
            cur=c.execute("""INSERT INTO studio_enrollment_journeys(inquiry_id,nonce,stage,enabled,source,channels,candidates,selected,plans,result,error,created_at,updated_at)
              VALUES(?,?,'draft',1,?,?,'[]','{}','[]','{}','',?,?)""",(i['id'],secrets.token_urlsafe(24),source,pack(channels),stamp(),stamp()))
            jid=cur.lastrowid;c.commit();return jid
        except Exception:c.rollback();raise
        finally:c.close()
    def add_window(self,d):
        c=self.db()
        try:
            cfg=catalog(c);t=next((t for t in cfg['teachers'] if t['id']==d['teacher_id'] and t['active']),None)
            ct=record(c,'SELECT * FROM course_types WHERE id=? AND active=1 AND COALESCE(is_group,0)=0',(int(d['course_type_id']),))
            if not t or not ct:raise ValueError('选择已发布老师与启用中的私课类型')
            if not record(c,'SELECT teacher_name FROM teachers WHERE teacher_name=?',(t['name'],)):raise ValueError('价格目录老师姓名与 CRM 老师不一致，请先核对')
            a=checked_date(d['date_from']);b=checked_date(d['date_until'])
            if b<a or (b-a).days>90:raise ValueError('可工作日期范围最长90天')
            if minutes(d['start_time'])>=minutes(d['end_time']):raise ValueError('工作时段无效')
            weekdays=[int(x) for x in d.getlist('weekdays')]
            if not weekdays or any(x not in range(7) for x in weekdays):raise ValueError('请选择工作星期')
            room=d.get('classroom','').strip();loc=d.get('location','').strip()
            if not room or not loc or len(room)>120 or len(loc)>120:raise ValueError('填写实际教室和校区')
            c.execute('INSERT INTO studio_enrollment_windows(teacher_id,course_type_id,date_from,date_until,weekdays,start_time,end_time,classroom,location,active) VALUES(?,?,?,?,?,?,?,?,?,1)',(t['id'],ct['id'],a.isoformat(),b.isoformat(),pack(weekdays),d['start_time'],d['end_time'],room,loc));c.commit()
        finally:c.close()
    def add_plan(self,jid,d):
        c=self.db()
        try:
            j=self.get(c,jid);i=record(c,'SELECT student_name FROM inquiries WHERE id=?',(j['inquiry_id'],))
            teacher=next((t for t in catalog(c)['teachers'] if t['id']==d['teacher_id'] and t['active']),None)
        finally:c.close()
        if not teacher:raise ValueError('老师不存在')
        pricing=self.api['get_final_pricing'](i['student_name'],teacher['name'],int(d['course_type_id']))
        if not pricing or pricing.get('teacher_pay_amount') is None:raise ValueError('请先在 CRM 核实该老师和课程的计薪规则')
        c=self.db()
        try:
            lock(c);j=self.get(c,jid)
            if j['stage'] not in ('draft','offered','selected','trial','followup') or j['order_id']:raise ValueError('报名订单已建立，不能更改方案')
            ct=record(c,'SELECT * FROM course_types WHERE id=? AND active=1 AND COALESCE(is_group,0)=0',(int(d['course_type_id']),))
            if not ct:raise ValueError('课程类型不存在')
            q=quote(c,d['teacher_id'],str(ct['duration']))
            if not record(c,'SELECT teacher_name FROM teachers WHERE teacher_name=?',(q['teacher']['name'],)):raise ValueError('老师姓名与 CRM 不一致')
            dates=sorted({x.strip() for x in d['dates'].replace('\r','').replace(',','\n').splitlines() if x.strip()})
            if len(dates)!=q['lessons']:raise ValueError(f"请明确列出 {q['lessons']} 个实际上课日期（已排除学校假期）")
            for day in dates:
                if checked_date(day)<datetime.now(LA).date():raise ValueError('正式课程日期不能在过去')
            room=d['classroom'].strip();loc=d['location'].strip();minutes(d['time'])
            if not room or not loc:raise ValueError('正式课程需要教室与校区')
            plan={'id':secrets.token_hex(8),'course_type_id':ct['id'],'course_name':ct['name'],'quote':q,'payroll':{k:pricing[k] for k in ('teacher_billing_method','teacher_pay','teacher_pay_amount')},'dates':dates,'time':d['time'],'classroom':room,'location':loc}
            for day in dates:self.check_plan_slot(c,j,plan,day)
            plans=json.loads(j['plans'])
            if len(plans)>=3:raise ValueError('每个家庭最多三个已审核报名方案')
            plans.append(plan);c.execute('UPDATE studio_enrollment_journeys SET plans=?,updated_at=? WHERE id=?',(pack(plans),stamp(),jid));c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def check_plan_slot(self,c,j,p,day):
        i=record(c,'SELECT student_name FROM inquiries WHERE id=?',(j['inquiry_id'],))
        conflict_check(c,{'student_name':i['student_name'],'teacher':p['quote']['teacher']['name'],'duration':p['quote']['minutes'],'classroom':p['classroom'],'location':p['location']},day,p['time'])
    def scan(self,c,j,start,end,course_type_id):
        a=checked_date(start);b=checked_date(end)
        if a<datetime.now(LA).date() or b<a or (b-a).days>28:raise ValueError('试听搜索需在未来29天范围内')
        ct=record(c,'SELECT * FROM course_types WHERE id=? AND active=1 AND COALESCE(is_group,0)=0',(int(course_type_id),))
        if not ct or int(ct['duration']) not in (30,45,60):raise ValueError('选择有效私课类型')
        teachers={t['id']:t for t in catalog(c)['teachers'] if t['active']}
        cur=c.execute('SELECT * FROM studio_enrollment_windows WHERE active=1 AND course_type_id=?',(ct['id'],));windows=[dict(zip([x[0] for x in cur.description],r)) for r in cur.fetchall()]
        i=record(c,'SELECT student_name FROM inquiries WHERE id=?',(j['inquiry_id'],));out=[]
        for offset in range((b-a).days+1):
            day=a+timedelta(days=offset)
            for w in windows:
                t=teachers.get(w['teacher_id'])
                if not t or not w['date_from']<=day.isoformat()<=w['date_until'] or day.weekday() not in json.loads(w['weekdays']):continue
                for clock in range(minutes(w['start_time']),minutes(w['end_time'])-int(ct['duration'])+1,30):
                    text=f'{clock//60:02}:{clock%60:02}'
                    if datetime.combine(day,datetime.strptime(text,'%H:%M').time(),LA)<=datetime.now(LA):continue
                    slot={'student_name':i['student_name'],'teacher':t['name'],'duration':int(ct['duration']),'classroom':w['classroom'],'location':w['location'],'date':day.isoformat(),'time':text,'window_id':w['id'],'course_type_id':ct['id']}
                    try:conflict_check(c,slot,slot['date'],text)
                    except ValueError:continue
                    if slot not in out:out.append(slot)
                    if len(out)>=12:return out
        return out
    def offer(self,jid,d):
        c=self.db()
        try:
            lock(c);j=self.get(c,jid);self.identity(c,j)
            if not j['enabled'] or j['trial_schedule_id'] or j['stage'] not in ('draft','offered','selected'):raise ValueError('试听已确认或流程暂停，不能重发选项')
            if not json.loads(j['plans']):raise ValueError('先添加已审核的正式报名方案，供试听后自动跟进读取')
            slots=self.scan(c,j,d['start'],d['end'],d['course_type_id'])
            if not slots:raise ValueError('没有符合已核实工作时段的空点；请补充时段或调整日期')
            fee=Decimal(d['trial_fee'])
            if not fee.is_finite() or fee<0 or fee>1000:raise ValueError('核实试听费用（美元），如免费明确填写0')
            for s in slots:s['fee']=str(fee.quantize(Decimal('0.01')))
            # No automatic re-send of a replacement offer; owner may share its stable link.
            self.set_stage(c,jid,'offered',candidates=pack(slots),selected='{}')
            self.notify(c,j,'trial-options','Choose your H-Music trial time',f"Please choose a trial time for {json.loads(j['source'])['student_name']}. Options are subject to final school confirmation. Trial fee: ${fee:.2f}. Open the secure link below.",self.path(j));c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def select(self,jid,index,choices_version):
        c=self.db()
        try:
            lock(c);j=self.get(c,jid)
            if j['stage']=='selected':return
            if not j['enabled'] or j['stage']!='offered':raise ValueError('This selection is no longer available.')
            choices=json.loads(j['candidates'])
            if choices_version!=fingerprint(choices):raise ValueError('Options changed. Reload before choosing.')
            if index<0 or index>=len(choices):raise ValueError('Choose one of the available options.')
            s=choices[index];self.check_trial(c,s)
            self.set_stage(c,jid,'selected',selected=pack(s));self.owner_notice(c,j,'selection','家长已选试听时间，请审核后确认。');c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def check_trial(self,c,s):
        w=record(c,'SELECT * FROM studio_enrollment_windows WHERE id=? AND active=1',(s['window_id'],))
        if not w or not w['date_from']<=s['date']<=w['date_until'] or checked_date(s['date']).weekday() not in json.loads(w['weekdays']):raise ValueError('老师可用时间已变，请重新提供选项')
        t=next((t for t in catalog(c)['teachers'] if t['id']==w['teacher_id'] and t['active']),None)
        if not t or t['name']!=s['teacher'] or w['classroom']!=s['classroom'] or w['location']!=s['location'] or minutes(s['time'])<minutes(w['start_time']) or minutes(s['time'])+s['duration']>minutes(w['end_time']):raise ValueError('试听选项已改变')
        if local(s['date']+'T'+s['time'])<=datetime.now(LA):raise ValueError('试听时间已过去')
        conflict_check(c,s,s['date'],s['time'])
    def approve(self,jid):
        c=self.db()
        try:
            lock(c);j=self.get(c,jid);self.identity(c,j)
            if j['trial_schedule_id']:return
            if not j['enabled'] or j['stage']!='selected':raise ValueError('家长还未选择或流程暂停')
            s=json.loads(j['selected']);self.check_trial(c,s)
            cur=c.execute("INSERT INTO schedule(student_name,teacher,lesson_date,lesson_time,classroom,location,status,duration,schedule_type,weekday,notes) VALUES(?,?,?,?,?,?,'scheduled',?,'trial',?,?)",(s['student_name'],s['teacher'],s['date'],s['time'],s['classroom'],s['location'],s['duration'],checked_date(s['date']).strftime('%A'),f"Enrollment journey #{jid}"))
            sid=cur.lastrowid
            c.execute("UPDATE inquiries SET trial_date=?,trial_time=?,trial_teacher=?,trial_location=?,trial_duration=?,trial_status='Scheduled',status='Trial Scheduled',owner_verified=1,updated_at=? WHERE id=?",(s['date'],s['time'],s['teacher'],s['location']+' / '+s['classroom'],str(s['duration']),stamp(),j['inquiry_id']))
            self.set_stage(c,jid,'trial',trial_schedule_id=sid)
            body=f"Trial confirmed: {s['student_name']}, {s['date']} {s['time']} (Los Angeles), {s['duration']} minutes, {s['teacher']}, {s['location']} / {s['classroom']}. Trial fee: ${s['fee']}."
            created=record(c,'SELECT * FROM schedule WHERE id=?',(sid,))
            self.notify(c,j,'trial-confirmed','H-Music trial confirmed',body,self.path(j),lesson_id=sid,lesson_version=fingerprint(created));self.notify(c,j,'teacher-trial','New trial lesson',body,teacher=s['teacher'],lesson_id=sid,lesson_version=fingerprint(created));c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def complete(self,jid,ended):
        end=local(ended)
        if end>datetime.now(LA):raise ValueError('实际结束时间不能在未来')
        c=self.db()
        try:
            lock(c);j=self.get(c,jid)
            if j['stage']!='trial' or not j['enabled']:raise ValueError('只可确认当前已安排试听')
            s=record(c,'SELECT * FROM schedule WHERE id=?',(j['trial_schedule_id'],))
            if not s or str(s.get('status','')).lower() in ('cancelled','canceled','teacher_cancelled','absent','excused','excused_24h','last_min_cancel'):raise ValueError('取消或未到课程不可按完成处理')
            if end<local(s['lesson_date']+'T'+s['lesson_time']):raise ValueError('结束时间不能早于开始')
            c.execute("UPDATE schedule SET status='present' WHERE id=?",(s['id'],))
            self.set_stage(c,jid,'followup',ended_at=end.isoformat(),followup_due=(end+timedelta(hours=2)).isoformat());c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def accept(self,jid,plan_id,signer,policy_version):
        c=self.db()
        try:
            lock(c);j=self.get(c,jid);self.identity(c,j)
            if j['order_id']:return j['order_id']
            if not j['enabled'] or j['stage']!='followup':raise ValueError('Enrollment is not available yet.')
            if not signer.strip() or len(signer)>100:raise ValueError('Enter the guardian name to confirm.')
            p=next((p for p in json.loads(j['plans']) if p['id']==plan_id),None)
            if not p:raise ValueError('Select an enrollment plan.')
            q=quote(c,p['quote']['teacher']['id'],str(p['quote']['minutes']))
            if fingerprint(q)!=fingerprint(p['quote']) or policy_version!=q['policy']['version']:raise ValueError('Tuition or policy changed. Contact H-Music for an updated offer.')
            for day in p['dates']:
                if checked_date(day)<datetime.now(LA).date():raise ValueError('The offered course dates have passed. Contact H-Music.')
                self.check_plan_slot(c,j,p,day)
            i=record(c,'SELECT * FROM inquiries WHERE id=?',(j['inquiry_id'],));q={**q,'student_name':i['student_name'],'email':i['parent_email'],'signed_by':signer.strip(),'accepted_at':stamp(),'checkoutEnabled':catalog(c)['checkoutEnabled'],'formal_plan':p}
            oid=secrets.token_urlsafe(24);access=self.signer.dumps(['order',jid,j['nonce']])
            c.execute("""INSERT INTO admissions_orders(id,request_key,access_hash,inquiry_id,student_key,teacher_id,partner_id,semester,snapshot,subtotal,discount,total,coupon_code,status,created_at) VALUES(?,?,?,?,?,?,?,'',?,?,?,?,?,'registration',?)""",(oid,'trial-enrollment:'+str(jid),digest(access),i['id'],digest(i['parent_email'].lower()+'|'+i['student_name'].casefold()),q['teacher']['id'],'',pack(q),q['subtotal'],q['discount'],q['total'],q['coupon'],stamp()))
            self.set_stage(c,jid,'payment',order_id=oid);c.commit();return oid
        except Exception:c.rollback();raise
        finally:c.close()
    def order_path(self,j):return '/enrollment-order/'+j['order_id']+'/'+self.signer.dumps(['order',j['id'],j['nonce']])
    def process(self,now=None):
        now=now or datetime.now(LA);c=self.db()
        try:
            cur=c.execute("SELECT id FROM studio_enrollment_journeys WHERE enabled=1 AND stage NOT IN ('draft','offered','selected','enrolled','attention','paused') ORDER BY id LIMIT 200")
            ids=[r[0] for r in cur.fetchall()]
        finally:c.close()
        for jid in ids:
            try:self.advance(jid,now)
            except Exception as e:
                # No recipient, payment token or upstream exception text leaks into the UI.
                c=self.db()
                try:
                    lock(c);j=self.get(c,jid);self.set_stage(c,jid,'attention',error='处理未完成，请核对课表、付款和通知队列后重试。');self.owner_notice(c,j,'attention','试听报名流程未完成，请打开管理页核对。');c.commit()
                finally:c.close()
                self.api.get('logger',__import__('logging').getLogger(__name__)).warning('Trial enrollment needs review: journey %s (%s)',jid,type(e).__name__)
    def has_reply(self,c,j):
        if not j['ended_at'] or not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",('studio_communications',)).fetchone():return False
        cur=c.execute("SELECT received_at FROM studio_communications WHERE direction='inbound' AND family_refs LIKE ? ORDER BY received_at DESC LIMIT 20",('%'+json.dumps('inquiry:'+str(j['inquiry_id']))+'%',))
        for row in cur.fetchall():
            try:
                if local(row[0])>=local(j['ended_at']):return True
            except (ValueError,TypeError):continue
        return False
    def advance(self,jid,now):
        c=self.db();paid=False
        try:
            lock(c);j=self.get(c,jid)
            if not j['enabled']:return
            self.identity(c,j)
            if j['stage']=='trial':
                s=record(c,'SELECT * FROM schedule WHERE id=?',(j['trial_schedule_id'],))
                # Attendance confirms actual occurrence; owner can supply an actual end time instead.
                if s and str(s.get('status','')).lower() in ('present','completed'):
                    end=local(s['lesson_date']+'T'+s['lesson_time'])+timedelta(minutes=int(s['duration']))
                    if end<=now:self.set_stage(c,jid,'followup',ended_at=end.isoformat(),followup_due=(end+timedelta(hours=2)).isoformat())
                elif not s or str(s.get('status','')).lower() in ('cancelled','canceled','teacher_cancelled','excused','excused_24h','last_min_cancel','absent'):
                    self.set_stage(c,jid,'attention',error='试听取消或未到，请重新核对安排。');self.owner_notice(c,j,'trial-review','试听取消或未到，已停止试听后自动跟进。')
            j=self.get(c,jid)
            if j['stage']=='followup' and j['followup_due'] and local(j['followup_due'])<=now:
                i=record(c,'SELECT * FROM inquiries WHERE id=?',(j['inquiry_id'],))
                if i.get('converted_student_name') or str(i.get('status','')).lower() in ('lost','closed','enrolled','converted'):
                    self.set_stage(c,jid,'attention',error='咨询状态已改变，停止自动跟进，请核实。')
                elif self.has_reply(c,j):
                    self.owner_notice(c,j,'parent-replied','家长试听后已有回复，请核对对话；未重复发送首次跟进。')
                else:
                    # Neutral approved template: no invented teacher feedback or child assessment.
                    self.notify(c,j,'post-trial','How was your H-Music trial?',f"Thank you for attending the trial. How did it feel for your family? Your school-reviewed enrollment options, lesson dates, tuition and policy are available through the secure link below. Choose a plan to review and pay; bank processing is not payment confirmation.",self.path(j))
            if j['order_id'] and j['stage'] in ('payment','paid'):
                o=record(c,'SELECT * FROM admissions_orders WHERE id=?',(j['order_id'],));paid=bool(o and o['status']=='paid')
            c.commit()
        finally:c.close()
        if paid:self.fulfill(jid)
    def fulfill(self,jid):
        # Called only from verified admissions paid state. Payment/credit posting remains existing CRM logic.
        c=self.db()
        try:
            lock(c);j=self.get(c,jid);self.identity(c,j)
            if not j['enabled'] or j['stage']=='enrolled':return
            o=record(c,'SELECT * FROM admissions_orders WHERE id=?',(j['order_id'],))
            if not o or o['status']!='paid':raise ValueError('尚未核实付款')
            q=json.loads(o['snapshot']);p=q['formal_plan'];i=record(c,'SELECT * FROM inquiries WHERE id=?',(j['inquiry_id'],))
            if not o['invoice_id']:
                existing=record(c,'SELECT id FROM students WHERE name=?',(i['student_name'],))
                if existing:raise ValueError('学生同名或已存在，需校长核实身份')
                matches=c.execute('SELECT id,active FROM parent_profiles WHERE lower(email)=lower(?)',(i['parent_email'],)).fetchall()
                if len(matches)>1 or (matches and not matches[0][1]):raise ValueError('家庭账号需核实')
                for day in p['dates']:
                    if checked_date(day)<datetime.now(LA).date():raise ValueError('付款已确认但课程日期已过，请重新安排')
                    self.check_plan_slot(c,j,p,day)
                c.execute('INSERT INTO students(name,teacher,parent_name,parent_email,parent_phone,lessons_left) VALUES(?,?,?,?,?,0)',(i['student_name'],q['teacher']['name'],i.get('parent_name',''),i['parent_email'],i.get('phone','')))
                if matches:pid=matches[0][0]
                else:
                    # Unusable random password, never displayed or sent. Parent uses existing self-service reset.
                    cur=c.execute("INSERT INTO parent_profiles(parent_name,email,phone,password,password_hash,must_change_password,active,created_at,updated_at) VALUES(?,?,?,'',?,1,1,?,?)",(i.get('parent_name',''),i['parent_email'],i.get('phone',''),self.api['hmusic_password_hash'](secrets.token_urlsafe(48)),stamp(),stamp()));pid=cur.lastrowid
                c.execute("INSERT OR IGNORE INTO parent_students(parent_id,student_name,relationship,active,created_at) VALUES(?,?,'Parent',1,?)",(pid,i['student_name'],stamp()))
                ct=record(c,'SELECT * FROM course_types WHERE id=? AND active=1 AND COALESCE(is_group,0)=0',(p['course_type_id'],))
                if not ct or int(ct['duration'])!=q['minutes']:raise ValueError('课程已变化')
                cur=c.execute("""INSERT INTO enrollments(student_name,course_type_id,course_type_name,teacher_name,duration,student_billing_method,base_price,final_price,lessons_left,status,notes,package_amount,package_lessons,auto_renew_enabled,created_at,updated_at)
                 VALUES(?,?,?,?,?,'Per Lesson',?,?,0,'active',?,?,?,0,?,?)""",(i['student_name'],ct['id'],ct['name'],q['teacher']['name'],q['minutes'],o['subtotal']/100/q['lessons'],o['total']/100/q['lessons'],'Paid enrollment order '+o['id'],o['total']/100,q['lessons'],stamp(),stamp()));eid=cur.lastrowid
                iid=self.api['create_enrollment_invoice'](c.cursor(),eid,'initial_tuition','Paid enrollment order '+o['id'],grant_credit_on_payment=True,attach_pending_charges=False)
                inv=record(c,'SELECT amount FROM invoices WHERE id=?',(iid,))
                if not inv or Decimal(str(inv['amount']))*100!=o['total']:raise ValueError('账单与已付款订单金额不一致')
                c.execute('UPDATE invoices SET discount_code=?,discount_amount=?,stripe_checkout_session_id=? WHERE id=?',(o['coupon_code'],o['discount']/100,o['checkout_id'],iid))
                c.execute('UPDATE admissions_orders SET enrollment_id=?,invoice_id=? WHERE id=?',(eid,iid,o['id']))
                c.execute('UPDATE inquiries SET converted_enrollment_id=? WHERE id=?',(eid,i['id']))
                self.set_stage(c,jid,'paid',result=pack({'parent_id':pid,'invoice_id':iid,'enrollment_id':eid}));c.commit()
            else:c.commit();iid=o['invoice_id']
        except Exception:c.rollback();raise
        finally:c.close()
        if not self.api['finalize_stripe_invoice_payment'](iid,checkout_session_id=o['checkout_id'],source='admissions-'+o['id']):raise ValueError('账单入账需核对')
        c=self.db()
        try:
            lock(c);j=self.get(c,jid);self.identity(c,j)
            if not j['enabled'] or j['stage']=='enrolled':return
            o=record(c,'SELECT * FROM admissions_orders WHERE id=?',(j['order_id'],));inv=record(c,'SELECT * FROM invoices WHERE id=?',(iid,))
            if not inv or inv['status']!='paid' or o['status']!='paid':raise ValueError('账单付款尚未完成')
            result=json.loads(j['result']);ids=[]
            for day in p['dates']:
                if checked_date(day)<datetime.now(LA).date():raise ValueError('课程已过，请重新安排')
                self.check_plan_slot(c,j,p,day)
            for day in p['dates']:
                cur=c.execute("""INSERT INTO schedule(student_name,teacher,lesson_date,lesson_time,classroom,location,status,duration,schedule_type,weekday,notes,enrollment_id,course_type_name,final_price,course_type_id,student_billing_method,student_price,student_charge_amount,teacher_billing_method,teacher_pay,teacher_pay_amount,is_group,start_date,package_type) VALUES(?,?,?,?,?,?,'scheduled',?,'one_time',?,?,?,?,?,?,'Per Lesson',?,?,?,?,?,0,?,?)""",(i['student_name'],q['teacher']['name'],day,p['time'],p['classroom'],p['location'],q['minutes'],checked_date(day).strftime('%A'),f'Paid enrollment journey #{jid}',o['enrollment_id'],p['course_name'],o['total']/100/q['lessons'],p['course_type_id'],o['total']/100/q['lessons'],o['total']/100/q['lessons'],p['payroll']['teacher_billing_method'],p['payroll']['teacher_pay'],p['payroll']['teacher_pay_amount'],p['dates'][0],str(q['lessons'])));ids.append(cur.lastrowid)
            c.execute("UPDATE inquiries SET converted_student_name=?,converted_enrollment_id=?,parent_profile_id=?,status='Active',follow_up_status='Converted',updated_at=? WHERE id=?",(i['student_name'],o['enrollment_id'],result['parent_id'],stamp(),i['id']))
            result['schedule_ids']=ids;self.set_stage(c,jid,'enrolled',result=pack(result),error='')
            # Existing onboarding scheduler supplies d3/d1/d0 reminders; no past node backfill.
            c.execute("INSERT INTO studio_workflows(inquiry_id,first_schedule_id,channels,followup_body,enabled,updated_at) VALUES(?,?,?,'',1,?) ON CONFLICT(inquiry_id) DO UPDATE SET first_schedule_id=excluded.first_schedule_id,channels=excluded.channels,followup_body='',enabled=1,updated_at=excluded.updated_at",(i['id'],ids[0],j['channels'],stamp()))
            body=f"Enrollment and payment confirmed for {i['student_name']}. {len(ids)} lessons with {q['teacher']['name']}; first lesson {p['dates'][0]} {p['time']} (Los Angeles), {p['location']} / {p['classroom']}. Parent App: {self.api['hmusic_public_app_url']('/parent_login')}. Use your existing account. New families: choose Forgot password and enter {i['parent_email']} to set up access. Install: {self.api['hmusic_public_app_url']('/app_install')}."
            self.notify(c,j,'welcome','Welcome to H-Music',body,'/parent_login');self.notify(c,j,'teacher-enrolled','New enrolled student',f"{i['student_name']}: {len(ids)} lessons, {', '.join(p['dates'])}, {p['time']}, {p['location']} / {p['classroom']}.",teacher=q['teacher']['name']);self.owner_notice(c,j,'enrolled','已核实付款、完成正式排课并建立欢迎通知任务。');c.commit()
        except Exception:c.rollback();raise
        finally:c.close()

STYLE='''<style>body{font:16px/1.6 system-ui;margin:0;background:#f5f5f1;color:#202c28}main{max-width:1050px;margin:32px auto;padding:24px}article,section{background:white;border:1px solid #ddd;border-radius:16px;padding:24px;margin:20px 0}label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;padding:9px;border:1px solid #bbb;border-radius:7px;max-width:100%;box-sizing:border-box}textarea{width:100%}button{background:#214b3b;color:white;cursor:pointer}a{color:#215b43}small{color:#66736c}.error{color:#9a3027}.row{display:flex;gap:18px;flex-wrap:wrap}.row>*{flex:1;min-width:180px}pre{white-space:pre-wrap}summary{cursor:pointer}h1,h2{line-height:1.25}nav{display:flex;gap:18px;flex-wrap:wrap}</style>'''
OWNER='''<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>试听到报名 · H-Music</title>{{style|safe}}</head><body><main>
<nav><a href="/owner_dashboard">CRM 工作台</a><a href="/admissions-admin">报名价格与政策</a><a href="/inquiries">咨询记录</a></nav>
<h1>试听到报名</h1><p><b>{{'后台自动化已启用，每分钟检查' if scheduler_enabled else '后台自动化未启用，定时跟进与缴费后排课不会自动执行'}}</b></p><p>只为逐个核实并启用的家庭执行。试听由家长选时间、校长确认；试听结束两小时后跟进；核实缴费后自动正式排课并通知。</p>
{% if error %}<section class="error">{{error}}</section>{% endif %}
<section><h2>启用一个家庭</h2><form method="post"><input type="hidden" name="action" value="create"><label>咨询记录<select name="inquiry_id" required>{% for i in inquiries %}<option value="{{i.id}}">#{{i.id}} · {{i.student_name}} · {{i.parent_email}} · {{i.source}}</option>{% endfor %}</select></label><label><input type="checkbox" name="email" checked>邮件</label><label><input type="checkbox" name="sms">短信（需有效手机号与已配置通道）</label><label><input type="checkbox" name="identity_confirmed" required>我已核对原始请求、家庭身份与联系方式，并批准该家庭按本流程接收消息和缴费后排课。</label><button>建立流程</button></form></section>
<details><summary>管理已核实的老师工作时段（自动扫描的依据）</summary><section><p>确认老师能够教授所选课程，并核实实际校区、教室与工作时段。课表空白本身不代表老师可工作。</p><form method="post"><input type="hidden" name="action" value="window">{{teacher_select|safe}}{{course_select|safe}}<div class="row"><label>开始日期<input name="date_from" type="date" required></label><label>结束日期<input name="date_until" type="date" required></label></div><div class="row"><label>开始时间<input name="start_time" type="time" required></label><label>结束时间<input name="end_time" type="time" required></label></div><p>每周工作日</p>{% for day in weekdays %}<label style="display:inline-block"><input type="checkbox" name="weekdays" value="{{loop.index0}}">{{day}}</label>{% endfor %}<div class="row"><label>教室<input name="classroom" required maxlength="120"></label><label>校区<input name="location" required maxlength="120"></label></div><label><input type="checkbox" required>已向老师核实时间、课程适配和地点</label><button>保存可工作时段</button></form>
{% for w in windows %}<p>#{{w.id}} · {{w.teacher_id}} · {{w.date_from}}—{{w.date_until}} · {{w.start_time}}—{{w.end_time}} · {{w.location}} / {{w.classroom}} · {{'启用' if w.active else '停用'}}</p>{% if w.active %}<form method="post"><input type="hidden" name="action" value="disable_window"><input type="hidden" name="window_id" value="{{w.id}}"><button>停用这个时段</button></form>{% endif %}{% endfor %}</section></details>
{% for j in journeys %}<article><h2>#{{j.id}} · {{j.student_name}} · {{stages.get(j.stage,j.stage)}}</h2><p>来源：{{j.source_info.get('source') or '待核实'}} · {{j.source_info.get('parent_email')}}</p>{% if j.error %}<p class="error">{{j.error}}</p>{% endif %}<p><a href="{{j.parent_path}}" target="_blank" rel="noopener">打开该家庭的私密选择页面</a>（仅向该家庭分享）</p>
{% if j.selected_info %}<p>家长选择：{{j.selected_info.date}} {{j.selected_info.time}} · {{j.selected_info.teacher}} · {{j.selected_info.location}} / {{j.selected_info.classroom}}</p>{% endif %}
{% if j.followup_due %}<p>试听后跟进时间：{{j.followup_due}}（洛杉矶时间，不限夜间）</p>{% endif %}
{% for p in j.plan_info %}<p>报名方案 {{loop.index}}：{{p.course_name}} · {{p.quote.teacher.name}} · {{p.quote.minutes}} 分钟 × {{p.quote.lessons}} · ${{'%.2f'|format(p.quote.total/100)}}<br>已审核日期：{{p.dates|join('、')}} {{p.time}} · {{p.location}} / {{p.classroom}}</p>{% endfor %}
{% if j.enabled and not j.order_id and j.stage in ['draft','offered','selected','trial','followup'] %}<details><summary>添加家长可选的正式报名方案</summary><form method="post"><input type="hidden" name="action" value="plan"><input type="hidden" name="jid" value="{{j.id}}">{{teacher_select|safe}}{{course_select|safe}}<label>正式课程日期（每行 YYYY-MM-DD；需与套餐课次数一致，先排除学校假期）<textarea name="dates" rows="5" required></textarea></label><div class="row"><label>每节开始时间<input name="time" type="time" required></label><label>教室<input name="classroom" required></label><label>校区<input name="location" required></label></div><label><input type="checkbox" required>已审核全部日期、老师工作时间、费用与政策。最终时段由家长选择方案后确认；付款前不占位。</label><button>保存已审核方案</button></form></details>{% endif %}
{% if j.enabled and j.stage in ['draft','offered','selected'] %}<details><summary>扫描试听空点并发送家长选项</summary><form method="post"><input type="hidden" name="action" value="offer"><input type="hidden" name="jid" value="{{j.id}}">{{course_select|safe}}<div class="row"><label>查询开始<input name="start" type="date" required></label><label>查询结束<input name="end" type="date" required></label><label>已核实试听费（美元；免费填0）<input name="trial_fee" type="number" min="0" step="0.01" required></label></div><p>最多提供12个不冲突选项；重新扫描不会重复发送同一邀请，可分享上方链接。</p><button>扫描并发送试听选项</button></form></details>{% endif %}
{% if j.enabled and j.stage=='selected' %}<form method="post"><input type="hidden" name="action" value="approve"><input type="hidden" name="jid" value="{{j.id}}"><label><input type="checkbox" required>确认上方家长选定的老师、时间、教室与试听费用</label><button>确认试听并通知家长和老师</button></form>{% endif %}
{% if j.enabled and j.stage=='trial' %}<form method="post"><input type="hidden" name="action" value="complete"><input type="hidden" name="jid" value="{{j.id}}"><label>试听实际结束时间<input name="ended" type="datetime-local" required></label><button>确认已完成，安排两小时后跟进</button></form><small>老师登记出勤后也会自动识别；默认使用课表结束时间。若实际时间不同，请在老师登记前填写。</small>{% endif %}
{% if j.order_id %}<p>报名订单：{{j.order_id}} · <a href="{{j.order_path}}">查看付款进度</a></p>{% endif %}
{% if j.result_info.schedule_ids %}<p>已建立正式课程编号：{{j.result_info.schedule_ids|join('、')}}</p>{% endif %}
{% if j.stage=='attention' and j.enabled %}<form method="post"><input type="hidden" name="action" value="retry"><input type="hidden" name="jid" value="{{j.id}}"><label><input type="checkbox" required>已核对当前付款、课表及失败原因；重试不会重新收费</label><button>重新核对并继续</button></form>{% endif %}
{% if j.enabled %}<form method="post"><input type="hidden" name="action" value="pause"><input type="hidden" name="jid" value="{{j.id}}"><button>暂停此家庭后续自动化</button></form>{% endif %}
<details><summary>通知任务与结果</summary>{% for t in j.tasks %}<p>{{t.title}} · {{task_states.get(t.state,t.state)}} · {{t.updated_at}}</p>{% else %}<p>尚无通知任务</p>{% endfor %}</details></article>{% endfor %}</main></body></html>'''
PUBLIC='''<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>H-Music · Trial & enrollment</title>{{style|safe}}</head><body><main><h1>H-Music · Trial & enrollment</h1><p>For {{student}}. Los Angeles time. Please keep this family link private.</p>{% if error %}<section class="error">{{error}}</section>{% endif %}
{% if j.stage=='offered' %}<section><h2>Choose a trial time</h2><p>Your choice will be reviewed by H-Music. It is not a confirmed reservation until the school confirms it.</p><form method="post"><input type="hidden" name="action" value="select"><input type="hidden" name="choices_version" value="{{choices_version}}">{% for s in choices %}<label><input type="radio" name="index" value="{{loop.index0}}" required>{{s.date}} {{s.time}} · {{s.teacher}} · {{s.duration}} minutes · {{s.location}} / {{s.classroom}} · trial fee ${{s.fee}}</label>{% endfor %}<button>Submit my preferred trial time</button></form></section>
{% elif j.stage=='selected' %}<section><h2>Your choice is waiting for school confirmation.</h2><p>H-Music will contact you after reviewing the schedule.</p></section>
{% elif j.stage=='trial' %}<section><h2>Your trial is confirmed.</h2><p>{{chosen.date}} {{chosen.time}} · {{chosen.teacher}} · {{chosen.location}} / {{chosen.classroom}}</p><p>After the lesson, we will follow up with your enrollment options.</p></section>
{% elif j.stage=='followup' %}<section><h2>Your enrollment options</h2><p>Please tell us how the trial felt. To enroll, choose a school-reviewed plan below and confirm the lesson dates, tuition and policy. Formal lessons are scheduled after verified payment, subject to a final availability check. If a slot becomes unavailable, H-Music will contact you rather than change it automatically.</p><form method="post"><input type="hidden" name="action" value="enroll">{% for p in plans %}<article><label><input type="radio" name="plan_id" value="{{p.id}}" required><b>{{p.course_name}} · {{p.quote.teacher.name}}</b></label><p>{{p.quote.minutes}} minutes × {{p.quote.lessons}} lessons · Total ${{'%.2f'|format(p.quote.total/100)}}</p><p>{{p.dates|join(', ')}}<br>{{p.time}} · {{p.location}} / {{p.classroom}}</p></article>{% endfor %}<h3>School policy · {{policy.version}}</h3><pre>{{policy.text}}</pre><input type="hidden" name="policy_version" value="{{policy.version}}"><label>Guardian name<input name="signed_by" required maxlength="100"></label><label><input name="accepted" value="yes" type="checkbox" required>I confirm my selected plan, all lesson dates, tuition and school policy.</label><button>Confirm enrollment & review secure payment</button></form></section>
{% elif j.stage in ['payment','paid'] %}<section><h2>Enrollment received</h2><p>Bank processing is not payment confirmation. Please use the same order; do not register or pay again.</p><a href="{{order_path}}">Review order and payment status →</a></section>
{% elif j.stage=='enrolled' %}<section><h2>Welcome! Payment and enrollment are confirmed.</h2><p>Your formal lessons have been added to the school schedule. Check your welcome notification for dates and Parent App access.</p><a href="/parent_login">Parent App login</a> · <a href="/parent_forgot_password">Set up / recover password</a> · <a href="/app_install">Install app</a></section>
{% else %}<section><p>H-Music is reviewing your request. Contact info@h-musicandarts.com for help. Please do not submit another payment.</p></section>{% endif %}</main></body></html>'''


def register_trial_enrollment(app,operations,api):
    service=Journey(operations,api,app.secret_key);bp=Blueprint('trial_enrollment',__name__)
    def html(template,**values):
        r=app.make_response(render_template_string(template,style=STYLE,**values));r.headers['Cache-Control']='private, no-store';r.headers['Referrer-Policy']='no-referrer';r.headers['X-Robots-Tag']='noindex, nofollow';return r
    def owner_data(error=''):
        c=service.db()
        try:
            cfg=catalog(c);teachers=[t for t in cfg['teachers'] if t['active']]
            def rows(sql):
                cur=c.execute(sql);return [dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
            courses=rows('SELECT id,name,duration FROM course_types WHERE active=1 AND COALESCE(is_group,0)=0 ORDER BY name,duration')
            from markupsafe import escape
            ts='<label>已发布老师<select name="teacher_id" required>'+''.join(f'<option value="{escape(t["id"])}">{escape(t["name"])} · {escape(t["subject"])}</option>' for t in teachers)+'</select></label>'
            cs='<label>课程类型<select name="course_type_id" required>'+''.join(f'<option value="{ct["id"]}">{escape(ct["name"])} · {ct["duration"]}分钟</option>' for ct in courses)+'</select></label>'
            js=rows('SELECT j.*,i.student_name FROM studio_enrollment_journeys j JOIN inquiries i ON i.id=j.inquiry_id ORDER BY j.id DESC LIMIT 100')
            for j in js:
                for raw,key in [('source','source_info'),('selected','selected_info'),('plans','plan_info'),('result','result_info')]:j[key]=json.loads(j[raw])
                j['parent_path']=service.path(j);j['order_path']=service.order_path(j) if j['order_id'] else ''
                cur=c.execute('SELECT payload,state,updated_at FROM studio_tasks WHERE operation_id=? ORDER BY id',(f"enrollment:{j['id']}",));j['tasks']=[{'title':json.loads(r[0])['title'],'state':r[1],'updated_at':r[2]} for r in cur.fetchall()]
            return html(OWNER,scheduler_enabled=__import__('os').environ.get('HMUSIC_STUDIO_AUTOMATION')=='1',journeys=js,inquiries=rows("SELECT id,student_name,parent_email,source FROM inquiries WHERE COALESCE(converted_student_name,'')='' ORDER BY id DESC LIMIT 200"),windows=rows('SELECT * FROM studio_enrollment_windows ORDER BY id DESC'),teacher_select=ts,course_select=cs,weekdays=['周一','周二','周三','周四','周五','周六','周日'],stages=STAGES,error=error,task_states={'pending':'待发送','running':'处理中','completed':'已完成','attention':'需核对发送结果','cancelled':'已取消'})
        finally:c.close()
    @bp.route(ROOT,methods=['GET','POST'])
    def owner():
        if not api['require_owner']():return redirect('/owner_login')
        if request.method=='GET':return owner_data('页面验证已过期，请核对后重新提交。' if request.args.get('csrf_refresh') else '')
        d=request.form
        try:
            action=d['action']
            if action=='create':
                if d.get('identity_confirmed')!='on':raise ValueError('请先核实家庭身份')
                service.create(int(d['inquiry_id']),[x for x in ('email','sms') if d.get(x)])
            elif action=='window':service.add_window(d)
            elif action=='plan':service.add_plan(int(d['jid']),d)
            elif action=='offer':service.offer(int(d['jid']),d)
            elif action=='approve':service.approve(int(d['jid']))
            elif action=='complete':service.complete(int(d['jid']),d['ended'])
            elif action in ('pause','retry','disable_window'):
                c=service.db()
                try:
                    lock(c)
                    if action=='disable_window':c.execute('UPDATE studio_enrollment_windows SET active=0 WHERE id=?',(int(d['window_id']),))
                    else:
                        j=service.get(c,int(d['jid']))
                        if action=='pause':
                            c.execute('UPDATE studio_enrollment_journeys SET enabled=0,updated_at=? WHERE id=?',(stamp(),j['id']))
                            c.execute('UPDATE studio_workflows SET enabled=0,updated_at=? WHERE inquiry_id=?',(stamp(),j['inquiry_id']))
                        else:
                            if not j['enabled'] or j['stage']!='attention':raise ValueError('仅能重试已启用的待处理流程')
                            service.set_stage(c,j['id'],'payment' if j['order_id'] else 'followup' if j['ended_at'] else 'trial',error='')
                    c.commit()
                except Exception:c.rollback();raise
                finally:c.close()
            else:raise ValueError('不支持的操作')
        except (ValueError,KeyError,TypeError,ArithmeticError) as e:return owner_data(str(e))
        return redirect(ROOT,code=303)
    @bp.route('/trial-enrollment/<token>',methods=['GET','POST'])
    def parent(token):
        c=service.db()
        try:j=service.public(c,token);policy=catalog(c)['policy']
        finally:c.close()
        error='The page expired. Please review and submit again.' if request.args.get('csrf_refresh') else ''
        if request.method=='POST':
            try:
                if request.form.get('action')=='select':service.select(j['id'],int(request.form['index']),request.form['choices_version'])
                elif request.form.get('action')=='enroll':
                    if request.form.get('accepted')!='yes':raise ValueError('Confirm the plan and policy before continuing.')
                    service.accept(j['id'],request.form['plan_id'],request.form['signed_by'],request.form['policy_version'])
                else:raise ValueError('Invalid action.')
                return redirect(service.path(j),code=303)
            except (ValueError,KeyError,TypeError):error='This option needs school review or the form is incomplete. Please contact H-Music; do not submit another payment.'
        return html(PUBLIC,j=j,choices_version=fingerprint(json.loads(j['candidates'])),student=json.loads(j['source'])['student_name'],choices=json.loads(j['candidates']),chosen=json.loads(j['selected']),plans=json.loads(j['plans']),policy=policy,order_path=service.order_path(j) if j['order_id'] else '',error=error)
    app.register_blueprint(bp);app.extensions['trial_enrollment']=service
    operations.journeys=service
    return service
