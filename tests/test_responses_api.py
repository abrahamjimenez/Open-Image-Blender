"""Responses-API behaviour: SSE assembly, SAM fallback, critic parsing,
driver clamps, and the 0-10 rating finish line. All HTTP mocked."""
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

from src import critic, driver, meta_api, scorer, segmentation


class _StreamResp:
    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self._lines)


def _sse(events):
    return [b"data: " + json.dumps(e).encode() for e in events] + [b"data: [DONE]"]


class SseAssemblyTest(unittest.TestCase):
    def setUp(self):
        meta_api.clear_file_cache()

    def test_streamed_text_is_assembled(self):
        events = [{"type": "response.output_text.delta", "delta": "hel"},
                  {"type": "response.output_text.delta", "delta": "lo"}]
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "a.png")
            Image.new("RGB", (8, 8)).save(img)

            def fake_post(url, **kw):
                if url.endswith("/files"):
                    m = mock.Mock(); m.status_code = 200
                    m.json = lambda: {"id": "f1"}; return m
                return _StreamResp(_sse(events))

            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}), \
                    mock.patch.object(meta_api.requests, "post", fake_post):
                text = meta_api.responses_text(
                    "critic", meta_api._text_input("hi", [img]))
        self.assertEqual(text, "hello")

    def test_models_use_contributor_driver(self):
        self.assertEqual(meta_api.MODELS["driver"], "muse-spark-1.3-contributor")
        self.assertEqual(meta_api.MODELS["critic"], "muse-wonder-1.0")
        self.assertEqual(meta_api.MODELS["segment"], "sam-3.1")


class CriticTest(unittest.TestCase):
    def test_critic_parses_rating_and_plan(self):
        payload = {"rating_10": 8.4, "critical_defects": [],
                   "notes": "n", "next_plan": "1. fix head",
                   "next_prompt": "p", "next_actions": {"width_scale": 1.05}}
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, "ref.png")
            Image.new("RGB", (16, 16), "white").save(ref)
            os.makedirs(os.path.join(tmp, "r"))
            render = os.path.join(tmp, "r", "front.png")
            Image.new("RGB", (16, 16), "white").save(render)
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}), \
                    mock.patch.object(meta_api, "responses_text",
                                      return_value=json.dumps(payload)), \
                    mock.patch.object(meta_api, "upload_file", return_value="f"):
                out = critic.critique({"front": ref}, os.path.join(tmp, "r"),
                                      {"front": {"score": 80}}, 80, [])
        self.assertEqual(out["rating_10"], 8.4)
        self.assertIn("fix head", out["next_plan"])

    def test_critic_falls_back_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = critic.critique({}, "/nonexistent", {"front": {"score": 1}}, 73, [])
        self.assertEqual(out["rating_10"], 7.3)


class DriverTest(unittest.TestCase):
    def test_actions_are_clamped(self):
        params = {"width_scale": 1.0, "height_scale": 1.0, "depth_scale": 1.0}
        params, strat = driver.apply_actions(
            params, {"width_scale": 5.0, "strategy": "B"})
        self.assertAlmostEqual(params["width_scale"], 1.18)
        self.assertEqual(strat, "B")
        _, strat = driver.apply_actions(params, {"strategy": "ZZZ"})
        self.assertIsNone(strat)


class RatingGateTest(unittest.TestCase):
    PV = {"front": {"score": 50, "critical_defects": []}}

    def test_below_target_continues_at_target_stops(self):
        fin, _ = scorer.check_finish(self.PV, 50, rating=7.9,
                                     rating_enabled=True, target_rating=8.0)
        self.assertFalse(fin)
        fin, _ = scorer.check_finish(self.PV, 50, rating=8.0,
                                     rating_enabled=True, target_rating=8.0)
        self.assertTrue(fin)

    def test_rating_disabled_never_stops_on_rating(self):
        fin, _ = scorer.check_finish(self.PV, 50, rating=9.9,
                                     rating_enabled=False, target_rating=8.0)
        self.assertFalse(fin)  # metric total 50 < 85 still gates

    def test_critical_defects_block_finish(self):
        pv = {"front": {"score": 99, "critical_defects": ["extra arm"]}}
        fin, reasons = scorer.check_finish(pv, 99, rating=9.5,
                                           rating_enabled=True)
        self.assertFalse(fin)
        self.assertTrue(any("critical" in r for r in reasons))


class SamFallbackTest(unittest.TestCase):
    def test_sam_mask_used_when_api_returns_png_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "c.png")
            base = Image.new("RGB", (32, 32), "white")
            for x in range(10, 22):
                for y in range(6, 26):
                    base.putpixel((x, y), (20, 20, 160))
            base.save(img)
            buf = io.BytesIO()
            mask_img = Image.new("L", (32, 32), 0)
            for x in range(10, 22):
                for y in range(6, 26):
                    mask_img.putpixel((x, y), 255)
            mask_img.save(buf, format="PNG")
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}), \
                    mock.patch.object(meta_api, "segment_image",
                                      return_value=buf.getvalue()):
                out = segmentation.analyze(img)
        self.assertEqual(out["mask_source"], "sam-3.1")
        self.assertTrue(out["mask"].any())

    def test_sam_failure_falls_back_to_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "c.png")
            base = Image.new("RGB", (32, 32), "white")
            for x in range(10, 22):
                for y in range(6, 26):
                    base.putpixel((x, y), (20, 20, 160))
            base.save(img)
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}), \
                    mock.patch.object(meta_api, "segment_image",
                                      side_effect=meta_api.MetaAPIError("boom")):
                out = segmentation.analyze(img)
        self.assertEqual(out["mask_source"], "local")


if __name__ == "__main__":
    unittest.main()
