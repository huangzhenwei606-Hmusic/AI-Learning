import unittest
from manager_labels import ManagerHTML,manager_text,manager_json
class Tests(unittest.TestCase):
 def test_labels(self):self.assertEqual(manager_text('Owner owner_parent owner_teacher owner review'),'Manager manager_parent manager_teacher manager review')
 def test_html(self):
  p=ManagerHTML();p.feed('<a href="/owner_parent" data-role="owner">Owner</a><script>role="owner";</script><input name="owner" value="Owner"><textarea>Owner draft</textarea><p>Type: owner_parent &amp; Owner approval</p>');p.close();s=''.join(p.parts)
  for text in ('href="/owner_parent" data-role="owner">Manager','<script>role="owner";</script>','<textarea>Owner draft</textarea>','name="owner" value="Owner"','Type: manager_parent &amp; Manager approval'):self.assertIn(text,s)
 def test_json(self):
  old={'role':'owner','type':'owner_parent','url':'/owner_dashboard','body':'Owner wrote this','items':[{'sender_name':'Owner','author_key':'owner'}],'error':'Ask the owner'};new=manager_json(old)
  for key in ('role','type','url','body'):self.assertEqual(old[key],new[key])
  self.assertEqual(new['items'][0],{'sender_name':'Manager','author_key':'owner'});self.assertEqual(new['error'],'Ask the manager')
if __name__=='__main__':unittest.main()
