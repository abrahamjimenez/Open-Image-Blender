"""AI driver (Muse Spark contributor): one prompt -> one bpy script.

The app is single-shot: ``generate_single_shot_bpy`` sends the reference
image(s) once, gets one bpy script back, and the caller executes it
exactly once. There is no critic plan and no retry round.

The bounded ``scale_multipliers``/``apply_actions`` helpers are kept
only for the existing-file tests that exercise them.
"""
from . import meta_api

_SCALE_KEYS = ("width_scale", "height_scale", "depth_scale")


def scale_multipliers(actions):
    """Clamped per-round scale multipliers from critic next_actions."""
    out = {}
    for key in _SCALE_KEYS:
        try:
            mult = float((actions or {}).get(key, 1.0))
        except (TypeError, ValueError):
            mult = 1.0
        out[key] = max(0.85, min(1.18, mult))
    return out


def apply_actions(params, actions):
    """Apply critic next_actions to params in place; return params."""
    for key, mult in scale_multipliers(actions).items():
        params[key] = round(max(0.4, min(2.5, params.get(key, 1.0) * mult)), 4)
    strategy = (actions or {}).get("strategy")
    return params, (strategy if strategy in ("A", "B") else None)


def _extract_bpy(raw):
    if "```" in raw:
        raw = raw.split("```", 2)[1]
        raw = raw.removeprefix("python").strip()
    if "import bpy" not in raw:
        raise meta_api.MetaAPIError("driver returned no bpy script")
    return raw


def generate_single_shot_bpy(image_paths, params, timeout=300,
                             edit_existing=False):
    """One prompt, one bpy script. No plan, no critic, no retry.

    ``image_paths`` are the reference views (front first) sent with the
    prompt. The caller executes the returned code exactly once; if it
    fails, the run fails — it is never re-asked or retried.
    """
    opening = ("The scene already contains a model in an existing file: "
               "edit it in place, do not delete all objects. "
               if edit_existing else
               "Start by clearing all objects/materials/cameras/lights. ")
    ask = (
        "Look at the attached reference image(s) of a character/object "
        "(front view first, then side/back/top where present). Write a "
        "complete, self-contained Blender Python (bpy) script that builds "
        f"a 3D model matching them as closely as you can in one pass. {opening}"
        "Use only bpy and mathutils. Match the silhouette, proportions, "
        "colours, outfit/parts and pose. Create materials with the "
        "reference colours. Do not render or save inside the script; the "
        "caller renders and saves. End with "
        "print(\"BUILT_AND_SAVED\"). Reply with ONLY a python code block.\n"
        f"Measured proportions: aspect (width/height)="
        f"{params.get('aspect')}, side_aspect={params.get('side_aspect')}, "
        f"band colours (top to bottom)={params.get('colors')}"
    )
    paths = [p for p in (image_paths or []) if p]
    raw = meta_api.responses_text(
        "driver", meta_api._text_input(ask, paths), timeout=timeout)
    return _extract_bpy(raw)


def generate_bpy(plan, prompt_text, params, timeout=300, edit_existing=False):
    """Ask Spark for a complete bpy build script. Returns code or raises."""
    opening = ("The scene already contains the model to improve: edit it in "
               "place, do not delete all objects. " if edit_existing else
               "Start by clearing all objects/materials/cameras/lights. ")
    ask = (
        "Write a complete, self-contained Blender Python (bpy) script that "
        "builds the character described below, improving on the previous "
        f"round. {opening}"
        "Use only bpy and mathutils. Do not render or save inside the "
        "script; the caller renders and saves. End with "
        "print(\"BUILT_AND_SAVED\"). Reply with ONLY a python code block.\n"
        f"Plan: {plan}\nPrompt: {prompt_text}\nCurrent scales: "
        f"width={params.get('width_scale')}, height={params.get('height_scale')}, "
        f"depth={params.get('depth_scale')}, aspect={params.get('aspect')}"
    )
    raw = meta_api.responses_text(
        "driver", meta_api._text_input(ask), timeout=timeout)
    return _extract_bpy(raw)
