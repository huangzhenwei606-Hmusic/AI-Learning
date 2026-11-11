"""Read-only Checkout guidance; never settles, releases, or creates a payment."""
from html import escape
from urllib.parse import urlsplit


def checkout_guidance(stripe, checkout):
    if checkout.get('payment_status') == 'paid':
        return 'paid', ''
    intent = checkout.get('payment_intent')
    try:
        if isinstance(intent, str):
            intent = stripe.PaymentIntent.retrieve(intent)
        if not intent:
            return 'incomplete', '<p><strong>Payment not submitted.</strong> Continue this same checkout to enter your bank details and confirm payment.</p>'
        state = intent.get('status')
        if state == 'requires_action':
            action = intent.get('next_action') or {}
            verification = action.get('verify_with_microdeposits') or {}
            url = verification.get('hosted_verification_url') or ''
            parsed = urlsplit(url)
            # Only Stripe-hosted verification pages, never arbitrary metadata URLs.
            safe = parsed.scheme == 'https' and parsed.hostname == 'payments.stripe.com' and not parsed.username and not parsed.password and parsed.port in (None,443)
            link = f'<p><a href="{escape(url, quote=True)}" rel="noopener noreferrer">Verify bank account</a></p>' if safe else ''
            if action.get('type') == 'verify_with_microdeposits':
                return 'verification', ('<p><strong>Bank verification required — payment has not been submitted.</strong> '
                    'Check your bank statement for the small Stripe deposit, then complete the verification using the code or amounts requested by Stripe. '
                    'Do not start a second payment. Credits and receipt are available only after payment is confirmed.</p>' + link)
            return 'action_required', '<p><strong>Action required.</strong> Complete the additional verification requested by Stripe. Payment is not yet confirmed; do not start a second payment.</p>'
        if state == 'processing':
            return 'processing', '<p><strong>Bank payment processing.</strong> Your bank payment was submitted. No further payment is needed while it processes. Credits are added after payment is confirmed.</p>'
        if state in ('requires_payment_method', 'requires_confirmation', 'canceled'):
            return 'incomplete', '<p><strong>Payment not completed.</strong> Return to the original checkout and complete the bank details and confirmation. Check this payment before starting another attempt.</p>'
    except Exception:
        pass
    return 'unknown', '<p><strong>Payment status needs checking.</strong> We could not confirm whether your bank payment needs verification or is processing. Do not submit another payment; contact H-Music.</p>'
