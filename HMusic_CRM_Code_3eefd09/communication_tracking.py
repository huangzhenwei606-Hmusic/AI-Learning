"""School-only read/track pipeline. No sending, billing, or changes to source mail."""
import base64
import hashlib
import imaplib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo
from email_reply_sync import mailbox_config, text_parts, reply_text, authenticated_sender

LA=ZoneInfo('America/Los_Angeles')
SCHOOL='info@h-musicandarts.com'

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def encode(x):return json.dumps(x,ensure_ascii=False,default=str)
def rows(c,sql,p=()):
 cur=c.execute(sql,p);return [dict(zip([x[0] for x in cur.description],r)) for r in cur.fetchall()]
def phone(v):
 v=re.sub(r'\D','',str(v or ''))
 return '1'+v if len(v)==10 else v

def ensure(c):
 for s in [
 '''CREATE TABLE IF NOT EXISTS studio_communications (id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,source_id TEXT NOT NULL,direction TEXT NOT NULL,contact TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,received_at TEXT NOT NULL,conversation_key TEXT NOT NULL,category TEXT NOT NULL,family_refs TEXT NOT NULL,match_state TEXT NOT NULL,provider_state TEXT NOT NULL,source_link TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source,source_id))''',
 '''CREATE TABLE IF NOT EXISTS studio_communication_sync (source TEXT PRIMARY KEY,state TEXT NOT NULL,updated_at TEXT NOT NULL)''',
 '''CREATE TABLE IF NOT EXISTS studio_communication_reports (report_date TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL)'''
 ]:c.execute(s)
 c.commit()

def classify(subject,body):
 text=(subject+' '+body).lower()
 for label,terms in [('改课/请假',['reschedule','cancel lesson','makeup','make-up','改课','请假','补课']),('试听/报名',['trial','enroll','registration','试听','报名']),('账单/付款',['invoice','payment','tuition','paid','付款','学费','账单']),('老师/课程',['teacher','lesson','class','老师','课程','上课'])]:
  if any(t in text for t in terms):return label
 return '其他待核对'

def expects_reply(body):
 text=body.lower()
 if any(x in text for x in ('do not reply','no reply required','无需回复')):return False
 return bool(re.search(r'[?？]|please (?:reply|confirm|let me know)|请回复|请确认|可以吗|方便吗',text))

def match_family(c,contact,source,verified=True):
 if not verified:return [],'待核实身份'
 found=[]
 parents=rows(c,'SELECT id,email,phone FROM parent_profiles WHERE COALESCE(active,1)=1')
 for p in parents:
  value=str(p['email'] or '').strip().lower() if source=='email' else phone(p['phone'])
  if value and value==contact:found.append('parent:'+str(p['id']))
 if len(found)==1:return found,'已关联家庭'
 if len(found)>1:return found,'多个匹配，待核对'
 for i in rows(c,'SELECT id,parent_email,phone FROM inquiries'):
  value=str(i['parent_email'] or '').strip().lower() if source=='email' else phone(i['phone'])
  if value and value==contact:found.append('inquiry:'+str(i['id']))
 return found,('已关联咨询' if len(found)==1 else '多个匹配，待核对' if found else '未匹配')

def add(c,item,verified=True):
 refs,state=match_family(c,item['contact'],item['source'],verified)
 c.execute('''INSERT OR IGNORE INTO studio_communications
 (source,source_id,direction,contact,subject,body,received_at,conversation_key,category,family_refs,match_state,provider_state,source_link,created_at)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(item['source'],item['source_id'],item['direction'],item['contact'],item.get('subject','')[:500],item.get('body','')[:12000],item['received_at'],item['conversation_key'],classify(item.get('subject',''),item.get('body','')),encode(refs),state,item.get('provider_state',''),item.get('source_link',''),now()))

def state(c,source):
 r=rows(c,'SELECT state FROM studio_communication_sync WHERE source=?',(source,));return json.loads(r[0]['state']) if r else {}
def save_state(c,source,data):
 c.execute('INSERT INTO studio_communication_sync VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at',(source,encode(data),now()));c.commit()

class Tracker:
 def __init__(self,connect,api):self.connect=connect;self.api=api;self.lock=threading.Lock();self.last=0;self.pid=None
 def db(self):c=self.connect();ensure(c);return c
 def email(self):
  config=mailbox_config({**os.environ,'HMUSIC_EMAIL_REPLY_SYNC':'1'})
  if not config or config['user'].strip().lower()!=SCHOOL:raise ValueError('学校邮箱IMAP未就绪或账号不匹配')
  client=imaplib.IMAP4_SSL(config['host'],config['port'],timeout=15)
  try:
   client.login(config['user'],config['password']);folders=[config['folder']];all_folder=None
   status,listing=client.list()
   if status=='OK':
    for raw in listing or []:
     line=raw.decode(errors='replace') if isinstance(raw,bytes) else str(raw)
     if re.search(r'\\All\b',line,re.I) and config['host']=='imap.gmail.com':
      m=re.search(r'\)\s+(?:"[^"]*"|NIL)\s+(.+)$',line)
      if m:all_folder=m.group(1).strip().strip('"')
     if re.search(r'\\Sent\b',line,re.I):
      m=re.search(r'\)\s+(?:"[^"]*"|NIL)\s+(.+)$',line)
      if m:folders.append(m.group(1).strip().strip('"'))
   if all_folder:folders=[all_folder]
   total=0;selected=0;deadline=time.monotonic()+35
   for folder in dict.fromkeys(folders):
    status,_=client.select('"'+folder.replace('"','')+'"',readonly=True)
    if status!='OK':continue
    selected+=1
    validity=client.response('UIDVALIDITY')[1];validity=str(validity)
    c=self.db();key='email:'+folder;s=state(c,key);completed=set(s.get('completed_uids',[])) if s.get('validity')==validity else set()
    try:
     since=(datetime.now(LA)-timedelta(days=7)).strftime('%d-%b-%Y')
     status,data=client.uid('search',None,'X-GM-RAW','"newer_than:7d -in:spam -in:trash -in:drafts"') if all_folder else client.uid('search',None,'SINCE',since)
     if status!='OK':raise ValueError('Mailbox search failed')
     uids={int(x) for x in (data[0] or b'').split()};completed.intersection_update(uids)
     pending=sorted(uids-completed,reverse=True)
     checked=0
     for uid in pending[:100]:
      if time.monotonic()>deadline:break
      status,data=client.uid('fetch',str(uid),'(BODY.PEEK[])')
      chunks=[x[1] for x in data or [] if isinstance(x,tuple)]
      if status!='OK' or not chunks:raise ValueError('Mailbox fetch incomplete')
      raw=chunks[0]
      oversized=len(raw)>25*1024*1024
      if oversized:raw=raw.split(b'\r\n\r\n',1)[0]+b'\r\n\r\n'
      msg=BytesParser(policy=policy.default).parsebytes(raw);sender=parseaddr(str(msg.get('From','')))[1].lower()
      outgoing=sender==SCHOOL
      recipient=parseaddr(str(msg.get('To','')))[1].lower()
      contact=recipient if outgoing else sender
      if not contact:
       completed.add(uid);checked+=1;continue
      parts=text_parts(msg);body='[邮件正文超出扫描上限，请打开原邮件]' if oversized else reply_text(*parts)
      reference=str(msg.get('References') or msg.get('In-Reply-To') or msg.get('Message-ID') or str(uid));root=re.findall(r'<[^>]+>',reference);root=root[0] if root else reference
      try:received=parsedate_to_datetime(str(msg.get('Date'))).astimezone(timezone.utc).isoformat()
      except (TypeError,ValueError,OverflowError):received=now()
      mid=str(msg.get('Message-ID') or '')
      sid=hashlib.sha256((mid or folder+validity+str(uid)).encode()).hexdigest()
      add(c,dict(source='email',source_id=sid,direction='outbound' if outgoing else 'inbound',contact=contact,subject=str(msg.get('Subject') or ''),body=body,received_at=received,conversation_key='email:'+hashlib.sha256((root+'|'+contact).encode()).hexdigest(),source_link='https://mail.google.com/mail/u/?authuser='+SCHOOL+'#search/'+quote('rfc822msgid:'+mid.strip('<>'),safe='')),verified=outgoing or bool(authenticated_sender(msg)))
      completed.add(uid);total+=1;checked+=1;c.commit()
      save_state(c,key,{'completed_uids':sorted(completed),'validity':validity,'backlog':len(pending)>checked,'last_success':now()})
     save_state(c,key,{'completed_uids':sorted(completed),'validity':validity,'backlog':len(pending)>checked,'last_success':now()})
    finally:c.close()
   if not selected:raise ValueError('没有可读取的学校邮件文件夹')
   return {'imported_or_checked':total,'folders':selected,'coverage':'全部邮件（排除垃圾、回收站、草稿）' if all_folder else '已配置收件箱和可用的已发送文件夹；归档邮件请结合每日Gmail汇总核对'}
  finally:
   try:client.logout()
   except Exception:pass
 def twilio_get(self,path):
  sid=os.environ.get('TWILIO_ACCOUNT_SID','');token=os.environ.get('TWILIO_AUTH_TOKEN','')
  if not re.fullmatch(r'AC[0-9a-fA-F]{32}',sid) or not token:raise ValueError('Twilio凭证未就绪')
  if not path.startswith('/2010-04-01/Accounts/'+sid+'/') or urlsplit(path).netloc:raise ValueError('Twilio分页地址无效')
  req=Request('https://api.twilio.com'+path,headers={'Authorization':'Basic '+base64.b64encode((sid+':'+token).encode()).decode()})
  class NoRedirect(HTTPRedirectHandler):
   def redirect_request(self,*args,**kwargs):raise ValueError('Twilio redirect refused')
  with build_opener(NoRedirect()).open(req,timeout=15) as response:return json.loads(response.read())
 def sms(self):
  number=os.environ.get('TWILIO_FROM_NUMBER','')
  if not number:raise ValueError('需要明确CRM收发短信号码TWILIO_FROM_NUMBER')
  sid=os.environ.get('TWILIO_ACCOUNT_SID','');total=0
  for direction,field in [('inbound','To'),('outbound','From')]:
   c=self.db();key='sms:'+direction;s=state(c,key)
   try:
    window=(datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat()
    path='/2010-04-01/Accounts/'+sid+'/Messages.json?'+urlencode({field:number,'DateSent>':window,'PageSize':100})
    head=self.twilio_get(path);messages=list(head.get('messages',[]))
    older=s.get('next_page') if s.get('window')==window else None
    overlap=bool(messages and rows(c,"SELECT id FROM studio_communications WHERE source='crm_sms' AND source_id=?",(messages[-1]['sid'],)))
    next_page=None
    if older:
     history=self.twilio_get(older);messages+=history.get('messages',[]);next_page=history.get('next_page_uri')
    elif not overlap:next_page=head.get('next_page_uri')
    for m in messages:
     inbound=m.get('direction')=='inbound'
     if (direction=='inbound')!=inbound:continue
     own=m.get('to') if inbound else m.get('from')
     if phone(own)!=phone(number):continue
     try:received=parsedate_to_datetime(m.get('date_sent') or m['date_created']).astimezone(timezone.utc).isoformat()
     except (ValueError,TypeError,KeyError):received=now()
     contact=phone(m.get('from') if inbound else m.get('to'))
     add(c,dict(source='crm_sms',source_id=m['sid'],direction=direction,contact=contact,subject='CRM SMS',body=m.get('body') or '',received_at=received,conversation_key='sms:'+contact,provider_state=m.get('status') or '',source_link=''))
     total+=1
    c.commit();save_state(c,key,{'next_page':next_page,'window':window,'backlog':bool(next_page),'last_success':now()})
   finally:c.close()
  return {'imported_or_checked':total}
 def report(self,c,day):
  start=datetime.fromisoformat(day).replace(tzinfo=LA).astimezone(timezone.utc).isoformat();end=(datetime.fromisoformat(day)+timedelta(days=1)).replace(tzinfo=LA).astimezone(timezone.utc).isoformat()
  data=rows(c,'SELECT id,source,source_id,direction,contact,subject,SUBSTR(body,1,1000) AS body,received_at,conversation_key,category,family_refs,match_state,provider_state,source_link FROM studio_communications WHERE received_at>=? AND received_at<? ORDER BY received_at DESC LIMIT 2001',(start,end));partial=len(data)>2000;data=data[:2000]
  latest={};keys={r['conversation_key'] for r in data}
  current=rows(c,'SELECT id,source,source_id,direction,contact,subject,SUBSTR(body,1,1000) AS body,received_at,conversation_key,category,family_refs,match_state,provider_state,source_link FROM studio_communications WHERE received_at>=? AND received_at<=? ORDER BY received_at DESC LIMIT 4001',(start,now()))
  partial=partial or len(current)>4000
  for r in current[:4000]:
   if r['conversation_key'] in keys:latest.setdefault(r['conversation_key'],r)
  needs=[r for r in latest.values() if r['direction']=='inbound' and r['category']!='其他待核对']
  waiting=[r for r in latest.values() if r['direction']=='outbound' and r['provider_state'] not in ('failed','undelivered','queued','sending') and expects_reply(r['body'])]
  slim=lambda r:{k:r[k] for k in ('id','source','contact','subject','category','match_state','received_at','source_link')}|{'excerpt':r['body'][:250]}
  return {'date':day,'timezone':'America/Los_Angeles','reply_status_as_of':now(),'message_count':len(data),'partial':partial,'needs_review_count':len(needs),'waiting_for_reply_count':len(waiting),'needs_review':[slim(r) for r in needs[:30]],'waiting_for_reply':[slim(r) for r in waiting[:20]],'note':'关键词初筛，不是已确认业务决定；待对方回复仅为疑似需要答复的发件；统计所选日已同步消息，回复状态核对到当前已同步记录。付款声明不是到账证明。个人iPhone消息由每日Codex任务通过Mac信息应用检查，不包含在本云端数量中。'}
 def overview(self,day=None):
  day=day or datetime.now(LA).date().isoformat();datetime.strptime(day,'%Y-%m-%d');c=self.db()
  try:
   report=self.report(c,day)
   data=rows(c,'SELECT id,source,direction,contact,subject,body,received_at,category,match_state,family_refs,provider_state,source_link FROM studio_communications ORDER BY received_at DESC LIMIT 60')
   for r in data:r['body']=r['body'][:1000]
   sources=rows(c,'SELECT source,state,updated_at FROM studio_communication_sync')
   for s in sources:s['state']=json.loads(s['state'])
   return {'report':report,'recent':data,'sources':sources,'school_email':SCHOOL,'enabled':os.environ.get('HMUSIC_COMMUNICATIONS_ENABLED',os.environ.get('HMUSIC_STUDIO_AUTOMATION','0'))=='1','personal_phone':{'connection':'Mac Messages via Codex daily task','cloud_import':False}}
  finally:c.close()
 def sync(self,force=False):
  import time
  if os.environ.get('HMUSIC_COMMUNICATIONS_ENABLED',os.environ.get('HMUSIC_STUDIO_AUTOMATION','0'))!='1' or (not force and time.monotonic()-self.last<300) or not self.lock.acquire(blocking=False):return
  self.last=time.monotonic()
  try:
   for key,fn in [('email',self.email),('crm_sms',self.sms)]:
    try:result={'status':'ok','last_success':now(),**fn()}
    except Exception as exc:result={'status':'error','error_type':type(exc).__name__,'status_code':getattr(exc,'code',None),'message':str(exc) if type(exc) is ValueError else '收件同步失败，请核对该来源连接；没有读到不等于没有消息。'}
    c=self.db()
    try:save_state(c,key,result)
    finally:c.close()
   c=self.db()
   try:
    local=datetime.now(LA);day=(local.date()-timedelta(days=1)).isoformat()
    if local.hour>=9 and not rows(c,'SELECT report_date FROM studio_communication_reports WHERE report_date=?',(day,)):
     report=self.report(c,day);c.execute('INSERT OR IGNORE INTO studio_communication_reports VALUES(?,?,?)',(day,encode(report),now()));c.commit()
   finally:c.close()
  finally:self.lock.release()

 def start(self):
  if os.environ.get('HMUSIC_COMMUNICATIONS_ENABLED',os.environ.get('HMUSIC_STUDIO_AUTOMATION','0'))!='1' or self.pid==os.getpid():return
  self.pid=os.getpid()
  def loop():
   while True:
    try:self.sync()
    except Exception as exc:self.api['logger'].warning('Communication tracking cycle failed (%s)',type(exc).__name__)
    time.sleep(300)
  threading.Thread(target=loop,name='studio-communication-tracking',daemon=True).start()
