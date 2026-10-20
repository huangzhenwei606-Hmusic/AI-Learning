"""Owner-selected guest checkout and explicit, guardian-scoped SMS delivery."""
import hashlib
import secrets
import time
from decimal import Decimal, ROUND_HALF_UP
from html import escape

from flask import abort, make_response, redirect, request, session

COLUMNS = ('token_hash invoice_id parent_id allocation_id amount_cents expires_at revoked '
           'attempt_key attempt_started checkout_id method status invoice_snapshot payment_description coverage_html fee_cents card_rate_bps').split()
CLOSED = {'paid', 'cancelled', 'canceled', 'void', 'waived', 'pending_owner_approval', 'draft'}


def cents(value):
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def ensure_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS quick_payment_links (
        token_hash TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL, parent_id INTEGER NOT NULL,
        allocation_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        revoked INTEGER DEFAULT 0, attempt_key TEXT, attempt_started INTEGER,
        checkout_id TEXT, method TEXT, status TEXT DEFAULT 'ready', invoice_snapshot TEXT NOT NULL,
        payment_description TEXT NOT NULL DEFAULT '', coverage_html TEXT NOT NULL DEFAULT '',
        fee_cents INTEGER NOT NULL DEFAULT 0, card_rate_bps INTEGER NOT NULL DEFAULT 0)''')
    cur.execute('PRAGMA table_info(quick_payment_links)')
    existing = {row[1] for row in cur.fetchall()}
    for name, definition in [('payment_description', "TEXT NOT NULL DEFAULT ''"),
                             ('coverage_html', "TEXT NOT NULL DEFAULT ''"),
                             ('fee_cents', 'INTEGER NOT NULL DEFAULT 0'),
                             ('card_rate_bps', 'INTEGER NOT NULL DEFAULT 0')]:
        if name not in existing:
            cur.execute(f'ALTER TABLE quick_payment_links ADD COLUMN {name} {definition}')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_quick_payment_allocation ON quick_payment_links(allocation_id)')
    cur.execute('''CREATE TABLE IF NOT EXISTS quick_payment_sms (
        token_hash TEXT PRIMARY KEY, destination TEXT NOT NULL, status TEXT NOT NULL,
        provider_response TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL)''')


def load(cur, digest):
    cur.execute('SELECT ' + ','.join(COLUMNS) + ' FROM quick_payment_links WHERE token_hash=?', (digest,))
    row = cur.fetchone()
    return dict(zip(COLUMNS, row)) if row else None


def install_quick_pay(app, api):
    def connect():
        return api['sqlite3'].connect('hmusic.db')

    def prepare():
        api['ensure_guardian_billing_schema']()
        conn = connect()
        try:
            ensure_schema(conn.cursor()); conn.commit()
        finally:
            conn.close()

    def page(title, body, status=200):
        response = make_response(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
        <style>body{{margin:0;background:#f5f6fa;font:16px system-ui;color:#172033}}main{{max-width:560px;margin:32px auto;padding:28px;background:white;border-radius:18px}}h1{{font-size:26px}}p{{line-height:1.6}}button,.button{{display:inline-block;border:0;border-radius:10px;background:#4f46e5;color:white;padding:15px 20px;font:600 16px system-ui;cursor:pointer;text-decoration:none}}input:not([type=checkbox]),select,textarea{{box-sizing:border-box;width:100%;padding:12px;font:16px system-ui;margin:8px 0 16px}}textarea{{min-height:150px}}.amount{{font-size:40px;font-weight:750}}.muted{{color:#64748b;font-size:14px}}.description{{background:#efedff;padding:16px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}}dl>div{{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid #e2e8f0}}dt{{color:#64748b}}dd{{margin:0;text-align:right}}.check{{display:flex;gap:10px;align-items:flex-start;margin:15px 0}}input[type=checkbox]{{width:20px;flex:none}}.notice{{background:#ecfdf5;padding:12px;border-radius:10px}}form{{margin:18px 0}}@media(max-width:600px){{main{{margin:12px;padding:22px}}}}</style></head>
        <body><main><p class="muted">H-MUSIC · SECURE PAYMENT</p><h1>{escape(title)}</h1>{body}</main></body></html>''', status)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    def unavailable(message='This payment link is unavailable. Please contact H-Music for a new link.', status=409):
        return page('Payment needs attention', f'<p>{escape(message)}</p>', status)

    def allowed(parent_id, student):
        return (api['parent_can_access_student'](parent_id, student)
                and api['parent_has_student_permission'](parent_id, student, 'view_billing')
                and api['parent_has_student_permission'](parent_id, student, 'pay'))

    def context(cur, link):
        cur.execute('''SELECT ia.amount,ia.status,ia.lock_token,ia.stripe_checkout_session_id,
            i.student_name,i.status,COALESCE(pp.active,1),i.charge_lessons,i.invoice_type,
            COALESCE(pp.email,''),i.enrollment_id,i.amount,
            COALESCE(i.coverage_title,''),COALESCE(i.coverage_class,''),
            COALESCE(i.coverage_start,''),COALESCE(i.coverage_note,''),COALESCE(i.due_date,''),
            COALESCE(e.course_type_name,''),COALESCE(e.teacher_name,''),COALESCE(e.duration,0)
            FROM invoice_allocations ia
            JOIN invoices i ON i.id=ia.invoice_id LEFT JOIN enrollments e ON e.id=i.enrollment_id
            JOIN parent_profiles pp ON pp.id=ia.parent_id
            WHERE ia.id=? AND ia.invoice_id=? AND ia.parent_id=?''',
            (link['allocation_id'], link['invoice_id'], link['parent_id']))
        return cur.fetchone()

    def snapshot(row):
        # A changed package/total/course must never collect using a stale link.
        return repr((row[4], str(Decimal(str(row[7] or 0)).normalize()),
                     row[8], row[10], cents(row[11]), tuple(row[12:])))

    def card_settings(cur):
        cur.execute("SELECT key,value FROM settings WHERE key IN ('quick_pay_card_enabled','quick_pay_card_rate_bps')")
        values = dict(cur.fetchall())
        try:
            bps = int(values.get('quick_pay_card_rate_bps') or 0)
        except (ValueError, TypeError):
            bps = 0
        return bps if values.get('quick_pay_card_enabled') == '1' and 0 < bps <= 300 else 0

    def coverage(cur, link):
        row = context(cur, link)
        from invoice_payment_ui import invoice_details_html
        course = row[13] or row[17]
        if row[19] and not row[13]:
            course += f' · {row[19]:g} min'
        html = invoice_details_html(link['invoice_id'], row[7], row[11], row[16],
                                   row[12], course, row[14], '', row[18])
        default = row[15] or ' · '.join(str(x) for x in [
            row[4], course, row[18], f'{row[7]:g} lesson(s)', row[12]] if x)
        return html, default

    def details(link):
        description = escape(link['payment_description'])
        return (f'<section><h2>What you are paying for</h2><div class="description">{description}</div></section>'
                + link['coverage_html'])

    def receipt(link, paid=False):
        fee = link['fee_cents'] if link['method'] == 'card' else 0
        return page('Payment received' if paid else 'Bank payment processing',
            f'<p>Invoice #{link["invoice_id"]} · {"Paid" if paid else "Processing — not yet confirmed"}</p>'
            f'<div class="amount">${(link["amount_cents"]+fee)/100:,.2f}</div>'
            f'<p>Tuition / assigned share: ${link["amount_cents"]/100:,.2f}<br>'
            f'Credit card surcharge: ${fee/100:,.2f}</p>' + details(link) +
            ('<p>Thank you. Your payment is confirmed. A receipt is sent to the family email on file.</p>'
             if paid else '<p>No further payment is needed while your bank payment is processing. Course credits are added only after payment is confirmed.</p>'))

    def validate(link, row):
        if not link or not row or link['revoked'] or link['expires_at'] <= int(time.time()):
            return False
        return bool(row[6] and allowed(link['parent_id'], row[4]))

    def reserved(cur, allocation_id):
        from family_billing import active_batch, ensure_schema as family_schema
        family_schema(cur)
        return active_batch(cur, allocation_id)

    def settle(obj, outcome):
        """Called only with a signed event or a Stripe-retrieved Checkout Session."""
        meta = obj.get('metadata') or {}
        digest = meta.get('quick_pay')
        if not digest:
            return False
        conn = connect(); cur = conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            link = load(cur, digest)
            if not link:
                raise ValueError('Unknown quick payment')
            # Serialize with other callbacks and invoice mutations on both DB backends.
            cur.execute('UPDATE invoices SET status=status WHERE id=?', (link['invoice_id'],))
            link = load(cur, digest); row = context(cur, link)
            if (not row or meta.get('attempt_key') != link['attempt_key']
                    or str(meta.get('invoice_id')) != str(link['invoice_id'])
                    or str(meta.get('allocation_id')) != str(link['allocation_id'])
                    or str(meta.get('parent_id')) != str(link['parent_id'])
                    or (link['checkout_id'] and link['checkout_id'] != obj.get('id'))
                    or obj.get('mode') != 'payment'
                    or obj.get('currency') != 'usd'
                    or obj.get('amount_total') != link['amount_cents'] + (link['fee_cents'] if link['method']=='card' else 0)
                    or cents(row[0]) != link['amount_cents']
                    or snapshot(row) != link['invoice_snapshot']):
                raise ValueError('Quick payment verification mismatch')
            if link['status'] == 'paid' or (link['status'] in ('expired', 'failed') and outcome == link['status']):
                conn.rollback(); return True
            if outcome == 'paid' and obj.get('payment_status') != 'paid':
                raise ValueError('Payment is not confirmed')
            if row[2] != link['attempt_key'] or row[1] != 'processing':
                raise ValueError('Payment reservation changed; owner review required')
            if outcome == 'paid':
                if str(row[5]).lower() in CLOSED and row[5] != 'paid':
                    raise ValueError('Closed invoice received a payment; owner review required')
                result = api['record_invoice_allocation_paid'](
                    cur, link['allocation_id'], 'Stripe Card' if link['method'] == 'card' else 'Stripe ACH',
                    reference=f'Quick payment link; tuition ${link["amount_cents"]/100:.2f}; credit card surcharge ${(link["fee_cents"] if link["method"] == "card" else 0)/100:.2f}')
                if not result.get('ok'):
                    raise ValueError(result.get('error') or 'Unable to record payment')
                cur.execute('''UPDATE invoice_allocations SET stripe_checkout_session_id=?,
                    stripe_payment_intent_id=? WHERE id=?''',
                    (obj.get('id'), obj.get('payment_intent'), link['allocation_id']))
                cur.execute("UPDATE quick_payment_links SET status='paid',checkout_id=? WHERE token_hash=?",
                            (obj.get('id'), digest))
                conn.commit()
                if not result.get('already_paid'):
                    api['notify_parent_payment_confirmed'](link['invoice_id'], result['student_name'],
                        result['amount'], 'Stripe Card' if link['method'] == 'card' else 'Stripe ACH',
                        api['date'].today().isoformat(), lessons_added=result['lessons_added'],
                        parent_id=link['parent_id'], allocation_id=link['allocation_id'],
                        invoice_status=result['invoice_status'])
                return True
            if outcome in ('expired', 'failed'):
                cur.execute("""UPDATE invoice_allocations SET status='unpaid',lock_token=NULL,
                    locked_at=NULL,stripe_checkout_session_id=NULL WHERE id=? AND lock_token=?""",
                    (link['allocation_id'], link['attempt_key']))
                cur.execute('UPDATE quick_payment_links SET status=?,checkout_id=? WHERE token_hash=?',
                            (outcome, obj.get('id'), digest))
                api['refresh_invoice_status_from_allocations'](cur, link['invoice_id'])
            else:
                cur.execute('UPDATE quick_payment_links SET checkout_id=? WHERE token_hash=?', (obj.get('id'), digest))
            conn.commit()
            return True
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def handle_event(event):
        obj = event.get('data', {}).get('object', {})
        if not (obj.get('metadata') or {}).get('quick_pay'):
            return None
        # Existing legacy webhook permits unsigned events without a configured secret.
        # Guest payments must never use that fallback.
        if not api['os'].environ.get('STRIPE_WEBHOOK_SECRET'):
            return 'Webhook signing secret required', 503
        kind = event.get('type')
        if kind not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded',
                        'checkout.session.async_payment_failed', 'checkout.session.expired'):
            return 'ok', 200
        outcome = ('expired' if kind.endswith('.expired') else 'failed' if kind.endswith('_failed')
                   else 'paid' if obj.get('payment_status') == 'paid' else 'processing')
        try:
            settle(obj, outcome)
        except Exception:
            app.logger.exception('Quick payment callback needs review')
            return 'Payment reconciliation needs review', 500
        return 'ok', 200

    api['handle_quick_pay_event'] = handle_event

    @app.before_request
    def protect_quick_payment_reservations():
        # Owner edits/manual confirmation and legacy payment routes must not race
        # an outstanding Checkout Session. Revoke/expire it first.
        protected = {'edit_invoice', 'delete_invoice', 'pay_invoice', 'parent_invoice',
                     'stripe_invoice_checkout', 'square_invoice_checkout'}
        if request.endpoint not in protected:
            return None
        if request.method != 'POST' and request.endpoint not in ('stripe_invoice_checkout', 'square_invoice_checkout'):
            return None
        invoice_id = (request.view_args or {}).get('invoice_id')
        if not invoice_id:
            return None
        prepare()
        conn = connect()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT q.token_hash FROM quick_payment_links q
                JOIN invoice_allocations ia ON ia.id=q.allocation_id
                WHERE q.invoice_id=? AND q.attempt_key=ia.lock_token
                AND ia.status='processing' AND q.status='checkout' LIMIT 1""", (invoice_id,))
            if cur.fetchone():
                return unavailable('A quick payment is in progress. Check or revoke its checkout before changing this invoice.')
        finally:
            conn.close()

    @app.route('/owner/quick-pay-settings', methods=['GET', 'POST'])
    def quick_pay_settings():
        if not api['require_owner']():
            return redirect('/owner_login')
        prepare()
        conn = connect(); cur = conn.cursor()
        notice = ''
        try:
            if request.method == 'POST':
                enabled = request.form.get('card_enabled') == '1'
                try:
                    value = Decimal(request.form.get('card_percent') or '0')
                    if not value.is_finite() or value < 0 or value > 3 or value*100 != (value*100).to_integral():
                        raise ValueError()
                    bps = int(value*100)
                except Exception:
                    return unavailable('Enter a percentage from 0 to 3 with up to two decimal places.', 400)
                if enabled and (bps == 0 or request.form.get('card_requirements') != '1'):
                    return unavailable('Confirm your processor/card-network requirements and enter the permitted credit card percentage before enabling.', 400)
                for key, value in [('quick_pay_card_enabled','1' if enabled else '0'),('quick_pay_card_rate_bps',str(bps))]:
                    cur.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,value))
                conn.commit()
                notice = '<p class="notice">Settings saved. They apply only to newly generated links.</p>'
            rate = card_settings(cur)
            configured = api['configure_stripe']() and bool(api['os'].environ.get('STRIPE_WEBHOOK_SECRET'))
            return page('Quick payment settings', f'''<p>ACH is the default. No extra ACH fee is charged to parents.</p>
                <p>Stripe / signed webhook: {'Configured' if configured else 'Missing — configure STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET in Render Environment'}</p>
                {notice}<form method="post"><label class="check"><input type="checkbox" name="card_enabled" value="1" {'checked' if rate else ''}>Offer optional credit card payment with a disclosed surcharge</label>
                <label>Approved credit card surcharge (%)<input name="card_percent" type="number" min="0" max="3" step="0.01" value="{rate/100:g}"></label>
                <label class="check"><input type="checkbox" name="card_requirements" value="1">I have confirmed the permitted rate, required processor/network notifications and credit-only acceptance for this business. The rate does not exceed applicable limits or acceptance cost.</label>
                <p class="muted">Debit and prepaid cards are blocked on the credit card checkout. ACH remains available without an added fee. Verify credit-only checkout with your Stripe account before enabling. Generating a link does not enable AutoPay or send a message.</p>
                <button>Save settings</button></form><p><a href="/owner/quick-pay-guide">How to send payment links</a> · <a href="/billing_settings">Stripe / ACH status</a> · <a href="/invoices">Invoices</a></p>''')
        finally:
            conn.close()

    @app.route('/owner/quick-pay-guide')
    def quick_pay_guide():
        if not api['require_owner']():
            return redirect('/owner_login')
        return page('账单付款链接操作指南', '''<h2>1. 一次性设置</h2><p>进入 <a href="/owner/quick-pay-settings">Quick payment settings · 快捷付款设置</a>。ACH 不向家长加收手续费。信用卡手续费默认关闭；先确认支付机构允许的费率、所需通知及信用卡限制，再填写百分比并开启。设置只影响新生成的链接。</p>
<h2>2. 准备账单</h2><p>打开 <a href="/invoices">Billing → Invoices</a>，找到或创建正确学生、课程的已批准未付账单。点 Edit 核对 Amount、课次、Coverage title（覆盖内容标题）、Course（课程）、Coverage starts（开始日期）、Payment due（到期日）及家长可见备注。内部 Notes 不会自动作为付款说明展示。</p>
<h2>3. 填写付款说明，生成链接</h2><p>在该账单行点 <b>Quick pay link</b>。选择正确的 Guardian / assigned amount（付款家长和应付份额）。在 <b>What this payment covers (parent visible)</b> 中填写学生、课程、老师、每节时长、节数、覆盖日期和特殊安排。金额来自账单，不能由家长自行修改。需要提供信用卡选项时，勾选 Also offer credit card payment；最后点 <b>Generate payment link</b>。</p>
<p>说明示例：Mia — 10 private piano lessons with Ms. Chen, 30 minutes each. Saturdays 3:30–4:00 PM, Oct 24–Dec 26, 2026. Tuition: 10 × $55 = $550. Only this piano package is covered. 请按真实课表填写，并核实节假日，不要直接套用示例日期。</p>
<h2>4. 发给指定家长</h2><p>核对显示的家长手机号，然后点击 <b>Send SMS to …</b>，系统会通过短信服务发送付款链接。生成链接本身不会发送短信。页面会提示服务商是否接受发送；接受不代表手机已收到。每个链接只发送一次，状态不明确时请先检查服务商记录。也可以使用 <b>Copy text message</b> 复制后发微信。家长无需安装 App 或登录。</p>
<h2>5. 家长付款流程</h2><p>短信/微信 → 点击专属链接 → 查看固定金额、课程和本次付款说明 → 选择 ACH 或已开启的信用卡 → 在 Stripe 页面完成付款。信用卡会单列学费、手续费及总金额，家长明确同意后才继续。这是一次性付款，不会自动开通未来扣费。</p>
<h2>6. 如何看付款结果</h2><p><b>Processing = 银行付款处理中，尚未确认到账；Paid = 已确认付款。</b> 系统在 Stripe 确认后更新账单并按既有规则增加课时。多人分摊账单须全额收齐才增加课时；手续费不计入课程课时。不要把处理中 ACH 手工标为 Paid，也不要让家长重复付款。</p>
<h2>7. 修改、过期或撤销链接</h2><p>链接有效期为 7 天。金额或课程信息修改后，请重新生成链接。同一账单的 Quick pay 页面可以点 <b>Revoke link</b> 撤销未使用的链接。已有付款正在进行时，须先核实或关闭对应 Checkout；银行已经提交的付款需要等待核实，不能直接取消后重新收取。</p>
<p><a href="/owner/quick-pay-settings">打开快捷付款设置</a> · <a href="/invoices">打开账单列表</a></p>
''')

    @app.route('/owner/invoice/<int:invoice_id>/quick-pay', methods=['GET', 'POST'])
    def owner_quick_pay(invoice_id):
        if not api['require_owner']():
            return redirect('/owner_login')
        prepare()
        conn = connect(); cur = conn.cursor()
        try:
            cur.execute('SELECT student_name,amount,status FROM invoices WHERE id=?', (invoice_id,))
            invoice = cur.fetchone()
            if not invoice:
                abort(404)
            api['sync_invoice_allocations'](cur, invoice_id, *invoice)
            conn.commit()
            cur.execute('''SELECT ia.id,ia.parent_id,pp.parent_name,ia.amount,ia.status,COALESCE(pp.phone,'')
                FROM invoice_allocations ia JOIN parent_profiles pp ON pp.id=ia.parent_id
                WHERE ia.invoice_id=? AND COALESCE(pp.active,1)=1 ORDER BY ia.id''', (invoice_id,))
            rows = [r for r in cur.fetchall() if allowed(r[1], invoice[0])]
            rate = card_settings(cur)
            sample_link = dict(invoice_id=invoice_id,allocation_id=rows[0][0],parent_id=rows[0][1]) if rows else None
            default_html, default_description = coverage(cur,sample_link) if sample_link else ('','')
            generated = ''
            token = None
            sms_notice = ''
            if request.method == 'POST' and request.form.get('action') == 'send_sms':
                token = request.form.get('token', '')
                digest = hashlib.sha256(token.encode()).hexdigest()
                link = load(cur, digest)
                row = next((r for r in rows if link and r[0] == link['allocation_id']), None)
                ctx = context(cur, link) if link else None
                if (not link or link['invoice_id'] != invoice_id or not row or not ctx
                        or link['revoked'] or link['expires_at'] <= int(time.time())
                        or row[4] not in ('unpaid', 'failed') or str(invoice[2]).lower() in CLOSED
                        or cents(row[3]) != link['amount_cents'] or snapshot(ctx) != link['invoice_snapshot']):
                    return unavailable('This link is no longer ready to send. Generate a current payment link.')
                ready, missing = api['sms_config_status']()
                phone = api['hmusic_normalize_sms_phone'](row[5])
                if not ready:
                    return unavailable('SMS service is not configured. Contact the manager.', 503)
                if not phone:
                    return unavailable('Add a valid phone number to this guardian profile before sending.', 400)
                # Reserve before contacting the provider: double clicks and uncertain responses must not resend.
                cur.execute('''INSERT INTO quick_payment_sms(token_hash,destination,status,created_at)
                    VALUES (?,?,'sending',?) ON CONFLICT(token_hash) DO NOTHING''', (digest, phone, int(time.time())))
                reserved_sms = cur.rowcount == 1
                conn.commit()
                if reserved_sms:
                    # The shared SMS provider expands relative paths to the public domain.
                    url = '/p/' + token
                    try:
                        ok, detail = api['send_sms_delivery'](phone, 'Tuition invoice',
                            f"{invoice[0]}'s invoice #{invoice_id} for ${row[3]:,.2f} is ready. View course details and pay securely without app login:", url)
                    except Exception:
                        ok, detail = False, 'Delivery could not be confirmed. Check provider records before sending another link.'
                    cur.execute('UPDATE quick_payment_sms SET status=?,provider_response=? WHERE token_hash=?',
                                ('accepted' if ok else 'unconfirmed', str(detail)[:500], digest))
                    conn.commit()
                cur.execute('SELECT status FROM quick_payment_sms WHERE token_hash=?', (digest,))
                sms_status = cur.fetchone()[0]
                sms_notice = ('SMS accepted by the provider for ' + phone + '. Delivery to the phone is not yet confirmed.'
                              if sms_status == 'accepted' else 'SMS delivery is unconfirmed. Check provider records before retrying. This link will not be sent twice.')
            if request.method == 'POST' and request.form.get('action') == 'create':
                if not api['configure_stripe']() or not api['os'].environ.get('STRIPE_WEBHOOK_SECRET'):
                    return unavailable('Stripe and its webhook signing secret must be configured first.', 503)
                row = next((r for r in rows if str(r[0]) == request.form.get('allocation_id')), None)
                if not row or row[4] not in ('unpaid', 'failed') or str(invoice[2]).lower() in CLOSED or cents(row[3]) <= 0:
                    return unavailable('Select an unpaid share that this guardian is allowed to pay.')
                if reserved(cur, row[0]):
                    return unavailable('This invoice share is reserved by a combined family payment.')
                description = (request.form.get('payment_description') or '').strip()
                if not description or len(description) > 2000:
                    return unavailable('Enter a parent-visible course description of up to 2000 characters.', 400)
                card_rate = rate if request.form.get('offer_card') == '1' else 0
                fee = int((Decimal(cents(row[3])) * Decimal(card_rate) / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                coverage_html, _ = coverage(cur, dict(allocation_id=row[0],invoice_id=invoice_id,parent_id=row[1]))
                token = secrets.token_urlsafe(32)
                digest = hashlib.sha256(token.encode()).hexdigest()
                cur.execute('''INSERT INTO quick_payment_links
                    (token_hash,invoice_id,parent_id,allocation_id,amount_cents,expires_at,invoice_snapshot,payment_description,coverage_html,fee_cents,card_rate_bps)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (digest, invoice_id, row[1], row[0], cents(row[3]), int(time.time())+7*86400,
                    snapshot(context(cur, dict(allocation_id=row[0], invoice_id=invoice_id, parent_id=row[1]))), description, coverage_html, fee, card_rate))
                conn.commit()
            if token:
                url = api['public_url_for']('/p/' + token)
                text = f'H-Music: {invoice[0]}\'s invoice #{invoice_id} for ${row[3]:,.2f} is ready. View course details & pay securely without app login: {url} Thank you!'
                generated = f'''<h2>Ready to share</h2><p>Recipient: {escape(str(row[2] or 'Guardian'))} · {escape(str(row[5]))}</p>
                    <label>Payment link<input id="quick-pay-url" readonly value="{escape(url, quote=True)}" onclick="this.select()"></label>
                    <button type="button" onclick="copyQuickPay('quick-pay-url',this)">Copy payment link</button>
                    <label>Text message<textarea id="quick-pay-text" readonly onclick="this.select()">{escape(text)}</textarea></label>
                    <button type="button" onclick="copyQuickPay('quick-pay-text',this)">Copy text message</button>
                    <p class="notice">{escape(sms_notice) if sms_notice else 'Nothing has been sent yet.'}</p>
                    <form method="post"><input type="hidden" name="action" value="send_sms">
                    <input type="hidden" name="token" value="{escape(token, quote=True)}">
                    <button {'disabled' if sms_notice else ''}>Send SMS to {escape(str(row[5] or 'guardian — phone missing'))}</button></form>
                    <script>async function copyQuickPay(id,button){{const field=document.getElementById(id);try{{await navigator.clipboard.writeText(field.value);button.textContent='Copied';}}catch(error){{field.select();button.textContent='Selected — copy manually';}}}}</script>
                    <p class="muted">Link valid for 7 days. Send only to this guardian. Anyone with this link can view this invoice share.</p>'''
            options = ''.join(f'<option value="{r[0]}">{escape(str(r[2] or "Guardian"))} · ${r[3]:,.2f}</option>'
                              for r in rows if r[4] in ('unpaid','failed') and cents(r[3]) > 0)
            cur.execute('''SELECT q.token_hash,q.parent_id,q.status,q.expires_at,
                COALESCE(s.status,'not sent'),COALESCE(s.destination,'') FROM quick_payment_links q
                LEFT JOIN quick_payment_sms s ON s.token_hash=q.token_hash
                WHERE q.invoice_id=? AND q.revoked=0 ORDER BY q.expires_at DESC''', (invoice_id,))
            history = ''.join(f'''<p>Guardian #{r[1]} · {escape(r[2])} · SMS: {escape(r[4])} {escape(r[5])}</p><form method="post">
                <input type="hidden" name="action" value="revoke"><input type="hidden" name="digest" value="{r[0]}">
                <button>Revoke link</button></form>''' for r in cur.fetchall() if r[2] != 'paid')
            if request.method == 'POST' and request.form.get('action') == 'revoke':
                link = load(cur, request.form.get('digest',''))
                if not link or link['invoice_id'] != invoice_id:
                    abort(404)
                if link['attempt_key'] and link['status'] not in ('expired','failed','paid'):
                    if not link['checkout_id'] or not api['configure_stripe']():
                        return unavailable('A checkout is being recovered. Resolve its Stripe status before revoking.')
                    obj = api['stripe'].checkout.Session.retrieve(link['checkout_id'])
                    if obj.get('status') == 'open':
                        obj = api['stripe'].checkout.Session.expire(link['checkout_id'])
                    conn.rollback()
                    if obj.get('status') != 'expired':
                        return unavailable('Payment is completed or processing. Check payment status before revoking.')
                    settle(obj, 'expired')
                cur.execute('UPDATE quick_payment_links SET revoked=1 WHERE token_hash=?', (link['token_hash'],))
                conn.commit()
                return redirect(request.path)
            return page(f'Quick payment · Invoice #{invoice_id}', f'''<p>{escape(str(invoice[0]))}</p>
                <p>Generate a guest payment link only for the guardian you choose.</p><p><a href="/owner/quick-pay-settings">Quick payment settings</a> · <a href="/owner/quick-pay-guide">Step-by-step guide</a> · <a href="/edit_invoice/{invoice_id}">Edit invoice / coverage</a></p>{default_html}
                {generated}<form method="post"><input type="hidden" name="action" value="create">
                <label>Guardian / assigned amount<select name="allocation_id" required>{options}</select></label>
                <label>What this payment covers (parent visible)<textarea name="payment_description" maxlength="2000" required>{escape(default_description)}</textarea></label>
                <label class="check"><input type="checkbox" name="offer_card" value="1" {'disabled' if not rate else ''}>Also offer credit card payment ({rate/100:g}% surcharge, parent must agree)</label>
                <button {'disabled' if not options or str(invoice[2]).lower() in CLOSED else ''}>Generate payment link</button></form>
                <p class="muted">ACH: no added parent fee. Optional credit card surcharge is shown separately. Generate a link, then click Send SMS to send it to the selected guardian.</p>
                {history}<p><a href="/invoices">Back to invoices</a></p>''')
        finally:
            conn.close()

    @app.route('/p/<token>', methods=['GET'])
    @app.route('/https://hmusic-crm.onrender.com/p/<token>', methods=['GET'], merge_slashes=False)
    @app.route('/https:/hmusic-crm.onrender.com/p/<token>', methods=['GET'], merge_slashes=False)
    def quick_pay_page(token):
        prepare()
        digest = hashlib.sha256(token.encode()).hexdigest()
        conn = connect(); cur = conn.cursor()
        try:
            link = load(cur, digest)
            row = context(cur, link) if link else None
        finally:
            conn.close()
        if not validate(link, row):
            return unavailable(status=404)
        if link['status'] == 'paid':
            return receipt(link, paid=True)
        if link['checkout_id'] and api['configure_stripe']():
            try:
                obj = api['stripe'].checkout.Session.retrieve(link['checkout_id'])
                if obj.get('payment_status') == 'paid':
                    settle(obj, 'paid')
                    return receipt(link, paid=True)
                if obj.get('status') == 'complete':
                    return receipt(link, paid=False)
                if obj.get('status') == 'expired':
                    settle(obj, 'expired')
                    return unavailable('This checkout expired. Please ask H-Music for a new link.')
            except Exception:
                app.logger.exception('Quick payment status verification failed')
                return unavailable('Payment status could not be verified. Please try again shortly.', 503)
        if row[1] == 'paid':
            return page('Already paid', '<p>This invoice share has already been paid. No additional payment is needed.</p>')
        if str(row[5]).lower() in CLOSED or cents(row[0]) != link['amount_cents'] or snapshot(row) != link['invoice_snapshot']:
            return unavailable('This invoice changed. Please ask H-Music for a new payment link.')
        if link['status'] in ('expired','failed'):
            return unavailable('This checkout ended. Please ask H-Music for a new link.')
        if row[1] == 'processing' and row[2] != link['attempt_key']:
            return unavailable('A payment is already in progress. Please contact H-Music before paying again.')
        if row[1] not in ('unpaid','failed','processing'):
            return unavailable('This payment is awaiting confirmation. Please contact H-Music before paying again.')
        csrf = api['hmusic_csrf_token']()
        session['quick_pay_grant'] = digest
        form = lambda method, label, consent='': f'''<form method="post" action="/p/{escape(token)}/checkout">
            <input type="hidden" name="_csrf_token" value="{escape(csrf)}"><input type="hidden" name="method" value="{method}">{consent}<button>{label}</button></form>'''
        if link['attempt_key']:
            buttons = form(link['method'], 'Continue / check payment')
            note = 'If you already submitted a bank payment, it may take several business days. Please do not pay again.'
        else:
            buttons = form('ach', f'Pay ${link["amount_cents"]/100:,.2f} by bank · ACH')
            if link['card_rate_bps']:
                total = (link['amount_cents']+link['fee_cents'])/100
                consent = f'<p>Tuition / share: ${link["amount_cents"]/100:,.2f}<br>Credit card surcharge ({link["card_rate_bps"]/100:g}%): ${link["fee_cents"]/100:,.2f}<br><b>Total: ${total:,.2f}</b></p><label class="check"><input type="checkbox" name="fee_consent" value="1" required>I choose credit card payment and agree to the surcharge and total shown above. ACH is available with no added fee.</label>'
                buttons += form('card', f'Pay ${total:,.2f} by credit card', consent)
            note = 'One-time payment only. Bank payments can take several business days to confirm. Debit / prepaid cards cannot use the optional credit card checkout.'
        return page(f'Invoice #{link["invoice_id"]}', f'''<p>{escape(str(row[4]))}</p>
            <div class="amount">${link['amount_cents']/100:,.2f}</div><p>Your assigned invoice share</p>
            {details(link)}{buttons}<p class="muted">{note}</p>''')

    @app.route('/p/<token>/checkout', methods=['POST'])
    def quick_pay_checkout(token):
        prepare()
        digest = hashlib.sha256(token.encode()).hexdigest()
        if session.get('quick_pay_grant') != digest:
            return unavailable('Please open the payment link again before paying.', 403)
        if not api['configure_stripe']() or not api['os'].environ.get('STRIPE_WEBHOOK_SECRET'):
            return unavailable('Online payment is temporarily unavailable. Please contact H-Music.', 503)
        method = request.form.get('method')
        if method not in ('card','ach'):
            abort(400)
        conn = connect(); cur = conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            link = load(cur, digest)
            if not link:
                return unavailable(status=404)
            cur.execute('UPDATE invoices SET status=status WHERE id=?', (link['invoice_id'],))
            link = load(cur, digest); row = context(cur, link)
            if not validate(link, row) or str(row[5]).lower() in CLOSED or cents(row[0]) != link['amount_cents'] or snapshot(row) != link['invoice_snapshot']:
                return unavailable()
            if reserved(cur, link['allocation_id']):
                return unavailable('This invoice share belongs to a combined family payment.')
            if link['status'] in ('paid','expired','failed'):
                return unavailable('This checkout ended. Please return to the payment link.')
            if method == 'card' and (not link['card_rate_bps'] or (not link['attempt_key'] and request.form.get('fee_consent') != '1')):
                return unavailable('Select ACH or explicitly agree to the displayed credit card surcharge.', 400)
            if not link['attempt_key']:
                # An existing bank checkout could still collect money. Never create a second session.
                if row[1] not in ('unpaid','failed') or row[2] or row[3]:
                    return unavailable('An existing payment needs review before starting another payment.')
                key = secrets.token_urlsafe(24)
                started = int(time.time())
                cur.execute('''UPDATE invoice_allocations SET status='processing',lock_token=?,locked_at=?,
                    payment_method=? WHERE id=? AND status IN ('unpaid','failed') AND lock_token IS NULL''',
                    (key, api['datetime'].now().strftime('%Y-%m-%d %H:%M'),
                     'Stripe Card' if method == 'card' else 'Stripe ACH', link['allocation_id']))
                if cur.rowcount != 1:
                    return unavailable('A payment is already in progress.')
                cur.execute("""UPDATE quick_payment_links SET attempt_key=?,attempt_started=?,method=?,status='checkout'
                    WHERE token_hash=?""", (key, started, method, digest))
                api['refresh_invoice_status_from_allocations'](cur, link['invoice_id'])
                conn.commit(); link = load(cur, digest)
            elif row[2] != link['attempt_key'] or row[1] != 'processing':
                return unavailable('This payment reservation changed. Please contact H-Music.')
            if link['checkout_id']:
                obj = api['stripe'].checkout.Session.retrieve(link['checkout_id'])
                if obj.get('status') == 'open':
                    return redirect(obj['url'], code=303)
                return redirect('/p/' + token, code=303)
            # Retry an ambiguous provider timeout with identical parameters and the same key.
            if int(time.time()) - link['attempt_started'] > 23*3600:
                return unavailable('This interrupted checkout needs H-Music to review Stripe before retrying.')
            conn.commit()
            meta = {k: str(link[k]) for k in ('invoice_id','parent_id','allocation_id','attempt_key')}
            meta['quick_pay'] = digest
            url = api['public_url_for']('/p/' + token)
            items = [{'price_data':{'currency':'usd','unit_amount':link['amount_cents'],
                'product_data':{'name':f'H-Music tuition · Invoice #{link["invoice_id"]}',
                                'description':link['payment_description'][:500]}},'quantity':1}]
            options = {}
            if link['method'] == 'card':
                items.append({'price_data':{'currency':'usd','unit_amount':link['fee_cents'],
                    'product_data':{'name':f'Credit card surcharge ({link["card_rate_bps"]/100:g}%)'}},'quantity':1})
                options['payment_method_options'] = {'card':{'restrictions':{'funding_types_blocked':['debit','prepaid']}}}
                options['stripe_version'] = '2026-09-30.endive'
            meta['tuition_cents'] = str(link['amount_cents'])
            meta['surcharge_cents'] = str(link['fee_cents'] if link['method']=='card' else 0)
            obj = api['stripe'].checkout.Session.create(
                mode='payment', payment_method_types=['card'] if link['method']=='card' else ['us_bank_account'],
                line_items=items, **options,
                metadata=meta, payment_intent_data={'metadata':meta},
                success_url=url, cancel_url=url, expires_at=link['attempt_started']+86400,
                idempotency_key='quick-pay-' + link['attempt_key'])
            cur.execute('UPDATE quick_payment_links SET checkout_id=? WHERE token_hash=? AND attempt_key=?',
                        (obj['id'],digest,link['attempt_key']))
            cur.execute('''UPDATE invoice_allocations SET stripe_checkout_session_id=?
                WHERE id=? AND lock_token=?''', (obj['id'],link['allocation_id'],link['attempt_key']))
            conn.commit()
            return redirect(obj['url'], code=303)
        except Exception:
            conn.rollback()
            app.logger.exception('Quick checkout interrupted; reservation retained for safe recovery')
            return unavailable('Payment could not be opened. Please use the same link to retry. If you already paid, contact H-Music before paying again.', 503)
        finally:
            conn.rollback(); conn.close()
