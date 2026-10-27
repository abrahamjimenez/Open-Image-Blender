"""Single-shot image -> .blend: one prompt, one build, no retries.

Usage: python3 -m src.loop inputs/character.png [--output outputs/model.blend]

Flow (each step happens exactly once):
1. Reference sheet (images only, no Blender): a 2x2 turnaround sheet is
   generated/supplied and split into front/side/back/top. The sheet is
   also saved automatically next to the output .blend as
   ``<output-stem>_sheet.png``.
2. One build: with a Meta API key, one Muse Spark prompt (reference
   images attached) returns one bpy script; without a key, one
   parametric build. The script is executed once in Blender.
3. One headless render of the four preview views, then the .blend is
   copied to the output path.

There is no scoring, critic, rating, plateau or retry loop. If the
single prompt or the single Blender execution fails, the run fails.
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import blender_host, critic, driver, meta_api, modeling, refs, scorer, segmentation
from src.mcp_client import MCPClient

VIEWS = ("front", "side", "back", "top")


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def make_params(front, side=None):
    params = {
        "aspect": front["props"]["aspect"],
        "side_aspect": 0.45,
        "colors": front["colors"],
        "profile": front["profile"],
        "width_scale": 1.0, "height_scale": 1.0, "depth_scale": 1.0,
    }
    if side is not None:
        params["side_aspect"] = round(
            side["props"]["width_px"] / max(1, front["props"]["width_px"]), 3)
    return params


def sheet_output_path(output):
    """Where the generated 3D-angle sheet is saved automatically."""
    stem, _ = os.path.splitext(os.path.abspath(output))
    return stem + "_sheet.png"


def save_sheet(ref_paths, sheet_used, output, run_dir, log_fn=log):
    """Save the 3D-angle sheet next to the output .blend. Returns path or None.

    If a generated/supplied sheet file exists it is copied verbatim.
    Otherwise, when split reference views are available (the GUI flow
    passes ``prepared_refs`` with no sheet file), a labelled 2x2 sheet
    is composed from them so the angle image is still saved.
    """
    dest = sheet_output_path(output)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if sheet_used and os.path.isfile(sheet_used):
            if os.path.abspath(sheet_used) != dest:
                shutil.copyfile(sheet_used, dest)
            log_fn(f"3D angle sheet saved: {dest}")
            return dest
        present = [v for v in VIEWS if ref_paths.get(v)
                   and os.path.isfile(ref_paths[v])]
        if len(present) <= 1:
            return None
        from PIL import Image, ImageDraw
        cell = 480
        sheet = Image.new("RGB", (cell * 2, cell * 2), (245, 240, 230))
        draw = ImageDraw.Draw(sheet)
        for i, view in enumerate(VIEWS):
            x, y = (i % 2) * cell, (i // 2) * cell
            if view in present:
                img = Image.open(ref_paths[view]).convert("RGB")
                img.thumbnail((cell - 16, cell - 40))
                sheet.paste(img, (x + (cell - img.width) // 2, y + 8))
            draw.text((x + 10, y + cell - 24), view, fill=(0, 0, 0))
        sheet.save(dest)
        log_fn(f"3D angle sheet saved: {dest}")
        return dest
    except Exception as e:
        log_fn(f"could not save 3D angle sheet: {e}")
        return None


def _render_views(blend, rdir):
    """One headless render of front/side/back/top into rdir."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        ["blender", "-b", blend, "--python-exit-code", "1", "-P",
         os.path.join(root, "src", "render_views.py"), "--", rdir],
        capture_output=True, text=True, timeout=900)
    if "VIEWS_RENDERED" not in proc.stdout:
        raise RuntimeError(
            f"headless render failed: {proc.stdout[-400:]} {proc.stderr[-400:]}")


def render_and_score(client, params, strategy, run_dir, round_no, ref_data,
                     history=None, segment_prompt="person", custom_code=None):
    # Kept for backwards compatibility with existing tests/callers.
    rdir = os.path.abspath(os.path.join(run_dir, f"round{round_no:02d}"))
    os.makedirs(rdir, exist_ok=True)
    blend = os.path.join(rdir, "model.blend")
    if custom_code:
        code = custom_code + f"\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={blend!r})\n"
        result = client.execute_code(code)
    else:
        result = client.execute_code(
            modeling.build_and_render(params, strategy, blend, rdir))
    if "BUILT_AND_SAVED" not in result:
        raise RuntimeError(f"Blender build failed: {result[:400]}")
    return _finish_round(rdir, blend, params, strategy, round_no, ref_data,
                         history, segment_prompt)


def _finish_round(rdir, blend, params, strategy, round_no, ref_data,
                  history=None, segment_prompt="person"):
    """Headless-render a saved .blend and score/critique it (legacy helper)."""
    _render_views(blend, rdir)
    per_view = {}
    for view, ref in ref_data.items():
        render_path = os.path.join(rdir, f"{view}.png")
        if not os.path.exists(render_path):
            continue
        render = segmentation.analyze(render_path, concept=segment_prompt)
        judge = None
        if meta_api.has_key():
            try:
                judge = meta_api.judge_render(ref["path"], render_path)
            except Exception as e:
                log(f"judge {view} unavailable: {e}")
        per_view[view] = scorer.score_view(ref["data"], render, judge)
    total = scorer.total_score(per_view)
    ref_paths = {v: d["path"] for v, d in ref_data.items()}
    crit = critic.critique(ref_paths, rdir, per_view, total, history or [])
    record = {"round": round_no, "strategy": strategy, "total": total,
              "rating_10": crit["rating_10"],
              "critical_defects": crit["critical_defects"],
              "notes": crit["notes"], "next_plan": crit["next_plan"],
              "next_prompt": crit["next_prompt"],
              "next_actions": crit["next_actions"],
              "per_view": per_view, "params": {k: params[k] for k in
              ("width_scale", "height_scale", "depth_scale", "aspect", "side_aspect")},
              "blend": blend}
    with open(os.path.join(rdir, "score.json"), "w") as f:
        json.dump(record, f, indent=2)
    return record, rdir


def render_existing_blend(blend_src, params, run_dir, round_no, ref_data,
                          history=None, segment_prompt="person"):
    """Score an existing .blend without rebuilding it (legacy helper)."""
    rdir = os.path.abspath(os.path.join(run_dir, f"round{round_no:02d}"))
    os.makedirs(rdir, exist_ok=True)
    blend = os.path.join(rdir, "model.blend")
    shutil.copyfile(os.path.abspath(blend_src), blend)
    return _finish_round(rdir, blend, params, "existing", round_no, ref_data,
                         history, segment_prompt)


def adjust(params, record, ref_data, run_dir):
    """Legacy hill-climb helper, kept for compatibility. Unused by run()."""
    rdir = os.path.join(run_dir, f"round{record['round']:02d}")
    try:
        render = segmentation.analyze(os.path.join(rdir, "front.png"))
        ratio = ref_data["front"]["data"]["props"]["aspect"] / render["props"]["aspect"]
        params["width_scale"] *= max(0.85, min(1.18, 0.5 + 0.5 * ratio))
        if "side" in ref_data and os.path.exists(os.path.join(rdir, "side.png")):
            srender = segmentation.analyze(os.path.join(rdir, "side.png"))
            sratio = (ref_data["side"]["data"]["props"]["aspect"]
                      / srender["props"]["aspect"])
            params["depth_scale"] *= max(0.85, min(1.18, 0.5 + 0.5 * sratio))
    except Exception as e:
        log(f"adjust skipped: {e}")
    return params


def _cancelled(cancel):
    if cancel is None:
        return False
    return bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())


def _ordered_ref_paths(ref_paths):
    return [ref_paths[v] for v in VIEWS if ref_paths.get(v)]


def run(source, output, strategy="auto", on_progress=None, cancel=None,
        sheet_path=None, confirm_sheet=None, prepared_refs=None,
        segment_prompt="person", blend_file=None, sheet_prompt=None,
        **_deprecated):
    """Single-shot run: one sheet, one prompt/build, one render.

    Deprecated loop arguments (``max_rounds``, ``target``,
    ``target_rating``, ``rating_enabled``, ``driver_code``,
    ``experiment``, ...) are accepted and ignored — there are no
    rounds to configure any more.
    """
    if _deprecated:
        log("ignoring loop options (single-shot, no retries): "
            + ", ".join(sorted(_deprecated)))
    def emit(event):
        if on_progress:
            on_progress(event)

    source = os.path.abspath(source)
    output = os.path.abspath(output)
    if blend_file:
        blend_file = os.path.abspath(blend_file)
        if not os.path.isfile(blend_file):
            raise RuntimeError(f"existing Blender file not found: {blend_file}")
        if os.path.abspath(output) == blend_file:
            raise RuntimeError("output must differ from the existing Blender "
                               "file (the original is never overwritten)")
    if _cancelled(cancel):
        raise RuntimeError("cancelled before the build started")
    run_dir = os.path.join(os.path.abspath("runs"), time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    log(f"run dir: {run_dir}")
    if prepared_refs is not None:
        ref_paths = prepared_refs
        sheet_used = None
    else:
        ref_paths, sheet_used = refs.prepare_references(
            source, run_dir, log, sheet_path=sheet_path,
            sheet_prompt=sheet_prompt)
    if confirm_sheet is not None and sheet_used:
        emit({"type": "sheet", "sheet": sheet_used, "refs": ref_paths})
        if not confirm_sheet(sheet_used):
            raise RuntimeError("reference sheet not confirmed; Blender work not started")
    # Save the generated 3D-angle image automatically, next to the .blend.
    saved_sheet = save_sheet(ref_paths, sheet_used, output, run_dir, log)
    if saved_sheet:
        emit({"type": "sheet_saved", "sheet": saved_sheet, "refs": ref_paths})

    ref_data = {v: {"path": p, "data": segmentation.analyze(p, concept=segment_prompt)}
                for v, p in ref_paths.items()}
    params = make_params(ref_data["front"]["data"],
                         ref_data.get("side", {}).get("data"))
    if not blender_host.ensure_blender(log):
        raise RuntimeError("Blender MCP is not available (see setup checks)")
    blend = None
    chosen = "ai" if meta_api.has_key() else "B"
    client = MCPClient()
    try:
        if "execute_blender_code" not in client.tools():
            raise RuntimeError("Blender MCP execute_blender_code tool missing")
        rdir = os.path.abspath(os.path.join(run_dir, "round01"))
        os.makedirs(rdir, exist_ok=True)
        blend = os.path.join(rdir, "model.blend")
        if blend_file:
            opened = client.execute_code(modeling.open_mainfile_code(blend_file))
            if "OPENED_MAINFILE" not in opened:
                raise RuntimeError(f"could not open existing Blender file: {opened[:300]}")
            log(f"Blender file: working from existing {blend_file}")
            chosen = "existing"
            if meta_api.has_key():
                # One prompt, executed once. No fallback edit on failure.
                code = driver.generate_single_shot_bpy(
                    _ordered_ref_paths(ref_paths), params, edit_existing=True)
                code += f"\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={blend!r})\n"
                if "BUILT_AND_SAVED" not in code:
                    code += '\nprint("BUILT_AND_SAVED")\n'
                result = client.execute_code(code)
            else:
                # No key: keep the existing model as-is, just re-save it.
                result = client.execute_code(
                    modeling.scale_edit_code(1.0, 1.0, 1.0)
                    + f"\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={blend!r})\n")
            if "BUILT_AND_SAVED" not in result:
                raise RuntimeError(f"Blender build failed: {result[:400]}")
        else:
            reset = client.execute_code(modeling.reset_empty_code())
            if "RESET_EMPTY" not in reset:
                raise RuntimeError(f"could not start a new Blender file: {reset[:300]}")
            log("Blender file: new empty file")
            if meta_api.has_key():
                # The one and only model prompt for this run.
                chosen = "ai"
                code = driver.generate_single_shot_bpy(
                    _ordered_ref_paths(ref_paths), params)
                code += f"\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={blend!r})\n"
                result = client.execute_code(code)
            else:
                chosen = strategy if strategy in ("A", "B") else "B"
                result = client.execute_code(
                    modeling.build_and_render(params, chosen, blend, rdir))
            if "BUILT_AND_SAVED" not in result:
                raise RuntimeError(f"Blender build failed: {result[:400]}")
        log(f"built once (strategy {chosen}) -> {blend}")
        # One preview render. A render failure does not re-run the build.
        try:
            _render_views(blend, rdir)
        except Exception as e:
            log(f"preview render failed (model still saved): {e}")
        record = {"round": 1, "strategy": chosen, "blend": blend,
                  "sheet": saved_sheet}
        with open(os.path.join(rdir, "result.json"), "w") as f:
            json.dump(record, f, indent=2)
        emit({"type": "round", "record": record, "run_dir": run_dir})
    finally:
        client.close()
    os.makedirs(os.path.dirname(output), exist_ok=True)
    shutil.copyfile(blend, output)
    summary = {"source": source, "output": output, "best_round": 1,
               "best_total": None, "best_rating": None,
               "strategy": chosen, "stop_reason": "single-shot",
               "blend_mode": "existing" if blend_file else "new",
               "blend_file": blend_file, "sheet": saved_sheet,
               "sheet_output": saved_sheet, "run_dir": run_dir}
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    log(f"single-shot .blend -> {output}")
    if saved_sheet:
        log(f"3D angle sheet -> {saved_sheet}")
    emit({"type": "done", "summary": summary})
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Single-shot image -> .blend (no retries)")
    ap.add_argument("source")
    ap.add_argument("--output", default="outputs/model.blend")
    ap.add_argument("--strategy", default="auto", choices=["auto", "A", "B"],
                    help="no-key fallback build strategy (default auto = B)")
    ap.add_argument("--sheet", default=None,
                    help="supplied 2x2 turnaround sheet image (front/side/back/top)")
    ap.add_argument("--confirm-sheet", action="store_true",
                    help="show the reference sheet path and ask before Blender work")
    ap.add_argument("--sheet-prompt", default=None,
                    help="custom prompt for the generated 3D-angle sheet "
                         "(default: the built-in turnaround prompt)")
    ap.add_argument("--segment-prompt", default="person",
                    help="SAM 3.1 concept prompt for segmentation")
    ap.add_argument("--blend-file", default=None,
                    help="work from this existing .blend instead of a new file")
    a = ap.parse_args()

    def confirm(path):
        answer = input(f"Reference sheet: {path}\nStart Blender work? [y/N] ")
        return answer.strip().lower() in ("y", "yes")

    run(a.source, a.output, a.strategy,
        sheet_path=a.sheet, confirm_sheet=confirm if a.confirm_sheet else None,
        segment_prompt=a.segment_prompt, blend_file=a.blend_file,
        sheet_prompt=a.sheet_prompt)
