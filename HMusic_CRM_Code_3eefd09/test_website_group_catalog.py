"""Public discovery must expose exactly the enrollable class data, never families."""
import unittest
import test_group_enrollment as fixtures

class WebsiteGroupCatalogTests(unittest.TestCase):
    setUp = fixtures.GroupEnrollmentTests.setUp
    tearDown = fixtures.GroupEnrollmentTests.tearDown
    create_class = fixtures.GroupEnrollmentTests.create_class
    publish = fixtures.GroupEnrollmentTests.publish

    def circle(self):
        self.conn.execute("UPDATE group_offerings SET title='Circle Piano Beginner',age_range='4–6' WHERE id=1")
        self.conn.commit()
        self.publish()
        with self.client.session_transaction() as state:
            state.clear()

    def test_public_response_is_scoped_and_contains_no_private_fields(self):
        self.circle()
        response=self.client.get('/api/website/group-classes?program=circle-piano')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Credentials',response.headers)
        data=response.json
        self.assertEqual(data['timezone'],'America/Los_Angeles')
        self.assertEqual(len(data['classes']),1)
        item=data['classes'][0]
        self.assertEqual(item['apply_path'],'/group-classes/1/apply')
        self.assertEqual(item['session_count'],2)
        self.assertEqual(item['tuition_cents'],50000)
        self.assertEqual([s['date'] for s in item['sessions']],['2099-11-01','2099-11-08'])
        self.assertNotIn('Existing',response.get_data(as_text=True))
        self.assertFalse({'applications','email','phone','parent_name','student_name','invoice_id','policy'} & set(item))
        self.assertEqual(self.client.post('/api/website/group-classes').status_code,405)

    def test_draft_unrelated_cancelled_and_started_packages_are_excluded(self):
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'],[])
        self.publish()
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'],[])
        self.circle()
        self.conn.execute("UPDATE schedule SET status='cancelled' WHERE id=2")
        self.conn.commit()
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'],[])
        self.conn.execute("UPDATE schedule SET status='scheduled',lesson_date='2000-01-01' WHERE id=2")
        self.conn.commit()
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'],[])

    def test_full_package_remains_visible_for_waitlist_with_live_capacity(self):
        self.circle()
        self.conn.execute('UPDATE group_offerings SET capacity=0 WHERE id=1')
        self.conn.commit()
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'][0]['remaining'],0)
        self.conn.execute('UPDATE group_offerings SET published=0 WHERE id=1')
        self.conn.commit()
        self.assertEqual(self.client.get('/api/website/group-classes').json['classes'],[])

    def test_explicit_circle_course_type_includes_generic_level_titles(self):
        self.publish()
        self.conn.execute("UPDATE schedule SET course_type_name='Circle Piano' WHERE id IN (1,2)")
        self.conn.commit()
        self.assertEqual(len(self.client.get('/api/website/group-classes').json['classes']),1)
        self.assertEqual(self.client.get('/api/website/group-classes?program=unknown').status_code,400)

if __name__=='__main__':unittest.main()
