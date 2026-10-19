import os
import sqlite3
import tempfile
import unittest
from flask import Flask
from website_trial_api import register_website_trial_api, PATH, DESTINATION

class WebsiteTrialTests(unittest.TestCase):
    def setUp(self):
        f = tempfile.NamedTemporaryFile(delete=False); self.path = f.name; f.close()
        self.saved=[]; self.mail=[]; self.delivered=[]
        app=Flask(__name__); app.testing=True
        def save(data, public):
            self.saved.append(data.copy()); return 100+len(self.saved)
        def queue(*args, **kwargs):
            self.mail.append((args,kwargs)); return len(self.mail)
        self.services={'v35_insert_trial_lead':save,'queue_direct_delivery':queue,
                       'send_queued_email_now':lambda q:self.delivered.append(q)}
        register_website_trial_api(app,self.services,self.path)
        self.client=app.test_client();self.headers={'Origin':'https://www.hmusicandart.com'}
        self.payload=dict(parent='Test Parent',student='Test Student',email='parent@example.test',age='7',
                          program='Private instrument lessons',location='Foster City',notes='Piano, beginner. Saturday morning.',request_key='a'*32)
    def tearDown(self): os.unlink(self.path)
    def post(self, **updates): return self.client.post(PATH,json={**self.payload,**updates},headers=self.headers)
    def test_saved_and_fixed_recipient_and_fee(self):
        r=self.post(recipient='attacker@example.test',trial_fee='$1')
        self.assertEqual(r.status_code,201); self.assertEqual(r.json,{'ok':True,'request_id':101})
        self.assertEqual(self.saved[0]['trial_fee'],'$30');self.assertEqual(self.mail[0][0][1],DESTINATION)
        self.assertEqual(self.delivered,[1]);self.assertEqual(r.headers['Access-Control-Allow-Origin'],self.headers['Origin'])
    def test_duplicate_retry_is_one_lead_and_one_email(self):
        self.post();r=self.post();self.assertEqual(r.status_code,200);self.assertEqual(len(self.saved),1);self.assertEqual(len(self.mail),1)
    def test_preflight_and_disallowed_origins(self):
        r=self.client.options(PATH,headers=self.headers);self.assertEqual(r.status_code,204)
        for origin in ['https://evil.test','null','']:
            r=self.client.post(PATH,json=self.payload,headers={'Origin':origin});self.assertEqual(r.status_code,403);self.assertNotIn('Access-Control-Allow-Origin',r.headers)
        self.assertEqual(self.saved,[])
    def test_invalid_fields_honeypot_and_limits(self):
        for updates in [dict(email='bad'),dict(email='a@example.test\nBcc:x@example.test'),dict(age='nan'),dict(age='101'),dict(notes='x'*1501),dict(student=''),dict(student='A\nB'),dict(website='spam'),dict(request_key='short'),dict(program=['bad'])]:
            self.assertEqual(self.post(**updates).status_code,400,updates)
        self.assertEqual(self.saved,[])
    def test_non_json_and_oversized_request(self):
        self.assertEqual(self.client.post(PATH,data=self.payload,headers=self.headers).status_code,415)
        self.assertEqual(self.post(notes='x'*13000).status_code,413)
    def test_mail_failure_keeps_saved_lead_and_does_not_duplicate(self):
        def fail(q):raise RuntimeError('SMTP unavailable')
        self.services['send_queued_email_now']=fail
        self.assertEqual(self.post().status_code,201);self.assertEqual(self.post().status_code,200);self.assertEqual(len(self.saved),1)
    def test_failed_save_can_be_retried(self):
        def fail(*a,**k):raise RuntimeError('DB unavailable')
        old=self.services['v35_insert_trial_lead'];self.services['v35_insert_trial_lead']=fail
        self.assertEqual(self.post().status_code,503)
        self.services['v35_insert_trial_lead']=old;self.assertEqual(self.post().status_code,201)
    def test_rate_limit_and_different_family(self):
        for i in range(10):self.assertEqual(self.post(request_key=str(i)*32).status_code,201)
        self.assertEqual(self.post(request_key='z'*32).status_code,429)
        self.assertEqual(self.post(request_key='z'*32,email='other@example.test').status_code,201)

if __name__=='__main__':unittest.main()
