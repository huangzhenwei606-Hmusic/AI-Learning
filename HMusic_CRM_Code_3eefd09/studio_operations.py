"""Scoped Studio operations, durable outbox, and opt-in onboarding automation.
Never imports app or sends on import. Business settlement stays in the CRM.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify

LA = ZoneInfo('America/Los_Angeles')
PREFIX = '/api/studio-agent/v1/operations'
CANCELLED = {'cancelled', 'canceled', 'teacher_cancelled', 'excused', 'excused_24h', 'last_min_cancel'}

def stamp(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def pack(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
def fingerprint(v): return hashlib.sha256(pack(v).encode()).hexdigest()
def record(c, sql, args=()):
    cur=c.execute(sql,args); r=cur.fetchone()
    return dict(zip([d[0] for d in cur.description],r)) if r else None

def schema(c):
    for sql in [
        '''CREATE TABLE IF NOT EXISTS studio_operations (id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL, baseline TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL, expires TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS studio_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT NOT NULL UNIQUE, operation_id TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS studio_workflows (inquiry_id INTEGER PRIMARY KEY, first_schedule_id INTEGER, channels TEXT NOT NULL, followup_body TEXT NOT NULL, enabled INTEGER NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS studio_leases (id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires TEXT NOT NULL)'''
    ]: c.execute(sql)
    c.commit()

def minutes(s):
    try:
        t=datetime.strptime(str(s),'%H:%M'); return t.hour*60+t.minute
    except (ValueError,TypeError): raise ValueError('时间须为 HH:MM')
def checked_date(s):
    d=date.fromisoformat(s)
    if d.isoformat()!=s: raise ValueError('日期无效')
    return d

def channels(v):
    if not isinstance(v,list) or not v or len(v)>3 or len(set(v))!=len(v) or any(x not in ('email','sms','push') for x in v): raise ValueError('选择邮件、短信或 App 渠道')
    return v

def get_target(c,p):
    kind=p.get('target_kind'); ident=int(p.get('target_id',0))
    if kind=='inquiry':
        r=record(c,'SELECT * FROM inquiries WHERE id=?',(ident,))
        if r:
            return {'kind':kind,'id':ident,'student_name':r['student_name'],'parent_id':r.get('parent_profile_id'),'email':r.get('parent_email'),'phone':r.get('phone')}
    elif kind=='parent':
        r=record(c,'SELECT * FROM parent_profiles WHERE id=? AND COALESCE(active,1)=1',(ident,))
        if r:return {'kind':kind,'id':ident,'parent_id':ident,'email':r.get('email'),'phone':r.get('phone'),'name':r.get('parent_name')}
    raise ValueError('找不到指定家庭，请重新选择')

def lesson(c,ident):
    r=record(c,'SELECT * FROM schedule WHERE id=?',(int(ident),))
    if not r:raise ValueError('课程不存在')
    return r

def conflict_check(c,r,day,clock):
    checked_date(day); start=minutes(clock); duration=int(r.get('duration') or 0)
    if duration<=0 or start+duration>1440:raise ValueError('课程时长无效或跨越午夜')
    if str(r.get('status') or '').lower() in CANCELLED:raise ValueError('已取消课程不能移动')
    if not r.get('teacher') or not r.get('classroom'):raise ValueError('课程缺少老师或教室')
    cur=c.execute('SELECT * FROM schedule WHERE lesson_date=? AND id<>?',(day,r.get('id',-1)))
    names=lambda x:{n.strip().casefold() for n in (str(x.get('student_name') or '')+','+str(x.get('group_student_names') or '')).replace(';',',').split(',') if n.strip()}
    for rr in cur.fetchall():
        other=dict(zip([d[0] for d in cur.description],rr))
        if str(other.get('status') or '').lower() in CANCELLED:continue
        same_teacher=other.get('teacher')==r['teacher']
        same_student=bool(names(r)&names(other))
        same_room=other.get('classroom')==r['classroom'] and (other.get('location_id')==r.get('location_id') if other.get('location_id') and r.get('location_id') else (not other.get('location') or not r.get('location') or other.get('location')==r.get('location')))
        if not (same_teacher or same_student or same_room):continue
        b=minutes(other.get('lesson_time')); d=int(other.get('duration') or 0)
        if d<=0:raise ValueError('相关课程缺少时长，需核实')
        if max(start,b)<min(start+duration,b+d):raise ValueError('课程冲突 #'+str(other['id']))
    cur=c.execute("SELECT * FROM teacher_time_off_requests WHERE teacher_name=? AND start_date<=? AND COALESCE(NULLIF(end_date,''),start_date)>=? AND status IN ('pending','approved')",(r['teacher'],day,day))
    for rr in cur.fetchall():
        off=dict(zip([d[0] for d in cur.description],rr))
        if off.get('all_day') or not off.get('start_time') or not off.get('end_time') or max(start,minutes(off['start_time']))<min(start+duration,minutes(off['end_time'])):raise ValueError('老师有请假记录')

def reminder_nodes(day,clock):
    start=datetime.combine(checked_date(day),datetime.strptime(clock,'%H:%M').time(),LA)
    return [('d3',datetime.combine(start.date()-timedelta(days=3),datetime.min.time(),LA).replace(hour=9)),('d1',datetime.combine(start.date()-timedelta(days=1),datetime.min.time(),LA).replace(hour=9)),('d0',start-timedelta(hours=2))]

class Operations:
    def __init__(self,connect,api):self.connect=connect;self.api=api;self.lock=threading.Lock();self.pid=None
    def db(self):
        c=self.connect();schema(c);return c
    def current(self,c,action,p):
        if action=='reschedule':
            r=lesson(c,p['lesson_id']);conflict_check(c,r,p['date'],p['time']);return r
        if action=='trial':
            r=record(c,'SELECT * FROM inquiries WHERE id=?',(int(p['inquiry_id']),))
            if not r:raise ValueError('试听记录不存在')
            if r.get('converted_student_name'):raise ValueError('该咨询已转为学生')
            if not record(c,'SELECT teacher_name FROM teachers WHERE teacher_name=?',(p['teacher'],)):raise ValueError('老师不存在')
            dummy={'student_name':r['student_name'],'teacher':p['teacher'],'classroom':p['classroom'],'duration':int(p['duration']),'location':p.get('location','')}
            if dummy['duration'] not in (30,45,60):raise ValueError('试听课长须为30、45或60分钟')
            if r.get('trial_date') and str(r.get('trial_status','')).lower()=='scheduled':raise ValueError('试听已安排，请使用现有课程改课')
            conflict_check(c,dummy,p['date'],p['time']);return r
        if action=='invoice':
            r=record(c,'SELECT * FROM enrollments WHERE id=?',(int(p['enrollment_id']),))
            if not r:raise ValueError('报名课程账户不存在')
            if not r.get('package_lessons') or float(r['package_lessons'])<=0 or not r.get('package_amount') or float(r['package_amount'])<=0:raise ValueError('请先在 CRM 确认课包课次和金额，Agent 不推算价格')
            existing=record(c,"SELECT * FROM invoices WHERE enrollment_id=? AND invoice_type='initial' AND status<>'paid' ORDER BY id DESC LIMIT 1",(p['enrollment_id'],))
            return {**r,'existing_invoice':existing,'review_amount':existing['amount'] if existing else r['package_amount']}
        if action=='message':
            channels(p.get('channels'))
            if not isinstance(p.get('body'),str) or not 1<=len(p['body'])<=4000 or not isinstance(p.get('title'),str) or not 1<=len(p['title'])<=120:raise ValueError('消息标题或正文长度无效')
            return get_target(c,p)
        if action=='workflow':
            channels(p.get('channels'));r=record(c,'SELECT * FROM inquiries WHERE id=?',(int(p['inquiry_id']),))
            if not r:raise ValueError('咨询记录不存在')
            if p.get('first_schedule_id'):
                s=lesson(c,p['first_schedule_id'])
                if s['student_name']!=(r.get('converted_student_name') or r['student_name']):raise ValueError('首课不属于这个学生')
                if str(s.get('schedule_type') or '').lower()=='trial':raise ValueError('请选择正式首课，试听提醒另行安排')
            if p.get('next_follow_up_at'):
                datetime.fromisoformat(p['next_follow_up_at'])
            if p.get('enabled') and p.get('followup_body') and not (p.get('next_follow_up_at') or r.get('next_follow_up_at')):raise ValueError('自动跟进需要明确发送日期与时间')
            if len(str(p.get('followup_body') or ''))>4000:raise ValueError('跟进模板过长')
            return {'inquiry':r,'first':lesson(c,p['first_schedule_id']) if p.get('first_schedule_id') else None,'workflow':record(c,'SELECT * FROM studio_workflows WHERE inquiry_id=?',(int(p['inquiry_id']),))}
        raise ValueError('不支持的操作')
    def prepare(self,action,p,actor):
        allowed={'reschedule':{'lesson_id','date','time','channels'},'trial':{'inquiry_id','teacher','date','time','classroom','duration','channels','location'},'invoice':{'enrollment_id','channels'},'message':{'target_kind','target_id','title','body','channels'},'workflow':{'inquiry_id','first_schedule_id','channels','followup_body','enabled','next_follow_up_at'}}
        if action not in allowed or not isinstance(p,dict):raise ValueError('不支持的操作')
        p={k:v for k,v in p.items() if k in allowed[action]}
        c=self.db()
        try:
            if action in ('trial','reschedule','invoice'):
                p={**p,'channels':channels(p.get('channels',['email','push']))}
            baseline=self.current(c,action,p);ident=secrets.token_urlsafe(20);now=stamp()
            c.execute('INSERT INTO studio_operations VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,actor,action,pack(p),fingerprint(baseline),'prepared','{}',(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),now,now));c.commit()
            summary={'action':action,'parameters':p,'record':baseline,'cautions':['已检查课程冲突和请假；老师工作时段、资质匹配和跨校区交通需 Owner 核实'] if action in ('trial','reschedule') else [],'expires_in_minutes':15}
            return {'id':ident,'state':'prepared','review':summary,'executed':False}
        finally:c.close()
    def task(self,c,key,op,p):
        c.execute("INSERT OR IGNORE INTO studio_tasks (task_key,operation_id,payload,state,result,created_at,updated_at) VALUES (?,?,?,'pending','{}',?,?)",(key,op,pack(p),stamp(),stamp()))
    def execute(self,ident,actor):
        c=self.db()
        try:
            # Serialize all Agent writes. PostgreSQL row locking also protects cross-process confirmations.
            c.execute("INSERT OR IGNORE INTO studio_leases VALUES ('write','', '')")
            c.execute("UPDATE studio_leases SET owner=? WHERE id='write'",(ident,))
            op=record(c,'SELECT * FROM studio_operations WHERE id=? AND actor=?',(ident,actor))
            if not op:raise ValueError('提案不存在')
            if op['state']!='prepared':c.rollback();return self.status(ident,actor)
            if op['expires']<stamp():raise ValueError('提案已过期，请重新检查')
            p=json.loads(op['payload']);action=op['action'];baseline=self.current(c,action,p)
            if fingerprint(baseline)!=op['baseline']:raise ValueError('原记录已经改变，请重新检查')
            result={}
            if action=='reschedule':
                changed=c.execute('UPDATE schedule SET lesson_date=?,lesson_time=?,weekday=? WHERE id=? AND lesson_date=? AND lesson_time=? AND teacher=?',(p['date'],p['time'],checked_date(p['date']).strftime('%A'),p['lesson_id'],baseline['lesson_date'],baseline['lesson_time'],baseline['teacher'])).rowcount
                if changed!=1:raise ValueError('原课程已被修改，请重新检查')
                result={'lesson':lesson(c,p['lesson_id'])}
                # Existing reminders are invalid after a move. Sent messages remain audit history.
                c.execute("UPDATE notification_delivery_queue SET status='cancelled' WHERE related_type IN ('lesson_reminder','teacher_lesson_reminder') AND related_id=? AND status='pending'",(p['lesson_id'],))
                participants=[n.strip() for n in (str(baseline['student_name'])+','+str(baseline.get('group_student_names') or '')).replace(';',',').split(',') if n.strip()]
                for parent in c.execute('SELECT DISTINCT parent_id FROM parent_students WHERE student_name IN ('+','.join('?' for _ in participants)+') AND active=1',participants).fetchall():
                    self.task(c,ident+':parent:'+str(parent[0]),ident,{'target_kind':'parent','target_id':parent[0],'channels':p['channels'],'title':'Lesson rescheduled','body':f"{baseline['student_name']}: {baseline['lesson_date']} {baseline['lesson_time']} → {p['date']} {p['time']}. Teacher: {baseline['teacher']}; room: {baseline['classroom']}.",'lesson_id':p['lesson_id'],'lesson_version':fingerprint(result['lesson'])})
                self.task(c,ident+':teacher',ident,{'teacher':baseline['teacher'],'channels':['push','email'],'title':'Lesson rescheduled','body':f"{baseline['student_name']}: {baseline['lesson_date']} {baseline['lesson_time']} → {p['date']} {p['time']}. Room: {baseline['classroom']}.",'lesson_id':p['lesson_id'],'lesson_version':fingerprint(result['lesson'])})
            elif action=='trial':
                c.execute("UPDATE inquiries SET trial_date=?,trial_time=?,trial_teacher=?,trial_location=?,trial_duration=?,trial_status='Scheduled',status='Trial Scheduled',owner_verified=1,updated_at=? WHERE id=?",(p['date'],p['time'],p['teacher'],p['classroom'],str(p['duration']),stamp(),p['inquiry_id']))
                cur=c.execute("INSERT INTO schedule (student_name,teacher,lesson_date,lesson_time,classroom,status,duration,schedule_type,notes) VALUES (?,?,?,?,?,'scheduled',?,'trial',?)",(baseline['student_name'],p['teacher'],p['date'],p['time'],p['classroom'],p['duration'],'Studio Agent inquiry #'+str(p['inquiry_id'])))
                schedule_id=cur.lastrowid
                result={'inquiry_id':p['inquiry_id'],'lesson':lesson(c,schedule_id)}
                self.task(c,ident+':trial',ident,{'target_kind':'inquiry','target_id':p['inquiry_id'],'channels':channels(p.get('channels',['email'])),'title':'Trial lesson confirmed','body':f"{baseline['student_name']}: trial on {p['date']} at {p['time']}, {p['duration']} minutes with {p['teacher']}. Room: {p['classroom']}.",'lesson_id':schedule_id,'lesson_version':fingerprint(result['lesson'])})
                self.task(c,ident+':teacher',ident,{'teacher':p['teacher'],'channels':['push','email'],'title':'Trial lesson confirmed','body':f"{baseline['student_name']}: {p['date']} {p['time']}, {p['duration']} minutes. Room: {p['classroom']}.",'lesson_id':schedule_id,'lesson_version':fingerprint(result['lesson'])})
            elif action=='invoice':
                invoice_id=baseline['existing_invoice']['id'] if baseline.get('existing_invoice') else self.api['create_enrollment_invoice'](c.cursor(),p['enrollment_id'],'initial',notes='Studio Agent owner-confirmed invoice',attach_pending_charges=False)
                result={'invoice':record(c,'SELECT * FROM invoices WHERE id=?',(invoice_id,)),'payment_path':'/parent_invoice/'+str(invoice_id)}
                if float(result['invoice']['amount'])!=float(baseline['review_amount']):raise ValueError('账单金额已变化，请重新检查')
                if result['invoice']['status'] not in ('unpaid','pending'):
                    raise ValueError('该账单不可作为未付款账单发送')
                for parent in c.execute('SELECT DISTINCT parent_id FROM parent_students WHERE student_name=? AND active=1',(baseline['student_name'],)).fetchall():
                    self.task(c,ident+':invoice:'+str(parent[0]),ident,{'target_kind':'parent','target_id':parent[0],'channels':channels(p.get('channels',['email','push'])),'title':'H-Music tuition invoice','body':f"{baseline['student_name']}: invoice #{invoice_id}, amount ${result['invoice']['amount']}. Please review and pay securely in the Parent App.",'invoice_id':invoice_id})
            elif action=='message':
                self.task(c,ident+':message',ident,p);result={'queued':True}
            elif action=='workflow':
                if p.get('next_follow_up_at'):
                    c.execute('UPDATE inquiries SET next_follow_up_at=?,updated_at=? WHERE id=?',(p['next_follow_up_at'].replace('T',' '),stamp(),p['inquiry_id']))
                c.execute('INSERT INTO studio_workflows (inquiry_id,first_schedule_id,channels,followup_body,enabled,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT (inquiry_id) DO UPDATE SET first_schedule_id=excluded.first_schedule_id,channels=excluded.channels,followup_body=excluded.followup_body,enabled=excluded.enabled,updated_at=excluded.updated_at',(p['inquiry_id'],p.get('first_schedule_id'),pack(p['channels']),str(p.get('followup_body') or ''),1 if p.get('enabled') else 0,stamp()))
                result={'workflow':record(c,'SELECT * FROM studio_workflows WHERE inquiry_id=?',(p['inquiry_id'],))}
            c.execute("UPDATE studio_operations SET state='completed',result=?,updated_at=? WHERE id=?",(pack(result),stamp(),ident));c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
        threading.Thread(target=self.tick,name='studio-dispatch',daemon=True).start()
        return self.status(ident,actor)
    def status(self,ident,actor):
        c=self.db()
        try:
            op=record(c,'SELECT id,action,state,result,updated_at FROM studio_operations WHERE id=? AND actor=?',(ident,actor))
            if not op:raise ValueError('操作不存在')
            op['result']=json.loads(op['result']);op['tasks']=[dict(zip([d[0] for d in cur.description],r)) for cur in [c.execute('SELECT id,state,result,updated_at FROM studio_tasks WHERE operation_id=? ORDER BY id',(ident,))] for r in cur.fetchall()]
            for t in op['tasks']:t['result']=json.loads(t['result'])
            op['executed']=op['state']=='completed';return op
        finally:c.close()
    def overview(self):
        c=self.db()
        try:
            rows=[]
            cur=c.execute('SELECT w.*,i.student_name,i.status,i.trial_teacher,i.trial_date,i.next_follow_up_at,i.converted_student_name FROM studio_workflows w JOIN inquiries i ON i.id=w.inquiry_id ORDER BY w.updated_at DESC LIMIT 100')
            for r in cur.fetchall():
                x=dict(zip([d[0] for d in cur.description],r));x['next_action']='核对报名及首课' if x['converted_student_name'] else '安排老师与试听' if not x['trial_date'] else '收集真实试听反馈并跟进';rows.append(x)
            cur=c.execute('SELECT id,action,state,updated_at,result FROM studio_operations ORDER BY created_at DESC LIMIT 30')
            ops=[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
            cur=c.execute("SELECT id,state,updated_at,result FROM studio_tasks WHERE state<>'completed' ORDER BY id DESC LIMIT 30")
            tasks=[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
            cur=c.execute('SELECT id,student_name,course_type_name,package_lessons,package_amount FROM enrollments ORDER BY student_name LIMIT 2000')
            enrollments=[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
            return {'enrollments':enrollments,'workflows':rows,'operations':ops,'attention':tasks,'reminders':{'days':[3,1,0],'advance_local_time':'09:00','same_day_hours_before':2,'timezone':'America/Los_Angeles'},'scheduler_enabled':os.environ.get('HMUSIC_STUDIO_AUTOMATION')=='1','delivery_configuration':{'email':self.api['smtp_config_status']()[0],'sms':self.api['sms_config_status']()[0],'stripe':bool(os.environ.get('STRIPE_SECRET_KEY')),'stripe_webhook':bool(os.environ.get('STRIPE_WEBHOOK_SECRET'))}}
        finally:c.close()
    def generate(self,c,now):
        cur=c.execute('SELECT * FROM studio_workflows WHERE enabled=1')
        for rr in cur.fetchall():
            w=dict(zip([d[0] for d in cur.description],rr));i=record(c,'SELECT * FROM inquiries WHERE id=?',(w['inquiry_id'],))
            if not i:continue
            base={'target_kind':'inquiry','target_id':i['id'],'channels':json.loads(w['channels']),'workflow_updated_at':w['updated_at']}
            due=str(i.get('next_follow_up_at') or '').replace('T',' ')
            if due and not i.get('converted_student_name') and str(i.get('status','')).lower() not in ('closed','lost','enrolled','converted') and w['followup_body']:
                try:when=datetime.fromisoformat(due).replace(tzinfo=LA)
                except ValueError:when=None
                if when and when<=now and when.date()==now.date():
                    key='followup:'+str(i['id'])+':'+fingerprint([due,w['followup_body']])
                    self.task(c,key,'workflow:'+str(i['id']),{**base,'title':'H-Music trial follow-up','body':w['followup_body'],'inquiry_due':due})
            if not w['first_schedule_id']:continue
            s=lesson(c,w['first_schedule_id'])
            if str(s.get('status') or '').lower() in CANCELLED:continue
            start=datetime.combine(checked_date(s['lesson_date']),datetime.strptime(s['lesson_time'],'%H:%M').time(),LA)
            if now>=start:continue
            version=fingerprint(s)
            for node,when in reminder_nodes(s['lesson_date'],s['lesson_time']):
                # No retroactive reminder burst; a node is valid only on its local calendar day.
                if now>=when and now.date()==when.date():
                    self.task(c,f"first:{s['id']}:{version}:{node}",'workflow:'+str(i['id']),{**base,'title':'Your first H-Music lesson','body':f"{s['student_name']}: {s['lesson_date']} {s['lesson_time']}, teacher {s['teacher']}, room {s['classroom']}. Please arrive on time.",'lesson_id':s['id'],'lesson_version':version})
    def deliver(self,task):
        p=json.loads(task['payload']);c=self.db()
        try:
            if task['operation_id'].startswith('workflow:'):
                w=record(c,'SELECT * FROM studio_workflows WHERE inquiry_id=?',(p['target_id'],))
                if not w or not w['enabled'] or w['updated_at']!=p.get('workflow_updated_at'):return {'cancelled':True,'reason':'workflow_paused'}
            if p.get('lesson_id'):
                s=lesson(c,p['lesson_id'])
                if fingerprint(s)!=p['lesson_version'] or str(s.get('status') or '').lower() in CANCELLED:return {'cancelled':True,'reason':'lesson_changed'}
            target=({'parent_id':None,'teacher':p['teacher']} if p.get('teacher') else get_target(c,p))
            if target.get('parent_id') and (p.get('lesson_id') or p.get('invoice_id')):
                pref=record(c,'SELECT * FROM parent_notification_preferences WHERE parent_id=?',(target['parent_id'],))
                pref_key='billing_alerts' if p.get('invoice_id') else 'lesson_reminders'
                if pref and not pref.get(pref_key,1):return {'cancelled':True,'reason':'parent_preferences'}
            if p.get('invoice_id'):
                inv=record(c,'SELECT status FROM invoices WHERE id=?',(p['invoice_id'],))
                if not inv or inv['status'] not in ('unpaid','pending'):return {'cancelled':True,'reason':'invoice_no_longer_due'}
            if p.get('inquiry_due'):
                i=record(c,'SELECT * FROM inquiries WHERE id=?',(p['target_id'],))
                if i.get('converted_student_name') or str(i.get('next_follow_up_at') or '').replace('T',' ')!=p['inquiry_due']:return {'cancelled':True,'reason':'followup_changed'}
        finally:c.close()
        results=[];api=self.api
        for ch in p['channels']:
            rel={'related_type':'studio_task','related_id':task['id']}
            path='/parent_invoice/'+str(p['invoice_id']) if p.get('invoice_id') else '/parent_dashboard'
            if target.get('teacher'):path='/teacher_dashboard?view=schedule'
            link=api['hmusic_public_app_url'](path)
            if ch=='push':
                if not target.get('parent_id') and not target.get('teacher'):results.append({'channel':ch,'state':'unavailable','reason':'no_parent_account'});continue
                nid=api['create_notification']('teacher' if target.get('teacher') else 'parent',str(target.get('teacher') or target['parent_id']),p['title'],p['body'],path,queue_delivery=False,**rel)
                results.append({'channel':ch,'state':'in_app_created','notification_id':nid});continue
            if target.get('parent_id') or target.get('teacher'):
                qid=api['queue_notification_delivery']('teacher' if target.get('teacher') else 'parent',str(target.get('teacher') or target['parent_id']),p['title'],p['body'],path if ch=='sms' else link,ch,**rel)
            else:
                dest=target.get('email' if ch=='email' else 'phone')
                qid=api['queue_direct_delivery'](ch,dest or '',p['title'],p['body'],path if ch=='sms' else link,**rel)
            if not qid:results.append({'channel':ch,'state':'unavailable','reason':'no_eligible_destination'});continue
            # Shared CRM senders use pending -> sending CAS; uncertain sends are never blindly retried.
            api['send_queued_email_now' if ch=='email' else 'send_queued_sms_now'](qid)
            c=self.db()
            try:r=record(c,'SELECT status FROM notification_delivery_queue WHERE id=?',(qid,))
            finally:c.close()
            results.append({'channel':ch,'state':r['status'] if r else 'unknown','queue_id':qid})
        if p.get('inquiry_due') and any(r['state'] in ('sent','in_app_created') for r in results):
            c=self.db()
            try:
                c.execute("UPDATE inquiries SET follow_up_status='Contacted',updated_at=? WHERE id=? AND next_follow_up_at=?",(stamp(),p['target_id'],p['inquiry_due']));c.commit()
            finally:c.close()
        return {'channels':results}
    def tick(self):
        if not self.lock.acquire(blocking=False):return
        try:
            c=self.db();owner=secrets.token_hex(12);now=stamp()
            try:
                c.execute("INSERT OR IGNORE INTO studio_leases VALUES ('tick','', '')")
                cur=c.execute("UPDATE studio_leases SET owner=?,expires=? WHERE id='tick' AND expires<?",(owner,(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),now))
                claimed=cur.rowcount==1;c.commit()
                if not claimed:return
                if os.environ.get('HMUSIC_STUDIO_AUTOMATION')=='1':self.generate(c,datetime.now(LA));c.commit()
                cur=c.execute("SELECT * FROM studio_tasks WHERE state='pending' ORDER BY id LIMIT 20")
                tasks=[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
            finally:c.close()
            for task in tasks:
                c=self.db()
                try:
                    claimed=c.execute("UPDATE studio_tasks SET state='running',updated_at=? WHERE id=? AND state='pending'",(stamp(),task['id'])).rowcount==1;c.commit()
                finally:c.close()
                if not claimed:continue
                try:
                    result=self.deliver(task)
                    state='cancelled' if result.get('cancelled') else 'attention' if any(r['state'] not in ('sent','in_app_created') for r in result['channels']) else 'completed'
                except Exception:result={'error':'Delivery interrupted; inspect CRM queue before retrying'};state='attention'
                c=self.db()
                try:c.execute('UPDATE studio_tasks SET state=?,result=?,updated_at=? WHERE id=?',(state,pack(result),stamp(),task['id']));c.commit()
                finally:c.close()
            c=self.db()
            try:c.execute("UPDATE studio_leases SET expires='' WHERE id='tick' AND owner=?",(owner,));c.commit()
            finally:c.close()
        finally:self.lock.release()
    def start(self):
        if os.environ.get('HMUSIC_STUDIO_AUTOMATION')!='1' or self.pid==os.getpid():return
        self.pid=os.getpid()
        def loop():
            while True:
                try:self.tick()
                except Exception:pass
                time.sleep(60)
        threading.Thread(target=loop,name='studio-automation',daemon=True).start()

def register_operations(app,connect,api):
    service=Operations(connect,api);bp=Blueprint('studio_operations',__name__)
    @bp.before_request
    def guard():
        token=os.environ.get('HMUSIC_AGENT_WRITE_TOKEN','')
        if len(token)<32:return jsonify(error='执行连接未配置'),503
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):return jsonify(error='Unauthorized'),401
        if request.method=='POST' and not request.is_json:return jsonify(error='JSON required'),415
        if request.content_length and request.content_length>20000:return jsonify(error='请求过长'),413
        if not request.headers.get('X-Studio-Actor'):return jsonify(error='缺少操作者'),400
    @bp.get(PREFIX)
    def overview():return jsonify(service.overview())
    @bp.post(PREFIX+'/prepare')
    def prepare():
        try:
            p=request.get_json();return jsonify(service.prepare(p['action'],p['parameters'],request.headers['X-Studio-Actor']))
        except (ValueError,KeyError,TypeError) as e:return jsonify(error=str(e) if isinstance(e,ValueError) else '资料不完整，请核对所选记录及必填项'),409
    @bp.post(PREFIX+'/confirm')
    def confirm():
        try:
            p=request.get_json()
            if p.get('confirmed') is not True:return jsonify(error='需要确认具体提案'),400
            return jsonify(service.execute(p['id'],request.headers['X-Studio-Actor']))
        except (ValueError,KeyError,TypeError) as e:return jsonify(error=str(e) if isinstance(e,ValueError) else '提案资料不完整'),409
    @bp.get(PREFIX+'/<ident>')
    def status(ident):
        try:return jsonify(service.status(ident,request.headers['X-Studio-Actor']))
        except ValueError:return jsonify(error='操作不存在'),404
    @bp.after_request
    def private_response(response):
        response.headers['Cache-Control']='private, no-store'
        return response
    app.register_blueprint(bp)
    @app.after_request
    def start_scheduler(response):
        service.start();return response
    app.extensions['studio_operations']=service
