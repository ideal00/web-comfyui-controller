"""Durable user images and authenticated creative-library import round trips."""
import base64
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import easy_panel
from easy_panel_app import visual_tag_library as vtl
from easy_panel_app.creative_index import CreativeIndex


class VisualTagUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(vtl,'USER_LIBRARY_DIR',self.root/'uploads'),
                        patch.object(vtl,'INDEX_FILE',self.root/'visual.sqlite'),
                        patch.object(vtl,'THUMB_DIR',self.root/'thumbs'),
                        patch.dict(os.environ,{vtl.ROOT_ENV_KEYS[0]:str(self.root/'missing-legacy')}),
                        patch.object(vtl,'warm_thumbnails_async')]
        for item in self.patches: item.start()
        self.reset_cache()
        image = io.BytesIO()
        Image.new('RGB',(48,32),(60,120,180)).save(image,format='PNG')
        self.image = image.getvalue()

    def reset_cache(self):
        vtl._INDEX_STATE.update(key=None,ts=0,value=None)
        vtl._SIGNATURE_CACHE.update(key=None,ts=0,value=None)
        vtl._ROWS_CACHE.update(signature=None,rows=None)

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.reset_cache()
        self.temp.cleanup()

    def test_uploaded_tags_and_image_survive_rebuild_and_cache_reset(self):
        entry = vtl.add_entry(self.image, {'tags':'white shirt, vest, white_shirt','name_zh':'白衬衫马甲','category':'服装参考'},generation_id='a'*32,artifact_id='b'*32)
        self.assertEqual(['white_shirt','vest'],entry['tags'])
        vtl.build_index()
        self.reset_cache()
        result = vtl.search('白衬衫',category='服装参考')
        self.assertTrue(result['available'])
        self.assertEqual(entry['id'], result['results'][0]['id'])
        indexed = vtl.find_entry(entry['id'])
        self.assertEqual('a'*32,indexed['generation_id'])
        self.assertEqual(self.image,vtl.image_path(indexed).read_bytes())
        self.assertTrue(vtl.thumbnail_bytes(vtl.image_path(indexed)))
        self.assertIsNone(vtl.image_path({'source':'user','image_path':'../secret.png'}))

    def test_invalid_metadata_or_image_never_creates_an_entry(self):
        for tags in ['中文提示词','<img src=x>','', 'standing, (bad anatomy:1.2)']:
            with self.assertRaises(ValueError): vtl.add_entry(self.image,{'tags':tags})
        with self.assertRaises(ValueError): vtl.add_entry(b'not an image',{'tags':'blazer'})
        self.assertFalse((self.root/'uploads').exists())

    def test_upload_appears_with_legacy_entries_without_changing_source_documents(self):
        legacy = self.root/'missing-legacy'/'服装'
        legacy.mkdir(parents=True)
        document = legacy/'tags.md'
        content = '## 1. blazer — 西装\n<img src="blazer.png" />\n| tag | blazer |\n'
        document.write_text(content,encoding='utf-8')
        before = vtl.search('')['total']
        vtl.add_entry(self.image,{'tags':'vest','name_zh':'马甲'})
        self.assertEqual(before+1,vtl.search('')['total'])
        self.assertEqual(content,document.read_text(encoding='utf-8'))

    def test_http_upload_and_selected_work_output_use_existing_auth(self):
        output = self.root/'output'; output.mkdir()
        (output/'source.png').write_bytes(self.image)
        db = self.root/'creative.sqlite'
        index = CreativeIndex(db)
        created = index.upsert_snapshot({'id':'c'*32,'createdAt':100,'payload':{'model':'test','prompt':'white_shirt'},'outputs':['source.png']},status='completed',output_root=output)
        work = index.get_generation(created['generation_id'])
        artifact = work['artifacts'][0]
        with patch.object(easy_panel,'CREATIVE_INDEX_FILE',db), patch.object(easy_panel,'OUTPUT',output), patch.dict(os.environ,{'EASY_PANEL_RPG_TOKEN':'test-token'}):
            server = easy_panel.ThreadingHTTPServer(('127.0.0.1',0),easy_panel.Handler)
            thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            def request(method,path,payload=None,auth=True):
                connection = http.client.HTTPConnection(*server.server_address,timeout=8)
                headers = {'Content-Type':'application/json'}
                if auth: headers['X-RPG-Token']='test-token'
                connection.request(method,path,body=json.dumps(payload).encode() if payload else None,headers=headers)
                response = connection.getresponse(); body=response.read(); status=response.status; connection.close()
                return status,body
            try:
                payload={'image':'data:image/png;base64,'+base64.b64encode(self.image).decode(),'tags':'white_shirt','name_zh':'上传示例'}
                with patch.object(easy_panel.Handler,'is_loopback_client',return_value=False):
                    self.assertEqual(401,request('POST','/api/visual-tags/add',payload,auth=False)[0])
                status,body=request('POST','/api/visual-tags/add',payload)
                self.assertEqual(200,status); self.assertTrue(json.loads(body)['entry']['custom'])
                linked={'generation_id':work['generation_id'],'artifact_id':artifact['artifact_id'],'tags':'vest','category':'作品参考','name_zh':'来源示例'}
                status,body=request('POST','/api/visual-tags/add',linked)
                self.assertEqual(200,status); entry=json.loads(body)['entry']
                self.assertEqual(work['generation_id'],entry['generation_id'])
                self.assertEqual(artifact['artifact_id'],entry['artifact_id'])
                (output/'source.png').unlink()  # The independent gallery copy survives source removal.
                vtl.build_index()
                status,body=request('GET','/api/visual-tags/image?id='+entry['id']+'&size=full')
                self.assertEqual(200,status); self.assertEqual(self.image,body)
                linked['artifact_id']='d'*32
                self.assertEqual(400,request('POST','/api/visual-tags/add',linked)[0])
                self.assertEqual(2,vtl.search('')['total'])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
