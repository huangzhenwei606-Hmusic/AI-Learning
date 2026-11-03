import json
import unittest
import test_group_enrollment as fixtures
from admissions import seed,validate_catalog

class TeachingLocationTests(unittest.TestCase):
 setUp=fixtures.GroupEnrollmentTests.setUp
 tearDown=fixtures.GroupEnrollmentTests.tearDown
 create_class=fixtures.GroupEnrollmentTests.create_class
 publish=fixtures.GroupEnrollmentTests.publish
 apply=fixtures.GroupEnrollmentTests.apply
 def assign(self,location):
  self.conn.execute("UPDATE group_offerings SET title='Circle Piano Beginner' WHERE id=1")
  self.conn.execute('INSERT INTO group_offering_locations(offering_id,location_id) VALUES(1,?)',(location,));self.conn.commit()
 def test_two_centers_and_four_partners(self):
  cfg=seed();validate_catalog(cfg);self.assertEqual(len(cfg['centers']),2);self.assertEqual(len(cfg['partners']),4)
  self.assertEqual(len({c['id'] for c in cfg['centers']}),2)
 def test_catalog_scopes_center_and_partner_without_cross_listing(self):
  self.assign('hanlin');self.publish()
  data=self.client.get('/api/website/group-classes?location=hanlin').json['classes'];self.assertEqual(len(data),1)
  self.assertEqual(data[0]['location_id'],'hanlin');self.assertIn('248 Harbor',data[0]['teaching_location']['address'])
  self.assertEqual(data[0]['apply_path'],'/group-classes/1/apply')
  self.assertEqual(self.client.get('/api/website/group-classes?location=center-edgewater').json['classes'],[])
  self.assertEqual(self.client.get('/api/website/group-classes?location=bogus').status_code,400)
 def test_application_shows_and_locks_assigned_location(self):
  self.assign('center-marlin');self.publish()
  page=self.client.get('/group-classes/1/apply');self.assertIn(b'1101 Marlin',page.data)
  response=self.apply(teaching_location_id='hanlin');self.assertIn(b'The class location changed',response.data)
  self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM group_applications').fetchone()[0],0)
 def test_admin_saves_location_and_rejects_unknown_location(self):
  response=self.create_class(offering_id='1',teaching_location_id='stemtree')
  self.assertEqual(response.status_code,303)
  self.assertEqual(self.conn.execute('SELECT location_id FROM group_offering_locations WHERE offering_id=1').fetchone()[0],'stemtree')
  response=self.create_class(offering_id='1',teaching_location_id='unknown')
  self.assertIn(b'Choose an available teaching location',response.data)
 def test_submitted_application_keeps_location_snapshot(self):
  self.assign('bright-horizon');response=self.apply(teaching_location_id='bright-horizon');self.assertEqual(response.status_code,303)
  snapshot=json.loads(self.conn.execute('SELECT policy_snapshot FROM group_applications').fetchone()[0]);self.assertEqual(snapshot['teaching_location']['id'],'bright-horizon')
