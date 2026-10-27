"""AI critic (Muse Wonder): rates a round 0-10 and plans the next one.

One vision call per round: reference views + render views + the score
history go in; strict JSON comes out:
{rating_10, critical_defects, notes, next_plan, next_prompt, next_actions}
``next_actions`` are bounded parameter deltas the driver can apply
safely; ``next_prompt`` is the human-readable improvement prompt kept
in the round record (and reused for image/driver follow-ups).
"""
import os

from . import meta_api

VIEWS = ("front", "side", "back", "top")

_PROMPT = (
    "You are a strict 3D modelling critic. The first images are the "
    "character references (front/side/back/top where present); the "
    "later images are the current 3D renders in the same order. "
    "Per-view metric scores (0-100): {scores}. Round history (totals): "
    "{history}. Rate the model 0-10 (10 = indistinguishable from the "
    "reference in shape, proportions, outfit and pose; 8 = good with "
    "only minor fixes; 5 = clearly wrong in major ways). Reply with "
    "ONLY JSON: {{\"rating_10\": 0-10, \"critical_defects\": [\"...\"], "
    "\"notes\": \"biggest problems\", \"next_plan\": \"numbered concrete "
    "modelling steps for the next round\", \"next_prompt\": \"one-paragraph "
    "improvement prompt\", \"next_actions\": {{\"width_scale\": 1.0, "
    "\"height_scale\": 1.0, \"depth_scale\": 1.0, \"strategy\": null}}}}. "
    "next_actions scales are multipliers (1.0 = unchanged, keep within "
    "0.85-1.18); strategy is \"A\", \"B\" or null to keep the current one. "
    "Critical defects: extra/missing limbs, broken face, wrong outfit."
)


def _fallback(per_view, total):
    rating = None if total is None else round(max(0.0, min(10.0, total / 10.0)), 2)
    defects = []
    for r in (per_view or {}).values():
        defects.extend(r.get("critical_defects") or [])
    return {"rating_10": rating, "critical_defects": defects,
            "notes": "AI critic unavailable; rating derived from metrics.",
            "next_plan": "", "next_prompt": "", "next_actions": {}}


def critique(ref_paths, render_dir, per_view, total, history):
    """Return the critic dict. Never raises: falls back to metrics."""
    if not meta_api.has_key():
        return _fallback(per_view, total)
    images, labels = [], []
    for v in VIEWS:
        if v in ref_paths and os.path.exists(ref_paths[v]):
            images.append(ref_paths[v]); labels.append(f"ref-{v}")
    for v in VIEWS:
        p = os.path.join(render_dir, f"{v}.png")
        if v in (per_view or {}) and os.path.exists(p):
            images.append(p); labels.append(f"render-{v}")
    if not images:
        return _fallback(per_view, total)
    scores = {v: r.get("score") for v, r in (per_view or {}).items()}
    prompt = _PROMPT.format(scores=scores, history=list(history or []))
    prompt += " Image order: " + ", ".join(labels) + "."
    try:
        raw = meta_api.responses_text(
            "critic", meta_api._text_input(prompt, images))
        out = meta_api._parse_json_object(raw, "critic")
    except Exception:
        return _fallback(per_view, total)
    rating = out.get("rating_10")
    try:
        rating = round(max(0.0, min(10.0, float(rating))), 2)
    except (TypeError, ValueError):
        rating = _fallback(per_view, total)["rating_10"]
    actions = out.get("next_actions") or {}
    if not isinstance(actions, dict):
        actions = {}
    return {"rating_10": rating,
            "critical_defects": list(out.get("critical_defects") or []),
            "notes": str(out.get("notes") or ""),
            "next_plan": str(out.get("next_plan") or ""),
            "next_prompt": str(out.get("next_prompt") or ""),
            "next_actions": actions}
