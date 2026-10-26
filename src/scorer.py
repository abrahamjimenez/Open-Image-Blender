"""Option C hybrid similarity scoring.

Per view: 35% silhouette IoU + 20% colour match + 45% Muse Wonder rubric.
Without an API key the judge part is dropped and the metric weights are
renormalised (flagged in the result). View weights: side .40, front .35,
back .20, top .05. Missing views are dropped and weights renormalised.
"""
import numpy as np
from PIL import Image

from . import segmentation

VIEW_WEIGHTS = {"side": 0.40, "front": 0.35, "back": 0.20, "top": 0.05}
W_SIL, W_COL, W_JUDGE = 0.35, 0.20, 0.45


def _aligned_mask(mask, size=128):
    x0, y0, x1, y1 = segmentation.mask_bbox(mask)
    crop = Image.fromarray((mask[y0:y1, x0:x1] * 255).astype(np.uint8))
    return np.asarray(crop.resize((size, size))) > 127


def silhouette_iou(ref_mask, render_mask):
    a, b = _aligned_mask(ref_mask), _aligned_mask(render_mask)
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def color_match(ref_mask, ref_rgb, render_mask, render_rgb, bins=2):
    """Shading-tolerant: coarse palette histogram + masked mean-colour match.
    3D shading shifts exact RGB values, so fine bins would score near zero
    even for the right colours."""
    def hist(mask, rgb):
        sel = rgb[mask]
        if len(sel) == 0:
            return np.zeros(bins ** 3)
        idx = (np.clip(sel, 0, 0.999) * bins).astype(int)
        h = np.zeros(bins ** 3)
        np.add.at(h, (idx[:, 0] * bins + idx[:, 1]) * bins + idx[:, 2], 1)
        return h / h.sum()

    def mean(mask, rgb):
        sel = rgb[mask]
        return sel.mean(axis=0) if len(sel) else np.zeros(3)

    a, b = hist(ref_mask, ref_rgb), hist(render_mask, render_rgb)
    hist_score = float(np.minimum(a, b).sum())
    dist = float(np.sqrt(((mean(ref_mask, ref_rgb)
                           - mean(render_mask, render_rgb)) ** 2).sum()))
    mean_score = max(0.0, 1.0 - dist / 1.2)
    return 0.5 * hist_score + 0.5 * mean_score


def score_view(ref, render, judge=None):
    sil = silhouette_iou(ref["mask"], render["mask"])
    col = color_match(ref["mask"], ref["rgb"], render["mask"], render["rgb"])
    if judge is None:
        score = 100 * (W_SIL * sil + W_COL * col) / (W_SIL + W_COL)
    else:
        score = 100 * (W_SIL * sil + W_COL * col + W_JUDGE * judge["score"] / 100)
    return {"score": round(float(score), 2), "silhouette": round(sil, 4),
            "color": round(col, 4),
            "judge": None if judge is None else judge.get("score"),
            "critical_defects": [] if judge is None else judge.get("critical_defects", [])}


def total_score(per_view):
    total_w = sum(VIEW_WEIGHTS[v] for v in per_view)
    if total_w == 0:
        return 0.0
    return round(sum(per_view[v]["score"] * VIEW_WEIGHTS[v]
                     for v in per_view) / total_w, 2)


def check_finish(per_view, total, target=85.0):
    """Return (finished, reasons). Side floor 75, other views 70."""
    reasons = []
    if total < target:
        reasons.append(f"total {total} < {target}")
    for view, r in per_view.items():
        floor = 75.0 if view == "side" else 70.0
        if r["score"] < floor:
            reasons.append(f"{view} {r['score']} < {floor}")
        if r["critical_defects"]:
            reasons.append(f"{view} critical defects: {r['critical_defects']}")
    return (not reasons), reasons
