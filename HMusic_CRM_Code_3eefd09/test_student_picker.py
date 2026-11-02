"""Verify schedule HTML receives the same picker for owner and teacher views."""
import ast
from pathlib import Path
import unittest
from flask import Flask


class StudentPickerResponseTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        tree = ast.parse(Path(__file__).with_name('app.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'inject_student_picker')
        from flask import request
        scope = {'app': self.app, 'request': request}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), scope)
        for endpoint in ('calendar', 'teacher_dashboard', 'add_schedule', 'unrelated'):
            self.app.add_url_rule('/' + endpoint, endpoint, lambda: '<html><head></head><body><form></form></body></html>')
        self.app.add_url_rule('/json', 'json', lambda: {'ok': True})
        self.client = self.app.test_client()

    def test_owner_teacher_and_full_schedule_share_asset(self):
        for endpoint in ('calendar', 'teacher_dashboard', 'add_schedule'):
            with self.subTest(endpoint=endpoint):
                result = self.client.get('/' + endpoint)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.text.count('/static/student_picker.js?v=1'), 1)
                self.assertLess(result.text.index('student_picker.js'), result.text.index('</head>'))
                self.assertEqual(result.content_length, len(result.data))

    def test_other_pages_and_json_are_unchanged(self):
        self.assertNotIn('student_picker.js', self.client.get('/unrelated').text)
        self.assertEqual(self.client.get('/json').json, {'ok': True})

    def test_picker_asset_is_available(self):
        app = Flask(__name__, static_folder=str(Path(__file__).with_name('static')))
        result = app.test_client().get('/static/student_picker.js')
        self.assertEqual(result.status_code, 200)
        self.assertIn('combobox', result.text)
        result.close()


if __name__ == '__main__':
    unittest.main()
