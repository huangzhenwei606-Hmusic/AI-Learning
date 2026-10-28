import unittest
from invoice_payment_ui import validated_manual_payment_method, owner_payment_confirmation_html


class OwnerPaymentConfirmationTest(unittest.TestCase):
    def test_actual_manual_method_is_preserved(self):
        for method in ('Zelle', 'Bank transfer', 'Check', 'Cash'):
            self.assertEqual(validated_manual_payment_method(method, 'unpaid', ''), method)

    def test_no_silent_zelle_or_forged_stripe_confirmation(self):
        for method in (None, '', 'Stripe ACH', 'Stripe Card', 'anything'):
            with self.assertRaises(ValueError):
                validated_manual_payment_method(method, 'unpaid', '')

    def test_processing_online_payment_cannot_be_manually_confirmed(self):
        for provider in ('Stripe ACH', 'Stripe Card', 'Square'):
            with self.assertRaises(ValueError):
                validated_manual_payment_method('Zelle', 'processing', provider)
            html = owner_payment_confirmation_html(7, 'processing', provider)
            self.assertNotIn('type="submit"', html)
            self.assertIn('processing', html)

    def test_bank_choice_is_clearly_manual_not_a_stripe_charge(self):
        html = owner_payment_confirmation_html(7, 'unpaid', '')
        self.assertIn('Bank payment (already received, manual verification)', html)
        self.assertIn('name="payment_method" required', html)
        self.assertNotIn('Confirm Zelle received', html)
        self.assertNotIn('value="Stripe ACH"', html)


if __name__ == '__main__':
    unittest.main()
