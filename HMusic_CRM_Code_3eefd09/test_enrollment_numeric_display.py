"""Exercise the real enrollment display arithmetic with both database types."""
import ast
from decimal import Decimal
from pathlib import Path
import unittest


class EnrollmentNumericDisplayTests(unittest.TestCase):
    def calculate(self, payment, schedule, enrollment):
        tree = ast.parse(Path(__file__).with_name('app.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'enrollment_detail')
        names = {'total_paid', 'total_lessons_purchased', 'lessons_used',
                 'package_value', 'outstanding_balance', 'utilization',
                 'confirmed_tuition', 'confirmed_package_lessons',
                 'confirmed_package_amount', 'tuition_profit'}
        statements = [n for n in function.body if
                      (isinstance(n, ast.Assign) and any(
                          isinstance(t, ast.Name) and t.id in names for t in n.targets))
                      or (isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                          and n.test.id == 'total_lessons_purchased')]
        namespace = dict(payment_summary=payment, financial_summary=schedule,
                         e=enrollment, suggested_price=55.0)
        exec(compile(ast.Module(body=statements, type_ignores=[]), 'app.py', 'exec'), namespace)
        return namespace

    def test_postgres_mixed_numeric_and_real(self):
        enrollment = [None] * 26
        enrollment[10], enrollment[13] = Decimal('55'), Decimal('30')
        enrollment[18], enrollment[19] = Decimal('550'), Decimal('10')
        result = self.calculate((Decimal('550'), Decimal('10')), (2.0,), enrollment)
        self.assertEqual(result['utilization'], 20.0)
        self.assertEqual(result['outstanding_balance'], 0)
        self.assertEqual(result['tuition_profit'], 25)

    def test_sqlite_and_empty_payments_with_suggested_price(self):
        enrollment = [None] * 26
        enrollment[13], enrollment[21] = Decimal('30'), Decimal('10')
        result = self.calculate((None, None), (None,), enrollment)
        self.assertEqual(result['utilization'], 0)
        self.assertEqual(result['confirmed_package_amount'], 550)
        self.assertEqual(result['tuition_profit'], 25)
        result = self.calculate((100.0, 4.0), (1.0,), enrollment)
        self.assertEqual(result['utilization'], 25)


if __name__ == '__main__':
    unittest.main()
