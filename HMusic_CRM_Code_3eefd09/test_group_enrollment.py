import io
import ast
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from flask import Flask, session
import group_enrollment as ge

APP_PATH = Path(__file__).with_name('app.py')


class GroupEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db')
        self.conn=sqlite3.connect(self.path);c=self.conn.cursor()
        c.executescript('''
        CREATE TABLE students(id INTEGER PRIMARY KEY,name TEXT UNIQUE,teacher TEXT,parent_name TEXT,parent_email TEXT,parent_phone TEXT,lessons_left REAL DEFAULT 0);
        CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name TEXT,email TEXT,phone TEXT,password TEXT,password_hash TEXT,must_change_password INTEGER,active INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE parent_students(id INTEGER PRIMARY KEY,parent_id INTEGER,student_name TEXT,relationship TEXT,active INTEGER,created_at TEXT);
        CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name TEXT,lesson_date TEXT,lesson_time TEXT,duration INTEGER,teacher TEXT,classroom TEXT,location TEXT,course_type_id INTEGER,course_type_name TEXT,status TEXT,is_group INTEGER,group_name TEXT,group_student_names TEXT,group_size INTEGER,owner_calendar_updated_at TEXT);
        CREATE TABLE group_schedule_students(id INTEGER PRIMARY KEY,schedule_id INTEGER,student_name TEXT,parent_name TEXT,credit_units REAL,student_rate REAL,billing_rule TEXT,billing_status TEXT,attendance_status TEXT,attendance_credit_applied REAL,attendance_enrollment_id INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE enrollments(id INTEGER PRIMARY KEY,student_name TEXT,course_type_id INTEGER,course_type_name TEXT,teacher_name TEXT,duration INTEGER,student_billing_method TEXT,base_price REAL,final_price REAL,lessons_left REAL,status TEXT,notes TEXT,package_amount REAL,package_lessons REAL,auto_renew_enabled INTEGER,start_date TEXT,created_at TEXT,updated_at TEXT,auto_renew_lessons REAL);
        CREATE TABLE invoices(id INTEGER PRIMARY KEY,student_name TEXT,schedule_id INTEGER,charge_lessons REAL,amount REAL,status TEXT,invoice_type TEXT,created_at TEXT,enrollment_id INTEGER,due_date TEXT,notes TEXT,credits_applied INTEGER,coverage_title TEXT,coverage_class TEXT,coverage_start TEXT,coverage_note TEXT);
        CREATE TABLE inquiries(id INTEGER PRIMARY KEY,student_name TEXT,parent_name TEXT,parent_email TEXT,phone TEXT,age TEXT,program_interest TEXT,source TEXT,status TEXT,trial_status TEXT,follow_up_status TEXT,notes TEXT,created_at TEXT,updated_at TEXT,converted_student_name TEXT,converted_enrollment_id INTEGER);
        INSERT INTO schedule(id,student_name,lesson_date,lesson_time,duration,teacher,classroom,course_type_id,course_type_name,status,is_group,group_name) VALUES
        (1,'Existing','2099-11-01','10:00',45,'Teacher One','Room 1',2,'Group Class','scheduled',1,'Beginner'),
        (2,'Existing','2099-11-08','10:00',45,'Teacher One','Room 1',2,'Group Class','scheduled',1,'Beginner'),
        (3,'Private','2099-11-15','10:00',45,'Teacher One','Room 1',3,'Private','scheduled',0,'');
        ''')
        ge.ensure_schema(self.conn)
        source=ast.parse(APP_PATH.read_text());node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='create_enrollment_invoice')
        from datetime import date,datetime
        scope={'date':date,'datetime':datetime};exec(compile(ast.Module(body=[node],type_ignores=[]),'invoice','exec'),scope)
        self.api={'sqlite3':SimpleNamespace(connect=lambda _:sqlite3.connect(self.path)),
                  'require_owner':lambda:session.get('user_role')=='owner',
                  'hmusic_password_hash':lambda p:'hashed:'+p,
                  'create_enrollment_invoice':scope['create_enrollment_invoice']}
        self.app=Flask(__name__);self.app.secret_key='test-secret';self.app.testing=True
        @self.app.post('/convert_inquiry_to_student/<int:inquiry_id>')
        def convert_inquiry_to_student(inquiry_id):return 'legacy conversion'
        ge.register_group_enrollment(self.app,self.api);self.client=self.app.test_client()
        self.owner=True
        with self.client.session_transaction() as s:s['user_role']='owner'
        self.create_class()

    def tearDown(self):self.conn.close();self.tmp.cleanup()
    def scalar(self,q,args=()):return self.conn.execute(q,args).fetchone()[0]
    def create_class(self,**kw):
        return self.client.post('/group-class-admin',data={'title':'Piano Group','policy':'No automatic refunds.','capacity':'2','tuition':'500','schedule_ids':['1','2'],**kw})
    def publish(self):return self.client.post('/group-class-admin',data={'action':'visibility','id':1,'published':'1'})
    def apply(self,name='Child',email='p@example.test',**kw):
        self.publish();r=self.client.get('/group-classes/1/apply')
        with self.client.session_transaction() as s:key=s['group_request_key']
        return self.client.post('/group-classes/1/apply',data={'request_key':key,'student_name':name,'birth_date':'2020-01-01','parent_name':'Parent','email':email,'phone':'6507977125','policy_ack':'yes',**kw})
    def approve(self,aid=1,choice='new'):
        return self.client.post('/group-enrollments',data={'id':aid,'action':'approve','student_id':choice})
    def confirm(self,aid=1):return self.client.post('/group-enrollments',data={'id':aid,'action':'confirm'})
    def paid(self,aid=1):
        invoice=self.scalar('SELECT invoice_id FROM group_applications WHERE id=?',(aid,))
        self.conn.execute("UPDATE invoices SET status='paid' WHERE id=?",(invoice,));self.conn.commit()

    def image_upload(self, data=None, filename='class.png'):
        if data is None:
            from PIL import Image
            out=io.BytesIO();Image.new('RGB',(80,40),'purple').save(out,format='PNG');data=out.getvalue()
        return self.client.post('/group-class-admin',data={'action':'image','id':'1','class_image':(io.BytesIO(data),filename)},content_type='multipart/form-data')

    def test_image_upload_draft_privacy_and_public_preview(self):
        self.assertEqual(self.image_upload().status_code,303)
        preview=self.client.get('/group-classes/1/apply?preview=1')
        self.assertIn(b'/group-class-image/1',preview.data)
        image=self.client.get('/group-class-image/1')
        self.assertEqual(image.mimetype,'image/jpeg')
        self.assertEqual(image.headers['X-Content-Type-Options'],'nosniff')
        with self.client.session_transaction() as ss:ss['user_role']=None
        self.assertEqual(self.client.get('/group-class-image/1').status_code,404)
        with self.client.session_transaction() as ss:ss['user_role']='owner'
        self.publish()
        with self.client.session_transaction() as ss:ss['user_role']=None
        self.assertEqual(self.client.get('/group-class-image/1').status_code,200)
        self.assertIn(b'/group-class-image/1',self.client.get('/group-classes').data)
        self.assertEqual(self.image_upload().status_code,403)

    def test_invalid_image_does_not_replace_saved_image_or_change_class(self):
        self.image_upload(); original=self.scalar('SELECT image_data FROM group_offering_images')
        self.assertIn(b'valid image',self.image_upload(b'<svg onload="alert(1)"></svg>','fake.png').data)
        self.assertEqual(self.scalar('SELECT image_data FROM group_offering_images'),original)
        self.assertIn(b'exceeds 4 MB',self.image_upload(b'x'*(4*1024*1024+1)).data)
        self.assertEqual(self.scalar('SELECT tuition_cents FROM group_offerings'),50000)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),0)

    def test_planning_draft_can_be_completed_before_publication(self):
        r=self.create_class(title='Planning',schedule_ids=[])
        self.assertEqual(r.status_code,303)
        blocked=self.client.post('/group-class-admin',data={'action':'visibility','id':2,'published':'1'})
        self.assertIn(b'cancelled',blocked.data)
        self.conn.execute('DELETE FROM group_offering_sessions WHERE offering_id=1');self.conn.commit()
        r=self.create_class(offering_id=2,title='Completed')
        self.assertEqual(r.status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offerings'),2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions WHERE offering_id=2'),2)

    def test_rotating_teachers_keep_real_session_teacher(self):
        self.conn.execute("UPDATE schedule SET teacher='Teacher Two' WHERE id=2");self.conn.commit()
        self.apply();self.approve();self.paid();self.confirm()
        self.assertEqual(self.scalar('SELECT teacher FROM schedule WHERE id=2'),'Teacher Two')
        self.assertIn('Teacher Two',self.scalar('SELECT coverage_note FROM invoices'))

    def test_draft_is_private_and_publish_displays_calendar_dates(self):
        self.assertEqual(self.client.get('/group-classes/1/apply').status_code,404)
        self.assertNotIn(b'Piano Group',self.client.get('/group-classes').data)
        self.assertIn(b'Manager draft preview',self.client.get('/group-classes/1/apply?preview=1').data)
        with self.client.session_transaction() as ss:ss['user_role']=None
        self.assertEqual(self.client.get('/group-classes/1/apply?preview=1').status_code,404)
        with self.client.session_transaction() as ss:ss['user_role']='owner'
        self.publish();r=self.client.get('/group-classes/1/apply');self.assertIn(b'2099-11-08',r.data);self.assertIn(b'$500.00',r.data)
    def test_submission_enters_intake_without_students_wallet_or_invoice(self):
        r=self.apply();self.assertEqual(r.status_code,303)
        for table in ('students','enrollments','invoices','group_schedule_students'):self.assertEqual(self.scalar('SELECT COUNT(*) FROM '+table),0)
        self.assertEqual(self.scalar('SELECT source FROM inquiries'),'Website Group Enrollment')
        self.assertIn(b'Application received',self.client.get(r.location).data)
    def test_retry_same_form_is_idempotent_and_other_form_detects_duplicate(self):
        r=self.apply()
        with self.client.session_transaction() as s:key=s['group_request_key']
        payload={'request_key':key,'student_name':'Child','birth_date':'2020-01-01','parent_name':'Parent','email':'p@example.test','phone':'6507977125','policy_ack':'yes'}
        again=self.client.post('/group-classes/1/apply',data=payload)
        self.assertEqual(again.location,r.location);self.assertEqual(self.scalar('SELECT COUNT(*) FROM inquiries'),1)
        self.assertIn(b'already exists',self.apply().data);self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_applications'),1)
    def test_approval_reserves_seat_and_real_invoice_does_not_grant_credit(self):
        self.apply();self.assertEqual(self.approve().status_code,303)
        self.assertEqual(self.scalar('SELECT lessons_left FROM enrollments'),0)
        self.assertEqual(self.scalar('SELECT credits_applied FROM invoices'),0)
        self.assertEqual(self.scalar('SELECT amount FROM invoices'),500)
        self.assertEqual(self.scalar('SELECT charge_lessons FROM invoices'),2)
        self.assertIn('2099-11-08',self.scalar('SELECT coverage_note FROM invoices'))
        self.assertEqual(self.scalar('SELECT status FROM group_applications'),'reserved')
        self.approve();self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)
    def test_unpaid_and_processing_cannot_enter_roster(self):
        self.apply();self.approve()
        for state in ('unpaid','processing','failed'):
            self.conn.execute('UPDATE invoices SET status=?',(state,));self.conn.commit()
            self.assertIn(b'only after',self.confirm().data);self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_schedule_students'),0)
    def test_paid_confirm_links_every_session_once_and_pins_wallet(self):
        self.apply();self.approve();self.paid();self.confirm();self.confirm()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_schedule_students'),2)
        self.assertEqual(self.scalar('SELECT attendance_enrollment_id FROM group_schedule_students LIMIT 1'),self.scalar('SELECT id FROM enrollments'))
        self.assertEqual(self.scalar('SELECT status FROM group_applications'),'enrolled')
        self.assertEqual(self.scalar('SELECT status FROM enrollments'),'active')
        self.assertEqual(self.scalar('SELECT lessons_left FROM enrollments'),0) # Admission itself cannot grant credits again.
        self.assertEqual(self.scalar('SELECT converted_enrollment_id FROM inquiries'),1)
    def test_full_class_uses_waitlist_and_prevents_overbooking(self):
        self.apply();self.approve();self.apply('Second');self.approve(2)
        self.apply('Third');self.assertEqual(self.scalar('SELECT status FROM group_applications WHERE id=3'),'waitlist')
        self.assertIn(b'full',self.approve(3).data);self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),2)
    def test_expired_unpaid_hold_releases_but_paid_hold_does_not(self):
        self.apply();self.approve();self.conn.execute("UPDATE group_applications SET reserved_until='2000-01-01'");self.conn.commit()
        self.assertEqual(ge.occupied(self.conn.cursor(),1),0)
        self.conn.execute("UPDATE invoices SET status='payment_processing'");self.conn.commit()
        self.assertEqual(ge.occupied(self.conn.cursor(),1),1)
        self.paid();self.assertEqual(ge.occupied(self.conn.cursor(),1),1)
    def test_existing_student_requires_explicit_profile_and_preserves_account(self):
        self.conn.execute("INSERT INTO students(id,name,teacher,lessons_left) VALUES(5,'Child','Original',9)")
        self.conn.execute("INSERT INTO parent_profiles(id,email,password_hash,parent_name) VALUES(7,'p@example.test','old-hash','Existing Parent')");self.conn.commit()
        self.apply();self.assertIn(b'name exists',self.approve().data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.approve(choice='5');self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)
        self.assertEqual(self.scalar('SELECT teacher FROM students'),'Original');self.assertEqual(self.scalar('SELECT lessons_left FROM students'),9)
        self.assertEqual(self.scalar('SELECT password_hash FROM parent_profiles'),'old-hash')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM parent_students'),1)
    def test_calendar_cancellation_stays_visible_and_blocks_admission(self):
        self.apply();self.approve();self.paid();self.conn.execute("UPDATE schedule SET status='teacher_cancelled' WHERE id=2");self.conn.commit()
        self.assertIn(b'cancelled',self.confirm().data);self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_schedule_students'),0)
    def test_mixed_or_private_sessions_are_rejected_without_partial_class(self):
        self.assertIn(b'upcoming',self.create_class(schedule_ids=['3']).data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offerings'),1)
    def test_duplicate_session_class_fails_without_partial_rows(self):
        self.assertIn(b'already belongs',self.create_class().data);self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offerings'),1)
    def test_manager_routes_reject_anonymous_and_teacher(self):
        for role in (None,'teacher','parent'):
            with self.client.session_transaction() as s:s['user_role']=role
            for path in ('/group-class-admin','/group-enrollments'):
                self.assertEqual(self.client.get(path).status_code,403);self.assertEqual(self.client.post(path,data={'action':'approve','id':1}).status_code,403)
    def test_private_receipt_does_not_expose_another_application(self):
        r=self.apply();self.assertEqual(self.client.get('/group-registration/'+'a'*64).status_code,404)
        self.assertEqual(self.client.get('/group-registration/1').status_code,404)
        self.assertEqual(self.client.get(r.location).headers['Referrer-Policy'],'no-referrer')
    def test_invalid_contact_date_policy_or_honeypot_not_saved(self):
        for override in ({'email':'bad'},{'birth_date':'2100-01-01'},{'policy_ack':''},{'website':'spam'},{'phone':'1'},{'student_name':'A\nB'}):
            self.assertEqual(self.apply(**({'name':override.pop('student_name')} if 'student_name' in override else {}),**override).status_code,200)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_applications'),0)
    def test_close_uninvoiced_application_and_no_automatic_paid_cancellation(self):
        self.apply();self.client.post('/group-enrollments',data={'id':1,'action':'cancel'})
        self.assertEqual(self.scalar('SELECT status FROM group_applications'),'cancelled')
        self.apply();self.approve(2);self.paid(2)
        self.assertIn(b'linked invoice',self.client.post('/group-enrollments',data={'id':2,'action':'cancel'}).data)
    def test_final_seat_serializes_concurrent_approvals(self):
        from concurrent.futures import ThreadPoolExecutor
        self.apply('First');self.apply('Second','second@example.test')
        self.conn.execute('UPDATE group_offerings SET capacity=1');self.conn.commit()
        def admit(aid):
            conn=sqlite3.connect(self.path,timeout=10)
            try:
                conn.execute('BEGIN IMMEDIATE')
                ge.approve(conn.cursor(),aid,'new',self.api);conn.commit();return 'approved'
            except ValueError:
                conn.rollback();return 'full'
            finally:conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(admit,[1,2]))
        self.assertEqual(sorted(result),['approved','full'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)

    def test_deleted_calendar_session_blocks_publication_and_admission(self):
        self.apply();self.approve();self.paid()
        self.conn.execute('DELETE FROM schedule WHERE id=2');self.conn.commit()
        self.assertIn(b'cancelled',self.confirm().data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_schedule_students'),0)
        self.assertNotIn(b'Piano Group',self.client.get('/group-classes').data)

    def test_legacy_intake_conversion_redirects_to_group_review(self):
        self.apply()
        r=self.client.post('/convert_inquiry_to_student/1')
        self.assertEqual(r.status_code,303)
        self.assertIn('/group-enrollments#application-1',r.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),0)
        self.assertEqual(self.client.post('/convert_inquiry_to_student/999').get_data(as_text=True),'legacy conversion')

    def test_legacy_calendar_roster_is_counted_and_preserved(self):
        self.conn.execute("INSERT INTO students(id,name,parent_name) VALUES(5,'Existing','Existing Parent')")
        self.conn.execute("UPDATE schedule SET group_student_names='Existing' WHERE id IN (1,2)")
        self.conn.commit()
        self.assertEqual(ge.occupied(self.conn.cursor(),1),1)
        self.apply();self.approve();self.paid();self.confirm()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_schedule_students'),4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM group_schedule_students WHERE student_name='Existing'"),2)
        self.assertIn('Existing',self.scalar('SELECT group_student_names FROM schedule WHERE id=1'))

    def test_no_show_and_cancelled_future_sessions_cannot_be_published(self):
        for status in ('excused_24h','last_min_cancel','no_show','parent_cancel_pending_confirm'):
            self.conn.execute('UPDATE schedule SET status=? WHERE id=2',(status,));self.conn.commit()
            self.assertIn(b'cancelled',self.publish().data)
            self.assertEqual(self.scalar('SELECT published FROM group_offerings'),0)

    def test_same_existing_child_cannot_receive_two_group_invoices(self):
        self.apply('Child');self.approve()
        self.apply('Different spelling','another@example.test')
        sid=self.scalar('SELECT id FROM students')
        self.assertIn(b'already has an approved',self.approve(2,str(sid)).data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)

    def test_template_escapes_public_names(self):
        r=self.apply('<script>alert(1)</script>');receipt=self.client.get(r.location)
        self.assertNotIn(b'<script>alert(1)</script>',receipt.data)
        self.assertIn(b'&lt;script&gt;',receipt.data)

if __name__=='__main__':unittest.main()
