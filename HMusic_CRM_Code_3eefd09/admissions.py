"""Published admissions catalog, scoped coupons and provider-confirmed enrollment orders.

No parent access or lesson credit is granted by a public registration. Orders are
linked to the existing intake for manager review; retries share one Stripe session.
"""
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from flask import request, session, redirect, jsonify, Response, abort

BASE=Path(__file__).with_name('admissions')
POLICY='''A standard term includes 10 lessons. Cancellations made within 24 hours do not qualify for a free emergency makeup credit or cancellation waiver.
More than 24 hours: Lessons may be rescheduled based on teacher and room availability.
Within 24 hours: Late cancellation fees are $15 (30 minutes), $22.50 (45 minutes), and $30 (60 minutes).
Within 2 hours: Full lesson tuition is charged. Makeup lessons may not be available unless approved by H-Music management.
Students should arrive on time and prepared. Lessons end at the scheduled time regardless of arrival time. Student or family delays do not qualify for guaranteed makeup time or tuition credits. Makeup time depends on instructor availability and is not guaranteed. Notify H-Music administration of delays. If an instructor arrives late or ends early, missed instructional time will be made up or credited after management review.
Invoices and account balances are available in the H-Music Parent App. Tuition, lesson packages, and billing arrangements are confirmed by H-Music management.'''
POLICY_ZH='''标准一期包含 10 节课。课前 24 小时内取消，不享有免费紧急补课额度或取消豁免。
提前超过 24 小时：可根据老师与教室的可用情况安排改期。
课前 24 小时内：迟取消费为 30 分钟 $15、45 分钟 $22.50、60 分钟 $30。
课前 2 小时内：收取全额课费。补课须经学校管理方批准，且不保证可安排。
学生应准时到达并做好准备。无论到达时间如何，课程均按原定时间结束。学生或家庭迟到不保证补时或学费抵扣，补时依老师时间安排。请将迟到告知行政。如老师迟到或提前下课，缺少的授课时间经管理方审核后将补足或抵扣。
账单与余额可在 H-Music Parent App 查看。学费、课程包及付款安排由 H-Music 管理方确认。'''

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def money(cents):return f'${cents/100:,.2f}'
def row(cur):
 r=cur.fetchone();return dict(zip([d[0] for d in cur.description],r)) if r else None

def seed():
 teachers=[]
 for names,prices,subject in [(['Xu Huang','Jason Kim'],[65000,97500,130000],'Instrument'),(['Jessie Gong','Hyewon Shin','Xueyang Wang','Yidan Sun','Chloe Lu'],[60000,90000,120000],'Instrument'),(['Mia Li','Claire Chen','Halley Hsieh','Jenny Lee'],[55000,82500,110000],'Instrument'),(['Jenny Lee','Yichi Dang'],[55000,82500,110000],'Voice')]:
  for name in names:
   teachers.append(dict(id=re.sub('[^a-z0-9]+','-',name.lower()+'-'+subject.lower()),name=name,subject=subject,active=True,prices=dict(zip(['30','45','60'],prices))))
 return dict(teachers=teachers,lessons=10,checkoutEnabled=True,policy=dict(version='2026-11-03',text=POLICY,textZh=POLICY_ZH),partners=json.loads((BASE/'partners.json').read_text()),events=[],copy={'enrollTitle':'Find your next musical chapter.','enrollTitleZh':'开启你的音乐新篇章。','eventsTitle':'On stage. Together.','eventsTitleZh':'一起走上舞台。'},navigation={'enroll':True,'events':True})

def ensure_schema(conn):
 for sql in [
  'CREATE TABLE IF NOT EXISTS admissions_settings (id INTEGER PRIMARY KEY,draft TEXT NOT NULL,published TEXT NOT NULL,revision INTEGER NOT NULL)',
  '''CREATE TABLE IF NOT EXISTS admissions_coupons (code TEXT PRIMARY KEY,kind TEXT NOT NULL,value INTEGER NOT NULL,teacher_ids TEXT NOT NULL,partner_id TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,max_uses INTEGER NOT NULL,per_student INTEGER NOT NULL,min_cents INTEGER NOT NULL,active INTEGER NOT NULL,notes TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0)''',
  '''CREATE TABLE IF NOT EXISTS admissions_orders (id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,access_hash TEXT NOT NULL,inquiry_id INTEGER,enrollment_id INTEGER,invoice_id INTEGER,student_key TEXT NOT NULL,teacher_id TEXT NOT NULL,partner_id TEXT NOT NULL,semester TEXT NOT NULL,snapshot TEXT NOT NULL,subtotal INTEGER NOT NULL,discount INTEGER NOT NULL,total INTEGER NOT NULL,coupon_code TEXT NOT NULL,status TEXT NOT NULL,checkout_id TEXT,checkout_started TEXT,created_at TEXT NOT NULL,paid_at TEXT)''',
  'CREATE INDEX IF NOT EXISTS idx_admissions_coupon ON admissions_orders(coupon_code,status,student_key)',
  '''CREATE TABLE IF NOT EXISTS admissions_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)'''
 ]:conn.execute(sql)
 s=json.dumps(seed(),ensure_ascii=False);conn.execute('INSERT OR IGNORE INTO admissions_settings(id,draft,published,revision) VALUES(1,?,?,0)',(s,s));conn.commit()
 # Add the requested partner directory once, preserving existing settings and edits.
 if not conn.execute("SELECT 1 FROM admissions_audit WHERE action='partner-directory-v1'").fetchone():
  row=conn.execute('SELECT draft,published FROM admissions_settings WHERE id=1').fetchone()
  updated=[]
  for raw in row:
   cfg=json.loads(raw);existing={p['id'] for p in cfg['partners']}
   cfg['partners'].extend(p for p in seed()['partners'] if p['id'] not in existing)
   updated.append(json.dumps(cfg,ensure_ascii=False))
  conn.execute('UPDATE admissions_settings SET draft=?,published=?,revision=revision+1 WHERE id=1',updated)
  conn.execute("INSERT INTO admissions_audit(action,payload,created_at) VALUES('partner-directory-v1','{}',?)",(now(),));conn.commit()



 if not conn.execute("SELECT 1 FROM admissions_audit WHERE action='partner-information-v2'").fetchone():
  defaults={p['id']:p for p in seed()['partners']}
  updated=[]
  for raw in conn.execute('SELECT draft,published FROM admissions_settings WHERE id=1').fetchone():
   cfg=json.loads(raw)
   for school in cfg['partners']:
    if school['id'] not in defaults:continue
    courses={c['id']:c for c in defaults[school['id']]['programs']}
    for course in school.get('programs',[]):
     if course['id'] in courses:
      for key in ['details','schedule','informationUrl']:course[key]=courses[course['id']][key]
   updated.append(json.dumps(cfg,ensure_ascii=False))
  conn.execute('UPDATE admissions_settings SET draft=?,published=?,revision=revision+1 WHERE id=1',updated)
  conn.execute("INSERT INTO admissions_audit(action,payload,created_at) VALUES('partner-information-v2','{}',?)",(now(),));conn.commit()

def validate_catalog(c):
 if not isinstance(c,dict):raise ValueError('Invalid catalog')
 if type(c.get('lessons')) is not int or not 1<=c['lessons']<=100:raise ValueError('Lesson count must be 1–100')
 if type(c.get('checkoutEnabled')) is not bool:raise ValueError('Invalid checkout switch')
 if not isinstance(c.get('teachers'),list) or len(c['teachers'])>100:raise ValueError('Invalid teachers')
 ids=set()
 for t in c['teachers']:
  if not isinstance(t,dict) or not re.fullmatch('[a-z0-9-]{1,100}',str(t.get('id',''))) or t['id'] in ids:raise ValueError('Unique teacher IDs required')
  ids.add(t['id'])
  if not all(isinstance(t.get(k),str) and 0<len(t[k])<=100 for k in ['name','subject']) or type(t.get('active')) is not bool:raise ValueError('Teacher name and subject required')
  if not isinstance(t.get('prices'),dict) or not t['prices'] or set(t['prices'])-{'30','45','60'}:raise ValueError('Invalid durations')
  if any(type(v) is not int or not 50<=v<=10000000 for v in t['prices'].values()):raise ValueError('Prices must be positive integer cents')
 p=c.get('policy',{})
 if any(not isinstance(p.get(k),str) or not p[k].strip() or len(p[k])>20000 for k in ['version','text','textZh']):raise ValueError('Policy version and English/Chinese text required')
 for group in ['partners','events']:
  if not isinstance(c.get(group),list) or len(c[group])>100:raise ValueError('Invalid '+group)
  seen=set()
  for item in c[group]:
   if not isinstance(item,dict) or not re.fullmatch('[a-z0-9-]{1,100}',str(item.get('id',''))) or item['id'] in seen:raise ValueError('Unique IDs required')
   seen.add(item['id'])
   for k in ['title','titleZh','description','descriptionZh','url','semester']:
    if not isinstance(item.get(k,''),str) or len(item.get(k,''))>3000:raise ValueError('Invalid text')
   if not item.get('title'):raise ValueError('Title required')
   if group=='partners':
    for k in ['city','address','phone','email','website','sourceUrl','locationNote']:
     if not isinstance(item.get(k,''),str) or len(item.get(k,''))>1000:raise ValueError('Invalid partner contact information')
    for k in ['website','sourceUrl']:
     u=item.get(k,'')
     if u and (urlsplit(u).scheme!='https' or not urlsplit(u).netloc or urlsplit(u).username or urlsplit(u).password):raise ValueError('Use HTTPS school links')
    courses=item.get('programs',[])
    if not isinstance(courses,list) or len(courses)>2:raise ValueError('Invalid partner courses')
    seen_courses=set()
    for course in courses:
     if course.get('id') not in ['circle-piano','private-instruments'] or course['id'] in seen_courses:raise ValueError('Invalid partner course')
     seen_courses.add(course['id'])
     if type(course.get('active')) is not bool:raise ValueError('Invalid course visibility')
     for k in ['title','description','details','schedule','tuition','registrationUrl','informationUrl']:
      if not isinstance(course.get(k,''),str) or len(course.get(k,''))>5000:raise ValueError('Invalid course information')
     for link_key in ['registrationUrl','informationUrl']:
      u=course.get(link_key,'')
      if u and (urlsplit(u).scheme!='https' or not urlsplit(u).netloc or urlsplit(u).username or urlsplit(u).password):raise ValueError('Use HTTPS course links')

   if type(item.get('active')) is not bool:raise ValueError('Invalid visibility')
   u=item.get('url','')
   if u and (urlsplit(u).scheme!='https' or not urlsplit(u).netloc or urlsplit(u).username or urlsplit(u).password):raise ValueError('Use HTTPS links')
 if not isinstance(c.get('copy'),dict) or any(not isinstance(v,str) or len(v)>500 for v in c['copy'].values()):raise ValueError('Invalid page copy')
 if not isinstance(c.get('navigation'),dict) or any(type(v) is not bool for v in c['navigation'].values()):raise ValueError('Invalid navigation settings')
 return c

def catalog(conn):return json.loads(conn.execute('SELECT published FROM admissions_settings WHERE id=1').fetchone()[0])
def coupon_validate(d):
 code=(d.get('code') or '').upper().strip()
 if not re.fullmatch('[A-Z0-9_-]{4,32}',code):raise ValueError('Code must contain 4–32 letters, numbers, _ or -')
 kind=d.get('kind');value=d.get('value')
 if kind not in ['percent','fixed'] or type(value) is not int or value<=0 or (kind=='percent' and value>10000) or value>10000000:raise ValueError('Invalid discount: percentage is 1–10000 basis points; fixed amount is cents')
 for k in ['max_uses','per_student','min_cents']:
  if type(d.get(k)) is not int or d[k]<0:raise ValueError('Invalid usage limit')
 if d['max_uses']<1 or d['per_student']<1:raise ValueError('Positive usage limits required')
 if type(d.get('active')) is not bool:raise ValueError('Invalid code status')
 for k in ['starts_at','ends_at']:
  if d.get(k):
   dt=datetime.fromisoformat(d[k]);d[k]=(dt.replace(tzinfo=ZoneInfo("America/Los_Angeles")) if dt.tzinfo is None else dt).astimezone(timezone.utc).isoformat(timespec='seconds')
  else:d[k]=''
 if d['starts_at'] and d['ends_at'] and d['ends_at']<=d['starts_at']:raise ValueError('End must follow start')
 if not isinstance(d.get('teacher_ids'),list) or any(not isinstance(x,str) for x in d['teacher_ids']):raise ValueError('Invalid scope')
 return {**d,'code':code}

def quote(conn,teacher_id,duration,code='',partner_id='',student_key='',reserve=False):
 c=catalog(conn);t=next((t for t in c['teachers'] if t['id']==teacher_id and t['active']),None)
 if not t or str(duration) not in t['prices']:raise ValueError('Choose an available teacher and duration')
 if partner_id and not any(p['id']==partner_id and p['active'] for p in c['partners']):raise ValueError('This partner program is not available')
 subtotal=t['prices'][str(duration)];discount=0;code=code.strip().upper()
 if code:
  if reserve:conn.execute('UPDATE admissions_coupons SET revision=revision WHERE code=?',(code,))
  cp=row(conn.execute('SELECT * FROM admissions_coupons WHERE code=?',(code,)))
  if not cp or not cp['active'] or (cp['starts_at'] and cp['starts_at']>now()) or (cp['ends_at'] and cp['ends_at']<=now()):raise ValueError('Discount code is invalid or expired')
  allowed=json.loads(cp['teacher_ids'])
  if (allowed and teacher_id not in allowed) or (cp['partner_id'] and cp['partner_id']!=partner_id) or subtotal<cp['min_cents']:raise ValueError('This code does not apply to your selection')
  used=conn.execute("SELECT COUNT(*) FROM admissions_orders WHERE coupon_code=? AND status NOT IN ('expired','failed','cancelled')",(code,)).fetchone()[0]
  student_used=conn.execute("SELECT COUNT(*) FROM admissions_orders WHERE coupon_code=? AND student_key=? AND status NOT IN ('expired','failed','cancelled')",(code,student_key)).fetchone()[0]
  if used>=cp['max_uses'] or (student_key and student_used>=cp['per_student']):raise ValueError('Discount usage limit reached')
  discount=int((Decimal(subtotal)*Decimal(cp['value'])/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if cp['kind']=='percent' else cp['value']
  discount=min(discount,subtotal)
 if subtotal-discount<50:raise ValueError('This discount requires school review; online payments must be at least $0.50')
 return dict(teacher=t,minutes=int(duration),lessons=c['lessons'],subtotal=subtotal,discount=discount,total=subtotal-discount,coupon=code,policy=c['policy'],partner_id=partner_id,semester=next((p.get('semester','') for p in c['partners'] if p['id']==partner_id),''))

def sync_order(conn,obj):
 oid=(obj.get('metadata') or {}).get('admissions_order');o=row(conn.execute('SELECT * FROM admissions_orders WHERE id=?',(oid,)))
 if not o:return None
 if obj.get('id')!=o['checkout_id'] or obj.get('mode')!='payment' or obj.get('currency')!='usd' or obj.get('amount_total')!=o['total']:raise ValueError('Payment does not match enrollment order')
 if o['status']=='paid':return 'paid'
 if o['status']=='failed' and obj.get('payment_status')!='paid':return 'failed'
 status='paid' if obj.get('payment_status')=='paid' else ('expired' if obj.get('status')=='expired' else ('processing' if obj.get('status')=='complete' else 'checkout'))
 conn.execute('UPDATE admissions_orders SET status=?,paid_at=? WHERE id=? AND status<>?',(status,now() if status=='paid' else None,oid,'paid'));conn.commit();return status

def register_admissions(app,api):
 def db():
  c=api['sqlite3'].connect('hmusic.db');ensure_schema(c);return c
 def owner():return api['require_owner']()
 def audit(c,action,payload):c.execute('INSERT INTO admissions_audit(action,payload,created_at) VALUES(?,?,?)',(action,json.dumps(payload,ensure_ascii=False),now()))
 def response(html,status=200):
  r=Response(html,status=status,mimetype='text/html');r.headers['Cache-Control']='no-store';r.headers['Referrer-Policy']='no-referrer';r.headers['X-Robots-Tag']='noindex';return r
 @app.get('/admissions-admin', endpoint='hmusic_admissions_admissions_admin')
 def admissions_admin():
  if not owner():return redirect('/owner_login')
  return response((BASE/'admin.html').read_text().replace('__CSRF__',api['hmusic_csrf_token']()))
 @app.get('/admissions-admin/editor.js', endpoint='hmusic_admissions_admissions_editor')
 def admissions_editor():
  if not owner():abort(403)
  return Response((BASE/'admin.js').read_text(),mimetype='application/javascript')
 @app.get('/api/website/admissions', endpoint='hmusic_admissions_public_admissions')
 def public_admissions():
  c=db()
  try:
   data=catalog(c);data['partners']=[p for p in data['partners'] if p['active']];data['events']=[e for e in data['events'] if e['active']];data['teachers']=[t for t in data['teachers'] if t['active']]
   r=jsonify(data);r.headers['Access-Control-Allow-Origin']='*';r.headers['Cache-Control']='no-store';return r
  finally:c.close()
 @app.route('/api/admissions/admin',methods=['GET','POST'], endpoint='hmusic_admissions_admissions_settings')
 def admissions_settings():
  if not owner():abort(403)
  c=db()
  try:
   if request.method=='GET':
    r=row(c.execute('SELECT * FROM admissions_settings WHERE id=1'));return dict(catalog=json.loads(r['draft']),revision=r['revision'],hasDraft=r['draft']!=r['published'])
   d=request.get_json(silent=True) or {};cat=validate_catalog(d.get('catalog'));payload=json.dumps(cat,ensure_ascii=False)
   if type(d.get('revision')) is not int:raise ValueError('Invalid revision')
   if len(payload)>200000:raise ValueError('Catalog too large')
   publish=d.get('publish') is True
   sql='UPDATE admissions_settings SET draft=?,revision=revision+1'+(',published=?' if publish else '')+' WHERE id=1 AND revision=?'
   params=(payload,payload,d['revision']) if publish else (payload,d['revision'])
   if c.execute(sql,params).rowcount!=1:return {'error':'Another editor saved changes. Reload.'},409
   audit(c,'publish' if publish else 'save',cat);c.commit();return {'ok':True,'revision':d['revision']+1,'published':publish}
  except (ValueError,TypeError,KeyError) as e:c.rollback();return {'error':str(e)},400
  finally:c.close()
 @app.route('/api/admissions/coupons',methods=['GET','POST'], endpoint='hmusic_admissions_coupons')
 def coupons():
  if not owner():abort(403)
  c=db()
  try:
   if request.method=='GET':
    cur=c.execute('SELECT * FROM admissions_coupons ORDER BY code');items=[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]
    for cp in items:
     cp['teacher_ids']=json.loads(cp['teacher_ids']);cp['active']=bool(cp['active']);cp['uses']=c.execute("SELECT COUNT(*) FROM admissions_orders WHERE coupon_code=? AND status NOT IN ('failed','expired','cancelled')",(cp['code'],)).fetchone()[0]
    return {'coupons':items}
   cp=coupon_validate(request.get_json(silent=True) or {});existing=row(c.execute('SELECT * FROM admissions_coupons WHERE code=?',(cp['code'],)))
   vals=(cp['kind'],cp['value'],json.dumps(cp['teacher_ids']),cp.get('partner_id',''),cp['starts_at'],cp['ends_at'],cp['max_uses'],cp['per_student'],cp['min_cents'],int(cp['active']),cp.get('notes',''))
   if existing:
    if c.execute('UPDATE admissions_coupons SET kind=?,value=?,teacher_ids=?,partner_id=?,starts_at=?,ends_at=?,max_uses=?,per_student=?,min_cents=?,active=?,notes=?,revision=revision+1 WHERE code=? AND revision=?',vals+(cp['code'],cp.get('revision',-1))).rowcount!=1:return {'error':'Reload the code before editing'},409
   else:c.execute('INSERT INTO admissions_coupons(kind,value,teacher_ids,partner_id,starts_at,ends_at,max_uses,per_student,min_cents,active,notes,code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',vals+(cp['code'],))
   audit(c,'coupon',cp);c.commit();return {'ok':True}
  except (ValueError,TypeError,KeyError) as e:c.rollback();return {'error':str(e)},400
  finally:c.close()
 @app.post('/api/admissions/quote', endpoint='hmusic_admissions_quote_api')
 def quote_api():
  c=db()
  try:
   d=request.get_json(silent=True) or {};q=quote(c,d.get('teacher_id'),d.get('duration'),d.get('code',''),d.get('partner_id',''));return {k:q[k] for k in ['subtotal','discount','total','lessons']}
  except (ValueError,TypeError) as e:return {'error':str(e)},400
  finally:c.close()
 @app.post('/api/admissions/order-action', endpoint='hmusic_admissions_owner_order_action')
 def owner_order_action():
  if not owner():abort(403)
  d=request.get_json(silent=True) or {};c=db()
  try:
   c.execute('UPDATE admissions_orders SET status=status WHERE id=?',(d.get('id'),))
   o=row(c.execute('SELECT * FROM admissions_orders WHERE id=?',(d.get('id'),)))
   if not o:return {'error':'Order not found'},404
   if o['checkout_id']:
    if not api['configure_stripe']():return {'error':'Stripe is unavailable'},503
    obj=api['stripe'].checkout.Session.retrieve(o['checkout_id'])
    if d.get('action')=='cancel' and obj.get('status')=='open':
     obj=api['stripe'].checkout.Session.expire(o['checkout_id'])
    sync_order(c,obj);o=row(c.execute('SELECT * FROM admissions_orders WHERE id=?',(o['id'],)))
   if d.get('action')=='cancel':
    if o['status'] not in ['registration','expired','failed','cancelled']:return {'error':'Submitted or paid orders cannot be cancelled here. Review payment with Billing.'},409
    if o['checkout_started'] and not o['checkout_id']:return {'error':'An unresolved provider attempt must be reconciled before releasing its discount reservation.'},409
    c.execute("UPDATE admissions_orders SET status='cancelled' WHERE id=?",(o['id'],))
   elif d.get('action')!='sync':return {'error':'Invalid action'},400
   audit(c,'order-'+d['action'],{'id':o['id']});c.commit();return {'ok':True}
  except ValueError as e:c.rollback();return {'error':str(e)},400
  finally:c.close()
 @app.get('/api/admissions/attach-options', endpoint='hmusic_admissions_attach_options')
 def attach_options():
  if not owner():abort(403)
  c=db()
  try:
   students=[{'id':r[0],'name':r[1]} for r in c.execute('SELECT id,name FROM students ORDER BY name').fetchall()]
   courses=[{'id':r[0],'name':r[1],'duration':r[2]} for r in c.execute('SELECT id,name,duration FROM course_types WHERE active=1 AND COALESCE(is_group,0)=0 ORDER BY duration,name').fetchall()]
   return {'students':students,'courses':courses}
  finally:c.close()
 @app.post('/api/admissions/attach', endpoint='hmusic_admissions_attach_order')
 def attach_order():
  if not owner():abort(403)
  api['ensure_v321_schema']();api['ensure_guardian_billing_schema']();d=request.get_json(silent=True) or {};c=db()
  try:
   c.execute('UPDATE admissions_orders SET status=status WHERE id=?',(d.get('id'),))
   o=row(c.execute('SELECT * FROM admissions_orders WHERE id=?',(d.get('id'),)))
   if not o or o['status']!='paid':raise ValueError('Only provider-confirmed paid orders can be posted to Billing')
   q=json.loads(o['snapshot'])
   if not o['invoice_id']:
    st=c.execute('SELECT name FROM students WHERE id=?',(d.get('student_id'),)).fetchone()
    ct=c.execute('SELECT id,name,duration FROM course_types WHERE id=? AND active=1 AND COALESCE(is_group,0)=0',(d.get('course_type_id'),)).fetchone()
    if not st or not ct or int(ct[2])!=q['minutes']:raise ValueError('Choose an existing student and matching private lesson duration')
    # A manager explicitly maps the verified order to an existing student. No public form can create family access.
    c.execute("""INSERT INTO enrollments(student_name,course_type_id,course_type_name,teacher_name,duration,student_billing_method,base_price,final_price,lessons_left,status,notes,package_amount,package_lessons,auto_renew_enabled,created_at,updated_at)
       VALUES(?,?,?,?,?,'Per Lesson',?,?,0,'active',?,?,?,0,?,?)""",(st[0],ct[0],ct[1],q['teacher']['name'],q['minutes'],o['subtotal']/100/q['lessons'],o['total']/100/q['lessons'], 'Paid enrollment order '+o['id'],o['total']/100,q['lessons'],now(),now()))
    eid=c.execute('SELECT id FROM enrollments WHERE notes=?',('Paid enrollment order '+o['id'],)).fetchone()[0]
    iid=api['create_enrollment_invoice'](c.cursor(),eid,'initial_tuition','Already paid online: enrollment order '+o['id'],grant_credit_on_payment=True,attach_pending_charges=False)
    c.execute('UPDATE invoices SET discount_code=?,discount_amount=?,stripe_checkout_session_id=? WHERE id=?',(o['coupon_code'],o['discount']/100,o['checkout_id'],iid))
    c.execute('UPDATE admissions_orders SET enrollment_id=?,invoice_id=? WHERE id=?',(eid,iid,o['id']))
    c.execute('UPDATE inquiries SET converted_enrollment_id=? WHERE id=?',(eid,o['inquiry_id']))
    audit(c,'attach-paid-order',{'order':o['id'],'invoice':iid,'enrollment':eid});c.commit()
   else:iid=o['invoice_id']
  except (ValueError,TypeError) as e:c.rollback();return {'error':str(e)},400
  finally:c.close()
  result=api['finalize_stripe_invoice_payment'](iid,checkout_session_id=o['checkout_id'],source='admissions-'+o['id'])
  if not result:return {'error':'The invoice is linked but needs Billing review before credits are granted.'},409
  return {'ok':True,'invoice_id':iid}
 @app.get('/api/admissions/orders', endpoint='hmusic_admissions_order_list')
 def order_list():
  if not owner():abort(403)
  c=db()
  try:
   cur=c.execute('SELECT id,inquiry_id,enrollment_id,invoice_id,snapshot,subtotal,discount,total,coupon_code,status,created_at,paid_at,partner_id,semester FROM admissions_orders ORDER BY created_at DESC LIMIT 200')
   return {'orders':[dict(zip([d[0] for d in cur.description],r)) for r in cur.fetchall()]}
  finally:c.close()
 def catalog_for_snapshot():
  c=db()
  try:return {'policy':catalog(c)['policy'],'accepted_at':now()}
  finally:c.close()
 def partner_context(values):
  pid=values.get('partner_id','');course_id=values.get('partner_course','')
  if not pid and not course_id:return None
  conn=db()
  try:cfg=catalog(conn)
  finally:conn.close()
  partner=next((p for p in cfg['partners'] if p['id']==pid and p['active']),None)
  course=next((p for p in (partner or {}).get('programs',[]) if p['id']==course_id and p['active']),None)
  if not partner or not course:raise ValueError('Choose an available school and course before registering')
  expected='Group Class' if course_id=='circle-piano' else 'Private Lesson'
  if values.get('program_interest',expected)!=expected:raise ValueError('The program must match your school course selection')
  return partner,course
 def partner_snapshot(values):
  ctx=partner_context(values)
  if not ctx:return ''
  p,c=ctx
  return json.dumps({'school_id':p['id'],'school':p['title'],'address':p.get('address',''),'course_id':c['id'],'course':c['title'],'semester':p.get('semester',''),'schedule':c.get('schedule',''),'tuition':c.get('tuition',''),'status':'School review required'},ensure_ascii=False)
 def decorate(html,values=None):
  c=db()
  try:data=catalog(c)
  finally:c.close()
  values=values or {};selected=values.get('teacher_id',request.args.get('teacher',''))
  opts='<option value="">Please help me match a teacher / school review</option>'+''.join(f'<option value="{escape(t["id"])}" {"selected" if selected==t["id"] else ""}>{escape(t["name"])} · {escape(t["subject"])}</option>' for t in data['teachers'] if t['active'])
  token=values.get('admissions_key') or secrets.token_urlsafe(24)
  keys=session.get('admissions_keys',[]);keys=(keys+[token])[-10:];session['admissions_keys']=keys
  partner=values.get('partner_id',request.args.get('partner',''));partner_item=next((p for p in data['partners'] if p['id']==partner and p['active']),None)
  if partner and not partner_item:partner=''
  partner_html=f'<p>Partner program: {escape(partner_item["title"])} · {escape(partner_item.get("semester",""))}</p>' if partner_item else ''
  fragment=f'''<section id="tuition-selection"><div class="section-title">Teacher & tuition · {data['lessons']} classes per term</div>{partner_html}<input type="hidden" name="_csrf_token" value="{escape(api['hmusic_csrf_token']())}"><input type="hidden" name="admissions_key" value="{escape(token)}"><input type="hidden" name="partner_id" value="{escape(partner)}"><input type="hidden" name="policy_version" value="{escape(data['policy']['version'])}"><label>Teacher<select name="teacher_id" id="admission-teacher">{opts}</select></label><label>Lesson length<select name="lesson_minutes" id="admission-minutes" data-selected="{escape(values.get('lesson_minutes',request.args.get('duration','')))}"></select></label><label>Discount code (optional)<input name="admission_code" id="admission-code" value="{escape(values.get('admission_code',''))}" maxlength="32"></label><button type="button" id="apply-admission-code">Apply code</button><p id="admission-price" role="status"></p><p>Tuition covers the selected package. H-Music will confirm the final schedule. No payment is collected for teacher matching requests.</p></section><script src="/static/admissions-registration.js" defer></script>'''
  if partner_item:
   course_id=values.get('partner_course',request.args.get('course',''))
   course=next((p for p in partner_item.get('programs',[]) if p['id']==course_id and p['active']),None)
   if not course:
    return '<html lang="en"><title>Choose your school course</title><h1>Choose your course before registering</h1><a href="https://www.hmusicandart.com/after-school.html?school='+escape(partner_item['id'])+'">View school courses</a></html>'
   program='Group Class' if course_id=='circle-piano' else 'Private Lesson'
   fragment='<section id="partner-selection"><div class="section-title">School program registration</div><h2>'+escape(partner_item['title'])+'</h2><p>'+escape(partner_item.get('address',''))+'</p><h3>'+escape(course['title'])+'</h3><p>'+escape(course.get('schedule') or 'Follow your school schedule. Our staff will follow up with you.')+'</p><p>'+escape(course.get('tuition') or 'Tuition will be confirmed before invoicing.')+'</p><p>Submit your details for school review. H-Music will confirm placement and send the appropriate payment instructions.</p><input type="hidden" name="partner_id" value="'+escape(partner)+'"><input type="hidden" name="partner_course" value="'+escape(course_id)+'"><input type="hidden" name="_csrf_token" value="'+escape(api['hmusic_csrf_token']())+'"></section>'
   if course.get('informationUrl'):fragment=fragment.replace('</h3>','</h3><p><a href="'+escape(course['informationUrl'])+'" target="_blank" rel="noopener">Read the H-Music course information</a></p>',1)
   html=re.sub(r'<select name="program_interest" required>.*?</select>','<input name="program_interest" value="'+program+'" readonly>',html,flags=re.S)
   if course_id=='circle-piano':html=re.sub(r'<select name="instrument" required>.*?</select>','<input name="instrument" value="Piano" readonly>',html,flags=re.S)
   html=html.replace('Review enrollment &amp; payment','Submit school registration').replace('Review enrollment & payment','Submit school registration')
  html=html.replace('<html>','<html lang="en">',1)
  html=html.replace('<section>',fragment+'<section>',1)
  html=html.replace('Do not enter bank account numbers here. H-Music will send a secure ACH setup link through the parent app.', 'Do not enter bank account numbers here. Bank details are entered only on Stripe’s secure payment page.')
  html=html.replace('After submission, our H-Music team will confirm package, tuition, teacher, schedule, invoice, and parent app login.', 'Selected a teacher? Review your order and continue to secure ACH payment on the next page. Matching requests are reviewed before invoicing. H-Music confirms your schedule separately.')
  start=html.find('<div class="policy-body">');end=html.find('</div>',start)
  if start!=-1 and end!=-1:html=html[:start]+'<div class="policy-body"><p>Policy version: '+escape(data['policy']['version'])+'</p>'+''.join('<p>'+escape(p)+'</p>' for p in data['policy']['text'].splitlines())+html[end:]
  if partner_item:
   html=html.replace('Selected a teacher? Review your order and continue to secure ACH payment on the next page. Matching requests are reviewed before invoicing. H-Music confirms your schedule separately.','Your school registration will be reviewed by H-Music. We will confirm placement, schedule and tuition before sending payment instructions.')
  return html
 def prepare(values):
  if values.get('partner_id') or values.get('partner_course'):
   partner_context(values)
   if values.get('teacher_id'):raise ValueError('School program tuition must be confirmed separately')
   return None
  tid=values.get('teacher_id','')
  if not tid:
   if values.get('admission_code','').strip():raise ValueError('Choose a teacher before applying a discount code')
   return None
  if values.get('program_interest','Private Lesson')!='Private Lesson':raise ValueError('Online teacher tuition applies to Private Lesson. Choose matching for other programs.')
  if values.get('admissions_key') not in session.get('admissions_keys',[]):raise ValueError('Reload the registration form before submitting')
  c=db()
  try:
   existing=row(c.execute('SELECT * FROM admissions_orders WHERE request_key=?',(digest(values['admissions_key']),)))
   if existing:
    existing['existing']=True
    return existing
   cfg=catalog(c)
   if values.get('policy_version')!=cfg['policy']['version']:raise ValueError('The policy changed. Review the updated policy and submit again.')
   identity=digest('|'.join([values.get('parent_email','').strip().lower(),values.get('student_name','').strip().casefold(),values.get('age','').strip().casefold()]))
   q=quote(c,tid,values.get('lesson_minutes'),values.get('admission_code',''),values.get('partner_id',''),identity,True)
   q['checkoutEnabled']=cfg['checkoutEnabled'];q['student_name']=values.get('student_name','');q['email']=values.get('parent_email','');q['signed_by']=values.get('guardian_signature','');q['signed_date']=values.get('signed_date','');q['accepted_at']=now()
   oid=secrets.token_urlsafe(24);access=secrets.token_urlsafe(32)
   c.execute('INSERT INTO admissions_orders(id,request_key,access_hash,student_key,teacher_id,partner_id,semester,snapshot,subtotal,discount,total,coupon_code,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,digest(values['admissions_key']),digest(access),identity,tid,q['partner_id'],q['semester'],json.dumps(q,ensure_ascii=False),q['subtotal'],q['discount'],q['total'],q['coupon'],'registration',now()));c.commit()
   session['admissions_receipts']={**session.get('admissions_receipts',{}),oid:access}
   return row(c.execute('SELECT * FROM admissions_orders WHERE id=?',(oid,)))
  finally:c.close()
 def finish(order,inquiry_id):
  c=db()
  try:c.execute('UPDATE admissions_orders SET inquiry_id=? WHERE id=? AND inquiry_id IS NULL',(inquiry_id,order['id']));c.commit()
  finally:c.close()
  return redirect('/enrollment-order/'+order['id']+'/'+session['admissions_receipts'][order['id']],code=303)
 def handle_event(event):
  obj=event.get('data',{}).get('object',{})
  if not (obj.get('metadata') or {}).get('admissions_order'):return None
  # Even legacy unsigned webhook deployments must retrieve authoritative provider state.
  if not api['configure_stripe']():return Response('Stripe unavailable',503)
  if not str(obj.get('id','')).startswith('cs_'):return Response('Invalid checkout',400)
  obj=api['stripe'].checkout.Session.retrieve(obj['id']);c=db()
  try:
   state=sync_order(c,obj)
   if event.get('type')=='checkout.session.async_payment_failed' and state!='paid' and obj.get('status')=='complete' and obj.get('payment_intent'):
    intent=api['stripe'].PaymentIntent.retrieve(obj['payment_intent'])
    if intent.get('status') in ['requires_payment_method','canceled']:
     c.execute("UPDATE admissions_orders SET status='failed' WHERE id=? AND status<>'paid'",((obj.get('metadata') or {})['admissions_order'],));c.commit()
   return {'received':True}
  except ValueError:return Response('Enrollment checkout mismatch',400)
  finally:c.close()
 def find_order(c,oid,token):
  o=row(c.execute('SELECT * FROM admissions_orders WHERE id=?',(oid,)))
  if not o or not secrets.compare_digest(o['access_hash'],digest(token)):abort(404)
  return o
 @app.get('/enrollment-order/<oid>/<token>', endpoint='hmusic_admissions_receipt')
 def receipt(oid,token):
  c=db()
  try:
   o=find_order(c,oid,token)
   if o['checkout_id'] and api['configure_stripe']():
    try:sync_order(c,api['stripe'].checkout.Session.retrieve(o['checkout_id']));o=find_order(c,oid,token)
    except Exception:app.logger.warning('Enrollment payment reconciliation needs retry')
   q=json.loads(o['snapshot']);csrf=escape(api['hmusic_csrf_token']())
   status={'paid':'Payment confirmed. H-Music will confirm your schedule and parent app access.','processing':'Bank payment is processing. Please do not pay again.','expired':'This checkout expired. Contact H-Music for a reviewed replacement.','registration':'Registration received. Review your order and continue to secure payment.','checkout':'Payment has not been confirmed. Resume the same checkout below.'}.get(o['status'],'Contact H-Music to review this registration.')
   button=''
   if o['status'] in ['registration','checkout'] and catalog(c)['checkoutEnabled'] and o['inquiry_id']:
    button=f'<form method="post" action="/enrollment-order/{oid}/{token}/checkout"><input type="hidden" name="_csrf_token" value="{csrf}"><button>Continue to secure ACH payment ↗</button></form>'
   body=f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Enrollment order</title><link rel="stylesheet" href="/static/admissions.css"></head><body><main><h1>Enrollment order</h1><p>{escape(status)}</p><h2>{escape(q['teacher']['name'])} · {q['minutes']} minutes</h2><p>{q['lessons']} lessons · {escape(q['teacher']['subject'])}</p><p>Tuition {money(o['subtotal'])}<br>Discount −{money(o['discount'])}<br><strong>Total {money(o['total'])}</strong></p><p>Order {escape(oid)} · Registration #{o['inquiry_id'] or 'pending'}</p>{button}<p>Scheduling and account activation are reviewed separately by H-Music. This page does not grant lesson credits.</p></main></body></html>'''
   return response(body)
  finally:c.close()
 @app.post('/enrollment-order/<oid>/<token>/checkout', endpoint='hmusic_admissions_checkout')
 def checkout(oid,token):
  c=db()
  try:
   c.execute('UPDATE admissions_orders SET status=status WHERE id=?',(oid,));o=find_order(c,oid,token);q=json.loads(o['snapshot'])
   if not o['inquiry_id'] or not catalog(c)['checkoutEnabled'] or o['status'] not in ['registration','checkout']:return redirect('/enrollment-order/'+oid+'/'+token,code=303)
   if not api['configure_stripe']():return response('<p>Online payment is unavailable. Contact H-Music; your registration is saved.</p>',503)
   if o['checkout_id']:
    obj=api['stripe'].checkout.Session.retrieve(o['checkout_id']);sync_order(c,obj)
    if obj.get('status')=='open' and obj.get('url'):return redirect(obj['url'],code=303)
    return redirect('/enrollment-order/'+oid+'/'+token,code=303)
   if o['checkout_started'] and (datetime.now(timezone.utc)-datetime.fromisoformat(o['checkout_started'])).total_seconds()>23*3600:
    return response('<p>This checkout requires school review before retrying. Contact H-Music; do not create another order.</p>',409)
   c.execute('UPDATE admissions_orders SET checkout_started=COALESCE(checkout_started,?) WHERE id=?',(now(),oid));c.commit()
   # Stable idempotency key covers lost provider responses and repeated clicks.
   base=api['public_url_for']('/enrollment-order/'+oid+'/'+token)
   obj=api['stripe'].checkout.Session.create(mode='payment',payment_method_types=['us_bank_account'],line_items=[{'price_data':{'currency':'usd','unit_amount':o['total'],'product_data':{'name':f"H-Music · {q['teacher']['name']} · {q['minutes']} min × {q['lessons']} lessons",'description':f"Tuition {money(o['subtotal'])}; discount {money(o['discount'])}"}},'quantity':1}],customer_email=q['email'],success_url=base,cancel_url=base,metadata={'admissions_order':oid,'inquiry_id':str(o['inquiry_id'])},idempotency_key='admissions-'+oid)
   c.execute("UPDATE admissions_orders SET checkout_id=?,status='checkout' WHERE id=?",(obj['id'],oid));c.commit();return redirect(obj['url'],code=303)
  except Exception:
   c.rollback();app.logger.exception('Enrollment checkout needs retry');return response('<p>Payment could not be opened. Return to your order and retry; do not start another registration.</p>',503)
  finally:c.close()
 api['admissions_partner_snapshot']=partner_snapshot;api['admissions_decorate']=decorate;api['admissions_prepare']=prepare;api['admissions_finish']=finish;api['handle_admissions_event']=handle_event;api['admissions_policy_snapshot']=lambda: json.dumps(catalog_for_snapshot(),ensure_ascii=False)
