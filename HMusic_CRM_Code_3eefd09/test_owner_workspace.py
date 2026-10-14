import unittest
from pathlib import Path
from flask import Flask, request, Response
from owner_workspace import apply_owner_workspace

class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__,template_folder=str(Path(__file__).parent/'templates'))
    def render(self,path='/',headers=None,owner=True,body=None,status=200,mimetype='text/html',attachment=False):
        with self.app.test_request_context(path,headers=headers or {}):
            r=Response(body or '<html><head></head><body><form method="post"><input name="csrf_token" value="safe"></form></body></html>',status=status,mimetype=mimetype)
            if attachment:r.headers['Content-Disposition']='attachment; filename=report.html'
            return apply_owner_workspace(r,request,owner).get_data(as_text=True)
    def test_direct_calendar_has_persistent_navigation_and_preserves_query(self):
        html=self.render('/calendar?month=2026-10&student=Joanna+Zhao')
        self.assertIn('name="hmusic-workspace"',html)
        self.assertIn('month=2026-10&amp;student=Joanna+Zhao&amp;_workspace=1',html)
        self.assertIn('data-section="/calendar"',html)
    def test_frame_does_not_nest_shell_and_keeps_form(self):
        html=self.render('/calendar?_workspace=1',{'Sec-Fetch-Dest':'iframe'})
        self.assertNotIn('<iframe',html)
        self.assertIn('value="safe"',html)
        self.assertIn('hmusic-workspace',html)
    def test_native_iframe_navigation_does_not_add_another_shell(self):
        self.assertNotIn('<iframe',self.render('/invoices?status=unpaid',{'Sec-Fetch-Dest':'iframe'}))
        self.assertIn('<iframe',self.render('/calendar',{'Sec-Fetch-Dest':'empty'}))
    def test_proxy_frame_navigation_with_workspace_referrer(self):
        html=self.render('/invoices?status=paid',{'Sec-Fetch-Dest':'empty','Referer':'http://localhost/invoices?_workspace=1'})
        self.assertNotIn('<iframe',html)
        self.assertIn('hmusic-workspace',html)
        self.assertIn('<iframe',self.render('/invoices',{'Referer':'https://external.example/?_workspace=1'}))
    def test_native_iframe_post_redirect_without_flag(self):
        with self.app.test_request_context('/invoice/1',method='POST',headers={'Sec-Fetch-Dest':'iframe'}):
            result=apply_owner_workspace(Response(status=302,headers={'Location':'/invoices'}),request,True)
            self.assertEqual(result.headers['Location'],'/invoices?_workspace=1')
    def test_frame_post_redirect_preserves_workspace(self):
        with self.app.test_request_context('/edit_schedule/1?_workspace=1',method='POST'):
            r=Response(status=302,headers={'Location':'/calendar?month=2026-10'})
            result=apply_owner_workspace(r,request,True)
            self.assertEqual(result.headers['Location'],'/calendar?month=2026-10&_workspace=1')
    def test_initial_frame_flag_and_overview(self):
        html=self.render('/?_workspace=1')
        self.assertNotIn('<iframe',html)
        self.assertIn('margin-left:0',html)
    def test_nonowner_and_api_fragments_untouched(self):
        self.assertNotIn('<iframe',self.render(owner=False))
        self.assertNotIn('<iframe',self.render(headers={'Sec-Fetch-Dest':'empty','Accept':'application/json'}))
        self.assertEqual(self.render(body='<div>fragment</div>'),'<div>fragment</div>')
        self.assertEqual(self.render(body='{"ok":true}',mimetype='application/json'),' {"ok":true}'.strip())
    def test_auth_print_download_and_errors_untouched(self):
        for path in ['/owner_login','/print_invoice/1','/export_students','/download']:
            self.assertNotIn('<iframe',self.render(path))
        self.assertNotIn('<iframe',self.render(attachment=True))
        self.assertNotIn('<iframe',self.render(status=403))

if __name__=='__main__':unittest.main()
