"""Audited correction of an accidentally confirmed manual, single-payer invoice."""
from datetime import datetime, timezone
from html import escape
from flask import request, session, redirect


def ensure_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS payment_reversals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
        payment_id INTEGER NOT NULL UNIQUE, reversal_payment_id INTEGER NOT NULL,
        amount REAL NOT NULL, credits REAL NOT NULL, reason TEXT NOT NULL,
        reversed_by TEXT NOT NULL, reversed_at TEXT NOT NULL)''')


def candidate(cur, iid):
    cur.execute('SELECT student_name,status,enrollment_id,credits_applied FROM invoices WHERE id=?',(iid,))
    invoice=cur.fetchone()
    if not invoice or invoice[1]!='paid': raise ValueError('Invoice is not paid; no correction was made.')
    cur.execute('SELECT id,status,payment_method,stripe_checkout_session_id,stripe_payment_intent_id,amount FROM invoice_allocations WHERE invoice_id=?',(iid,))
    allocations=cur.fetchall()
    if len(allocations)!=1: raise ValueError('Split-payer invoices require individual review.')
    allocation=allocations[0]
    if allocation[1]!='paid' or allocation[2] not in ('Zelle','Cash','Check') or allocation[3] or allocation[4]:
        raise ValueError('Only manually confirmed payments can be reversed here. Online payments require provider review.')
    cur.execute("SELECT 1 FROM family_payment_items fi JOIN family_payments fp ON fp.id=fi.family_payment_id WHERE fi.invoice_id=? AND fp.status!='cancelled' LIMIT 1",(iid,))
    if cur.fetchone(): raise ValueError('This invoice belongs to a combined bill; review the combined payment first.')
    cur.execute('''SELECT p.id,p.amount,p.lessons_added,p.enrollment_id FROM payments p
        JOIN student_ledger sl ON sl.related_payment_id=p.id AND sl.related_invoice_id=?
        WHERE sl.entry_type='invoice_payment_share' AND NOT EXISTS
        (SELECT 1 FROM payment_reversals r WHERE r.payment_id=p.id)''',(iid,))
    payments=cur.fetchall()
    if len(payments)!=1: raise ValueError('Payment history is ambiguous; no correction was made.')
    payment=payments[0]
    if (float(payment[1] or 0)<=0 or round(float(payment[1]),2)!=round(float(allocation[5]),2)
            or payment[3]!=invoice[2] or float(payment[2] or 0)<0):
        raise ValueError('Payment or course binding needs review.')
    if float(payment[2] or 0) and (not invoice[3] or not invoice[2]): raise ValueError('Course credit history needs review.')
    return invoice,allocation,payment


def reverse(cur, iid, payment_id, reason, actor):
    if not reason.strip(): raise ValueError('A correction reason is required.')
    cur.execute('UPDATE invoices SET status=status WHERE id=?',(iid,))
    invoice,allocation,payment=candidate(cur,iid)
    if payment[0]!=payment_id: raise ValueError('Payment changed. Review again before confirming.')
    amount,credits=float(payment[1]),float(payment[2] or 0)
    now=datetime.now(timezone.utc).isoformat()
    note=f'Reversal of payment #{payment_id}, invoice #{iid}: {reason.strip()}'
    cur.execute('''INSERT INTO payments(student_name,amount,lessons_added,payment_method,payment_date,enrollment_id,
        course_type_name,teacher_name,package_name,notes,visible_to_parent)
        SELECT student_name,?,?,'Manual correction',?,enrollment_id,course_type_name,teacher_name,
        'Payment reversal',?,visible_to_parent FROM payments WHERE id=?''',(-amount,-credits,now[:10],note,payment_id))
    reversal_id=cur.lastrowid
    cur.execute('''INSERT INTO payment_reversals(invoice_id,payment_id,reversal_payment_id,amount,credits,reason,reversed_by,reversed_at)
        VALUES(?,?,?,?,?,?,?,?)''',(iid,payment_id,reversal_id,amount,credits,reason.strip(),actor,now))
    cur.execute('''INSERT INTO student_ledger(student_name,entry_type,amount,description,related_invoice_id,
        related_payment_id,related_schedule_id,created_at) VALUES(?,'payment_reversal',?,?,?, ?,NULL,?)''',
        (invoice[0],-amount,note+f' | Course credits reversed: {credits:g}',iid,reversal_id,now))
    if credits:
        cur.execute('UPDATE enrollments SET lessons_left=COALESCE(lessons_left,0)-?,updated_at=? WHERE id=?',(credits,now,invoice[2]))
        if cur.rowcount!=1: raise ValueError('Course was not found; correction cancelled.')
    cur.execute("UPDATE invoice_allocations SET status='unpaid',payment_method=NULL,paid_at=NULL,manual_payment_status=NULL,lock_token=NULL,locked_at=NULL WHERE id=?",(allocation[0],))
    cur.execute("UPDATE invoices SET status='unpaid',credits_applied=0 WHERE id=?",(iid,))
    return credits


def audited_payment(cur, payment_id):
    ensure_schema(cur)
    cur.execute('SELECT 1 FROM payment_reversals WHERE payment_id=? OR reversal_payment_id=?',(payment_id,payment_id))
    return bool(cur.fetchone())


def install_payment_reversal(app, api):
    @app.route('/owner/invoice/<int:iid>/reverse-payment',methods=['GET','POST'])
    def reverse_manual_payment(iid):
        if not api['require_owner'](): return redirect('/owner_login')
        api['ensure_v321_schema']();api['ensure_guardian_billing_schema']()
        c=api['sqlite3'].connect('hmusic.db');cur=c.cursor()
        try:
            ensure_schema(cur);c.commit()
            if request.method=='POST':
                cur.execute('BEGIN IMMEDIATE')
                credits=reverse(cur,iid,int(request.form.get('payment_id','0')),request.form.get('reason',''),str(session.get('user_id') or session.get('owner_name') or session.get('username') or 'owner'))
                c.commit()
                return f'<h1>Payment correction saved</h1><p>Invoice #{iid} is unpaid. {credits:g} course credits were reversed. The original payment and correction audit are retained. No refund or message was sent.</p><a href="/edit_invoice/{iid}">Back to invoice</a>'
            cur.execute('SELECT payment_id,amount,credits,reason,reversed_by,reversed_at FROM payment_reversals WHERE invoice_id=? ORDER BY id',(iid,))
            history=''.join('<li>'+escape(f'Payment #{p}: ${a:.2f}, {l:g} credits reversed · {r} · {by} · {at}')+'</li>' for p,a,l,r,by,at in cur.fetchall())
            try:
                invoice,allocation,payment=candidate(cur,iid)
                form=f'''<h2>{escape(invoice[0])} · Invoice #{iid}</h2><p>Reverse recorded manual payment #{payment[0]}: ${float(payment[1]):,.2f}; remove {float(payment[2] or 0):g} course credits. This corrects records only and does not refund or transfer money.</p>
                <form method="post"><input type="hidden" name="_csrf_token" value="{escape(api['hmusic_csrf_token'](),quote=True)}"><input type="hidden" name="payment_id" value="{payment[0]}"><label>Reason <input name="reason" required maxlength="1000"></label><button>Confirm reversal — mark unpaid</button></form>'''
            except ValueError as exc: form='<p>'+escape(str(exc))+'</p>'
            return f'<html><body><h1>Reverse mistaken Paid</h1>{form}<h2>Correction history</h2><ul>{history or "<li>No corrections recorded.</li>"}</ul><a href="/edit_invoice/{iid}">Back to invoice</a></body></html>'
        except (ValueError,TypeError) as exc:
            c.rollback();return '<h1>Correction not applied</h1><p>'+escape(str(exc))+'</p>',409
        finally:c.close()
