"""New vs existing Blender file modes.

New mode must factory-reset Blender so an old open file never leaks
in; existing mode must rate the chosen file as round 1 and edit copies
in place — the original file is never overwritten.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from src import driver, loop, modeling, segmentation


class CodeShapeTest(unittest.TestCase):
    def test_new_file_resets_to_empty(self):
        code = modeling.reset_empty_code()
        self.assertIn("read_factory_settings(use_empty=True)", code)
        self.assertIn("RESET_EMPTY", code)

    def test_existing_file_opens_mainfile(self):
        code = modeling.open_mainfile_code("/tmp/my model.blend")
        self.assertIn("open_mainfile", code)
        self.assertIn("my model.blend", code)
        self.assertIn("OPENED_MAINFILE", code)

    def test_scale_edit_preserves_objects(self):
        code = modeling.scale_edit_code(1.1, 0.9, 1.0)
        self.assertIn('type == "MESH"', code)
        self.assertNotIn("objects.remove", code)
        self.assertIn("BUILT_AND_SAVED", code)


class ExistingBaselineTest(unittest.TestCase):
    def test_existing_blend_scored_as_round_without_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref_img = os.path.join(tmp, "ref.png")
            img = Image.new("RGB", (64, 64), "white")
            for x in range(20, 44):
                for y in range(10, 54):
                    img.putpixel((x, y), (30, 30, 120))
            img.save(ref_img)
            ref = {"path": ref_img, "data": segmentation.analyze(ref_img)}
            src_blend = os.path.join(tmp, "mine.blend")
            with open(src_blend, "wb") as f:
                f.write(b"FAKE-BLEND-ORIGINAL")
            params = {"aspect": 0.5, "side_aspect": 0.45,
                      "colors": ref["data"]["colors"],
                      "profile": ref["data"]["profile"],
                      "width_scale": 1.0, "height_scale": 1.0, "depth_scale": 1.0}

            def fake_render(*args, **kwargs):
                outdir = args[0][-1]
                for view in ("front", "side", "back", "top"):
                    frame = Image.new("RGB", (64, 64), "white")
                    for x in range(20, 44):
                        for y in range(10, 54):
                            frame.putpixel((x, y), (30, 30, 120))
                    frame.save(os.path.join(outdir, view + ".png"))
                m = mock.Mock(); m.stdout = "VIEWS_RENDERED"; m.stderr = ""
                return m

            with mock.patch("subprocess.run", side_effect=fake_render):
                record, rdir = loop.render_existing_blend(
                    src_blend, params, os.path.join(tmp, "runs"), 1,
                    {"front": ref})
            self.assertEqual(record["strategy"], "existing")
            self.assertIsNotNone(record["rating_10"])
            # round copy exists; the user's original is byte-identical
            self.assertTrue(os.path.exists(os.path.join(rdir, "model.blend")))
            with open(src_blend, "rb") as f:
                self.assertEqual(f.read(), b"FAKE-BLEND-ORIGINAL")


class ScaleMultipliersTest(unittest.TestCase):
    def test_multipliers_clamped(self):
        m = driver.scale_multipliers({"width_scale": 9, "depth_scale": 0.1})
        self.assertEqual(m["width_scale"], 1.18)
        self.assertEqual(m["depth_scale"], 0.85)
        self.assertEqual(m["height_scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
