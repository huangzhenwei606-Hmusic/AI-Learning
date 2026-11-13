"""Previewed group intake batches; no payment or credit is inferred from a send."""
import json
import secrets
from decimal import Decimal, InvalidOperation
from flask import request, session, abort, redirect


def ensure_bulk_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS group_bulk_batches(
        id TEXT PRIMARY KEY,created_at TEXT NOT NULL,status TEXT NOT NULL,actor TEXT NOT NULL,
        payload TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS group_bulk_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,batch_id TEXT NOT NULL,application_id INTEGER NOT NULL,
        snapshot TEXT NOT NULL,invoice_id INTEGER,payment_url TEXT NOT NULL DEFAULT '',
        UNIQUE(batch_id,application_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS group_bulk_deliveries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL,channel TEXT NOT NULL,
        destination TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,
        queue_id INTEGER,result TEXT NOT NULL DEFAULT '',UNIQUE(item_id,channel))''')


def amount(value):
    try:
        n=Decimal(str(value))
        if not n.is_finite() or n<0 or n>100000 or n.as_tuple().exponent < -2:raise ValueError()
        return int(n*100)
    except (ValueError,InvalidOperation):raise ValueError('Enter an amount from $0 to $100,000, with at most two decimals.')


def install_group_bulk(bp,api,db,owner,page):
    from group_enrollment import now,rows,one,approve,resolve_profile,get_offering,valid_sessions,schedule_version,existing_application_student

    def batch(cur,key):
        cur.execute('SELECT * FROM group_bulk_batches WHERE id=?',(key,));b=one(cur)
        if not b:abort(404)
        b['plan']=json.loads(b['payload'])
        cur.execute('SELECT * FROM group_bulk_items WHERE batch_id=? ORDER BY id',(key,));items=rows(cur)
        for item in items:
            item['application']=json.loads(item['snapshot'])
            cur.execute('SELECT * FROM group_bulk_deliveries WHERE item_id=? ORDER BY id',(item['id'],));item['deliveries']=rows(cur)
            if api.get('ensure_v33_schema'):
                for delivery in item['deliveries']:
                    if delivery['queue_id']:
                        cur.execute('SELECT status,provider_response FROM notification_delivery_queue WHERE id=?',(delivery['queue_id'],));latest=cur.fetchone()
                        if latest:delivery['status']='submitted' if latest[0]=='sent' else latest[0];delivery['result']=latest[1]
        return b,items

    @bp.post('/group-enrollments/bulk-preview')
    def preview():
        owner()
        try:
            ids=sorted(set(int(x) for x in request.form.getlist('application_ids')))
            if not ids or len(ids)>100:raise ValueError('Select between 1 and 100 applications.')
            action=request.form.get('bulk_action')
            if action not in ('invoice','message','convert'):raise ValueError('Choose a batch action.')
            channels=[x for x in ('email','sms') if request.form.get(x)=='1']
            if action=='message' and not channels:raise ValueError('Choose Email or SMS.')
            text=request.form.get('message','').strip()
            if action!='convert' and (not text or len(text)>3000):raise ValueError('Enter a message of up to 3,000 characters.')
            description=request.form.get('description','').strip()
            if action=='invoice' and not description:raise ValueError('Describe what the invoice covers.')
            plan=dict(action=action,channels=channels,message=text,description=description)
            with db(write=True) as conn:
                cur=conn.cursor();prepared=[]
                for aid in ids:
                    cur.execute('SELECT a.*,o.title FROM group_applications a JOIN group_offerings o ON o.id=a.offering_id WHERE a.id=?',(aid,));a=one(cur)
                    if not a or a['status']=='cancelled':raise ValueError('An application is missing or closed.')
                    a['offering_version']=schedule_version(get_offering(cur,a['offering_id']))
                    a['student_choice']=request.form.get('student_'+str(aid),'')
                    if action in ('invoice','convert') and not a['student_id'] and not a['student_choice']:raise ValueError('Choose a student profile for '+a['student_name'])
                    if a['student_choice']=='new' and not a['student_id']:
                        existing=existing_application_student(cur,a)
                        if existing:a['student_choice']=str(existing[0])
                    if a['student_choice'] and a['student_choice']!='new':
                        cur.execute('SELECT name FROM students WHERE id=?',(a['student_choice'],));student=cur.fetchone()
                        if not student:raise ValueError('Student profile not found.')
                        a['profile_label']=student[0]+' (#'+a['student_choice']+')'
                    else:a['profile_label']='Existing linked profile #'+str(a['student_id']) if a['student_id'] else 'Create new profile: '+a['student_name']
                    if action=='invoice':
                        if a['invoice_id']:raise ValueError(a['student_name']+' already has invoice #'+str(a['invoice_id'])+'. Use Billing to send its existing link.')
                        full=amount(request.form.get('full_amount',''));deposit=0
                        if request.form.get('scheme_'+str(aid))=='deposit':
                            deposit=amount(request.form.get('deposit_amount',''))
                            if not deposit or request.form.get('verified_'+str(aid))!='1':raise ValueError('Verify the received deposit for '+a['student_name'])
                            reference=request.form.get('reference_'+str(aid),'').strip()
                            if not reference:raise ValueError('Enter the deposit receipt/reference for '+a['student_name'])
                        else:reference=''
                        override=request.form.get('amount_'+str(aid),'').strip()
                        net=amount(override) if override else full-deposit
                        if net<=0 or net>full or deposit>full:raise ValueError('Invoice balance must be positive and no greater than full tuition.')
                        a['billing']=dict(amount_cents=net,description=description,deposit_note=f'Full tuition ${full/100:,.2f}; verified deposit ${deposit/100:,.2f}; reference: {reference or "none"}; balance invoiced ${net/100:,.2f}.',full_cents=full,deposit_cents=deposit)
                    for channel in channels:
                        dest=a['email'] if channel=='email' else api['hmusic_normalize_sms_phone'](a['phone'])
                        if not dest or (channel=='email' and not api['hmusic_is_real_email'](dest)):raise ValueError('Missing valid '+channel+' contact for '+a['student_name'])
                    prepared.append(a)
                key=secrets.token_urlsafe(24)
                cur.execute('INSERT INTO group_bulk_batches(id,created_at,status,actor,payload) VALUES(?,?,?,?,?)',(key,now(),'preview',str(session.get('user_name') or session.get('user_role') or 'manager'),json.dumps(plan)))
                for a in prepared:cur.execute('INSERT INTO group_bulk_items(batch_id,application_id,snapshot) VALUES(?,?,?)',(key,a['id'],json.dumps(a)))
            return redirect('/group-enrollments/bulk/'+key,code=303)
        except (ValueError,TypeError) as exc:return page('bulk.html',error=str(exc),batch=None,items=[]),400

    @bp.route('/group-enrollments/bulk/<key>',methods=['GET','POST'])
    def execute(key):
        owner();error=''
        try:
            if request.method=='POST':
                if api.get('ensure_guardian_billing_schema'):api['ensure_guardian_billing_schema']()
                with db(write=True) as conn:
                    cur=conn.cursor();cur.execute('UPDATE group_bulk_batches SET status=status WHERE id=?',(key,));b,items=batch(cur,key)
                    if b['status']=='preview':
                        for item in items:
                            a=item['application'];cur.execute('SELECT * FROM group_applications WHERE id=?',(a['id'],));current=one(cur)
                            if not current or any(current.get(k)!=a.get(k) for k in ('updated_at','email','phone','invoice_id','student_id','status')):raise ValueError('Application changed. Create a fresh preview.')
                            if b['plan']['action'] in ('invoice','convert') and schedule_version(get_offering(cur,a['offering_id']))!=a['offering_version']:raise ValueError('Class schedule changed. Create a fresh preview.')
                            iid=None;url=''
                            if b['plan']['action']=='invoice':
                                approve(cur,a['id'],a['student_choice'],api,billing=a['billing'])
                                cur.execute('SELECT invoice_id,student_id FROM group_applications WHERE id=?',(a['id'],));iid,sid=cur.fetchone()
                                cur.execute('UPDATE group_bulk_items SET invoice_id=? WHERE id=?',(iid,item['id']))
                            elif b['plan']['action']=='convert':
                                offering=get_offering(cur,a['offering_id']);ss=valid_sessions(cur,offering)
                                sid,name,pid=resolve_profile(cur,current,a['student_choice'],ss,api)
                                cur.execute('UPDATE group_applications SET student_id=?,student_name=?,updated_at=? WHERE id=?',(sid,name,now(),a['id']))
                            else:iid=None;url=''
                        cur.execute("UPDATE group_bulk_batches SET status='prepared' WHERE id=?",(key,))
                # Profiles and invoices must be committed before permission helpers read them.
                with db(write=True) as conn:
                    cur=conn.cursor();cur.execute('UPDATE group_bulk_batches SET status=status WHERE id=?',(key,));b,items=batch(cur,key)
                    if b['status']=='prepared':
                        for item in items:
                            a=item['application'];iid=item['invoice_id'];url=''
                            if b['plan']['action']=='invoice' and b['plan']['channels']:
                                cur.execute('SELECT id FROM parent_profiles WHERE lower(email)=lower(?) AND active=1',(a['email'],));parents=cur.fetchall()
                                if len(parents)!=1:raise ValueError('Review guardian account before sending.')
                                url=api['group_payment_link'](cur,iid,parents[0][0],b['plan']['description'])
                                cur.execute('UPDATE group_bulk_items SET payment_url=? WHERE id=?',(url,item['id']))
                            body=b['plan']['message'].replace('{parent}',a['parent_name']).replace('{student}',a['student_name']).replace('{class}',a['title'])
                            if url:body+=f"\nInvoice #{iid}: ${a['billing']['amount_cents']/100:,.2f}\n{b['plan']['description']}\nDownload invoice:\n{url}/invoice.pdf\nPay here:\n{url}"
                            for channel in b['plan']['channels'] if b['plan']['action']!='convert' else []:
                                destination=a['email'] if channel=='email' else api['hmusic_normalize_sms_phone'](a['phone'])
                                cur.execute('INSERT INTO group_bulk_deliveries(item_id,channel,destination,body,status,created_at) VALUES(?,?,?,?,?,?)',(item['id'],channel,destination,body,'pending',now()))
                        cur.execute("UPDATE group_bulk_batches SET status='confirmed' WHERE id=?",(key,))
                # Claim each attempt durably before contacting the provider. A lost response is never resent automatically.
                with db() as conn:
                    cur=conn.cursor();b,items=batch(cur,key)
                for item in items:
                    for delivery in item['deliveries']:
                        with db(write=True) as conn:
                            cur=conn.cursor();cur.execute("UPDATE group_bulk_deliveries SET status='submitting' WHERE id=? AND status='pending'",(delivery['id'],))
                            claimed=cur.rowcount
                        if not claimed:continue
                        qid=None;detail='Delivery outcome is unconfirmed; review before retrying.';status='unconfirmed'
                        try:
                            qid=api['queue_direct_delivery'](delivery['channel'],delivery['destination'],'H-Music group class',delivery['body'],'',related_type='group_bulk',related_id=delivery['id'])
                            if qid:
                                sender=api['send_queued_email_now'] if delivery['channel']=='email' else api['send_queued_sms_now']
                                ok,detail=sender(qid);status='submitted' if ok else ('unconfirmed' if any(word in str(detail).lower() for word in ('unknown','unconfirmed','claimed')) else 'failed')
                            else:status='not_sent';detail='Delivery was suppressed or contact unavailable.'
                        except Exception:pass
                        with db(write=True) as conn:conn.execute('UPDATE group_bulk_deliveries SET queue_id=?,status=?,result=? WHERE id=?',(qid,status,str(detail)[:2000],delivery['id']))
                return redirect('/group-enrollments/bulk/'+key,code=303)
        except ValueError as exc:error=str(exc)
        with db() as conn:b,items=batch(conn.cursor(),key)
        return page('bulk.html',batch=b,items=items,error=error)
