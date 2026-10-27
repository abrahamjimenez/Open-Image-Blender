"""Meta Model API client (OpenAI-compatible). Only allow-listed models are used."""
import base64
import json
import os
import urllib.request
import urllib.error

BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
MODELS = {
    "judge": "muse-wonder-1.0",
    "driver": "muse-spark-1.3",
    "image": "muse-image-1.0",
    "segment": "sam-3.1",
    "triage": "muse-glimmer-1.0",
    "fallback": "muse-spark-open-1.0",
}


class MetaAPIError(RuntimeError):
    pass


def has_key():
    return bool(os.environ.get("MODEL_API_KEY"))


def _post(path, payload, timeout=120):
    if not has_key():
        raise MetaAPIError("MODEL_API_KEY is not set (copy .env.example to .env)")
    req = urllib.request.Request(
        BASE.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["MODEL_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise MetaAPIError(f"{path} HTTP {e.code}: {e.read().decode()[:400]}") from e


def chat(model_key, messages, timeout=120):
    out = _post("/chat/completions", {"model": MODELS[model_key], "messages": messages}, timeout)
    return out["choices"][0]["message"]["content"]


def image_to_data_uri(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    with open(path, "rb") as f:
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode()


def judge_render(ref_path, render_path):
    """Muse Wonder rubric judge. Returns dict with score/critical_defects/notes."""
    prompt = (
        "Compare the 3D render (second image) to the character reference (first image). "
        "Reply with ONLY JSON: {\"score\": 0-100, \"critical_defects\": [\"...\"], "
        "\"notes\": \"biggest fix needed\"}. Score proportions, face/hair, outfit, pose, "
        "and artifacts. Critical defects: extra/missing limbs, broken face, wrong outfit."
    )
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_to_data_uri(ref_path)}},
        {"type": "image_url", "image_url": {"url": image_to_data_uri(render_path)}},
    ]}]
    raw = chat("judge", msgs)
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception as e:
        raise MetaAPIError(f"judge returned unparseable output: {raw[:200]}") from e


def generate_reference_sheet(source_path, out_path):
    """One 2x2 turnaround sheet image: front, side, back, top of the SAME
    3D character, matching the source design/pose, plain background, each
    panel labelled. This is an image step — no Blender is involved."""
    prompt = (
        "Create a 2x2 turnaround sheet of 3D angles of the character in the "
        "reference image. Top-left: Front View. Top-right: Side View. "
        "Bottom-left: Back View. Bottom-right: Top View. Same character, "
        "same outfit, colors, proportions and pose in every panel, shown as "
        "a clean 3D model on the same plain cream background, with the "
        "view name labelled under each panel."
    )
    out = _post("/images/generations", {
        "model": MODELS["image"],
        "prompt": prompt,
        "image": image_to_data_uri(source_path),
    }, timeout=240)
    data = out.get("data", [{}])[0]
    if data.get("b64_json"):
        raw = base64.b64decode(data["b64_json"])
    elif data.get("url"):
        with urllib.request.urlopen(data["url"], timeout=120) as r:
            raw = r.read()
    else:
        raise MetaAPIError(f"sheet generation returned no image: {str(out)[:300]}")
    with open(out_path, "wb") as f:
        f.write(raw)
    return out_path


def generate_view(source_path, view, out_path):
    """Muse Image multi-view generation. Raises MetaAPIError if endpoint/model rejects."""
    prompt = (
        f"Same animated character as the reference, exact same outfit, colors, proportions "
        f"and pose, seen from the {view}. Plain white background, full body, centered."
    )
    out = _post("/images/generations", {
        "model": MODELS["image"],
        "prompt": prompt,
        "image": image_to_data_uri(source_path),
    }, timeout=180)
    data = out.get("data", [{}])[0]
    if data.get("b64_json"):
        raw = base64.b64decode(data["b64_json"])
    elif data.get("url"):
        with urllib.request.urlopen(data["url"], timeout=120) as r:
            raw = r.read()
    else:
        raise MetaAPIError(f"image generation returned no image data: {str(out)[:300]}")
    with open(out_path, "wb") as f:
        f.write(raw)
    return out_path
