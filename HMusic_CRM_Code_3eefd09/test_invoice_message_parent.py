import ast
import sqlite3
import unittest
from pathlib import Path

class InvoiceMessageParentTest(unittest.TestCase):
    def test_assigned_payer_selection(self):
        source=ast.parse(Path(__file__).with_name('app.py').read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='invoice_message_parent')
        ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE invoice_allocations(id,invoice_id,parent_id)')
            choose=lambda preferred: ns['invoice_message_parent'](db.cursor(),275,preferred)
            self.assertIsNone(choose(4780))
            db.execute('INSERT INTO invoice_allocations VALUES(1,275,180675)')
            self.assertEqual(choose(4780),180675)
            db.execute('INSERT INTO invoice_allocations VALUES(2,275,42)')
            self.assertIsNone(choose(4780))
            self.assertEqual(choose(42),42)
