"""Stage 1 (pre-Blender): 3D-angle reference views of the source image.

The source image is the front view. The other angles are created as IMAGES
first — an AI-generated 2x2 turnaround sheet (front / side / back / top) in
the style of the example the project was designed around — and only after
the user confirms that sheet does Blender work begin.

Accepted inputs, in priority order:
1. A supplied turnaround sheet: <stem>_sheet.png next to the source, or an
   explicit sheet path. It is split into the four views.
2. Supplied separate views: <stem>_side.png etc.
3. An AI sheet generated with Muse Image (needs MODEL_API_KEY).
Without any of those, only the front view is available and Blender work
proceeds front-only with a warning.
"""
import os

from PIL import Image

from . import meta_api

VIEWS = ("side", "back", "top")
# 2x2 sheet layout: quadrant -> view. Labels sit below each panel, so each
# crop keeps the top ~82% of its cell and drops the label strip.
CELLS = {"front": (0, 0), "side": (1, 0), "back": (0, 1), "top": (1, 1)}


def split_sheet(sheet_path, workdir):
    """Split a 2x2 turnaround sheet into {view: path} PNGs in workdir."""
    img = Image.open(sheet_path).convert("RGB")
    w, h = img.size
    out = {}
    os.makedirs(workdir, exist_ok=True)
    for view, (cx, cy) in CELLS.items():
        x0 = int(w * cx / 2 + w * 0.02)
        x1 = int(w * (cx + 1) / 2 - w * 0.02)
        y0 = int(h * cy / 2 + h * 0.02)
        y1 = int(h * cy / 2 + h * 0.41)  # exclude the caption under the panel
        path = os.path.join(workdir, f"ref_{view}.png")
        img.crop((x0, y0, x1, y1)).save(path)
        out[view] = path
    return out


def find_user_sheet(source_path):
    stem, _ = os.path.splitext(source_path)
    for cand in (f"{stem}_sheet.png", f"{stem}_sheet.jpg",
                 os.path.join(os.path.dirname(source_path), "sheet.png")):
        if os.path.exists(cand):
            return cand
    return None


def find_user_views(source_path):
    stem, _ = os.path.splitext(source_path)
    found = {}
    for view in VIEWS:
        for cand in (f"{stem}_{view}.png", f"{stem}_{view}.jpg",
                     os.path.join(os.path.dirname(source_path), "views",
                                  f"{os.path.basename(stem)}_{view}.png")):
            if os.path.exists(cand):
                found[view] = cand
                break
    return found


def generate_sheet(source_path, out_path, prompt=None):
    """Ask Muse Image for the 2x2 turnaround sheet. Pre-Blender step."""
    return meta_api.generate_reference_sheet(source_path, out_path, prompt=prompt)


def prepare_references(source_path, workdir, log, sheet_path=None,
                       sheet_prompt=None):
    """Return (refs, sheet_used). refs maps view -> image path.

    This function performs NO Blender work. Callers show the sheet/views to
    the user for confirmation before starting the Blender loop.
    """
    os.makedirs(workdir, exist_ok=True)
    sheet = sheet_path or find_user_sheet(source_path)
    if sheet:
        log(f"reference sheet: using supplied {sheet}")
        return split_sheet(sheet, workdir), sheet
    views = find_user_views(source_path)
    if views:
        refs = {"front": source_path}
        refs.update(views)
        for v in views:
            log(f"reference {v}: using supplied {views[v]}")
        return refs, None
    out = os.path.join(workdir, "ref_sheet.png")
    if meta_api.has_key():
        try:
            generate_sheet(source_path, out, prompt=sheet_prompt)
            log("reference sheet: generated with Muse Image (pre-Blender)")
            return split_sheet(out, workdir), out
        except Exception as e:
            log(f"reference sheet generation failed ({e}); front view only")
    else:
        log("reference sheet: no MODEL_API_KEY and none supplied; front view only")
    return {"front": source_path}, None


def get_references(source_path, workdir, log):
    """Backwards-compatible wrapper returning only the refs dict."""
    refs, _ = prepare_references(source_path, workdir, log)
    return refs
