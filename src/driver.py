"""AI driver (Muse Spark contributor): turns a critic plan into action.

Phase A (default): bounded parameter multipliers applied to the
Strategy A/B params — safe and testable.
Phase B (opt-in, --driver-code): Spark writes free-form bpy for the
next round. The caller must execute it with a timeout/sentinel check
and keep the best-so-far .blend, because generated code can fail.
"""
from . import meta_api

_SCALE_KEYS = ("width_scale", "height_scale", "depth_scale")


def apply_actions(params, actions):
    """Apply critic next_actions to params in place; return params."""
    actions = actions or {}
    for key in _SCALE_KEYS:
        try:
            mult = float(actions.get(key, 1.0))
        except (TypeError, ValueError):
            continue
        mult = max(0.85, min(1.18, mult))
        params[key] = round(max(0.4, min(2.5, params.get(key, 1.0) * mult)), 4)
    strategy = actions.get("strategy")
    return params, (strategy if strategy in ("A", "B") else None)


def generate_bpy(plan, prompt_text, params, timeout=300):
    """Ask Spark for a complete bpy build script. Returns code or raises."""
    ask = (
        "Write a complete, self-contained Blender Python (bpy) script that "
        "builds the character described below, improving on the previous "
        "round. Start by clearing all objects/materials/cameras/lights. "
        "Use only bpy and mathutils. Do not render or save inside the "
        "script; the caller renders and saves. End with "
        "print(\"BUILT_AND_SAVED\"). Reply with ONLY a python code block.\n"
        f"Plan: {plan}\nPrompt: {prompt_text}\nCurrent scales: "
        f"width={params.get('width_scale')}, height={params.get('height_scale')}, "
        f"depth={params.get('depth_scale')}, aspect={params.get('aspect')}"
    )
    raw = meta_api.responses_text(
        "driver", meta_api._text_input(ask), timeout=timeout)
    if "```" in raw:
        raw = raw.split("```", 2)[1]
        raw = raw.removeprefix("python").strip()
    if "import bpy" not in raw:
        raise meta_api.MetaAPIError("driver returned no bpy script")
    return raw
