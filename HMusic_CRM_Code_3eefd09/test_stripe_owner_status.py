import unittest
from types import SimpleNamespace
from stripe_owner_status import owner_payment_states, owner_status_label, sync_outcome

class OwnerStatusTest(unittest.TestCase):
    def provider(self, statuses):
        return SimpleNamespace(PaymentIntent=SimpleNamespace(retrieve=lambda key: {'status': statuses[key]}))

    def test_action_required_never_claims_in_transit(self):
        states = owner_payment_states(self.provider({'pi_a':'requires_action'}), [(279, None, 'pi_a')])
        self.assertEqual(states[279], 'requires_action')
        self.assertIn('verification pending', owner_status_label(states[279]))
        self.assertNotIn('processing', owner_status_label(states[279]))

    def test_split_payment_action_takes_precedence(self):
        states = owner_payment_states(self.provider({'pi_a':'requires_action','pi_b':'processing'}), [(1,None,'pi_a'),(1,None,'pi_b')])
        self.assertEqual(states[1], 'requires_action')

    def test_unavailable_or_unknown_is_never_processing(self):
        self.assertEqual(owner_payment_states(None, [(1,None,'pi_a')])[1], 'unknown')
        self.assertEqual(owner_payment_states(self.provider({'pi_a':'new_status'}), [(1,None,'pi_a')])[1], 'unknown')

    def test_succeeded_needs_reconciliation_not_duplicate_charge(self):
        states = owner_payment_states(self.provider({'pi_a':'succeeded'}), [(1,None,'pi_a')])
        self.assertIn('reconciliation required', owner_status_label(states[1]))

    def test_quick_checkout_processing_does_not_hide_action(self):
        self.assertEqual(sync_outcome('requires_action'), 'action_required')
        self.assertEqual(sync_outcome('requires_capture'), 'requires_capture')
        self.assertEqual(sync_outcome('processing'), 'processing')
        self.assertEqual(sync_outcome('new_status'), 'unknown')
