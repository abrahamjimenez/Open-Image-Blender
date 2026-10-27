"""Single-shot contract: one prompt, one build, no retries.

Also: the generated 3D-angle sheet is saved automatically next to the
output .blend as ``<stem>_sheet.png``.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from src import loop


def _img(path, color=(30, 30, 120)):
    img = Image.new("RGB", (64, 64), "white")
    for x in range(20, 44):
        for y in range(10, 54):
            img.putpixel((x, y), color)
    img.save(path)
    return path


class FakeClient:
    instances = []

    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        FakeClient.instances.append(self)

    def tools(self):
        return ["execute_blender_code"]

    def execute_code(self, code):
        self.calls.append(code)
        # Simulate Blender saving the .blend the code asks it to save.
        if "save_as_mainfile" in code:
            import re
            m = re.search(r"save_as_mainfile\(filepath=(?:'|\")([^'\"]+)", code)
            if m:
                with open(m.group(1), "wb") as f:
                    f.write(b"FAKE-BLEND")
        return self.results.pop(0) if self.results else "BUILT_AND_SAVED"

    def close(self):
        pass


class SheetSaveTest(unittest.TestCase):
    def test_sheet_output_path_next_to_blend(self):
        self.assertEqual(loop.sheet_output_path("/tmp/out/model.blend"),
                         "/tmp/out/model_sheet.png")

    def test_supplied_sheet_copied_next_to_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = _img(os.path.join(tmp, "ref_sheet.png"))
            out = os.path.join(tmp, "model.blend")
            saved = loop.save_sheet({"front": sheet}, sheet, out, tmp,
                                    log_fn=lambda m: None)
            self.assertEqual(saved, os.path.join(tmp, "model_sheet.png"))
            self.assertTrue(os.path.isfile(saved))

    def test_prepared_refs_compose_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            refs = {v: _img(os.path.join(tmp, f"ref_{v}.png"))
                    for v in ("front", "side", "back", "top")}
            out = os.path.join(tmp, "char.blend")
            saved = loop.save_sheet(refs, None, out, tmp, log_fn=lambda m: None)
            self.assertEqual(saved, os.path.join(tmp, "char_sheet.png"))
            self.assertTrue(os.path.isfile(saved))
            self.assertGreater(os.path.getsize(saved), 0)

    def test_front_only_saves_no_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            front = _img(os.path.join(tmp, "front.png"))
            saved = loop.save_sheet({"front": front}, None,
                                    os.path.join(tmp, "m.blend"), tmp,
                                    log_fn=lambda m: None)
            self.assertIsNone(saved)


class SingleShotRunTest(unittest.TestCase):
    def _run(self, tmp, client_results, driver_side=None):
        src = _img(os.path.join(tmp, "char.png"))
        refs = {v: _img(os.path.join(tmp, f"ref_{v}.png"))
                for v in ("front", "side", "back", "top")}
        out = os.path.join(tmp, "model.blend")
        FakeClient.instances.clear()
        fake = FakeClient(client_results)
        driver = mock.Mock(side_effect=driver_side) if driver_side else mock.Mock(
            return_value="import bpy\nprint('BUILT_AND_SAVED')\n")
        with mock.patch.object(loop, "MCPClient", lambda: fake), \
             mock.patch.object(loop.blender_host, "ensure_blender", return_value=True), \
             mock.patch.object(loop.meta_api, "has_key", return_value=True), \
             mock.patch.object(loop.driver, "generate_single_shot_bpy", driver), \
             mock.patch.object(loop, "_render_views", return_value=None):
            # run_dir is created under CWD/runs; keep it inside tmp
            old = os.getcwd()
            os.chdir(tmp)
            try:
                summary = loop.run(src, out, prepared_refs=refs)
            finally:
                os.chdir(old)
        return summary, fake, driver, out, refs

    def test_one_prompt_one_build_and_sheet_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, fake, driver, out, refs = self._run(
                tmp, ["RESET_EMPTY", "BUILT_AND_SAVED"])
            self.assertEqual(driver.call_count, 1)          # one query/prompt
            builds = [c for c in fake.calls if "save_as_mainfile" in c]
            self.assertEqual(len(builds), 1)                # one build
            self.assertTrue(os.path.isfile(out))
            self.assertEqual(summary["stop_reason"], "single-shot")
            self.assertEqual(summary["sheet_output"],
                             os.path.join(tmp, "model_sheet.png"))
            self.assertTrue(os.path.isfile(summary["sheet_output"]))

    def test_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _img(os.path.join(tmp, "char.png"))
            out = os.path.join(tmp, "model.blend")
            fake = FakeClient(["RESET_EMPTY", "Error: boom"])
            driver = mock.Mock(return_value="import bpy\nprint('BUILT_AND_SAVED')\n")
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(loop, "MCPClient", lambda: fake), \
                     mock.patch.object(loop.blender_host, "ensure_blender", return_value=True), \
                     mock.patch.object(loop.meta_api, "has_key", return_value=True), \
                     mock.patch.object(loop.driver, "generate_single_shot_bpy", driver), \
                     mock.patch.object(loop, "_render_views", return_value=None):
                    with self.assertRaises(RuntimeError):
                        loop.run(src, out, prepared_refs={"front": src})
            finally:
                os.chdir(old)
            self.assertEqual(driver.call_count, 1)  # never re-asked
            builds = [c for c in fake.calls if "save_as_mainfile" in c]
            self.assertEqual(len(builds), 1)        # never re-executed


if __name__ == "__main__":
    unittest.main()
