import unittest
import test_group_enrollment as fixtures

class GroupDirectSaveTests(unittest.TestCase):
 setUp=fixtures.GroupEnrollmentTests.setUp
 tearDown=fixtures.GroupEnrollmentTests.tearDown
 create_class=fixtures.GroupEnrollmentTests.create_class
 publish=fixtures.GroupEnrollmentTests.publish
 apply=fixtures.GroupEnrollmentTests.apply
 scalar=fixtures.GroupEnrollmentTests.scalar
 def test_published_class_saves_without_closing_and_keeps_calendar(self):
  self.publish();before=list(self.conn.execute('SELECT * FROM group_offering_sessions'))
  response=self.create_class(offering_id=1,title='Updated published class',teaching_location_id='hanlin',schedule_ids=[])
  self.assertEqual(response.status_code,303);self.assertIn('information_saved=1',response.location)
  self.assertEqual(self.scalar('SELECT published FROM group_offerings'),1)
  self.assertEqual(list(self.conn.execute('SELECT * FROM group_offering_sessions')),before)
  self.assertEqual(self.scalar('SELECT location_id FROM group_offering_locations'),'hanlin')
  self.assertIn(b'Class information updated and saved',self.client.get(response.location).data)
 def test_existing_applications_keep_their_original_terms(self):
  self.apply();snapshot=self.scalar('SELECT policy_snapshot FROM group_applications');inquiry=self.scalar('SELECT inquiry_id FROM group_applications')
  self.conn.execute("INSERT INTO invoices(student_name,amount,status,credits_applied) VALUES('Child',500,'paid',1)");self.conn.commit();invoice=list(self.conn.execute('SELECT * FROM invoices'))
  response=self.create_class(offering_id=1,title='Updated title',tuition='600',policy='Updated terms for new registrations')
  self.assertEqual(response.status_code,303)
  self.assertEqual(self.scalar('SELECT policy_snapshot FROM group_applications'),snapshot)
  self.assertEqual(self.scalar('SELECT inquiry_id FROM group_applications'),inquiry)
  self.assertEqual(self.scalar('SELECT tuition_cents FROM group_offerings'),60000)
  self.assertEqual(list(self.conn.execute('SELECT * FROM invoices')),invoice)
 def test_started_calendar_does_not_block_basic_updates(self):
  self.publish();self.conn.execute("UPDATE schedule SET lesson_date='2020-01-01' WHERE id=1");self.conn.commit()
  self.assertEqual(self.create_class(offering_id=1,title='Corrected information').status_code,303)
  self.assertEqual(self.scalar('SELECT lesson_date FROM schedule WHERE id=1'),'2020-01-01')
 def test_invalid_values_roll_back_without_closing_registration(self):
  self.publish();self.assertIn(b'Tuition must be',self.create_class(offering_id=1,tuition='-10').data)
  self.assertEqual(self.scalar('SELECT tuition_cents FROM group_offerings'),50000)
  self.assertEqual(self.scalar('SELECT published FROM group_offerings'),1)
