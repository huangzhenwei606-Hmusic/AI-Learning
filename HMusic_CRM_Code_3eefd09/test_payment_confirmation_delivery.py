import ast
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from invoice_payment_ui import owner_payment_confirmation_html

class ConfirmationDeliveryTest(TestCase):
    def setUp(self):
        node=next(n for n in ast.parse(Path(__file__).with_name('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='notify_parent_payment_confirmed')
        self.ns={k:Mock() for k in ['queue_notification_delivery','send_queued_email_now','get_or_create_message_thread','add_message','create_notification','app']}
        self.ns.update(hmusic_money=lambda n:f'{n:.2f}',hmusic_number=lambda n:str(n))
        self.ns['queue_notification_delivery'].return_value=123
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),self.ns)
    def call(self, enabled):
        self.ns['notify_parent_payment_confirmed'](274,'Leo',990,'Zelle','2026-11-12',lessons_added=10,parent_id=1,allocation_id=2,send_message=enabled)
    def test_email_required_when_message_unchecked(self):
        self.call(False)
        self.assertEqual(self.ns['queue_notification_delivery'].call_args.args[5],'email')
        self.ns['send_queued_email_now'].assert_called_once_with(123)
        self.ns['add_message'].assert_not_called();self.ns['create_notification'].assert_not_called()
    def test_checked_sends_email_and_app_message(self):
        self.call(True)
        self.ns['send_queued_email_now'].assert_called_once_with(123)
        self.ns['add_message'].assert_called_once()
        self.assertIn('Lessons added: 10',self.ns['add_message'].call_args.args[4])
        self.assertFalse(self.ns['create_notification'].call_args.kwargs['send_email_now'])
    def test_message_failure_cannot_prevent_email(self):
        self.ns['add_message'].side_effect=RuntimeError('message failure');self.call(True)
        self.ns['send_queued_email_now'].assert_called_once_with(123)
    def test_checkbox_default(self):
        html=owner_payment_confirmation_html(2,'unpaid','Zelle')
        self.assertIn('name="send_confirmation_message" value="1" checked',html)
        self.assertIn('confirmation email is always sent',html)
