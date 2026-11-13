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
        CREATE TABLE teachers(teacher_name TEXT,active INTEGER);
        INSERT INTO teachers VALUES ('Teacher One',1),('Teacher Two',1),('Inactive Teacher',0);
        CREATE TABLE course_types(id INTEGER,name TEXT,duration INTEGER,is_group INTEGER,active INTEGER);
        INSERT INTO course_types VALUES(2,'Group Class',45,1,1),(4,'Circle Piano',50,1,1),(3,'Private',30,0,1);
        CREATE TABLE studio_locations(id INTEGER,location_name TEXT,active INTEGER);
        INSERT INTO studio_locations VALUES(1,'Studio',1);
        CREATE TABLE studio_rooms(id INTEGER,room_name TEXT,location_id INTEGER,active INTEGER);
        INSERT INTO studio_rooms VALUES(1,'Group Room',1,1);
        CREATE TABLE students(id INTEGER PRIMARY KEY,name TEXT UNIQUE,teacher TEXT,parent_name TEXT,parent_email TEXT,parent_phone TEXT,lessons_left REAL DEFAULT 0);
        CREATE TABLE parent_profiles(id INTEGER PRIMARY KEY,parent_name TEXT,email TEXT,phone TEXT,password TEXT,password_hash TEXT,must_change_password INTEGER,active INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE parent_students(id INTEGER PRIMARY KEY,parent_id INTEGER,student_name TEXT,relationship TEXT,active INTEGER,created_at TEXT);
        CREATE TABLE schedule(id INTEGER PRIMARY KEY,student_name TEXT,lesson_date TEXT,lesson_time TEXT,duration INTEGER,teacher TEXT,classroom TEXT,location TEXT,course_type_id INTEGER,course_type_name TEXT,status TEXT,is_group INTEGER,group_name TEXT,group_student_names TEXT,group_size INTEGER,owner_calendar_updated_at TEXT,room_id INTEGER,location_id INTEGER,charge_lessons REAL,student_billing_method TEXT,student_price REAL,teacher_billing_method TEXT,teacher_pay REAL,student_charge_amount REAL,teacher_pay_amount REAL,schedule_type TEXT,notes TEXT);
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
                  'create_enrollment_invoice':scope['create_enrollment_invoice'],
                  'schedule_has_conflict':lambda *args,**kwargs:dict(has_conflict=False),
                  'get_final_pricing':lambda *args,**kwargs:dict(student_billing_method='Per Lesson',student_price=55,teacher_billing_method='Hourly',teacher_pay=60,student_charge_amount=55,teacher_pay_amount=50)}
        self.app=Flask(__name__);self.app.secret_key='test-secret';self.app.testing=True
        @self.app.post('/convert_inquiry_to_student/<int:inquiry_id>')
        def convert_inquiry_to_student(inquiry_id):return 'legacy conversion'
        ge.register_group_enrollment(self.app,self.api);self.client=self.app.test_client()
        self.owner=True
        with self.client.session_transaction() as s:s['user_role']='owner'
        self.create_class()

    def test_bulk_preview_no_writes_then_invoice_idempotent(self):
        self.apply()
        form={'application_ids':['1'],'bulk_action':'invoice','student_1':'new','full_amount':'500','deposit_amount':'100','scheme_1':'deposit','verified_1':'1','reference_1':'Zelle verified 11/12 ref abc','description':'Two 45-minute group lessons','message':'Hi {parent}, {student} is starting.'}
        preview=self.client.post('/group-enrollments/bulk-preview',data=form)
        self.assertEqual(preview.status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.assertIn(b'$400.00',self.client.get(preview.location).data)
        result=self.client.post(preview.location)
        self.assertEqual(result.status_code,303)
        self.assertEqual(self.scalar('SELECT amount FROM invoices'),400)
        self.assertEqual(self.scalar('SELECT charge_lessons FROM invoices'),2)
        self.assertEqual(self.scalar('SELECT lessons_left FROM enrollments'),0)
        self.client.post(preview.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)
    def test_bulk_deposit_requires_evidence(self):
        self.apply()
        result=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'invoice','student_1':'new','full_amount':'500','deposit_amount':'100','scheme_1':'deposit','description':'Lessons','message':'Hi'})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
    def test_bulk_convert_then_invoice_reuses_student(self):
        self.apply()
        result=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'convert','student_1':'new'})
        self.client.post(result.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.approve()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)
    def test_bulk_notification_saved_and_no_duplicate_send(self):
        self.apply()
        calls=[]
        self.api['hmusic_normalize_sms_phone']=lambda value:'+16507977125'
        self.api['hmusic_is_real_email']=lambda value:True
        self.api['queue_direct_delivery']=lambda *a,**kw:calls.append(a) or 10
        self.api['send_queued_email_now']=lambda q:(True,'Provider accepted')
        result=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'message','email':'1','message':'Hi {parent}, {student} starts soon.'})
        self.client.post(result.location);self.client.post(result.location)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.scalar('SELECT status FROM group_bulk_deliveries'),'submitted')
        self.assertIn(b'Provider accepted',self.client.get(result.location).data)
    def test_bulk_stale_preview_rejected(self):
        self.apply()
        result=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'convert','student_1':'new'})
        self.conn.execute("UPDATE group_applications SET email='changed@test.com'");self.conn.commit()
        self.client.post(result.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),0)

    def test_bulk_invoice_notice_has_individual_guest_link(self):
        self.apply()
        calls=[]
        self.api.update(hmusic_is_real_email=lambda v:True,group_payment_link=lambda cur,iid,pid,description:'https://school.example/p/individual',queue_direct_delivery=lambda *a,**kw:calls.append(a) or 11,send_queued_email_now=lambda q:(True,'Accepted'))
        r=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'invoice','student_1':'new','full_amount':'500','description':'Group term','message':'Hi {parent}','email':'1'})
        self.client.post(r.location)
        self.assertEqual(len(calls),1)
        self.assertIn('https://school.example/p/individual/invoice.pdf',calls[0][3])
        self.assertTrue(calls[0][3].endswith('Pay here:\nhttps://school.example/p/individual'))
    def test_bulk_unknown_send_is_not_retried(self):
        self.apply();calls=[]
        self.api.update(hmusic_is_real_email=lambda v:True,queue_direct_delivery=lambda *a,**kw:calls.append(a) or 12,send_queued_email_now=lambda q:(False,'Email outcome unknown; owner review required.'))
        r=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'message','email':'1','message':'Hello'})
        self.client.post(r.location);self.client.post(r.location)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.scalar('SELECT status FROM group_bulk_deliveries'),'unconfirmed')

    def test_existing_profile_same_guardian_reused(self):
        self.apply()
        self.conn.execute("INSERT INTO students(name,parent_email,lessons_left) VALUES('Child','p@example.test',7)");self.conn.commit()
        self.approve()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)
        self.assertEqual(self.scalar('SELECT lessons_left FROM students'),7)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),1)
    def test_existing_same_name_wrong_guardian_is_blocked(self):
        self.apply()
        self.conn.execute("INSERT INTO students(name,parent_email) VALUES('Child','other@example.test')");self.conn.commit()
        self.approve()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM parent_students'),0)
    def test_bulk_preview_reuses_existing_profile_label(self):
        self.apply()
        self.conn.execute("INSERT INTO students(name,parent_email) VALUES('Child','p@example.test')");self.conn.commit()
        r=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1'],'bulk_action':'convert','student_1':'new'})
        self.assertEqual(r.status_code,303)
        self.assertIn(b'Child (#1)',self.client.get(r.location).data)
        self.client.post(r.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),1)

    def test_bulk_restricted_guardian_does_not_block_other_families(self):
        self.apply(name='First',email='first@example.test');self.apply(name='Second',email='second@example.test')
        calls=[]
        def payment_link(cur,iid,pid,description):
            if iid==1:raise ValueError('Guardian cannot pay this invoice.')
            return 'https://school.example/p/second'
        self.api.update(hmusic_is_real_email=lambda v:True,group_payment_link=payment_link,queue_direct_delivery=lambda *a,**kw:calls.append(a) or 15,send_queued_email_now=lambda q:(True,'Accepted'))
        r=self.client.post('/group-enrollments/bulk-preview',data={'application_ids':['1','2'],'bulk_action':'invoice','student_1':'new','student_2':'new','full_amount':'500','description':'Group term','message':'Hello','email':'1'})
        self.client.post(r.location);self.client.post(r.location)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),2)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],'second@example.test')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM group_bulk_deliveries WHERE status='blocked'"),1)
        self.assertIn(b'Guardian cannot pay',self.client.get(r.location).data)

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

    def test_registration_center_separates_parent_links_and_drafts(self):
        self.publish();self.create_class(title='Vocal Draft',schedule_ids=[])
        page=self.client.get('/group-class-admin')
        self.assertIn(b'+ New Group Class',page.data)
        self.assertIn(b'/group-class-admin?new=1',page.data)
        self.assertIn(b'https://hmusic-crm.onrender.com/group-classes/1/apply',page.data)
        self.assertNotIn(b'https://hmusic-crm.onrender.com/group-classes/2/apply',page.data)
        self.assertIn(b'Vocal Draft',page.data)
        self.assertNotIn(b'Create a class offer',page.data)
        self.assertIn(b'Create a new group class',self.client.get('/group-class-admin?new=1').data)
        self.assertIn(b'Upload class image',self.client.get('/group-class-admin?class_id=1').data)

    def test_applications_are_filtered_to_selected_class(self):
        self.apply(name='Piano Child');self.create_class(title='Vocal',schedule_ids=[])
        self.conn.execute("""INSERT INTO group_applications(offering_id,student_name,birth_date,experience,parent_name,email,phone,status,request_key,receipt_hash,policy_snapshot,created_at,updated_at)
            SELECT 2,'Vocal Child',birth_date,experience,parent_name,email,phone,status,'vocal-key','vocal-hash',policy_snapshot,created_at,updated_at FROM group_applications WHERE id=1""");self.conn.commit()
        page=self.client.get('/group-enrollments?offering_id=1')
        self.assertIn(b'Piano Child',page.data);self.assertNotIn(b'Vocal Child',page.data)
        page=self.client.get('/group-enrollments?offering_id=2')
        self.assertIn(b'Vocal Child',page.data);self.assertNotIn(b'Piano Child',page.data)
        self.assertEqual(self.client.get('/group-enrollments?offering_id=999').status_code,404)
        self.assertEqual(self.client.get('/group-enrollments?offering_id=bad').status_code,400)
        center=self.client.get('/group-class-admin')
        self.assertIn(b'1 applications',center.data)
        self.assertIn(b'1 need review',center.data)

    def test_basic_information_editor_preserves_class_dates(self):
        page=self.client.get('/group-class-admin?edit=1')
        self.assertIn(b'Edit basic information',page.data)
        self.assertIn(b'name="schedule_ids" value="1"',page.data)
        result=self.create_class(offering_id=1,title='Renamed',policy='One make-up lesson included.')
        self.assertEqual(result.status_code,303)
        self.assertEqual(self.scalar('SELECT title FROM group_offerings'),'Renamed')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)

    def schedule_plan(self):
        return [dict(id=0,date='2099-12-05',time='11:10',teacher='Teacher One',room_id=1,course_id=4),
                dict(id=0,date='2099-12-12',time='12:10',teacher='Teacher Two',room_id=1,course_id=4)]

    def save_calendar(self,plan,version=None):
        import json
        if version is None:version=ge.schedule_version(ge.get_offering(self.conn.cursor(),1))
        return self.client.post('/group-class-admin/1/schedule',data={'sessions':json.dumps(plan),'version':version})

    def test_each_class_has_inline_curriculum_upload_and_save_keeps_class_terms(self):
        page=self.client.get('/group-class-admin?class_id=1')
        self.assertIn(b'Edit introduction &amp; upload curriculum images',page.data)
        self.assertIn(b'name="offering_id" value="1"',page.data)
        self.assertIn(b'name="image_0"',page.data)
        self.publish()
        result=self.client.post('/group-program-admin',data={'id':'1','offering_id':'1','name':'Circle Piano','summary':'Updated in class upload page','website_url':'https://www.hmusicandart.com/'})
        self.assertEqual(result.status_code,303)
        self.assertIn('class_id=1',result.location)
        self.assertEqual(self.scalar('SELECT program_id FROM group_offering_programs WHERE offering_id=1'),1)
        self.assertEqual(self.scalar('SELECT tuition_cents FROM group_offerings'),50000)
        self.assertEqual(self.scalar('SELECT capacity FROM group_offerings'),2)
        self.assertEqual(self.scalar('SELECT published FROM group_offerings'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)
        self.assertIn(b'Updated in class upload page',self.client.get('/group-classes/1/apply').data)

    def test_shared_curriculum_uses_live_class_facts_and_is_reusable(self):
        pid=self.scalar("SELECT id FROM group_programs WHERE name='Circle Piano'")
        self.assertEqual(self.create_class(offering_id='1',program_id=str(pid),description='OLD $999 99 students').status_code,303)
        self.assertEqual(self.scalar('SELECT program_id FROM group_offering_programs WHERE offering_id=1'),pid)
        page=self.client.get('/group-classes/1/apply?preview=1')
        self.assertIn(b'Learning materials',page.data)
        self.assertIn(b'Learn More on Our Website',page.data)
        self.assertIn(b'$500.00',page.data)
        self.assertIn(b'Up to 2 students',page.data)
        self.assertNotIn(b'OLD $999',page.data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        response=self.client.post('/group-program-admin',data=dict(id=pid,name='Circle Piano updated',summary='Shared summary',classroom='Class activities',materials='Visual materials',home_practice='Home activities',website_url='https://www.hmusicandart.com/page.html?id=example'))
        self.assertEqual(response.status_code,303)
        self.assertIn(b'Shared summary',self.client.get('/group-classes/1/apply?preview=1').data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_programs'),1)
        self.assertEqual(self.scalar('SELECT tuition_cents FROM group_offerings'),50000)
        self.publish()
        catalog=self.client.get('/api/website/group-classes').get_json()
        self.assertEqual(catalog['classes'][0]['description'],'Shared summary')
        self.assertEqual(catalog['classes'][0]['tuition_cents'],50000)

    def test_program_upload_private_until_linked_class_is_published(self):
        from PIL import Image
        pid=self.scalar('SELECT id FROM group_programs LIMIT 1')
        data=io.BytesIO();Image.new('RGB',(20,20),'blue').save(data,'PNG');data.seek(0)
        response=self.client.post('/group-program-admin',data={'id':str(pid),'name':'Circle Piano','summary':'Hello','image_0':(data,'class.png')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.client.get('/group-program-image/1/0').status_code,200)
        with self.client.session_transaction() as sess:sess.clear()
        self.assertEqual(self.client.get('/group-program-image/1/0').status_code,404)
        self.assertEqual(self.client.post('/group-program-admin',data={'name':'bad'}).status_code,403)
        with self.client.session_transaction() as sess:sess['user_role']='owner'
        self.create_class(offering_id='1',program_id=str(pid));self.publish()
        with self.client.session_transaction() as sess:sess.clear()
        image=self.client.get('/group-program-image/1/0')
        self.assertEqual(image.status_code,200);self.assertEqual(image.mimetype,'image/jpeg')

    def test_curriculum_rejects_external_or_unsafe_links_and_bad_program(self):
        for url in ('javascript:alert(1)','https://evil.test/a','https://hmusicandart.com.evil.test/a'):
            response=self.client.post('/group-program-admin',data={'name':'Circle Piano','id':'1','website_url':url})
            self.assertIn(b'HTTPS link on hmusicandart.com',response.data)
        response=self.create_class(offering_id='1',program_id='999')
        self.assertIn(b'Choose an existing program',response.data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_programs'),0)

    def test_coteachers_share_one_lesson_and_roundtrip_without_duplicate_credits(self):
        plan=self.schedule_plan()
        plan[0]['teachers']=['Teacher One','Teacher Two','Teacher Two']
        self.assertEqual(self.save_calendar(plan).status_code,303)
        offering=ge.get_offering(self.conn.cursor(),1)
        self.assertEqual(offering['sessions'][0]['teachers'],['Teacher One','Teacher Two'])
        self.assertEqual(offering['session_count'],2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM enrollments'),0)
        ids=[x['id'] for x in offering['sessions']]
        for item,sid in zip(plan,ids):item['id']=sid
        self.assertEqual(self.save_calendar(plan).status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)
        plan[0]['teachers']=['Teacher Two']
        self.assertEqual(self.save_calendar(plan).status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_session_teachers WHERE schedule_id=?',(ids[0],)),0)
        self.assertEqual(self.scalar('SELECT teacher FROM schedule WHERE id=?',(ids[0],)),'Teacher Two')
        self.publish()
        page=self.client.get('/group-classes/1/apply')
        self.assertIn(b'Teacher Two',page.data)

    def test_invalid_secondary_teacher_rolls_back_calendar(self):
        for names in ([],['Teacher One','Inactive Teacher'],['Teacher One','Missing'], 'Teacher One'):
            plan=self.schedule_plan();plan[0]['teachers']=names
            response=self.save_calendar(plan)
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_session_teachers'),0)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM schedule'),3)

    def test_date_picker_saves_empty_calendar_sessions_and_rotating_teachers(self):
        self.conn.execute('DELETE FROM group_offering_sessions');self.conn.commit()
        page=self.client.get('/group-class-admin/1/schedule')
        self.assertIn(b'Select class dates',page.data)
        version=ge.schedule_version(ge.get_offering(self.conn.cursor(),1))
        r=self.save_calendar(self.schedule_plan(),version)
        self.assertEqual(r.status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.assertEqual(self.scalar('SELECT duration FROM schedule WHERE lesson_date=?',('2099-12-05',)),50)
        self.assertEqual(self.scalar('SELECT teacher FROM schedule WHERE lesson_date=?',('2099-12-12',)),'Teacher Two')
        self.assertEqual(self.scalar('SELECT teacher_pay FROM schedule WHERE lesson_date=?',('2099-12-12',)),60)
        self.assertEqual(self.scalar('SELECT published FROM group_offerings'),0)
        duplicate=self.save_calendar(self.schedule_plan(),version)
        self.assertIn(b'another window',duplicate.data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)

    def test_calendar_conflicts_warn_without_blocking_creation(self):
        self.api['schedule_has_conflict']=lambda *args,**kwargs:dict(has_conflict=True,message='Teacher conflict with another lesson at 11:15.')
        result=self.save_calendar(self.schedule_plan())
        self.assertEqual(result.status_code,303)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM schedule WHERE status='scheduled' AND lesson_date LIKE '2099-12-%'"),2)
        notice=self.client.get(result.location)
        self.assertIn(b'Dates &amp; times saved',notice.data)
        self.assertIn(b'reminder only',notice.data)
        self.assertIn(b'Teacher conflict with another lesson at 11:15.',notice.data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM students'),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)
        self.assertEqual(self.scalar('SELECT published FROM group_offerings'),0)

    def test_invalid_calendar_plan_still_rolls_back(self):
        count=self.scalar('SELECT COUNT(*) FROM schedule')
        for field,value in [('teacher','Inactive Teacher'),('course_id',3),('room_id',99),('date','2000-01-01'),('time','25:00'),('id',3)]:
            plan=self.schedule_plan();plan[0][field]=value
            self.assertEqual(self.save_calendar(plan).status_code,200)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM schedule'),count)
        plan=self.schedule_plan();plan[1]['date']=plan[0]['date']
        self.assertIn(b'only once',self.save_calendar(plan).data)

    def test_calendar_edit_keeps_ids_and_soft_cancels_removed_dates(self):
        plan=self.schedule_plan();plan[0]['id']=1
        self.assertEqual(self.save_calendar([plan[0]]).status_code,303)
        self.assertEqual(self.scalar('SELECT lesson_date FROM schedule WHERE id=1'),'2099-12-05')
        self.assertEqual(self.scalar('SELECT status FROM schedule WHERE id=2'),'cancelled')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM schedule'),3)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),1)

    def test_published_calendar_updates_without_closing_registration(self):
        self.publish()
        plan=self.schedule_plan();plan[0]['id']=1;plan[1]['id']=2
        self.assertEqual(self.save_calendar(plan).status_code,303)
        self.assertEqual(self.scalar('SELECT published FROM group_offerings'),1)
        self.assertEqual(self.scalar('SELECT lesson_date FROM schedule WHERE id=1'),'2099-12-05')

    def test_existing_applications_require_review_and_preserve_roster_and_credits(self):
        self.apply()
        self.conn.execute("INSERT INTO group_schedule_students(schedule_id,student_name,attendance_credit_applied,attendance_enrollment_id) VALUES (1,'Child',0,42)")
        self.conn.execute("UPDATE schedule SET group_size=1,group_student_names='Child',student_charge_amount=55 WHERE id=1");self.conn.commit()
        plan=[dict(id=x['id'],date=x['lesson_date'],time='12:00',teacher=x['teacher'],room_id=1,course_id=2) for x in ge.get_sessions(self.conn.cursor(),1)]
        response=self.save_calendar(plan)
        self.assertIn(b'Review schedule changes',response.data)
        self.assertEqual(self.scalar('SELECT lesson_time FROM schedule WHERE id=1'),'10:00')
        with self.client.session_transaction() as sess:key=sess['group_schedule_review']
        result=self.client.post('/group-class-admin/1/schedule',data={'sessions':__import__('json').dumps(plan),'version':ge.schedule_version(ge.get_offering(self.conn.cursor(),1)),'confirm_changes':key})
        self.assertEqual(result.status_code,303)
        self.assertEqual(self.scalar('SELECT lesson_time FROM schedule WHERE id=1'),'12:00')
        self.assertEqual(self.scalar('SELECT group_size FROM schedule WHERE id=1'),1)
        self.assertEqual(self.scalar('SELECT attendance_enrollment_id FROM group_schedule_students WHERE schedule_id=1'),42)
        self.assertEqual(self.scalar('SELECT student_charge_amount FROM schedule WHERE id=1'),55)
        self.assertEqual(self.scalar('SELECT published FROM group_offerings'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'),0)

    def test_review_cannot_be_bypassed_and_rechecks_new_applications(self):
        self.apply()
        plan=self.schedule_plan();plan[0]['id']=1;plan[1]['id']=2
        version=ge.schedule_version(ge.get_offering(self.conn.cursor(),1))
        response=self.client.post('/group-class-admin/1/schedule',data={'sessions':__import__('json').dumps(plan),'version':version,'confirm_changes':'forged'})
        self.assertIn(b'Review schedule changes',response.data)
        with self.client.session_transaction() as sess:key=sess['group_schedule_review']
        self.conn.execute("UPDATE group_applications SET updated_at='new update'");self.conn.commit()
        response=self.client.post('/group-class-admin/1/schedule',data={'sessions':__import__('json').dumps(plan),'version':version,'confirm_changes':key})
        self.assertIn(b'Review schedule changes',response.data)
        self.assertEqual(self.scalar('SELECT lesson_date FROM schedule WHERE id=1'),'2099-11-01')

    def test_enrolled_lesson_cannot_be_deleted_or_duration_changed(self):
        self.conn.execute("INSERT INTO group_schedule_students(schedule_id,student_name) VALUES (1,'Child')");self.conn.commit()
        plan=[dict(id=2,date='2099-12-12',time='12:00',teacher='Teacher One',room_id=1,course_id=2)]
        self.assertIn(b'cannot be removed',self.save_calendar(plan).data)
        plan.insert(0,dict(id=1,date='2099-12-05',time='12:00',teacher='Teacher One',room_id=1,course_id=4))
        self.assertIn(b'course and duration',self.save_calendar(plan).data)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)

    def test_past_lessons_preserved_when_future_calendar_changes(self):
        self.conn.execute("UPDATE schedule SET lesson_date='2020-01-01',status='present' WHERE id=1");self.conn.commit()
        plan=[dict(id=2,date='2099-12-12',time='12:00',teacher='Teacher One',room_id=1,course_id=2)]
        self.assertEqual(self.save_calendar(plan).status_code,303)
        self.assertEqual(self.scalar('SELECT status FROM schedule WHERE id=1'),'present')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM group_offering_sessions'),2)

    def test_calendar_cannot_change_existing_enrollments_or_other_classes(self):
        self.apply()
        self.client.post('/group-class-admin',data={'action':'visibility','id':1,'published':'0'})
        self.assertIn(b'Review schedule changes',self.save_calendar(self.schedule_plan()).data)
        with self.client.session_transaction() as ss:ss['user_role']=None
        self.assertEqual(self.client.get('/group-class-admin/1/schedule').status_code,403)
        self.assertEqual(self.save_calendar(self.schedule_plan()).status_code,403)

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
