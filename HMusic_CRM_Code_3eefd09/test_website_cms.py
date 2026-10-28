import json
import sqlite3
import tempfile
import unittest
from flask import Flask, session
from website_cms import register_website_cms

class WebsiteCMSTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Flask(__name__); self.app.secret_key='test'
        register_website_cms(self.app,lambda:sqlite3.connect(self.temp.name+'/cms.db'),lambda:session.get('user_role')=='owner',lambda:'test-token')
        self.client=self.app.test_client()
    def tearDown(self):self.temp.cleanup()
    def owner(self):
        with self.client.session_transaction() as s:s['user_role']='owner'
    def test_owner_only(self):
        self.assertEqual(self.client.get('/website-admin').status_code,302)
        self.assertEqual(self.client.get('/api/website/admin').status_code,403)
        self.assertEqual(self.client.post('/api/website/admin',json={}).status_code,403)
    def test_draft_publish_hide_conflict(self):
        self.owner(); data=self.client.get('/api/website/admin').json
        original=self.client.get('/api/website/content').json
        data['pages'][0]['title']='Changed title'
        response=self.client.post('/api/website/admin',json=data)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/website/content').json,original)
        self.assertEqual(self.client.post('/api/website/admin',json=data).status_code,409)
        data['revision']=response.json['revision'];data['publish']=True;data['pages'][0]['hidden']=True
        self.assertEqual(self.client.post('/api/website/admin',json=data).status_code,200)
        self.assertNotIn(data['pages'][0]['id'],[p['id'] for p in self.client.get('/api/website/content').json])
    def test_invalid_payload(self):
        self.owner();data=self.client.get('/api/website/admin').json
        data['pages'][0]['images']=['javascript:alert(1)']
        self.assertEqual(self.client.post('/api/website/admin',json=data).status_code,400)
        data['pages'][0]['images']=[];data['pages'].append(data['pages'][0])
        self.assertEqual(self.client.post('/api/website/admin',json=data).status_code,400)
    def test_public_cors_and_editor(self):
        self.owner()
        self.assertIn(b'test-token',self.client.get('/website-admin').data)
        self.assertEqual(self.client.get('/api/website/content').headers['Access-Control-Allow-Origin'],'*')
if __name__=='__main__':unittest.main()
