"""Image generation must go through POST /responses with the
image_generation tool (user-supplied Muse Image example), with the
source uploaded via /files and sent as input_image. Mocked: no credits.
"""
import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from src import meta_api


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload


class MetaImageResponsesTest(unittest.TestCase):
    def setUp(self):
        meta_api.clear_file_cache()

    def test_sheet_uses_responses_image_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "char.png")
            Image.new("RGB", (32, 32), (200, 100, 100)).save(src)
            out_path = os.path.join(tmp, "sheet.png")
            png_b64 = base64.b64encode(open(src, "rb").read()).decode()
            seen = []

            def fake_post(url, **kw):
                seen.append((url, kw))
                if url.endswith("/files"):
                    return _Resp({"id": "file-123"})
                return _Resp({"id": "resp-1", "status": "completed", "output": [
                    {"type": "image_generation_call", "result": png_b64}]})

            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "test-key"}), \
                    mock.patch.object(meta_api.requests, "post", fake_post):
                meta_api.generate_reference_sheet(src, out_path)

            urls = [u for u, _ in seen]
            self.assertTrue(any(u.endswith("/files") for u in urls), urls)
            resp_calls = [kw for u, kw in seen if u.endswith("/responses")]
            self.assertEqual(len(resp_calls), 1)
            payload = resp_calls[0]["json"]
            self.assertEqual(payload["model"], "muse-image-1.0")
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["tools"][0]["type"], "image_generation")
            self.assertEqual(payload["tools"][0]["output_format"], "png")
            content = payload["input"][0]["content"]
            self.assertIn({"type": "input_image", "file_id": "file-123"}, content)
            self.assertTrue(os.path.exists(out_path))
            self.assertTrue(os.path.exists(out_path + ".response.json"))


if __name__ == "__main__":
    unittest.main()
