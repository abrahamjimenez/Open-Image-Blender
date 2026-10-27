"""A supplied 2x2 turnaround sheet must split into the four views,
caption strips excluded, before any Blender work."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw

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


if __name__ == "__main__":
    unittest.main()
