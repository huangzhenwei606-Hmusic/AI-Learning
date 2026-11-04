"""Guest trial ACH checkout, independently reconciled from tuition credits."""
import hashlib
import json
import secrets
import time
from html import escape
from flask import abort, make_response, redirect, request, session
from werkzeug.exceptions import HTTPException

FEES = {'15 mins': 1500, '30 mins': 3000, '45 mins': 4500, '60 mins': 6000}


def register_trial_payment(app, api):
    def db():
        c = api['sqlite3'].connect('hmusic.db')
        c.execute('''CREATE TABLE IF NOT EXISTS trial_payment_orders (
            token_hash TEXT PRIMARY KEY, inquiry_id INTEGER, amount_cents INTEGER NOT NULL,
            duration TEXT NOT NULL, student TEXT NOT NULL, email TEXT NOT NULL,
            status TEXT NOT NULL, checkout_id TEXT, created_at INTEGER NOT NULL, notified_status TEXT NOT NULL DEFAULT '')''')
        c.commit()
        return c

    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def load(c, key):
        row = c.execute('SELECT token_hash,inquiry_id,amount_cents,duration,student,email,status,checkout_id,created_at FROM trial_payment_orders WHERE token_hash=?', (key,)).fetchone()
        return dict(zip(('key','inquiry','amount','duration','student','email','status','checkout','created'), row)) if row else None

    def page(title, body, code=200):
        r = make_response(f'''<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>body{{background:#f6f7fb;font:16px system-ui;color:#172033}}main{{max-width:560px;margin:40px auto;background:white;padding:28px;border-radius:18px}}img{{width:48px}}button,a{{display:inline-block;padding:12px;color:#216bb2}}button{{background:#216bb2;color:white;border:0;border-radius:8px}}p{{line-height:1.6}}</style></head><body><main><img src="/static/hmusic-icon.png" alt="H-Music"><h1>{escape(title)}</h1>{body}</main></body></html>''', code)
        r.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})
        return r

    def notify(c, o, status):
        if status not in ('processing','paid','failed'):
            return
        previous=c.execute('SELECT notified_status FROM trial_payment_orders WHERE token_hash=?',(o['key'],)).fetchone()[0]
        if previous==status:
            return
        api['create_notification']('owner','owner',f'Trial payment {status}',
            f"Request #{o['inquiry']} · {o['student']} · ${o['amount']/100:.2f} · {status}. Trial time still requires confirmation.",
            f"/owner/trial-payment/{o['inquiry']}",related_type='trial_payment',related_id=o['inquiry'])
        c.execute('UPDATE trial_payment_orders SET notified_status=? WHERE token_hash=?',(status,o['key']))
        c.commit()

    def sync(c, obj, failed=False):
        key = (obj.get('metadata') or {}).get('trial_payment')
        o = load(c, key)
        if not o or o['checkout'] != obj.get('id') or obj.get('mode') != 'payment' or obj.get('currency') != 'usd' or obj.get('amount_total') != o['amount']:
            raise ValueError('Trial checkout mismatch')
        if o['status'] == 'paid':
            notify(c,o,'paid')
            return o
        status = ('paid' if obj.get('payment_status') == 'paid' else 'failed' if failed else
                  'expired' if obj.get('status') == 'expired' else
                  'processing' if obj.get('status') == 'complete' else 'checkout')
        if o['status'] == 'failed' and status != 'paid':
            status = 'failed'
        changed = c.execute("UPDATE trial_payment_orders SET status=? WHERE token_hash=? AND status<>? AND status<>'paid'", (status,key,status)).rowcount
        c.commit()
        notify(c,o,status)
        return load(c,key)

    def checkout(token):
        c = db()
        try:
            o = load(c,digest(token))
            if not o or not o['inquiry']:
                abort(404)
            if o['status'] in ('paid','processing','failed','expired'):
                return redirect('/trial-payment/'+token,code=303)
            if not api['configure_stripe']() or not api['os'].environ.get('STRIPE_WEBHOOK_SECRET'):
                return page('Payment temporarily unavailable', '<p>Your trial request is saved. Please return to this page to retry or contact H-Music.</p>',503)
            if o['checkout']:
                obj = api['stripe'].checkout.Session.retrieve(o['checkout'])
                sync(c,obj)
                return redirect(obj['url'] if obj.get('status')=='open' else '/trial-payment/'+token,code=303)
            if time.time()-o['created'] > 23*3600:
                return page('Payment needs review','<p>Please contact H-Music before starting another payment.</p>',409)
            meta = {'trial_payment':o['key'],'inquiry_id':str(o['inquiry'])}
            url = api['public_url_for']('/trial-payment/'+token)
            kwargs = dict(mode='payment',payment_method_types=['us_bank_account'],
                line_items=[{'price_data':{'currency':'usd','unit_amount':o['amount'],'product_data':{'name':f"H-Music trial · {o['duration']}",'description':f"{o['student']} · Request #{o['inquiry']}. Trial time confirmed separately."}},'quantity':1}],
                success_url=url,cancel_url=url,metadata=meta,payment_intent_data={'metadata':meta},
                expires_at=o['created']+86400,idempotency_key='trial-'+o['key'])
            if o['email']:
                kwargs['customer_email']=o['email']
            obj = api['stripe'].checkout.Session.create(**kwargs)
            c.execute("UPDATE trial_payment_orders SET checkout_id=?,status='checkout' WHERE token_hash=? AND checkout_id IS NULL",(obj['id'],o['key']))
            c.commit()
            return redirect(obj['url'],code=303)
        except HTTPException:
            raise
        except Exception:
            c.rollback()
            app.logger.exception('Trial payment checkout needs retry')
            return page('Payment could not be opened',f'<p>Your request is saved. Retry the same payment; do not submit another trial request.</p><a href="/trial-payment/{escape(token)}">Return to payment</a>',503)
        finally:
            c.close()

    def start(data):
        amount = FEES[data['trial_duration']]
        nonce = session.setdefault('trial_payment_nonce',secrets.token_urlsafe(32))
        token = hashlib.sha256((nonce+json.dumps(data,sort_keys=True)).encode()).hexdigest()
        key = digest(token)
        c = db()
        try:
            o = load(c,key)
            if not o:
                inserted = c.execute("INSERT INTO trial_payment_orders(token_hash,amount_cents,duration,student,email,status,created_at) VALUES(?,?,?,?,?,'creating',?) ON CONFLICT(token_hash) DO NOTHING",(key,amount,data['trial_duration'],data['student_name'],data['parent_email'],int(time.time())))
                c.commit()
                if inserted.rowcount == 1:
                    try:
                        inquiry = api['v35_insert_trial_lead'](data,public=True)
                    except Exception:
                        c.execute('DELETE FROM trial_payment_orders WHERE token_hash=? AND inquiry_id IS NULL',(key,));c.commit()
                        raise
                    c.execute("UPDATE trial_payment_orders SET inquiry_id=?,status='ready' WHERE token_hash=?",(inquiry,key));c.commit()
            o = load(c,key)
            if not o['inquiry']:
                return page('Request is being saved','<p>Please wait and retry this submission.</p>',409)
        finally:
            c.close()
        return checkout(token)

    @app.get('/trial-payment/<token>')
    def trial_payment_status(token):
        c = db()
        try:
            o = load(c,digest(token))
            if not o:
                abort(404)
            if o['checkout'] and api['configure_stripe']():
                try:
                    o = sync(c,api['stripe'].checkout.Session.retrieve(o['checkout']))
                except Exception:
                    app.logger.exception('Trial status could not refresh')
            labels = {'paid':'Trial payment received','processing':'Bank payment processing','failed':'Trial payment failed','expired':'Trial payment expired'}
            body = f"<p>Request #{o['inquiry']} · {escape(o['student'])}</p><p>{escape(o['duration'])} · <b>${o['amount']/100:.2f}</b></p>"
            if o['status'] in ('ready','checkout'):
                body += f'<form method="post" action="/trial-payment/{token}/checkout"><input type="hidden" name="_csrf_token" value="{escape(api["hmusic_csrf_token"](),quote=True)}"><button>Continue to ACH payment</button></form>'
            elif o['status']=='processing':
                body += '<p>Your bank is processing the payment. Please do not pay again.</p>'
            elif o['status'] in ('failed','expired'):
                body += '<p>Please contact H-Music to review the payment before retrying.</p>'
            body += '<p>Payment covers the trial fee. H-Music will confirm your teacher and time separately.</p><a href="/trial">Back to trial form</a>'
            return page(labels.get(o['status'],'Trial request received'),body)
        finally:
            c.close()

    app.add_url_rule('/trial-payment/<token>/checkout','trial_payment_checkout',checkout,methods=['POST'])

    @app.get('/owner/trial-payment/<int:inquiry_id>')
    def owner_trial_payment(inquiry_id):
        if not api['require_owner']():
            return redirect('/owner_login')
        c=db()
        try:
            row=c.execute('SELECT student,duration,amount_cents,status,checkout_id FROM trial_payment_orders WHERE inquiry_id=?',(inquiry_id,)).fetchone()
            if not row:abort(404)
            return page('Trial payment',f'<p>Request #{inquiry_id} · {escape(row[0])}</p><p>{escape(row[1])} · ${row[2]/100:.2f}</p><p>Status: <b>{escape(row[3])}</b></p><p>Stripe checkout: {escape(row[4] or "Not started")}</p><a href="/inquiry/{inquiry_id}">Back to trial request</a>')
        finally:c.close()

    def owner_status(inquiry_id):
        c=db()
        try:
            r=c.execute('SELECT status,amount_cents FROM trial_payment_orders WHERE inquiry_id=?',(inquiry_id,)).fetchone()
            if not r:return ''
            return f'<div class="card"><span>Trial payment</span><b>{escape(r[0])} · ${r[1]/100:.2f}</b><br><a href="/owner/trial-payment/{inquiry_id}">View payment status</a></div>'
        finally:c.close()

    def event_handler(event):
        obj=event.get('data',{}).get('object',{})
        if not (obj.get('metadata') or {}).get('trial_payment'):return None
        if not api['os'].environ.get('STRIPE_WEBHOOK_SECRET'):return 'Signature required',503
        if event.get('type') not in ('checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.async_payment_failed','checkout.session.expired'):return 'ok',200
        if not api['configure_stripe']():return 'Stripe unavailable',503
        c=db()
        try:
            obj=api['stripe'].checkout.Session.retrieve(obj['id'])
            failed=False
            if event['type']=='checkout.session.async_payment_failed' and obj.get('payment_intent'):
                pi=api['stripe'].PaymentIntent.retrieve(obj['payment_intent'])
                failed=pi.get('status') in ('requires_payment_method','canceled')
            sync(c,obj,failed)
            return 'ok',200
        except Exception:
            app.logger.exception('Trial payment reconciliation failed')
            return 'Payment needs reconciliation',500
        finally:c.close()

    api['trial_payment_owner_status']=owner_status
    api['start_trial_payment']=start
    api['handle_trial_payment_event']=event_handler
