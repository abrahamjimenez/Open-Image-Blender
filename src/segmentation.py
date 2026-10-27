"""Character segmentation, proportions and palette.

Primary path is SAM 3.1 via the Meta API when a key is configured; the local
background-distance mask below is the always-available fallback and is also
what the scorer uses on renders (plain backgrounds), so scores stay comparable.
"""
import io

import numpy as np
from PIL import Image


def load_mask(path):
    """Return (mask bool array, rgb float array). Background = corner colour."""
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img).astype(np.float32) / 255.0
    h, w, _ = rgb.shape
    corners = np.concatenate([
        rgb[: max(2, h // 20), : max(2, w // 20)].reshape(-1, 3),
        rgb[: max(2, h // 20), -max(2, w // 20):].reshape(-1, 3),
        rgb[-max(2, h // 20):, : max(2, w // 20)].reshape(-1, 3),
        rgb[-max(2, h // 20):, -max(2, w // 20):].reshape(-1, 3)])
    bg = corners.mean(axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    mask = dist > 0.18
    # Drop specks: keep only rows/cols mass via simple opening on a coarse grid.
    return mask, rgb


def mask_bbox(mask):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise ValueError("empty mask: no character found")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def proportions(mask):
    """Vertical band widths and median colours, top to bottom (8 bands)."""
    x0, y0, x1, y1 = mask_bbox(mask)
    bands = []
    for i in range(8):
        ya = y0 + (y1 - y0) * i // 8
        yb = y0 + (y1 - y0) * (i + 1) // 8
        strip = mask[ya:yb, x0:x1]
        width = float(strip.any(axis=0).mean()) if strip.size else 0.0
        bands.append({"width_frac": round(width, 3), "y_frac": round(i / 8, 3)})
    return {"bbox": [x0, y0, x1, y1], "height_px": y1 - y0,
            "width_px": x1 - x0, "aspect": round((x1 - x0) / max(1, y1 - y0), 3),
            "bands": bands}


def band_colors(mask, rgb, bands=8):
    x0, y0, x1, y1 = mask_bbox(mask)
    out = []
    for i in range(bands):
        ya = y0 + (y1 - y0) * i // bands
        yb = y0 + (y1 - y0) * (i + 1) // bands
        sel = rgb[ya:yb, x0:x1][mask[ya:yb, x0:x1]]
        if len(sel) == 0:
            out.append([0.5, 0.5, 0.5])
        else:
            out.append([round(float(c), 3) for c in np.median(sel, axis=0)])
    return out


def row_profile(mask, rows=48):
    """Normalised (left, right, centre_y) profile of the silhouette, top first."""
    x0, y0, x1, y1 = mask_bbox(mask)
    w = max(1, x1 - x0)
    prof = []
    for i in range(rows):
        y = y0 + (y1 - y0) * i // rows
        xs = np.where(mask[y, x0:x1])[0]
        if len(xs) == 0:
            prof.append([0.5, 0.5])
        else:
            prof.append([round(float(xs.min()) / w, 3), round(float(xs.max()) / w, 3)])
    return prof


def _sam_mask(path, rgb, concept):
    """SAM 3.1 mask via the Meta API, decoded to rgb's shape. Raises on failure."""
    from . import meta_api
    raw = meta_api.segment_image(path, concept=concept)
    mimg = Image.open(io.BytesIO(raw)).convert("L")
    if mimg.size != (rgb.shape[1], rgb.shape[0]):
        mimg = mimg.resize((rgb.shape[1], rgb.shape[0]), Image.NEAREST)
    mask = np.asarray(mimg) > 127
    if not mask.any():
        raise ValueError("SAM returned an empty mask")
    return mask


def analyze(path, concept="person", use_sam=True):
    """Return {mask, rgb, props, colors, profile} for an image.

    SAM 3.1 is tried first when a key is configured; any failure falls
    back to the local background-distance mask so analysis never hard-
    fails on the API. ``mask_source`` records which path produced it.
    """
    mask, rgb = load_mask(path)
    source = "local"
    if use_sam:
        try:
            from . import meta_api
            if meta_api.has_key():
                mask = _sam_mask(path, rgb, concept)
                source = "sam-3.1"
        except Exception:
            source = "local"  # expected fallback; caller may log upstream
    return {"mask": mask, "rgb": rgb, "props": proportions(mask),
            "colors": band_colors(mask, rgb), "profile": row_profile(mask),
            "mask_source": source}
