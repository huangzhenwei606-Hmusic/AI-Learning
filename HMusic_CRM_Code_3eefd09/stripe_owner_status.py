"""Read-only Stripe truth for the owner invoice list; no accounting mutations."""
LABELS = {
    'requires_action': 'Action required — customer verification pending',
    'requires_confirmation': 'Incomplete — confirmation required',
    'requires_payment_method': 'Incomplete / failed — payment method required',
    'requires_capture': 'Action required — capture pending',
    'processing': 'ACH processing — not yet paid',
    'succeeded': 'Stripe succeeded — CRM reconciliation required',
    'canceled': 'Canceled — review payment',
    'unknown': 'Payment status unverified — review required',
}


def owner_status_label(state):
    return LABELS.get(state, LABELS['unknown'])


def owner_payment_states(provider, targets):
    states = {}
    priority = {'processing': 0, 'succeeded': 1, 'canceled': 2,
                'requires_payment_method': 3, 'requires_confirmation': 4,
                'requires_capture': 5, 'requires_action': 6, 'unknown': 7}
    for invoice_id, session_id, intent_id in targets:
        state = 'unknown'
        try:
            if provider is not None:
                if not intent_id and session_id:
                    checkout = provider.checkout.Session.retrieve(session_id)
                    intent_id = checkout.get('payment_intent')
                if intent_id:
                    intent = (provider.PaymentIntent.retrieve(intent_id)
                              if isinstance(intent_id, str) else intent_id)
                    raw = intent.get('status')
                    state = raw if raw in LABELS else 'unknown'
        except Exception:
            pass
        if priority[state] >= priority.get(states.get(invoice_id), -1):
            states[invoice_id] = state
    return states


def sync_outcome(state):
    if state == 'processing':
        return 'processing'
    if state in ('requires_action', 'requires_confirmation'):
        return 'action_required'
    if state == 'requires_capture':
        return 'requires_capture'
    return 'unknown'
