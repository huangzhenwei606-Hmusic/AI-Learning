import base64
from io import BytesIO
import json
import unittest
from test_director_portal import DirectorPortalTest

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJz0AAAAASUVORK5CYII=')

class DirectorFilesTest(DirectorPortalTest):
    def test_upload_preview_privacy_and_targeted_announcement(self):
        self.director()
        url=self.draft(kind='event',audience='selected',parent_ids=['1'],attachments=[(BytesIO(PNG),'课表.png','image/png'),(BytesIO(b'%PDF-test'),'details.pdf','application/pdf')])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM notifications'),[(0,)])
        ids=[r[0] for r in self.sql('SELECT id FROM school_post_files ORDER BY id')]
        preview=self.client.get(url).get_data(as_text=True)
        self.assertIn('课表.png',preview);self.assertIn('details.pdf',preview)
        self.assertIn('multipart/form-data',preview)
        self.assertEqual(self.client.get(f'/director/files/{ids[0]}').data,PNG)
        self.login('parent',parent_id=1)
        self.assertEqual(self.client.get(f'/school/files/{ids[0]}').status_code,404)
        self.director();self.publish(url)
        self.login('parent',parent_id=1)
        page=self.client.get('/school/announcements/'+url.rsplit('/',1)[1]).get_data(as_text=True)
        self.assertIn('课表.png',page)
        image=self.client.get(f'/school/files/{ids[0]}')
        self.assertEqual(image.data,PNG);self.assertEqual(image.headers['Cache-Control'],'private, no-store')
        self.assertIn('inline',image.headers['Content-Disposition'])
        pdf=self.client.get(f'/school/files/{ids[1]}')
        self.assertEqual(pdf.data,b'%PDF-test');self.assertIn('attachment',pdf.headers['Content-Disposition'])
        self.login('parent',parent_id=2)
        self.assertEqual(self.client.get(f'/school/files/{ids[0]}').status_code,404)
        self.login(None)
        self.assertEqual(self.client.get(f'/message_uploads/school_{ids[0]}').status_code,403)

    def test_broadcast_files_are_shared_and_existing_parent_attachment_urls_work(self):
        self.director();url=self.draft(attachments=(BytesIO(PNG),'poster.png','image/png'))
        fid=self.sql('SELECT id FROM school_post_files')[0][0]
        self.publish(url);self.publish(url)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM school_post_files'),[(1,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM message_attachments'),[(2,)])
        self.assertEqual(self.sql('SELECT DISTINCT stored_filename FROM message_attachments'),[(f'school_{fid}',)])
        self.login('parent',parent_id=1)
        self.assertEqual(self.client.get(f'/message_uploads/school_{fid}').data,PNG)
        self.login('parent',parent_id=2)
        self.assertEqual(self.client.get(f'/message_uploads/school_{fid}').data,PNG)
        self.director()
        aid=self.sql('SELECT id FROM message_attachments ORDER BY id LIMIT 1')[0][0]
        self.assertEqual(self.client.get(f'/director/attachments/{aid}',follow_redirects=True).data,PNG)

    def test_wrong_type_empty_and_oversized_file_roll_back_draft(self):
        self.director()
        common={'kind':'message','title':'Files','body':'Details','audience':'all'}
        for file,expected in [((BytesIO(b'<svg/>'),'x.svg','image/svg+xml'),400),((BytesIO(b''),'empty.pdf','application/pdf'),400),((BytesIO(b'x'*(10*1024*1024+1)),'big.pdf','application/pdf'),413)]:
            self.assertEqual(self.client.post('/director/compose',data={**common,'attachments':file}).status_code,expected)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM school_posts'),[(0,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM school_post_files'),[(0,)])

    def test_append_draft_file_and_prevent_published_file_edits(self):
        self.director();url=self.draft(attachments=(BytesIO(PNG),'first.png','image/png'))
        response=self.client.post(url,data={'action':'save','title':'Updated','body':'Updated text','attachments':(BytesIO(b'%PDF'), 'second.pdf','application/pdf')})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM school_post_files'),[(2,)])
        self.publish(url)
        self.assertEqual(self.client.post(url,data={'action':'save','title':'No','body':'No','attachments':(BytesIO(PNG),'late.png','image/png')}).status_code,409)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM school_post_files'),[(2,)])

    def test_other_director_and_revoked_director_cannot_read_draft_files(self):
        self.director();self.draft(attachments=(BytesIO(PNG),'private.png','image/png'))
        fid=self.sql('SELECT id FROM school_post_files')[0][0]
        self.sql('INSERT INTO director_access(user_id,enabled,permissions) VALUES (2,1,?)',(json.dumps({'broadcast':True}),))
        self.login('director',username='other')
        self.assertEqual(self.client.get(f'/director/files/{fid}').status_code,403)
        self.login('director',username='xueyang');self.sql('UPDATE director_access SET enabled=0 WHERE user_id=1')
        self.assertEqual(self.client.get(f'/director/files/{fid}').status_code,302)
        self.assertEqual(self.client.get(f'/school/files/{fid}').status_code,403)

# Imported fixture is the parent class, not an additional discovered suite.
del DirectorPortalTest

if __name__=='__main__':unittest.main()
