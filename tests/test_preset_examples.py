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
from easy_panel_app import preset_examples as examples
from easy_panel_app.shared_state import SharedStateStore


class PresetExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory_patch = patch.object(examples, 'EXAMPLE_DIR', self.root / 'examples')
        self.directory_patch.start()
        content = io.BytesIO()
        Image.new('RGB', (1800, 900), (70, 140, 180)).save(content, 'PNG')
        self.image = content.getvalue()

    def tearDown(self):
        self.directory_patch.stop()
        self.temp.cleanup()

    def test_image_is_a_durable_resized_copy_and_upload_is_deduplicated(self):
        first = examples.save_example(self.image)
        second = examples.save_example(self.image)
        self.assertEqual(first, second)
        self.assertEqual((1600, 800), (first['width'], first['height']))
        self.assertEqual(1, len(list(examples.EXAMPLE_DIR.iterdir())))
        with Image.open(examples.example_path(first['exampleImage'])) as image:
            self.assertEqual('WEBP', image.format)
            self.assertEqual((1600, 800), image.size)

    def test_invalid_images_and_paths_do_not_create_files(self):
        for data in [b'', b'not an image']:
            with self.assertRaises(ValueError): examples.save_example(data)
        with patch.object(examples, 'MAX_UPLOAD_BYTES', 10):
            with self.assertRaises(ValueError): examples.save_example(self.image)
        for value in ['../secret', 'https://example.com/a.png', 'a' * 63, None]:
            self.assertEqual('', examples.normalize_example_id(value))
            with self.assertRaises(ValueError): examples.example_path(value)
        self.assertFalse(examples.EXAMPLE_DIR.exists())

    def test_sync_round_trip_preserves_image_and_explicit_removal(self):
        image = examples.save_example(self.image)['exampleImage']
        path = self.root / 'shared.json'
        store = SharedStateStore(path)
        preset = dict(id='preset_test', name='坐姿例图', category='pose', content='sitting', exampleImage=image, updatedAt=100)
        result = store.merge(dict(promptPresets=[preset]), 0)
        self.assertEqual(image, SharedStateStore(path).read()['promptPresets'][0]['exampleImage'])
        preset.update(exampleImage='', updatedAt=200)
        result = store.merge(dict(promptPresets=[preset]), result['state']['revision'])
        self.assertEqual('', result['state']['promptPresets'][0]['exampleImage'])
        self.assertTrue(examples.example_path(image).is_file())
        preset.update(exampleImage='../../outside', updatedAt=300)
        result = store.merge(dict(promptPresets=[preset]), result['state']['revision'])
        self.assertEqual('', result['state']['promptPresets'][0]['exampleImage'])
        self.assertEqual('sitting', result['state']['promptPresets'][0]['content'])

    def test_http_upload_read_and_authentication(self):
        boundary = 'preset-example-test'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="test.png"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + self.image + f'\r\n--{boundary}--\r\n'.encode()
        with patch.dict(os.environ, {'EASY_PANEL_RPG_TOKEN':'preset-test-token'}):
            server = easy_panel.ThreadingHTTPServer(('127.0.0.1', 0), easy_panel.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def request(method, path, content=None, auth=True):
                conn = http.client.HTTPConnection(*server.server_address, timeout=8)
                headers = {'Content-Type':'multipart/form-data; boundary=' + boundary}
                if auth: headers['X-RPG-Token'] = 'preset-test-token'
                conn.request(method, path, body=content, headers=headers)
                response = conn.getresponse(); data = response.read(); status = response.status; conn.close()
                return status, data
            try:
                with patch.object(easy_panel.Handler, 'is_loopback_client', return_value=False):
                    self.assertEqual(401, request('POST', '/api/preset-examples/upload', b'', False)[0])
                    self.assertEqual(401, request('GET', '/api/preset-examples/image?id=' + 'a'*64, auth=False)[0])
                status, data = request('POST', '/api/preset-examples/upload', body)
                self.assertEqual(200, status)
                uploaded = json.loads(data)
                status, data = request('GET', uploaded['url'])
                self.assertEqual(200, status)
                self.assertEqual(examples.example_path(uploaded['exampleImage']).read_bytes(), data)
                self.assertEqual(404, request('GET', '/api/preset-examples/image?id=' + 'a'*64)[0])
                self.assertEqual(400, request('GET', '/api/preset-examples/image?id=../secret')[0])
                self.assertEqual(400, request('POST', '/api/preset-examples/upload', b'invalid multipart')[0])
                self.assertEqual(413, request('POST', '/api/preset-examples/upload', b'')[0])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
