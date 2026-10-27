"""Regression: Blender (via MCP) is a separate process with its own working
directory, so render_and_score must hand it an absolute .blend save path even
when the caller passes a relative run dir. Previously a relative path made
Blender fail with 'Cannot open file .../runs/.../model.blend for writing'
whenever the app and Blender were launched from different folders."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from src import loop, segmentation


class FakeClient:
    def __init__(self):
        self.code = None

    def execute_code(self, code):
        self.code = code
        return "BUILT_AND_SAVED"


class BlenderPathsTest(unittest.TestCase):
    def test_save_path_sent_to_blender_is_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                ref_img = os.path.join(tmp, "ref.png")
                Image.new("RGB", (64, 64), "white").save(ref_img)
                # draw a dark blob so segmentation finds a character
                img = Image.open(ref_img)
                for x in range(20, 44):
                    for y in range(10, 54):
                        img.putpixel((x, y), (30, 30, 120))
                img.save(ref_img)
                ref = {"path": ref_img, "data": segmentation.analyze(ref_img)}
                params = {"aspect": 0.5, "side_aspect": 0.45,
                          "colors": ref["data"]["colors"],
                          "profile": ref["data"]["profile"],
                          "width_scale": 1.0, "height_scale": 1.0,
                          "depth_scale": 1.0}
                client = FakeClient()

                def fake_render(*args, **kwargs):
                    outdir = args[0][-1]
                    for view in ("front", "side", "back", "top"):
                        frame = Image.new("RGB", (64, 64), "white")
                        for x in range(20, 44):
                            for y in range(10, 54):
                                frame.putpixel((x, y), (30, 30, 120))
                        frame.save(os.path.join(outdir, view + ".png"))
                    m = mock.Mock()
                    m.stdout = "VIEWS_RENDERED"
                    m.stderr = ""
                    return m

                with mock.patch("subprocess.run", side_effect=fake_render):
                    record, rdir = loop.render_and_score(
                        client, params, "A", "runs/relrun", 1,
                        {"front": ref})
                self.assertTrue(os.path.isabs(record["blend"]), record["blend"])
                self.assertIn(record["blend"], client.code)
                self.assertTrue(os.path.isdir(rdir))
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
