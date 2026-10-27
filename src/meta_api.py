"""Meta Model API client — Responses API (https://api.meta.ai/v1/responses).

All models go through POST /responses. Images use the image_generation
tool (non-streaming, wait-for-completed). Wonder / Spark / SAM stream
over SSE (``data:`` lines terminated by ``[DONE]``). SAM first uploads
the image via POST /files (purpose=user_data) and references it by
file_id. Settings follow the user-supplied examples verbatim where
they apply. Only allow-listed models are used.
"""
import base64
import json
import os

import requests

BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
MODELS = {
    "judge": "muse-wonder-1.0",
    "critic": "muse-wonder-1.0",
    "driver": "muse-spark-1.3-contributor",
    "image": "muse-image-1.0",
    "segment": "sam-3.1",
    "triage": "muse-glimmer-1.0",
    "fallback": "muse-spark-open-1.0",
}

_TEXT_DEFAULTS = {"temperature": 1, "top_p": 1, "max_output_tokens": 32000,
                  "reasoning": {"effort": "medium"}}
_IMAGE_DEFAULTS = {"temperature": 0.6, "top_p": 0.9, "max_output_tokens": 2048,
                   "store": True}


class MetaAPIError(RuntimeError):
    pass


def has_key():
    return bool(os.environ.get("MODEL_API_KEY"))


def _headers(extra=None):
    if not has_key():
        raise MetaAPIError("MODEL_API_KEY is not set (copy .env.example to .env)")
    h = {"Authorization": "Bearer " + os.environ["MODEL_API_KEY"]}
    if extra:
        h.update(extra)
    return h


def _url(path):
    return BASE.rstrip("/") + path


# -- file uploads ------------------------------------------------------
_file_cache = {}


def upload_file(path):
    """POST /files (purpose=user_data); return the file_id (cached per path)."""
    apath = os.path.abspath(path)
    if apath in _file_cache:
        return _file_cache[apath]
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}.get(os.path.splitext(apath)[1].lower(),
                                       "application/octet-stream")
    with open(apath, "rb") as f:
        resp = requests.post(
            _url("/files"), headers=_headers(), data={"purpose": "user_data"},
            files={"file": (os.path.basename(apath), f, mime)}, timeout=120)
    if resp.status_code >= 400:
        raise MetaAPIError(f"/files HTTP {resp.status_code}: {resp.text[:400]}")
    fid = resp.json().get("id")
    if not isinstance(fid, str) or not fid:
        raise MetaAPIError("File upload completed without a file id.")
    _file_cache[apath] = fid
    return fid


def clear_file_cache():
    _file_cache.clear()


# -- /responses core ----------------------------------------------------

def _iter_sse(resp):
    """Yield parsed JSON events from an SSE response (data: lines)."""
    for line in resp.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data.strip() == "[DONE]":
            break
        try:
            yield json.loads(data)
        except ValueError:
            continue


def _event_text(evt):
    """Best-effort text delta carried by one streamed event."""
    if not isinstance(evt, dict):
        return ""
    if isinstance(evt.get("delta"), str):
        return evt["delta"]
    if isinstance(evt.get("text"), str) and "delta" in str(evt.get("type", "")):
        return evt["text"]
    return ""


def _output_text(result):
    """Extract assistant text from a completed Responses result."""
    if not isinstance(result, dict):
        return ""
    chunks = []
    for item in result.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    if chunks:
        return "".join(chunks)
    if isinstance(result.get("output_text"), str):
        return result["output_text"]
    return ""


def responses_create(payload, timeout=300):
    """POST /responses. Handles both streamed (SSE) and completed replies.

    Returns a normalised dict: the completed response when available,
    otherwise one assembled from streamed events, always carrying
    ``output`` (list), ``id`` when seen, and ``_events`` for callers
    that need raw streamed payloads (SAM masks).
    """
    stream = bool(payload.get("stream"))
    headers = _headers({"Content-Type": "application/json"})
    if stream:
        headers["Accept"] = "text/event-stream"
    if not stream:
        resp = requests.post(_url("/responses"), headers=headers,
                             json=payload, timeout=timeout)
        if resp.status_code >= 400:
            raise MetaAPIError(
                f"/responses HTTP {resp.status_code}: {resp.text[:400]}")
        result = resp.json()
        if result.get("error") or result.get("status") not in (None, "completed"):
            raise MetaAPIError(str(result.get("error")
                                   or result.get("incomplete_details")
                                   or result)[:400])
        return result
    text_parts, events, final, resp_id = [], [], None, None
    with requests.post(_url("/responses"), headers=headers, json=payload,
                       stream=True, timeout=timeout) as resp:
        if resp.status_code >= 400:
            raise MetaAPIError(
                f"/responses HTTP {resp.status_code}: {resp.text[:400]}")
        for evt in _iter_sse(resp):
            events.append(evt)
            text_parts.append(_event_text(evt))
            if isinstance(evt.get("response"), dict):
                final = evt["response"]
            if isinstance(evt.get("id"), str):
                resp_id = evt["id"]
    if final is not None:
        final["_events"] = events
        return final
    out = {"id": resp_id, "status": "completed", "_events": events,
           "output": [{"type": "message", "content": [
               {"type": "output_text", "text": "".join(text_parts)}]}]}
    return out


def responses_text(model_key, input_items, timeout=300, **overrides):
    """Streamed text call (Wonder / Spark). Returns the full reply text."""
    payload = {"model": MODELS[model_key], "input": input_items,
               "stream": True, **_TEXT_DEFAULTS, **overrides}
    result = responses_create(payload, timeout=timeout)
    text = _output_text(result)
    if not text:
        # Fall back to concatenated deltas if the final shape differed.
        text = "".join(_event_text(e) for e in result.get("_events", []))
    return text


def _text_input(text, image_paths=None):
    content = [{"type": "input_text", "text": text}]
    for p in image_paths or []:
        content.append({"type": "input_image", "file_id": upload_file(p)})
    return [{"type": "message", "role": "user", "content": content}]


def _parse_json_object(raw, what):
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception as e:
        raise MetaAPIError(f"{what} returned unparseable output: {raw[:200]}") from e


# -- image generation (muse-image-1.0) -----------------------------------

def generate_image(prompt, out_path, source_path=None,
                   previous_response_id=None, timeout=300):
    """Image via the image_generation tool on /responses (non-streaming).

    With ``source_path`` the source is uploaded and sent as input_image
    (image-to-image); ``previous_response_id`` chains an edit onto a
    prior generation instead. Returns out_path; the response id is kept
    in ``<out_path>.response.json`` for follow-up edits.
    """
    content = [{"type": "input_text", "text": prompt}]
    if source_path and not previous_response_id:
        content.append({"type": "input_image",
                        "file_id": upload_file(source_path)})
    payload = {"model": MODELS["image"],
               "input": [{"type": "message", "role": "user", "content": content}],
               "stream": False,
               "tools": [{"type": "image_generation",
                          "enable_image_search": True, "enable_shell": True,
                          "enable_web_search": True, "output_format": "png",
                          "reasoning_strength": "high"}],
               **_IMAGE_DEFAULTS}
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    result = responses_create(payload, timeout=timeout)
    saved = False
    for item in result.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "image_generation_call" \
                and item.get("result"):
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(item["result"]))
            saved = True
    if not saved:
        raise MetaAPIError(f"image request returned no image: {str(result)[:300]}")
    if result.get("id"):
        try:
            with open(out_path + ".response.json", "w") as f:
                json.dump({"id": result["id"]}, f)
        except OSError:
            pass
    return out_path


def generate_reference_sheet(source_path, out_path):
    """One 2x2 turnaround sheet (front/side/back/top), pre-Blender."""
    prompt = (
        "Create a 2x2 turnaround sheet of 3D angles of the character in the "
        "reference image. Top-left: Front View. Top-right: Side View. "
        "Bottom-left: Back View. Bottom-right: Top View. Same character, "
        "same outfit, colors, proportions and pose in every panel, shown as "
        "a clean 3D model on the same plain cream background, with the "
        "view name labelled under each panel."
    )
    return generate_image(prompt, out_path, source_path=source_path, timeout=300)


def generate_view(source_path, view, out_path):
    prompt = (
        f"Same animated character as the reference, exact same outfit, colors, proportions "
        f"and pose, seen from the {view}. Plain white background, full body, centered."
    )
    return generate_image(prompt, out_path, source_path=source_path, timeout=300)


# -- vision judge (muse-wonder-1.0) ----------------------------------------

def judge_render(ref_path, render_path):
    """Wonder rubric judge. Returns {score 0-100, critical_defects, notes}."""
    prompt = (
        "Compare the 3D render (second image) to the character reference (first image). "
        "Reply with ONLY JSON: {\"score\": 0-100, \"critical_defects\": [\"...\"], "
        "\"notes\": \"biggest fix needed\"}. Score proportions, face/hair, outfit, pose, "
        "and artifacts. Critical defects: extra/missing limbs, broken face, wrong outfit."
    )
    raw = responses_text("judge", _text_input(prompt, [ref_path, render_path]))
    return _parse_json_object(raw, "judge")


# -- segmentation (sam-3.1) -------------------------------------------------

def _find_mask_b64(obj):
    """Recursively find a base64 mask payload in a SAM result/event."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if "mask" in str(key).lower() and isinstance(val, str) and len(val) > 100:
                return val
        for val in obj.values():
            found = _find_mask_b64(val)
            if found:
                return found
    elif isinstance(obj, list):
        for val in obj:
            found = _find_mask_b64(val)
            if found:
                return found
    return None


def segment_image(path, concept="person", timeout=300):
    """SAM 3.1 segmentation. Returns raw mask bytes (PNG) or raises.

    The streamed payload shape is not fully documented in the supplied
    example (it only prints events), so the mask is located by a
    recursive search for a base64 mask field across the final response
    and every streamed event. Callers must treat failure as expected
    and fall back to local segmentation.
    """
    payload = {
        "model": MODELS["segment"],
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": concept},
            {"type": "input_image", "file_id": upload_file(path)},
        ]}],
        "stream": True,
        "metadata": {"mask_encoding": "lossless"},
    }
    result = responses_create(payload, timeout=timeout)
    b64 = _find_mask_b64(result) or _find_mask_b64(result.get("_events", []))
    if not b64:
        raise MetaAPIError("SAM response carried no decodable mask payload")
    try:
        return base64.b64decode(b64)
    except Exception as e:
        raise MetaAPIError(f"SAM mask is not valid base64: {e}") from e


# -- kept for backwards compatibility ---------------------------------------

def image_to_data_uri(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    with open(path, "rb") as f:
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode()
