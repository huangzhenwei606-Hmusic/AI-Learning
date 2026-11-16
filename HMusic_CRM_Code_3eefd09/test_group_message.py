import json
from contextlib import closing
import sqlite3
from test_director_portal import DirectorPortalTest

class GroupMessageTest(DirectorPortalTest):
    def prepare_group(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                ALTER TABLE schedule ADD COLUMN id INTEGER;
                ALTER TABLE schedule ADD COLUMN group_name TEXT;
                ALTER TABLE schedule ADD COLUMN is_group INTEGER DEFAULT 0;
                INSERT INTO schedule(student_name,teacher,course_type_name,lesson_date,status,id,group_name,is_group)
                VALUES('Group','Xueyang Wang','Group Class','2020-01-01','present',91,'Completed <Class>',1);
                INSERT INTO group_schedule_students VALUES(91,'Student One','present'),(91,'Student One','present');
                INSERT INTO parent_students VALUES(3,'Student One',1);
            """)
            db.commit()

    def test_completed_group_preselects_linked_active_families_once(self):
        self.prepare_group()
        self.login('owner','owner')
        response=self.client.get('/director/compose?group_schedule_id=91')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('Completed &lt;Class&gt;',html)
        import re
        data=json.loads(re.search(r'data-audience-data>(.*?)</script>',html,re.S).group(1))
        self.assertEqual(data['rule']['selected'],[1])
        self.assertEqual(data['rule']['mode'],'selected')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM school_posts').fetchone()[0],0)

    def test_invalid_group_and_private_lesson_rejected(self):
        self.prepare_group();self.login('owner','owner')
        for source,status in [('bad',400),('999',404)]:
            self.assertEqual(self.client.get('/director/compose?group_schedule_id='+source).status_code,status)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE schedule SET is_group=0 WHERE id=91');db.commit()
        self.assertEqual(self.client.get('/director/compose?group_schedule_id=91').status_code,404)

    def test_parent_cannot_open_group_composer(self):
        self.prepare_group();self.login('parent','1')
        self.assertIn(self.client.get('/director/compose?group_schedule_id=91').status_code,(302,403))

    def test_shortcut_resolves_legacy_roster(self):
        self.prepare_group();self.login('owner','owner')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE schedule ADD COLUMN group_student_names TEXT')
            db.execute('DELETE FROM group_schedule_students WHERE schedule_id=91')
            db.execute("UPDATE schedule SET group_student_names='Student One, Student Two' WHERE id=91")
            db.commit()
        html=self.client.get('/director/compose?group_schedule_id=91').get_data(as_text=True)
        import re
        data=json.loads(re.search(r'data-audience-data>(.*?)</script>',html,re.S).group(1))
        self.assertEqual(data['rule']['selected'],[1,2])

    def test_reviewed_application_selects_existing_link_without_calendar_roster(self):
        self.prepare_group();self.login('owner','owner')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                ALTER TABLE students ADD COLUMN id INTEGER;
                UPDATE students SET id=1 WHERE name='Student One';
                UPDATE students SET id=2 WHERE name='Student Two';
                ALTER TABLE parent_profiles ADD COLUMN email TEXT;
                UPDATE parent_profiles SET email='one@school.test' WHERE id=1;
                UPDATE parent_profiles SET email='two@school.test' WHERE id=2;
                CREATE TABLE group_offerings(id,title);
                CREATE TABLE group_offering_sessions(offering_id,schedule_id);
                CREATE TABLE group_applications(id,offering_id,student_id,email,status);
                INSERT INTO group_offerings VALUES(1,'Reviewed class');
                INSERT INTO group_offering_sessions VALUES(1,91);
                DELETE FROM group_schedule_students;
                INSERT INTO group_applications VALUES(1,1,1,'one@school.test','reserved');
                INSERT INTO group_applications VALUES(2,1,2,'two@school.test','review');
            """)
            db.commit()
        import re
        def selected():
            response=self.client.get('/director/compose?group_schedule_id=91')
            self.assertEqual(response.status_code,200)
            data=json.loads(re.search(r'data-audience-data>(.*?)</script>',response.get_data(as_text=True),re.S).group(1))
            if data['rule']['selected']:
                self.assertIn('Class: Reviewed class',data['families'][0]['courses'])
            return data['rule']['selected']
        self.assertEqual(selected(),[1])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE parent_students SET active=0 WHERE parent_id=1');db.commit()
        self.assertEqual(selected(),[])
