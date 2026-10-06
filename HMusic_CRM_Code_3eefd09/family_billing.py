"""Family payments keep immutable invoice/allocation/enrollment line items.

A batch is one receipt, never a shared lesson balance. Provider settlement and
all per-course grants commit in one transaction; callbacks are idempotent.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from html import escape
import json
from flask import request, session, redirect, Response


class FamilyPaymentError(ValueError):
    pass


def cents(value):
    amount = Decimal(str(value or 0))
    if not amount.is_finite():
        raise FamilyPaymentError("Invalid amount.")
    return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def ensure_schema(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS family_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER NOT NULL,
        request_key TEXT NOT NULL UNIQUE, method TEXT NOT NULL,
        status TEXT NOT NULL, total_cents INTEGER NOT NULL,
        provider_id TEXT UNIQUE, provider_url TEXT, provider_payment_id TEXT,
        reference TEXT, created_at TEXT NOT NULL, paid_at TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS family_payment_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, family_payment_id INTEGER NOT NULL,
        allocation_id INTEGER NOT NULL, invoice_id INTEGER NOT NULL,
        student_name TEXT NOT NULL, enrollment_id INTEGER, lessons REAL NOT NULL,
        amount_cents INTEGER NOT NULL, course_name TEXT, teacher_name TEXT,
        UNIQUE(family_payment_id, allocation_id)
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS family_payment_allocation_idx ON family_payment_items(allocation_id)")


def active_batch(cursor, allocation_id):
    ensure_schema(cursor)
    cursor.execute("""SELECT fp.id FROM family_payments fp JOIN family_payment_items fi
        ON fi.family_payment_id=fp.id WHERE fi.allocation_id=?
        AND fp.status NOT IN ('paid', 'cancelled') LIMIT 1""", (allocation_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def snapshot(cursor, allocation_id, parent_id, api):
    cursor.execute("""SELECT ia.id, i.id, i.student_name, i.enrollment_id,
        i.charge_lessons, ia.amount, ia.status, i.invoice_type, i.status,
        e.student_name, e.course_type_name, e.teacher_name, ia.lock_token,
        i.amount, COALESCE(i.credits_applied,0)
        FROM invoice_allocations ia JOIN invoices i ON i.id=ia.invoice_id
        LEFT JOIN enrollments e ON e.id=i.enrollment_id
        WHERE ia.id=? AND ia.parent_id=?""", (allocation_id, parent_id))
    row = cursor.fetchone()
    if not row:
        raise FamilyPaymentError("An invoice share is not assigned to this family.")
    if row[6] not in ('unpaid', 'failed') or row[8] in ('paid', 'cancelled', 'canceled', 'void', 'waived', 'pending_owner_approval') or row[12]:
        raise FamilyPaymentError("An invoice is already paid or has a payment in progress.")
    if row[14]:
        raise FamilyPaymentError("This invoice already has course credit applied.")
    if not api['parent_has_student_permission'](parent_id, row[2], 'view_billing') or not api['parent_has_student_permission'](parent_id, row[2], 'pay'):
        raise FamilyPaymentError("Payment permission is required for every child.")
    lessons = api['invoice_credit_to_grant'](cursor, row[1], row[4], row[7])
    if lessons and (not row[3] or row[9] != row[2]):
        raise FamilyPaymentError("Set up the invoice's correct course before combining payments.")
    amount = cents(row[5])
    if amount <= 0:
        raise FamilyPaymentError("Only positive unpaid shares can be combined.")
    cursor.execute('SELECT amount FROM invoice_allocations WHERE invoice_id=?', (row[1],))
    if sum(cents(r[0]) for r in cursor.fetchall()) != cents(row[13]):
        raise FamilyPaymentError("Invoice shares do not match the invoice total. Review billing first.")
    return (row[0], row[1], row[2], row[3], lessons, amount, row[10] or '', row[11] or '')


def create_batch(cursor, parent_id, allocation_ids, method, request_key, api):
    ensure_schema(cursor)
    cursor.execute('SELECT id FROM family_payments WHERE request_key=? AND parent_id=?', (request_key, parent_id))
    existing = cursor.fetchone()
    if existing:
        return existing[0]
    ids = sorted(set(int(i) for i in allocation_ids))
    if len(ids) < 2 or len(ids) > 100:
        raise FamilyPaymentError("Select between 2 and 100 unpaid invoice shares.")
    placeholders = ','.join('?' for _ in ids)
    cursor.execute(f'SELECT DISTINCT invoice_id FROM invoice_allocations WHERE parent_id=? AND id IN ({placeholders}) ORDER BY invoice_id', [parent_id] + ids)
    invoice_ids = [r[0] for r in cursor.fetchall()]
    for invoice_id in invoice_ids:
        cursor.execute('UPDATE invoices SET status=status WHERE id=?', (invoice_id,))
    items = [snapshot(cursor, i, parent_id, api) for i in ids]
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""INSERT INTO family_payments
        (parent_id, request_key, method, status, total_cents, created_at)
        VALUES (?,?,?,'creating',?,?)""", (parent_id, request_key, method, sum(i[5] for i in items), now))
    batch_id = cursor.lastrowid
    for item in items:
        if active_batch(cursor, item[0]):
            raise FamilyPaymentError("This invoice is already included in a combined payment.")
        cursor.execute("""UPDATE invoice_allocations SET status='processing',
            payment_method=?, lock_token=?, locked_at=?, updated_at=?
            WHERE id=? AND status IN ('unpaid','failed') AND lock_token IS NULL""",
            (method, 'family:' + str(batch_id), now, now, item[0]))
        if cursor.rowcount != 1:
            raise FamilyPaymentError("An invoice changed. Refresh and select again.")
        cursor.execute("""INSERT INTO family_payment_items
            (family_payment_id, allocation_id, invoice_id, student_name, enrollment_id,
             lessons, amount_cents, course_name, teacher_name) VALUES (?,?,?,?,?,?,?,?,?)""", (batch_id,) + item)
        api['refresh_invoice_status_from_allocations'](cursor, item[1])
    return batch_id


def settle_batch(cursor, batch_id, method, reference, paid_cents, api, payment_date=None):
    # The conditional UPDATE is also the PostgreSQL row lock. A concurrent
    # callback waits, then sees 'paid', so it cannot grant credit twice.
    cursor.execute("UPDATE family_payments SET status=status WHERE id=?", (batch_id,))
    cursor.execute('SELECT parent_id, status, total_cents, method FROM family_payments WHERE id=?', (batch_id,))
    batch = cursor.fetchone()
    if not batch or paid_cents != batch[2] or method != batch[3]:
        raise FamilyPaymentError("Payment amount or method does not match the combined bill.")
    if batch[1] == 'paid':
        return False
    if batch[1] == 'cancelled':
        raise FamilyPaymentError("This combined bill was cancelled. Review the received payment.")
    cursor.execute("""SELECT allocation_id, invoice_id, student_name, enrollment_id,
        lessons, amount_cents FROM family_payment_items WHERE family_payment_id=? ORDER BY invoice_id,allocation_id""", (batch_id,))
    items = cursor.fetchall()
    if not items or sum(i[5] for i in items) != batch[2]:
        raise FamilyPaymentError("Combined bill totals do not match.")
    for allocation_id, invoice_id, student_name, enrollment_id, lessons, amount in items:
        cursor.execute("UPDATE invoices SET status=status WHERE id=?", (invoice_id,))
        cursor.execute("""SELECT ia.amount, ia.status, i.student_name, i.enrollment_id,
            i.charge_lessons, i.invoice_type, e.student_name, i.amount, i.status
            FROM invoice_allocations ia JOIN invoices i ON i.id=ia.invoice_id
            LEFT JOIN enrollments e ON e.id=i.enrollment_id WHERE ia.id=? AND ia.parent_id=? AND i.id=?""",
            (allocation_id, batch[0], invoice_id))
        current = cursor.fetchone()
        if not current or current[1] == 'paid' or current[8] in ('paid','cancelled','canceled','void','waived','pending_owner_approval') or cents(current[0]) != amount or current[2] != student_name or current[3] != enrollment_id:
            raise FamilyPaymentError("An invoice changed after checkout. No course credits were applied; review payment.")
        cursor.execute('SELECT amount FROM invoice_allocations WHERE invoice_id=?', (invoice_id,))
        if sum(cents(r[0]) for r in cursor.fetchall()) != cents(current[7]):
            raise FamilyPaymentError('Invoice total changed. Review the received payment before applying credit.')
        actual_lessons = api['invoice_credit_to_grant'](cursor, invoice_id, current[4], current[5])
        if actual_lessons != lessons or (lessons and current[6] != student_name):
            raise FamilyPaymentError("The course or lesson count changed. Review payment before applying credit.")
        result = api['record_invoice_allocation_paid'](cursor, allocation_id, method,
            payment_date=payment_date, reference=f'Family payment #{batch_id} · {reference}', family_payment_id=batch_id)
        if not result.get('ok'):
            raise FamilyPaymentError(result.get('error') or 'Unable to apply payment.')
    cursor.execute("""UPDATE family_payments SET status='paid', reference=?, paid_at=? WHERE id=?""",
        (reference, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), batch_id))
    return True


def release_batch(cursor, batch_id, api):
    cursor.execute("UPDATE family_payments SET status=status WHERE id=?", (batch_id,))
    cursor.execute("SELECT status FROM family_payments WHERE id=?", (batch_id,))
    row = cursor.fetchone()
    if not row or row[0] == 'paid':
        raise FamilyPaymentError('A settled payment cannot be cancelled.')
    cursor.execute("UPDATE family_payments SET status='cancelled' WHERE id=?", (batch_id,))
    cursor.execute('SELECT allocation_id,invoice_id FROM family_payment_items WHERE family_payment_id=?',(batch_id,))
    for aid,iid in cursor.fetchall():
        cursor.execute("UPDATE invoice_allocations SET status='unpaid',lock_token=NULL,locked_at=NULL WHERE id=? AND lock_token=?",(aid,'family:'+str(batch_id)))
        api['refresh_invoice_status_from_allocations'](cursor,iid)


def install_family_billing(app, api):
    @app.after_request
    def family_billing_release_marker(response):
        response.headers['X-Hmusic-Family-Billing'] = '1'
        return response

    def connect():
        api['ensure_v321_schema']()
        api['ensure_guardian_billing_schema']()
        conn = api['sqlite3'].connect('hmusic.db')
        ensure_schema(conn.cursor())
        conn.commit()
        return conn

    def load(cursor, batch_id):
        cursor.execute('SELECT id,parent_id,method,status,total_cents,provider_id,provider_url,reference,created_at FROM family_payments WHERE id=?', (batch_id,))
        row = cursor.fetchone()
        if not row:
            raise FamilyPaymentError('Combined payment not found.')
        return row

    def authorize(parent_id):
        if api['require_owner']():
            return
        if not api['require_parent']() or str(session.get('parent_id')) != str(parent_id):
            from flask import abort
            abort(403)

    def error(message, status=409):
        return '<h1>Payment needs review</h1><p>' + escape(str(message)) + '</p><p><a href="javascript:history.back()">Back</a></p>', status

    def page(title, body):
        return f'''<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
        <style>body{{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0;padding:24px}}main{{max-width:1000px;margin:auto;background:white;padding:24px;border-radius:16px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #e2e8f0}}button,.button{{display:inline-block;background:#2273ba;color:white;padding:12px 18px;border:0;border-radius:8px;text-decoration:none;cursor:pointer}}form{{margin:16px 0}}.muted{{color:#64748b}}input,select{{padding:10px}}.table-wrap{{overflow:auto}}</style></head>
        <body><main><h1>{escape(title)}</h1>{body}</main></body></html>'''

    def choose(parent_id):
        authorize(parent_id)
        conn = connect(); cur = conn.cursor()
        cur.execute("""SELECT DISTINCT i.id,i.student_name,i.amount,i.status FROM invoices i
            JOIN parent_students ps ON ps.student_name=i.student_name
            WHERE ps.parent_id=? AND ps.active=1 AND i.status NOT IN ('paid','cancelled','canceled','void','waived','pending_owner_approval')""", (parent_id,))
        invoices = cur.fetchall()
        for invoice_id, student, amount, status in invoices:
            api['sync_invoice_allocations'](cur, invoice_id, student, amount, status)
        conn.commit()
        if request.method == 'POST':
            try:
                method = request.form.get('method')
                if method not in ('Stripe ACH','Square','Zelle','Check','Cash'):
                    raise FamilyPaymentError('Select a supported payment method.')
                key = request.form.get('request_key') or ''
                if key not in session.get('family_payment_keys', []):
                    raise FamilyPaymentError('Refresh this page before submitting.')
                cur.execute('BEGIN IMMEDIATE')
                batch_id = create_batch(cur, parent_id, request.form.getlist('allocation_id'), method, key, api)
                conn.commit()
                return redirect(f'/family_payment/{batch_id}')
            except (ValueError, FamilyPaymentError) as exc:
                conn.rollback(); return error(exc)
            finally:
                conn.close()
        cur.execute("""SELECT ia.id,i.id,i.student_name,e.course_type_name,e.teacher_name,
            ia.amount,i.charge_lessons,ia.status,ia.lock_token,i.invoice_type FROM invoice_allocations ia
            JOIN invoices i ON i.id=ia.invoice_id LEFT JOIN enrollments e ON e.id=i.enrollment_id
            WHERE ia.parent_id=? AND ia.status IN ('unpaid','failed')
            AND i.status NOT IN ('paid','cancelled','canceled','void','waived','pending_owner_approval')
            ORDER BY i.student_name,e.id,i.id""", (parent_id,))
        rows = ''
        for a,i,s,c,t,amount,lessons,status,lock,kind in cur.fetchall():
            if lock or active_batch(cur,a) or not api['parent_has_student_permission'](parent_id,s,'pay') or not api['parent_has_student_permission'](parent_id,s,'view_billing'):
                continue
            grant = api['invoice_credit_to_grant'](cur,i,lessons,kind)
            rows += f'<tr><td><input type="checkbox" name="allocation_id" value="{a}" data-cents="{cents(amount)}"></td><td>#{i}</td><td>{escape(s)}</td><td>{escape(c or "Fee")} · {escape(t or "")}</td><td>{grant:g}</td><td>${cents(amount)/100:,.2f}</td></tr>'
        cur.execute('SELECT id,status,total_cents,method FROM family_payments WHERE parent_id=? ORDER BY id DESC LIMIT 20',(parent_id,))
        history = ''.join(f'<p><a href="/family_payment/{b}">Combined payment #{b}</a> · ${n/100:,.2f} · {escape(m)} · {escape(st)}</p>' for b,st,n,m in cur.fetchall())
        conn.close()
        key = api['secrets'].token_urlsafe(24)
        session['family_payment_keys'] = (session.get('family_payment_keys',[]) + [key])[-20:]
        options = '<option>Zelle</option><option value="Check">Check</option><option value="Cash">Cash</option>'
        if api['configure_stripe'](): options += '<option value="Stripe ACH">Bank payment (Stripe ACH)</option>'
        if api['square_is_configured'](): options += '<option value="Square">Card payment (Square)</option>'
        return page('Combine family payments', f'''<p>Select the invoices to pay together. Each child's course keeps its own credits. Only your assigned share is included.</p>
        <form method="post"><input type="hidden" name="request_key" value="{key}"><div class="table-wrap"><table><tr><th>Select</th><th>Invoice</th><th>Student</th><th>Course / Teacher</th><th>Course credits</th><th>Your share</th></tr>{rows or '<tr><td colspan="6">No eligible unpaid invoices.</td></tr>'}</table></div>
        <h2>Total: $<span id="total">0.00</span></h2><label>Payment method <select name="method">{options}</select></label> <button>Review combined payment</button></form>
        <p class="muted">Credits are added after payment is confirmed and the corresponding invoice is fully paid. Existing negative balances are deducted within that course.</p>{history}
        <script>document.querySelectorAll('[data-cents]').forEach(x=>x.addEventListener('change',()=>{{let n=0;document.querySelectorAll('[data-cents]:checked').forEach(y=>n+=Number(y.dataset.cents));document.getElementById('total').textContent=(n/100).toFixed(2);}}));</script>''')

    app.add_url_rule('/family_billing/<int:parent_id>', 'family_billing', choose, methods=['GET','POST'])

    @app.route('/family_payment/<int:batch_id>', methods=['GET','POST'])
    def family_payment(batch_id):
        conn = connect(); cur = conn.cursor()
        try:
            batch = load(cur,batch_id); authorize(batch[1])
            if request.method == 'POST':
                action = request.form.get('action')
                cur.execute('BEGIN IMMEDIATE')
                if action == 'confirm':
                    if not api['require_owner']() or batch[2] not in ('Zelle','Check','Cash'):
                        return error('Only the owner can confirm a received manual payment.',403)
                    if cents(request.form.get('received_amount')) != batch[4]:
                        raise FamilyPaymentError('Enter the exact total actually received. Partial payments need individual billing.')
                    payment_date = request.form.get('payment_date') or date.today().isoformat()
                    date.fromisoformat(payment_date)
                    settle_batch(cur,batch_id,batch[2],request.form.get('reference') or 'Owner confirmed',batch[4],api,payment_date)
                elif action == 'notify':
                    if batch[2] not in ('Zelle','Check','Cash') or batch[3] not in ('creating','pending_confirmation'):
                        raise FamilyPaymentError('This payment cannot be marked as sent.')
                    cur.execute("UPDATE family_payments SET status='pending_confirmation', reference=? WHERE id=?",(request.form.get('reference') or '',batch_id))
                    # Still no payment records or credit until owner confirmation.
                elif action == 'cancel':
                    if not api['require_owner']() or batch[2] not in ('Zelle','Check','Cash') or batch[3] == 'paid':
                        raise FamilyPaymentError('Only an unreceived manual payment can be cancelled by the owner.')
                    release_batch(cur,batch_id,api)
                else: raise FamilyPaymentError('Unknown action.')
                conn.commit(); return redirect(f'/family_payment/{batch_id}')
            cur.execute('SELECT invoice_id,student_name,course_name,teacher_name,lessons,amount_cents FROM family_payment_items WHERE family_payment_id=? ORDER BY id',(batch_id,))
            rows = ''.join(f'<tr><td>#{i}</td><td>{escape(s)}</td><td>{escape(c or "Fee")} · {escape(t or "")}</td><td>{l:g}</td><td>${n/100:,.2f}</td></tr>' for i,s,c,t,l,n in cur.fetchall())
            actions = ''
            if batch[3] != 'paid' and batch[3] != 'cancelled':
                if batch[2] in ('Stripe ACH','Square'):
                    actions = f'<form method="post" action="/family_payment/{batch_id}/checkout"><button>Pay ${batch[4]/100:,.2f} via {escape(batch[2])}</button></form><form method="post" action="/family_payment/{batch_id}/check"><button>Check payment status</button></form><p>Bank payments may take several days. Credit is added after settlement. Keep this bill to resume an interrupted checkout.</p>'
                else:
                    instructions = '<p>Send Zelle to <strong>hmusicjustplay@gmail.com</strong>.</p>' if batch[2]=='Zelle' else '<p>Provide one payment to the studio using the selected method.</p>'
                    actions = instructions + f'<p>Payment note: Family payment #{batch_id}</p><form method="post"><input type="hidden" name="action" value="notify"><input name="reference" placeholder="Payment reference"><button>I sent the combined payment</button></form>'
                    if api['require_owner']():
                        actions += f'<form method="post"><input type="hidden" name="action" value="confirm"><label>Amount received <input name="received_amount" type="number" step="0.01" required></label><label>Date <input type="date" name="payment_date" value="{date.today().isoformat()}" required></label><input name="reference" placeholder="Check / transfer reference"><button>Confirm total received &amp; apply course credits</button></form><form method="post"><input type="hidden" name="action" value="cancel"><button>Cancel — no payment received</button></form>'
            return page(f'Family payment #{batch_id}',f'<p>Status: <strong>{escape(batch[3])}</strong> · {escape(batch[2])}</p><div class="table-wrap"><table><tr><th>Invoice</th><th>Student</th><th>Course / Teacher</th><th>Course credits</th><th>Share</th></tr>{rows}</table></div><h2>Total ${batch[4]/100:,.2f}</h2><p>Each invoice keeps its course binding. Split-guardian invoices receive credit only when all shares have been paid.</p>{actions}<a href="/family_billing/{batch[1]}">Family billing</a>')
        except (ValueError,FamilyPaymentError) as exc:
            conn.rollback(); return error(exc)
        finally: conn.close()

    @app.route('/family_payment/<int:batch_id>/checkout',methods=['POST'])
    def checkout(batch_id):
        conn=connect();cur=conn.cursor()
        try:
            batch=load(cur,batch_id);authorize(batch[1])
            if batch[3]=='paid': return redirect(f'/family_payment/{batch_id}')
            if batch[2] not in ('Stripe ACH','Square') or batch[3]=='cancelled': raise FamilyPaymentError('This payment cannot use online checkout.')
            if batch[5] and batch[6]: return redirect(batch[6])
            if (datetime.now() - datetime.fromisoformat(batch[8])).total_seconds() > 23 * 3600:
                raise FamilyPaymentError('The checkout attempt is too old to retry safely. Review provider records before paying again.')
            # Same immutable batch and provider idempotency key on every retry.
            cur.execute('SELECT invoice_id,student_name,course_name,teacher_name,amount_cents FROM family_payment_items WHERE family_payment_id=? ORDER BY id',(batch_id,))
            items=cur.fetchall()
            if batch[2]=='Stripe ACH':
                if not api['configure_stripe'](): raise FamilyPaymentError('Stripe is not configured.')
                customer=api['get_or_create_stripe_customer'](cur,batch[1]);conn.commit()
                result=api['stripe'].checkout.Session.create(mode='payment',customer=customer,payment_method_types=['us_bank_account'],
                    line_items=[{'price_data':{'currency':'usd','product_data':{'name':f'{s} · {c or "Fee"} · {t or ""} · Invoice #{i}'},'unit_amount':n},'quantity':1} for i,s,c,t,n in items],
                    success_url=api['public_url_for'](f'/family_payment/{batch_id}'),cancel_url=api['public_url_for'](f'/family_payment/{batch_id}'),
                    metadata={'family_payment_id':str(batch_id),'parent_id':str(batch[1])},
                    idempotency_key=f'hmusic-family-{batch_id}')
                pid,url=result.id,result.url
            else:
                if not api['square_is_configured'](): raise FamilyPaymentError('Square is not configured.')
                result=api['square_api_request']('/v2/online-checkout/payment-links',{
                    'idempotency_key':f'hmusic-family-{batch_id}',
                    'order':{'location_id':api['get_square_location_id'](),'reference_id':f'hmusic-family-{batch_id}',
                        'metadata':{'family_payment_id':str(batch_id)},
                        'line_items':[{'name':f'{s} · {c or "Fee"} · {t or ""} · Invoice #{i}','quantity':'1','base_price_money':{'amount':n,'currency':'USD'}} for i,s,c,t,n in items]},
                    'checkout_options':{'redirect_url':api['public_url_for'](f'/family_payment/{batch_id}'),'accepted_payment_methods':{'card':True}},
                    'payment_note':f'H-Music family payment #{batch_id}'})
                link=result.get('payment_link') or {};pid,url=link.get('order_id'),link.get('url')
            if not pid or not url: raise FamilyPaymentError('Provider response is incomplete. Retry this same combined bill.')
            cur.execute("UPDATE family_payments SET provider_id=?,provider_url=?,status=CASE WHEN status='paid' THEN 'paid' ELSE 'processing' END WHERE id=?",(pid,url,batch_id))
            conn.commit();return redirect(url)
        except FamilyPaymentError as exc:
            conn.rollback();return error(exc)
        except Exception:
            conn.rollback();app.logger.exception('Family checkout interrupted for batch %s',batch_id)
            return error('Checkout could not be confirmed. Your bill is reserved; retry this same bill to avoid duplicate payment.',503)
        finally:conn.close()

    def reconcile(batch_id, stripe_session_id=None, square_payment_id=None):
        conn=connect();cur=conn.cursor()
        try:
            batch=load(cur,batch_id)
            if batch[3]=='paid': return True
            if batch[3]=='cancelled': return False
            pid=batch[5] or stripe_session_id
            if batch[2]=='Stripe ACH':
                if not api['configure_stripe']() or not pid: return False
                obj=api['stripe'].checkout.Session.retrieve(pid)
                metadata=obj.get('metadata') or {}
                if str(metadata.get('family_payment_id'))!=str(batch_id) or str(metadata.get('parent_id'))!=str(batch[1]): raise FamilyPaymentError('Provider bill identity mismatch.')
                if obj.get('payment_status')!='paid':
                    if obj.get('status')=='expired' and not obj.get('payment_intent'):
                        cur.execute('BEGIN IMMEDIATE')
                        release_batch(cur,batch_id,api)
                        conn.commit()
                    return False
                if obj.get('currency')!='usd' or obj.get('amount_total')!=batch[4] or (stripe_session_id and stripe_session_id!=pid): raise FamilyPaymentError('Provider amount or session mismatch.')
                reference=obj.get('payment_intent') or obj.get('id')
            elif batch[2]=='Square':
                if not api['square_is_configured'](): return False
                if square_payment_id:
                    payment=api['square_api_request']('/v2/payments/'+square_payment_id,method='GET').get('payment') or {}
                    pid=pid or payment.get('order_id')
                else:
                    if not pid:return False
                    order=api['square_api_request']('/v2/orders/'+pid,method='GET').get('order') or {}
                    tenders=order.get('tenders') or []
                    if len(tenders)!=1 or not tenders[0].get('payment_id'):return False
                    payment=api['square_api_request']('/v2/payments/'+tenders[0]['payment_id'],method='GET').get('payment') or {}
                order=api['square_api_request']('/v2/orders/'+pid,method='GET').get('order') or {}
                if order.get('reference_id')!=f'hmusic-family-{batch_id}' or payment.get('order_id')!=pid or order.get('location_id')!=api['get_square_location_id']():raise FamilyPaymentError('Square order identity mismatch.')
                if payment.get('status')!='COMPLETED':return False
                money=payment.get('amount_money') or {}
                if money.get('currency')!='USD' or money.get('amount')!=batch[4]:raise FamilyPaymentError('Square amount mismatch.')
                reference=payment['id']
            else:return False
            cur.execute('BEGIN IMMEDIATE')
            settle_batch(cur,batch_id,batch[2],reference,batch[4],api)
            cur.execute('UPDATE family_payments SET provider_id=?,provider_payment_id=? WHERE id=?',(pid,reference,batch_id))
            conn.commit();return True
        except Exception:
            conn.rollback();raise
        finally:conn.close()

    @app.route('/family_payment/<int:batch_id>/check',methods=['POST'])
    def check(batch_id):
        conn=connect()
        try: authorize(load(conn.cursor(),batch_id)[1])
        finally:conn.close()
        try:reconcile(batch_id)
        except Exception:
            app.logger.exception('Family reconciliation needs review: %s',batch_id)
            return error('Provider confirmation needs review. Credits have not been changed; do not pay again.',503)
        return redirect(f'/family_payment/{batch_id}')

    @app.before_request
    def family_payment_webhook_and_guards():
        # Family callbacks never trust the posted amount/status. Fetch the
        # payment using existing authenticated provider APIs before settlement.
        if request.path in ('/stripe/webhook','/square/webhook'):
            event=request.get_json(silent=True) or {};obj=event.get('data',{}).get('object',{}) or {}
            bid=(obj.get('metadata') or {}).get('family_payment_id')
            sid=None;spid=None
            if request.path=='/stripe/webhook' and bid:
                if str(obj.get('id','')).startswith('cs_'):sid=obj['id']
                else:
                    conn=connect();cur=conn.cursor();cur.execute('SELECT provider_id FROM family_payments WHERE id=?',(bid,));row=cur.fetchone();conn.close()
                    sid=row[0] if row else None
            elif request.path=='/square/webhook':
                payment=obj.get('payment') or obj;spid=payment.get('id');oid=payment.get('order_id')
                if oid:
                    conn=connect();cur=conn.cursor();cur.execute("SELECT id FROM family_payments WHERE provider_id=? AND method='Square'",(oid,));row=cur.fetchone();conn.close()
                    bid=row[0] if row else None
                    # Recover a checkout whose provider response was interrupted.
                    if not bid and spid and api['square_is_configured']():
                        try:
                            verified=api['square_api_request']('/v2/payments/'+spid,method='GET').get('payment') or {}
                            if verified.get('order_id')==oid:
                                order=api['square_api_request']('/v2/orders/'+oid,method='GET').get('order') or {}
                                bid=(order.get('metadata') or {}).get('family_payment_id')
                        except Exception: pass
            if bid:
                try:reconcile(int(bid),stripe_session_id=sid,square_payment_id=spid)
                except Exception:
                    app.logger.exception('Family payment webhook not settled: %s',bid)
                    return Response('Retry family payment confirmation',status=503)
                return Response('ok',status=200)
        # Prevent individual edits/checkouts from modifying reserved line items.
        endpoint=request.endpoint or ''
        guarded={'edit_invoice','delete_invoice','pay_invoice','stripe_invoice_checkout','square_invoice_checkout','parent_invoice'}
        if endpoint not in guarded or request.method!='POST':return None
        iid=(request.view_args or {}).get('invoice_id')
        if not iid:return None
        conn=connect();cur=conn.cursor()
        cur.execute("""SELECT fp.id FROM family_payments fp JOIN family_payment_items fi ON fi.family_payment_id=fp.id
            WHERE fi.invoice_id=? AND fp.status NOT IN ('paid','cancelled') LIMIT 1""",(iid,))
        row=cur.fetchone();conn.close()
        if row:return error(f'This invoice belongs to combined payment #{row[0]}. Open that combined bill to continue.')
