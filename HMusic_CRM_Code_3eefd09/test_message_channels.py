from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from flask import Flask
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest
import message_channels as channels


class MessageChannelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'test.db')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''CREATE TABLE parent_profiles(id,email,phone,active);
                INSERT INTO parent_profiles VALUES(1,'parent@school.test','+16505550100',1);
                CREATE TABLE teachers(teacher_name,email,phone,active);
                INSERT INTO teachers VALUES('Teacher One','teacher@school.test','+16505550101',1);
                CREATE TABLE messages(id,thread_id,sender_role);
                INSERT INTO messages VALUES(10,20,'owner');
                CREATE TABLE notification_delivery_queue(id INTEGER PRIMARY KEY,channel,status,related_type,related_id,user_role);
                INSERT INTO notification_delivery_queue VALUES(1,'email','sent','message',10,'parent');''');db.commit()
        self.calls=[];self.queued=[];self.sms_ready=True;self.email_ready=True;self.suppressed=False
        self.api=dict(sqlite3=SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),
            smtp_config_status=lambda:(self.email_ready,[]),sms_config_status=lambda:(self.sms_ready,[]),
            hmusic_is_real_email=lambda x:bool(x and '@' in x),hmusic_normalize_sms_phone=lambda x:x if x and x.startswith('+1') else None,
            hmusic_is_email_suppressed=lambda *a:self.suppressed,ensure_v33_schema=lambda:None)
        self.api['queue_notification_delivery']=self.queue
        self.api['send_queued_email_now']=lambda q:self.calls.append(('email',q))
        self.api['send_queued_sms_now']=lambda q:self.calls.append(('sms',q))
        self.app=Flask(__name__)

    def queue(self,*args,**kwargs):
        self.queued.append((args,kwargs));return len(self.queued)

    def choose(self,values,explicit=True):
        form=MultiDict([('delivery_channels',v) for v in values])
        if explicit:form['delivery_selection']='1'
        return channels.selected_channels(form)

    def deliver(self,selected):
        channels.deliver(self.api,'parent','1','New message','Body','/message_thread/20','message',10,selected)

    def test_email_sms_both_and_in_app_only(self):
        for selected in (['email'],['sms'],['email','sms'],[]):
            self.calls.clear();self.queued.clear();self.deliver(selected)
            self.assertEqual([x[0] for x in self.calls],selected)
            self.assertEqual([x[0][5] for x in self.queued],selected)

    def test_choices_default_legacy_and_unknown_channel(self):
        self.assertIsNone(self.choose(['sms'],explicit=False))
        self.assertEqual(self.choose(['sms','email','sms']),['email','sms'])
        self.assertEqual(self.choose([]),[])
        with self.assertRaises(BadRequest):self.choose(['push'])

    def test_validate_missing_contact_configuration_inactive_and_suppression(self):
        channels.validate(self.api,'parent',1,['email','sms'])
        channels.validate(self.api,'teacher','Teacher One',['sms'])
        self.sms_ready=False
        with self.assertRaises(BadRequest):channels.validate(self.api,'parent',1,['sms'])
        channels.validate(self.api,'parent',1,['email'])
        self.sms_ready=True;self.suppressed=True
        with self.assertRaises(BadRequest):channels.validate(self.api,'parent',1,['email'])
        channels.validate(self.api,'parent',1,['sms'])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE parent_profiles SET phone='',active=1");db.commit()
        with self.assertRaises(BadRequest):channels.validate(self.api,'parent',1,['sms'])
        with self.assertRaises(BadRequest):channels.validate(self.api,'parent',999,['email'])
        self.assertEqual(self.calls,[])

    def test_controls_and_provider_acceptance_not_delivered(self):
        html=channels.controls(self.api)
        self.assertIn('value="email" checked',html)
        self.assertIn('Mobile SMS',html)
        self.assertNotIn('value="sms" checked',html)
        self.sms_ready=False
        self.assertIn('value="sms" disabled',channels.controls(self.api))
        summary=channels.summary(self.api,20)
        self.assertIn('Email: Accepted by provider',summary)
        self.assertIn('does not confirm',summary)
        self.assertNotIn('Delivered',summary)

    def test_notification_still_saved_when_no_external_channels(self):
        # Exercise the actual notification function, retaining its persistence path.
        from test_message_email_delivery import DeliveryTests
        case=DeliveryTests('test_new_messages_send_and_repeated_notification_does_not_resend');case.setUp()
        self.addCleanup(case.tearDown)
        case.ns['deliver_message_channels']=channels.deliver
        case.ns['send_queued_sms_now']=lambda q: self.calls.append(('sms',q))
        notify=case.ns['create_notification']
        notify('parent','1','New message','App only','/message_thread/20',related_type='message',related_id=10,delivery_channels=[])
        self.assertEqual(case.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
        self.assertEqual(case.db.execute('SELECT COUNT(*) FROM notification_delivery_queue').fetchone()[0],0)
        notify('parent','1','New message','SMS only','/message_thread/21',related_type='message',related_id=11,delivery_channels=['sms'])
        self.assertEqual(case.db.execute('SELECT channel FROM notification_delivery_queue').fetchall(),[('sms',)])
        self.assertEqual(case.sent,[])
        self.assertEqual(len(self.calls),1)
        notify('parent','1','New message','SMS only','/message_thread/21',related_type='message',related_id=11,delivery_channels=['sms'])
        self.assertEqual(len(self.calls),1)

    def test_sms_preview_is_short_but_email_preserves_full_content(self):
        body='Long message '*200
        channels.deliver(self.api,'parent','1','New message',body,'/message_thread/20','message',10,['email','sms'])
        self.assertEqual(self.queued[0][0][3],body)
        self.assertLess(len(self.queued[1][0][3]),705)
        self.assertEqual(self.queued[1][0][4],'/message_thread/20')


if __name__=='__main__':unittest.main()
