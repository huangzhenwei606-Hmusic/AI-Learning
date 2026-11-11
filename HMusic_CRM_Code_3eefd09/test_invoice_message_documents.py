import ast
import re
import time
from pathlib import Path
from datetime import date
from html import escape
from unittest.mock import patch
from flask import request, redirect, session
from test_billing_documents import BillingDocumentsTest
from invoice_message_documents import install_invoice_message_documents


class InvoiceDeliveryTest(BillingDocumentsTest):
    def setUp(self):
        super().setUp()
        self.api['hmusic_public_app_url'] = lambda p: 'https://school.invalid' + p
        install_invoice_message_documents(self.app, self.api)

    def token(self):
        with self.app.test_request_context(), self.connect() as c:
            return self.api['invoice_document_token'](c.cursor(), 240, 1)

    def test_guest_link_scope_and_receipt_settlement(self):
        token = self.token()
        with self.client.session_transaction() as s:
            s.clear()
        url = f'/invoice-share/{token}'
        response = self.client.get(url + '/invoice.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'%PDF'))
        self.assertEqual(self.client.get(url + '/receipt.pdf').status_code, 409)
        self.paid()
        self.assertEqual(self.client.get(url + '/receipt.pdf').status_code, 200)
        with self.app.test_request_context():
            doc = self.api['invoice_document_load_token'](token)
            self.assertEqual(str(doc['total']), '400.00')
            self.assertNotIn('Other guardian', str(doc))

    def test_token_expired_tampered_changed_revoked(self):
        token = self.token()
        url = f'/invoice-share/{token}/invoice.pdf'
        self.assertEqual(self.client.get(url.replace(token, token + 'x')).status_code, 403)
        with patch('time.time', return_value=time.time() + 8 * 86400):
            self.assertEqual(self.client.get(url).status_code, 403)
        with self.connect() as c:
            c.execute('UPDATE invoice_allocations SET amount=401 WHERE id=1')
        self.assertEqual(self.client.get(url).status_code, 403)
        token = self.token()
        self.permission = False
        self.assertEqual(self.client.get(f'/invoice-share/{token}/invoice.pdf').status_code, 403)

    def test_email_attachment_recipient_and_unrelated_messages(self):
        token = self.token()
        body = f'Please pay. https://school.invalid/invoice-share/{token}/invoice.pdf'
        with self.app.test_request_context():
            self.assertIsNone(self.api['invoice_message_attachment']('test@example.invalid', 'Hello'))
            name, pdf = self.api['invoice_message_attachment']('TEST@example.invalid', body)
            self.assertEqual(name, 'H-Music-invoice-I-240-A1.pdf')
            self.assertTrue(pdf.startswith(b'%PDF'))
            from werkzeug.exceptions import Forbidden
            with self.assertRaises(Forbidden):
                self.api['invoice_message_attachment']('other@example.invalid', body)

    def test_preview_and_confirm_reuses_invoice_and_preserves_edits(self):
        sent = []
        with self.connect() as c:
            c.execute('DELETE FROM invoice_allocations WHERE invoice_id=240 AND parent_id=2')
            for name in ('student_name', 'final_price', 'package_amount', 'package_lessons', 'auto_renew_lessons'):
                c.execute(f'ALTER TABLE enrollments ADD COLUMN {name}')
            c.execute("UPDATE enrollments SET student_name='Mia Chen',final_price=55,package_amount=550,package_lessons=10,auto_renew_lessons=10")
        ns = dict(self.api, request=request, redirect=redirect, session=session, date=date, escape=escape,
                  require_owner=lambda: True, get_primary_parent_for_student=lambda *a: 999,
                  hmusic_enrollment_invoice_message_body=lambda *a, **k: 'Default',
                  create_enrollment_invoice=lambda *a, **k: 240,
                  sync_invoice_allocations=lambda *a: None,
                  create_invoice_message_event=lambda *a, **k: sent.append((a, k)))
        node = next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'create_enrollment_invoice_route')
        helper = next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'invoice_message_parent')
        node.decorator_list = []
        exec(compile(ast.Module(body=[helper, node], type_ignores=[]), 'app.py', 'exec'), ns)
        self.app.add_url_rule('/send/<int:enrollment_id>', 'send', ns[node.name], methods=['GET', 'POST'])
        response = self.client.post('/send/1', data={'action': 'send', 'message_body': 'Custom <note>'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Nothing has been sent', response.data)
        self.assertIn(b'Custom &lt;note&gt;', response.data)
        self.assertEqual(sent, [])
        token = re.search(r'name="document_token" value="([^"]+)"', response.text).group(1)
        response = self.client.post('/send/1', data={'action': 'confirm_send', 'invoice_id': 240, 'document_token': token, 'message_body': 'Edited text'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]['parent_id'], 1)
        self.assertEqual(sent[0][0][:2], (240, 'sent'))
        self.assertIn('Edited text', sent[0][0][2])
        self.assertIn('/invoice-share/', sent[0][0][2])
        self.assertEqual(self.client.post('/send/1', data={'action': 'confirm_send', 'invoice_id': 240, 'document_token': token, 'message_body': 'Edited text'}).status_code, 409)
        self.assertEqual(len(sent), 1)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM invoices').fetchone()[0], 2)

    def test_draft_only_owner_can_preview_until_confirmed(self):
        with self.connect() as c:
            c.execute("UPDATE invoices SET status='pending_owner_approval' WHERE id=240")
        with self.client.session_transaction() as s:
            s['owner'] = True
        with self.app.test_request_context(), self.connect() as c:
            session['owner'] = True
            token = self.api['invoice_document_token'](c.cursor(), 240, 1)
        url = f'/invoice-share/{token}/invoice.pdf'
        self.assertEqual(self.client.get(url).status_code, 200)
        with self.client.session_transaction() as s:
            s.clear()
        self.assertEqual(self.client.get(url).status_code, 404)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM invoices WHERE id=240').fetchone()[0], 'pending_owner_approval')

    def test_smtp_receives_pdf_attachment_without_real_network(self):
        import os
        from email.message import EmailMessage
        from types import SimpleNamespace
        token = self.token()
        delivered = []
        class SMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def ehlo(self): pass
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, message): delivered.append(message)
        ns = dict(self.api, os=os, re=re, EmailMessage=EmailMessage,
                  hmusic_is_real_email=lambda x: True,
                  hmusic_is_email_suppressed=lambda *a: False,
                  HMUSIC_TRANSACTIONAL_EMAIL='info@h-musicandarts.com',
                  smtplib=SimpleNamespace(SMTP=SMTP, SMTP_SSL=SMTP))
        node = next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name=='send_email_delivery')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        with self.app.test_request_context(), patch.dict(os.environ, dict(HMUSIC_SMTP_HOST='fake.invalid', HMUSIC_SMTP_USER='info@h-musicandarts.com', HMUSIC_SMTP_PASSWORD='fake', HMUSIC_FROM_EMAIL='info@h-musicandarts.com')):
            ok, _ = ns['send_email_delivery']('test@example.invalid', 'Invoice', f'Invoice: https://school.invalid/invoice-share/{token}/invoice.pdf', '/message_thread/1')
            self.assertTrue(ok)
            attachments = list(delivered[0].iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_content_type(), 'application/pdf')
            self.assertTrue(attachments[0].get_payload(decode=True).startswith(b'%PDF'))
            ok, _ = ns['send_email_delivery']('other@example.invalid', 'Invoice', f'/invoice-share/{token}/invoice.pdf', '/message_thread/1')
            self.assertFalse(ok)
            self.assertEqual(len(delivered), 1)

# Do not rediscover the imported fixture class as a second test suite.
del BillingDocumentsTest
