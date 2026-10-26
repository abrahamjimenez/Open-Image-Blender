"""Reference views: use the user's own views when supplied, else generate.

User views are looked for next to the source image as
<stem>_side.png, <stem>_back.png, <stem>_top.png (or a views/ folder).
Generation uses Muse Image and requires MODEL_API_KEY.
"""
import os

from . import meta_api

VIEWS = ("side", "back", "top")


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


def get_references(source_path, workdir, log):
    """Return {view: path}. Front is always the source image itself."""
    refs = {"front": source_path}
    refs.update(find_user_views(source_path))
    for view in VIEWS:
        if view in refs:
            log(f"reference {view}: using supplied {refs[view]}")
            continue
        out = os.path.join(workdir, f"ref_{view}.png")
        if meta_api.has_key():
            try:
                meta_api.generate_view(source_path, view, out)
                refs[view] = out
                log(f"reference {view}: generated with Muse Image")
                continue
            except Exception as e:
                log(f"reference {view}: generation failed ({e}); continuing without it")
        else:
            log(f"reference {view}: no MODEL_API_KEY; continuing without it")
    return refs
