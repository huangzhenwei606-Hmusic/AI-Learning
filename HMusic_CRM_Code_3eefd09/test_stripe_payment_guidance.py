import unittest
from types import SimpleNamespace
from stripe_payment_guidance import checkout_guidance

class GuidanceTest(unittest.TestCase):
    def result(self, intent):
        return checkout_guidance(SimpleNamespace(PaymentIntent=SimpleNamespace(retrieve=lambda _: intent)), {'payment_status':'unpaid','payment_intent':'pi_test'})
    def test_microdeposit_is_not_processing(self):
        state, html = self.result({'status':'requires_action','next_action':{'type':'verify_with_microdeposits','verify_with_microdeposits':{'hosted_verification_url':'https://payments.stripe.com/microdeposit?slug=test'}}})
        self.assertEqual(state,'verification'); self.assertIn('Verify bank account',html)
        self.assertIn('payment has not been submitted',html); self.assertNotIn('No further payment is needed',html)
    def test_missing_bank_and_processing_are_distinct(self):
        self.assertEqual(self.result({'status':'requires_payment_method'})[0],'incomplete')
        self.assertEqual(self.result({'status':'processing'})[0],'processing')
    def test_unknown_provider_does_not_claim_processing(self):
        self.assertEqual(checkout_guidance(SimpleNamespace(), {'payment_intent':'pi_test'})[0],'unknown')
    def test_untrusted_verification_links_are_not_rendered(self):
        for url in ['https://evil.invalid','https://payments.stripe.com.evil.invalid','javascript:alert(1)','https://user@payments.stripe.com/x','https://payments.stripe.com:444/x']:
            _, html=self.result({'status':'requires_action','next_action':{'type':'verify_with_microdeposits','verify_with_microdeposits':{'hosted_verification_url':url}}})
            self.assertNotIn('href=',html)
    def test_paid_does_not_fetch_or_offer_verification(self):
        self.assertEqual(checkout_guidance(SimpleNamespace(),{'payment_status':'paid'}),('paid',''))
