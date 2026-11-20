import ast
from pathlib import Path
from types import SimpleNamespace
from html import escape
from unittest import TestCase
from unittest.mock import Mock


class InvoiceDescriptionEditorTest(TestCase):
    def route(self, description, owner=True):
        node = next(n for n in ast.parse(Path(__file__).with_name('app.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'pay_invoice')
        node.decorator_list = []
        cursor = Mock()
        cursor.fetchone.side_effect = [(290, 'Test', 10, 825, 'unpaid', 'tuition', '', 1), ('Private Lesson',)]
        conn = Mock()
        conn.cursor.return_value = cursor
        notify = Mock()
        scope = dict(require_owner=lambda: owner, redirect=lambda url: url,
                     request=SimpleNamespace(method='POST', form={'action':'save_description', 'invoice_description':description}),
                     ensure_v321_schema=lambda: None, ensure_guardian_billing_schema=lambda: None,
                     ensure_v33_schema=lambda: None, sqlite3=SimpleNamespace(connect=lambda _:conn),
                     escape=escape, notify_parent_payment_confirmed=notify)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), scope)
        return scope['pay_invoice'](290), cursor, conn, notify

    def test_save_description_never_confirms_payment(self):
        result, cur, conn, notify = self.route('Piano lessons')
        self.assertEqual(result, '/pay_invoice/290?description_saved=1')
        updates = [call.args for call in cur.execute.call_args_list if call.args[0].startswith('UPDATE')]
        self.assertEqual(updates, [('UPDATE invoices SET coverage_class=? WHERE id=?', ('Piano lessons',290))])
        conn.commit.assert_called_once()
        notify.assert_not_called()

    def test_invalid_description_does_not_write(self):
        for text in ('', 'x'*201):
            result, cur, conn, _ = self.route(text)
            self.assertEqual(result[1], 400)
            conn.commit.assert_not_called()

    def test_requires_owner(self):
        result, cur, conn, _ = self.route('Piano lessons', False)
        self.assertEqual(result, '/owner_login')
        cur.execute.assert_not_called()
