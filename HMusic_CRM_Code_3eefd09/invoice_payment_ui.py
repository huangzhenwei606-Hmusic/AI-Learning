"""Parent invoice presentation only; payment authorization stays in app.py."""
from datetime import datetime
from html import escape


MANUAL_PAYMENT_METHODS = ('Zelle', 'Bank transfer', 'Check', 'Cash')


def validated_manual_payment_method(value, share_status='', current_method=''):
    if share_status == 'processing' and str(current_method).lower().startswith(('stripe', 'square')):
        raise ValueError('Online payment is processing. Wait for the provider result before recording another payment.')
    if value not in MANUAL_PAYMENT_METHODS:
        raise ValueError('Choose the method of the payment actually received. Stripe ACH is confirmed automatically.')
    return value


def owner_payment_confirmation_html(allocation_id, share_status, current_method):
    if share_status == 'processing' and str(current_method).lower().startswith(('stripe', 'square')):
        return '<p role="status">Bank / online payment processing. This updates automatically after the provider confirms payment.</p>'
    options = '<option value="">Choose received payment method…</option>'
    for method in MANUAL_PAYMENT_METHODS:
        label = 'Bank payment (already received, manual verification)' if method == 'Bank transfer' else method
        selected = ' selected' if method == current_method else ''
        options += f'<option value="{escape(method)}"{selected}>{escape(label)}</option>'
    return f'''<form method="POST" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <input type="hidden" name="action" value="confirm_allocation">
        <input type="hidden" name="allocation_id" value="{int(allocation_id)}">
        <label>Received payment method <select name="payment_method" required>{options}</select></label>
        <button type="submit">Confirm payment received</button>
    </form>'''


def display_date(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        date = datetime.strptime(raw[:10], '%Y-%m-%d')
        return f'{date:%b} {date.day}, {date.year}'
    except ValueError:
        return raw


def invoice_details_html(invoice_id, lessons, subtotal, due_date='', title='', course='',
                         coverage_start='', note='', teacher='', discount=0, discount_code=''):
    """Only explicit parent-facing fields are accepted, never internal invoice notes."""
    count = float(lessons or 0)
    count_label = f'{count:g}'
    package = f'{count_label} lesson' + ('' if count == 1 else 's') if count > 0 else ''
    if count > 0:
        package += f' × ${float(subtotal or 0) / count:,.2f}'
    rows = [('Invoice', f'#{invoice_id}'), ('Coverage', title), ('Course', course),
            ('Teacher', teacher), ('Package', package),
            ('Coverage from', display_date(coverage_start)), ('Payment due', display_date(due_date))]
    if float(discount or 0) > 0:
        rows += [('Subtotal', f'${float(subtotal or 0):,.2f}'),
                 ('Discount' + (f' ({discount_code})' if discount_code else ''), f'−${float(discount):,.2f}')]
    items = ''.join(f'<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>'
                    for label, value in rows if str(value or '').strip())
    result = f'<section class="invoice-details"><h2>Invoice details</h2><dl>{items}</dl></section>'
    if str(note or '').strip():
        result += f'<section class="manager-note"><h2>Note from H-Music</h2><p>{escape(str(note))}</p></section>'
    return result


def payment_choices_html(invoice_id, student, amount, allowed_methods, ach_ready, can_autopay):
    money = f'{float(amount or 0):,.2f}'
    student = escape(str(student))
    cards = []
    if 'ach' in allowed_methods:
        if ach_ready:
            consent = ''
            if can_autopay:
                consent = f'''<label class="autopay-consent">
                    <input type="checkbox" name="autopay" value="1">
                    <span><b>Enable AutoPay for future tuition <small>(optional)</small></b>
                    <small>Save your bank account and authorize H-Music to automatically charge future tuition invoices for {student}. You can turn AutoPay off later.</small></span>
                </label>'''
            cards.append(f'''<details class="payment-choice ach-choice" name="payment-method" open>
                <summary><span><b>Bank transfer (ACH)</b><small>Secure payment through Stripe</small></span><span class="chevron" aria-hidden="true">⌄</span></summary>
                <div class="method-body"><form method="GET" action="/stripe/invoice/{int(invoice_id)}/checkout">
                    <input type="hidden" name="method" value="ach">
                    <button class="primary-action" type="submit">Pay ${money} by bank transfer →</button>
                    <p class="method-help">Connect your bank and confirm payment on Stripe. Processing may take several business days.</p>
                    {consent}
                </form></div></details>''')
        else:
            cards.append('''<section class="payment-choice disabled"><h3>Bank transfer (ACH)</h3>
                <p>Bank transfer is currently unavailable. Please use Zelle or contact H-Music.</p></section>''')
    if 'zelle' in allowed_methods:
        opened = ' open' if 'ach' not in allowed_methods or not ach_ready else ''
        cards.append(f'''<details class="payment-choice zelle-choice" name="payment-method"{opened}>
            <summary><b>Pay with Zelle instead</b><span class="chevron" aria-hidden="true">⌄</span></summary>
            <div class="method-body"><ol class="payment-steps">
                <li><h3>Open your banking app</h3><p>Find Zelle and send <strong>${money}</strong> to:</p>
                    <div class="account-box"><span class="copy-account-text">6507977125</span></div>
                    <button type="button" class="copy-account-button" data-copy-value="6507977125">Copy Zelle phone number</button>
                    <p class="copy-help" role="status" aria-live="polite">Copying the phone number does not send payment.</p></li>
                <li><h3>Complete your transfer</h3><p>Send ${money} in your banking app. Add <strong>{student} / Invoice #{int(invoice_id)}</strong> in the memo.</p></li>
                <li><h3>Let H-Music know</h3><form method="POST">
                    <input type="hidden" name="action" value="notify_paid"><input type="hidden" name="payment_method" value="Zelle">
                    <label for="payment-note">Confirmation number or note <span>(optional)</span></label>
                    <textarea id="payment-note" name="payment_note" rows="2" placeholder="Add transfer details"></textarea>
                    <button class="primary-action" type="submit">I’ve sent ${money} via Zelle</button>
                    <p class="method-help">We will verify your transfer before marking this invoice paid.</p>
                </form></li></ol></div></details>''')
    if not cards:
        return '<p class="hint">No payment method is enabled for this invoice yet. Please contact H-Music.</p>'
    return '<h2 class="section-title">Choose how to pay</h2><div class="payment-choice-grid">' + ''.join(cards) + '</div>'
