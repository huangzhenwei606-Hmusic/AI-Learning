import os,sqlite3,tempfile,unittest
from unittest.mock import Mock,patch
from communication_tracking import Tracker,ensure,add,match_family,phone
class CommunicationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/db';self.connect=lambda:sqlite3.connect(self.path)
  c=self.connect();c.executescript("CREATE TABLE parent_profiles(id INTEGER,email TEXT,phone TEXT,active INTEGER);INSERT INTO parent_profiles VALUES(1,'p@example.com','650-555-0001',1);CREATE TABLE inquiries(id INTEGER,parent_email TEXT,phone TEXT);INSERT INTO inquiries VALUES(1,'lead@example.com','6505550002');");ensure(c);c.close();self.tracker=Tracker(self.connect,{'logger':Mock()})
 def tearDown(self):self.tmp.cleanup()
 def item(self,**kw):
  d=dict(source='email',source_id='one',direction='inbound',contact='p@example.com',subject='Trial lesson',body='Can we schedule a trial?',received_at='2026-11-07T16:00:00+00:00',conversation_key='root');d.update(kw);return d
 def test_dedup_and_unverified_identity(self):
  c=self.connect();add(c,self.item());add(c,self.item());c.commit();self.assertEqual(c.execute('SELECT count(*) FROM studio_communications').fetchone()[0],1);self.assertEqual(match_family(c,'p@example.com','email',False)[1],'待核实身份');c.close()
 def test_ambiguous_family(self):
  c=self.connect();c.execute("INSERT INTO parent_profiles VALUES(2,'p@example.com','650-555-0001',1)");self.assertEqual(match_family(c,'p@example.com','email')[1],'多个匹配，待核对');self.assertEqual(phone('(650) 555-0001'),'16505550001');c.close()
 def test_phone_matching(self):
  c=self.connect();self.assertEqual(match_family(c,'16505550001','crm_sms')[0],['parent:1']);self.assertEqual(match_family(c,'16505550002','crm_sms')[0],['inquiry:1']);self.assertEqual(match_family(c,'unknown','email')[1],'未匹配');c.close()
 def test_reply_after_day_resolves_wait(self):
  c=self.connect();add(c,self.item(received_at='2026-11-06T18:00:00+00:00'));add(c,self.item(source_id='two',direction='outbound',received_at='2026-11-07T16:00:00+00:00'));c.commit();r=self.tracker.report(c,'2026-11-06');self.assertEqual(r['message_count'],1);self.assertEqual(r['needs_review_count'],0);self.assertEqual(r['waiting_for_reply_count'],1);c.close()
 def test_failed_send_not_waiting_for_parent(self):
  c=self.connect();add(c,self.item(direction='outbound',provider_state='failed'));c.commit();self.assertEqual(self.tracker.report(c,'2026-11-07')['waiting_for_reply_count'],0);c.close()
 def test_twilio_path_scope(self):
  with patch.dict(os.environ,{'TWILIO_ACCOUNT_SID':'AC'+'1'*32,'TWILIO_AUTH_TOKEN':'test'}):
   for path in ['https://evil.example/','/2010-04-01/Accounts/AC'+'2'*32+'/Messages.json']:
    with self.assertRaises(ValueError):self.tracker.twilio_get(path)
 def test_failed_source_visible(self):
  self.tracker.email=Mock(side_effect=RuntimeError('private credential'));self.tracker.sms=Mock(return_value={'imported_or_checked':0})
  with patch.dict(os.environ,{'HMUSIC_COMMUNICATIONS_ENABLED':'1'}):self.tracker.sync(force=True)
  r=self.tracker.overview('2026-11-07');s={x['source']:x['state'] for x in r['sources']};self.assertEqual(s['email']['status'],'error');self.assertNotIn('private credential',str(s));self.assertEqual(s['crm_sms']['status'],'ok')
 def test_imap_is_readonly_and_checkpoint_prevents_duplicate_fetch(self):
  raw=b'From: Parent <p@example.com>\r\nTo: info@h-musicandarts.com\r\nDate: Sat, 07 Nov 2026 08:00:00 -0800\r\nMessage-ID: <mail-one@example.com>\r\nSubject: Trial\r\nAuthentication-Results: mx.google.com; dmarc=pass\r\n\r\nTrial please.'
  client=Mock();client.list.return_value=('OK',[]);client.select.return_value=('OK',[]);client.response.return_value=('UIDVALIDITY',[b'1'])
  def uid(command,*args):return ('OK',[b'1']) if command=='search' else ('OK',[(b'1',raw)])
  client.uid.side_effect=uid
  config={'host':'imap.gmail.com','port':993,'user':'info@h-musicandarts.com','password':'test','folder':'INBOX'}
  with patch('communication_tracking.mailbox_config',return_value=config),patch('communication_tracking.imaplib.IMAP4_SSL',return_value=client):
   self.tracker.email();self.tracker.email()
  self.assertTrue(client.select.call_args.kwargs['readonly']);self.assertEqual(sum(x.args[0]=='fetch' for x in client.uid.call_args_list),1);self.assertEqual(client.uid.call_args_list[1].args[-1],'(BODY.PEEK[])')
  c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM studio_communications').fetchone()[0],1);c.close()
 def test_sms_only_imports_configured_number_and_preserves_direction(self):
  msg={'sid':'SM1','direction':'inbound','from':'+16505550001','to':'+16505559999','date_created':'Sat, 07 Nov 2026 16:00:00 +0000','body':'Trial please','status':'received'}
  self.tracker.twilio_get=Mock(side_effect=[{'messages':[msg,{**msg,'sid':'SM2','to':'+16505558888'}]},{'messages':[{**msg,'sid':'SM3','direction':'outbound-api','from':'+16505559999','to':'+16505550001','status':'delivered'}]}])
  with patch.dict(os.environ,{'TWILIO_FROM_NUMBER':'+16505559999','TWILIO_ACCOUNT_SID':'AC'+'1'*32}):self.tracker.sms()
  c=self.connect();self.assertEqual(c.execute('SELECT count(*) FROM studio_communications').fetchone()[0],2);self.assertEqual(c.execute("SELECT direction FROM studio_communications WHERE source_id='SM3'").fetchone()[0],'outbound');c.close()
 def test_newest_mail_precedes_history_and_all_mail_excludes_drafts(self):
  client=Mock();client.list.return_value=('OK',[b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']);client.select.return_value=('OK',[]);client.response.return_value=('UIDVALIDITY',[b'1']);fetched=[]
  def uid(command,*args):
   if command=='search':return ('OK',[b'1 2 3'])
   fetched.append(int(args[0]));raw=('From: p@example.com\r\nTo: info@h-musicandarts.com\r\nMessage-ID: <'+str(args[0])+'@example.com>\r\nSubject: Trial\r\n\r\nTrial please.').encode();return ('OK',[(b'uid',raw)])
  client.uid.side_effect=uid;config={'host':'imap.gmail.com','port':993,'user':'info@h-musicandarts.com','password':'test','folder':'INBOX'}
  with patch('communication_tracking.mailbox_config',return_value=config),patch('communication_tracking.imaplib.IMAP4_SSL',return_value=client):self.tracker.email()
  self.assertEqual(fetched,[3,2,1]);self.assertIn('X-GM-RAW',client.uid.call_args_list[0].args);self.assertIn('-in:drafts',client.uid.call_args_list[0].args[-1])
 def test_new_sms_checked_even_while_history_is_pending(self):
  from communication_tracking import save_state
  from datetime import datetime,timedelta,timezone
  sid='AC'+'1'*32;old='/2010-04-01/Accounts/'+sid+'/Messages.json?Page=old';window=(datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat();c=self.connect();save_state(c,'sms:inbound',{'next_page':old,'window':window});c.close()
  msg={'sid':'SM-new','direction':'inbound','from':'+16505550001','to':'+16505559999','date_created':'Sat, 07 Nov 2026 16:00:00 +0000','body':'Trial please','status':'received'}
  self.tracker.twilio_get=Mock(side_effect=[{'messages':[msg]},{'messages':[{**msg,'sid':'SM-old'}]},{'messages':[]}])
  with patch.dict(os.environ,{'TWILIO_FROM_NUMBER':'+16505559999','TWILIO_ACCOUNT_SID':sid}):self.tracker.sms()
  self.assertNotEqual(self.tracker.twilio_get.call_args_list[0].args[0],old);self.assertEqual(self.tracker.twilio_get.call_args_list[1].args[0],old)
 def test_personal_phone_separate(self):
  r=self.tracker.overview('2026-11-07');self.assertFalse(r['personal_phone']['cloud_import']);self.assertEqual(r['report']['message_count'],0)
if __name__=='__main__':unittest.main()
