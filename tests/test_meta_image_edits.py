"""Image-to-image must go to /images/edits as a multipart file upload.

Regression: posting JSON {"image": <data uri>} to /images/generations was
rejected by the live API with HTTP 400 "unknown parameter `image`".
This test mocks the HTTP layer, so it spends no API credits.
"""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from src import meta_api


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class MetaImageEditsTest(unittest.TestCase):
    def test_sheet_uses_edits_multipart_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "char.png")
            Image.new("RGB", (32, 32), (200, 100, 100)).save(src)
            out_path = os.path.join(tmp, "sheet.png")
            png_b64 = base64.b64encode(open(src, "rb").read()).decode()
            payload = json.dumps({"data": [{"b64_json": png_b64}]}).encode()
            seen = {}

            def fake_urlopen(req, timeout=0):
                seen["url"] = req.full_url
                seen["type"] = req.headers.get("Content-type", "")
                seen["body"] = req.data
                return _Resp(payload)

            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "test-key"}), \
                    mock.patch.object(meta_api.urllib.request, "urlopen", fake_urlopen):
                meta_api.generate_reference_sheet(src, out_path)

            self.assertTrue(seen["url"].endswith("/images/edits"), seen["url"])
            self.assertIn("multipart/form-data; boundary=", seen["type"])
            body = seen["body"]
            self.assertIn(b'name="model"', body)
            self.assertIn(b"muse-image-1.0", body)
            self.assertIn(b'name="prompt"', body)
            self.assertIn(b'name="image"; filename="char.png"', body)
            self.assertIn(b"Content-Type: image/png", body)
            self.assertTrue(os.path.exists(out_path))


if __name__ == "__main__":
    unittest.main()
