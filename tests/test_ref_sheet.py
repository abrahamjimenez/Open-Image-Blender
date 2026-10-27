"""A supplied 2x2 turnaround sheet must split into the four views,
caption strips excluded, before any Blender work."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw

from unittest import mock

from src import refs


class RefSheetTest(unittest.TestCase):
    def test_split_sheet_gives_four_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = os.path.join(tmp, "sheet.png")
            img = Image.new("RGB", (800, 800), (245, 240, 230))
            d = ImageDraw.Draw(img)
            d.ellipse([120, 120, 300, 300], fill=(120, 110, 100))   # front panel
            d.ellipse([520, 120, 700, 300], fill=(120, 110, 100))   # side panel
            d.ellipse([120, 500, 300, 650], fill=(120, 110, 100))   # back panel
            d.ellipse([520, 500, 700, 650], fill=(120, 110, 100))   # top panel
            d.text((180, 360), "Front View", fill=(0, 0, 0))
            img.save(sheet)
            out = refs.split_sheet(sheet, os.path.join(tmp, "views"))
            self.assertEqual(set(out), {"front", "side", "back", "top"})
            for path in out.values():
                self.assertTrue(os.path.exists(path), path)
                # caption strip must be excluded: crop height < half sheet
                self.assertLess(Image.open(path).size[1], 400)

    def test_sheet_prompt_forwarded_to_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "char.png")
            Image.new("RGB", (32, 32), (200, 100, 100)).save(src)
            seen = {}

            def fake_generate(source, out, prompt=None):
                seen["prompt"] = prompt
                Image.new("RGB", (800, 800), (245, 240, 230)).save(out)
                return out

            with mock.patch.object(refs.meta_api, "has_key", return_value=True), \
                    mock.patch.object(refs, "generate_sheet", fake_generate):
                out_refs, sheet = refs.prepare_references(
                    src, tmp, lambda m: None, sheet_prompt="my own prompt")
            self.assertEqual(seen["prompt"], "my own prompt")
            self.assertEqual(set(out_refs), {"front", "side", "back", "top"})

    def test_sheet_prompt_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "char.png")
            Image.new("RGB", (32, 32), (200, 100, 100)).save(src)
            seen = {}

            def fake_generate(source, out, prompt=None):
                seen["prompt"] = prompt
                Image.new("RGB", (800, 800), (245, 240, 230)).save(out)
                return out

            with mock.patch.object(refs.meta_api, "has_key", return_value=True), \
                    mock.patch.object(refs, "generate_sheet", fake_generate):
                refs.prepare_references(src, tmp, lambda m: None)
            self.assertIsNone(seen["prompt"])


if __name__ == "__main__":
    unittest.main()
