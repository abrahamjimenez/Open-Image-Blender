"""Autonomous image -> .blend loop with Option C scoring and stop rules.

Usage: python3 -m src.loop inputs/character.png [--max-rounds 25] [--target 85]
       python3 -m src.loop inputs/character.png --experiment
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
        # Depth of the model relative to its front width.
        params["side_aspect"] = round(
            side["props"]["width_px"] / max(1, front["props"]["width_px"]), 3)
    return params


def render_and_score(client, params, strategy, run_dir, round_no, ref_data,
                     history=None, segment_prompt="person", custom_code=None):
    # Blender is a separate process: never hand it a relative save path.
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
    """Headless-render a saved .blend and score/critique the round."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        ["blender", "-b", blend, "--python-exit-code", "1", "-P",
         os.path.join(root, "src", "render_views.py"), "--", rdir],
        capture_output=True, text=True, timeout=900)
    if "VIEWS_RENDERED" not in proc.stdout:
        raise RuntimeError(f"headless render failed: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    per_view, judges = {}, {}
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
    """Score an existing .blend as a round without rebuilding it.

    The file is copied into the round dir first: the original the user
    pointed at is never rendered from or overwritten in place.
    """
    rdir = os.path.abspath(os.path.join(run_dir, f"round{round_no:02d}"))
    os.makedirs(rdir, exist_ok=True)
    blend = os.path.join(rdir, "model.blend")
    shutil.copyfile(os.path.abspath(blend_src), blend)
    return _finish_round(rdir, blend, params, "existing", round_no, ref_data,
                         history, segment_prompt)


def adjust(params, record, ref_data, run_dir):
    """Hill-climb: fix silhouette aspect mismatch, explore on plateau."""
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


def run(source, output, max_rounds=25, target=85.0, strategy="auto", experiment=False,
        on_progress=None, cancel=None, sheet_path=None, confirm_sheet=None,
        prepared_refs=None, target_rating=8.0, rating_enabled=True,
        driver_code=False, segment_prompt="person", blend_file=None):
    def emit(event):
        if on_progress:
            on_progress(event)

    # Absolute paths everywhere: Blender (via MCP) and the headless renderer
    # are separate processes with different working directories, so a
    # relative runs/... path saved fine for us but not for Blender.
    source = os.path.abspath(source)
    output = os.path.abspath(output)
    if blend_file:
        blend_file = os.path.abspath(blend_file)
        if not os.path.isfile(blend_file):
            raise RuntimeError(f"existing Blender file not found: {blend_file}")
        if os.path.abspath(output) == blend_file:
            raise RuntimeError("output must differ from the existing Blender "
                               "file (the original is never overwritten)")
    run_dir = os.path.join(os.path.abspath("runs"), time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    log(f"run dir: {run_dir}")
    if prepared_refs is not None:
        ref_paths = prepared_refs
        sheet_used = None
    else:
        # Stage 1 is image-only: build/confirm the 3D-angle references
        # BEFORE any Blender work starts.
        ref_paths, sheet_used = refs.prepare_references(
            source, run_dir, log, sheet_path=sheet_path)
    if confirm_sheet is not None and sheet_used:
        emit({"type": "sheet", "sheet": sheet_used, "refs": ref_paths})
        if not confirm_sheet(sheet_used):
            raise RuntimeError("reference sheet not confirmed; Blender work not started")
    ref_data = {v: {"path": p, "data": segmentation.analyze(p, concept=segment_prompt)}
                for v, p in ref_paths.items()}
    params = make_params(ref_data["front"]["data"],
                         ref_data.get("side", {}).get("data"))
    if not blender_host.ensure_blender(log):
        raise RuntimeError("Blender MCP is not available (see setup checks)")
    client = MCPClient()
    try:
        if "execute_blender_code" not in client.tools():
            raise RuntimeError("Blender MCP execute_blender_code tool missing")
        strategies = ["A", "B"] if (experiment or strategy == "auto") else [strategy]
        best = None
        chosen = strategies[0]
        round_no = 0
        stop_reason = "max-rounds"
        history = []
        if blend_file:
            # Existing-file mode: Blender works from the chosen file.
            # Rate it as round 1 before changing anything; rounds after
            # that open the best-so-far copy and edit it in place.
            opened = client.execute_code(modeling.open_mainfile_code(blend_file))
            if "OPENED_MAINFILE" not in opened:
                raise RuntimeError(f"could not open existing Blender file: {opened[:300]}")
            log(f"Blender file: working from existing {blend_file}")
            round_no += 1
            rec, _ = render_existing_blend(blend_file, params, run_dir, round_no,
                                           ref_data, history=history,
                                           segment_prompt=segment_prompt)
            history.append(rec["total"])
            best = rec
            log(f"existing file baseline: total {rec['total']} rating {rec['rating_10']}")
            emit({"type": "round", "record": rec, "run_dir": run_dir})
        else:
            # New-file mode: never inherit the scene Blender happens
            # to have open from earlier work.
            reset = client.execute_code(modeling.reset_empty_code())
            if "RESET_EMPTY" not in reset:
                raise RuntimeError(f"could not start a new Blender file: {reset[:300]}")
            log("Blender file: new empty file")
        if not blend_file and len(strategies) > 1:
            for s in strategies:
                round_no += 1
                rec, _ = render_and_score(client, dict(params), s, run_dir,
                                          round_no, ref_data, history=history,
                                          segment_prompt=segment_prompt)
                history.append(rec["total"])
                log(f"experiment strategy {s}: total {rec['total']} rating {rec['rating_10']}")
                emit({"type": "round", "record": rec, "run_dir": run_dir})
                if best is None or rec["total"] > best["total"]:
                    best, chosen = rec, s
                if _cancelled(cancel):
                    stop_reason = "user"
                    log("cancelled by user; keeping best so far")
                    break
            if best:
                log(f"experiment winner: strategy {chosen} ({best['total']})")
                params.update(best["params"])
        while round_no < max_rounds and not _cancelled(cancel):
            if best:
                finished, reasons = scorer.check_finish(
                    best["per_view"], best["total"], target,
                    rating=best.get("rating_10"), rating_enabled=rating_enabled,
                    target_rating=target_rating)
                if best.get("critical_defects"):
                    finished = False
                if finished:
                    stop_reason = "target"
                    log(f"FINISHED at round {best['round']}: total {best['total']} "
                        f"rating {best.get('rating_10')}")
                    break
                if len(history) >= 4 and max(history[-3:]) - max(history[:-3] or [0]) < 1.0 \
                        and best["round"] >= 3:
                    stop_reason = "plateau"
                    log("plateau: <1 point gain over last 3 rounds; stopping with best")
                    break
            round_no += 1
            custom_code = None
            if best and blend_file:
                # Existing-file round: reopen the best copy and edit in
                # place — never rebuild from primitives over it.
                params, _ = driver.apply_actions(
                    params, best.get("next_actions") or {})
                mult = driver.scale_multipliers(best.get("next_actions") or {})
                edit = modeling.scale_edit_code(
                    mult["width_scale"], mult["height_scale"], mult["depth_scale"])
                if driver_code and meta_api.has_key() and best.get("next_plan"):
                    try:
                        edit = driver.generate_bpy(
                            best["next_plan"], best.get("next_prompt", ""), params,
                            edit_existing=True)
                        if "BUILT_AND_SAVED" not in edit:
                            edit += '\nprint("BUILT_AND_SAVED")\n'
                    except Exception as e:
                        log(f"driver edit unavailable, using scale edit: {e}")
                custom_code = modeling.open_mainfile_code(best["blend"]) + edit
                chosen = "existing"
            elif best:
                # Critic-driven step: bounded driver actions first.
                params, new_strategy = driver.apply_actions(
                    params, best.get("next_actions") or {})
                if new_strategy:
                    chosen = new_strategy
                params = adjust(params, best, ref_data, run_dir)
                if driver_code and meta_api.has_key() and best.get("next_plan"):
                    try:
                        custom_code = driver.generate_bpy(
                            best["next_plan"], best.get("next_prompt", ""), params)
                    except Exception as e:
                        log(f"driver code unavailable, using strategy {chosen}: {e}")
            try:
                rec, _ = render_and_score(client, params, chosen, run_dir, round_no,
                                          ref_data, history=history,
                                          segment_prompt=segment_prompt,
                                          custom_code=custom_code)
            except Exception as e:
                if not custom_code:
                    raise
                if blend_file:
                    # Never fall back to a primitive rebuild over an
                    # existing file: retry with the plain scale edit.
                    log(f"existing-file edit failed ({e}); retrying with scale edit")
                    mult = driver.scale_multipliers(best.get("next_actions") or {})
                    retry = modeling.open_mainfile_code(best["blend"]) + \
                        modeling.scale_edit_code(mult["width_scale"],
                                                 mult["height_scale"],
                                                 mult["depth_scale"])
                    rec, _ = render_and_score(client, params, chosen, run_dir, round_no,
                                              ref_data, history=history,
                                              segment_prompt=segment_prompt,
                                              custom_code=retry)
                else:
                    log(f"driver-code round failed ({e}); retrying with strategy {chosen}")
                    rec, _ = render_and_score(client, params, chosen, run_dir, round_no,
                                              ref_data, history=history,
                                              segment_prompt=segment_prompt)
            history.append(rec["total"])
            log(f"round {round_no} strategy {chosen}: total {rec['total']} "
                f"rating {rec['rating_10']} plan: {rec['next_plan'][:120]}")
            emit({"type": "round", "record": rec, "run_dir": run_dir})
            if best is None or rec["total"] > best["total"]:
                best = rec
        if _cancelled(cancel) and stop_reason == "max-rounds":
            stop_reason = "user"
    finally:
        client.close()
    if best is None:
        raise RuntimeError("cancelled before any round completed")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    shutil.copyfile(best["blend"], output)
    summary = {"source": source, "output": output, "best_round": best["round"],
               "best_total": best["total"], "best_rating": best.get("rating_10"),
               "strategy": best["strategy"], "stop_reason": stop_reason,
               "rating_enabled": rating_enabled, "target_rating": target_rating,
               "blend_mode": "existing" if blend_file else "new",
               "blend_file": blend_file,
               "per_view": best["per_view"], "run_dir": run_dir}
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    log(f"best .blend (round {best['round']}, score {best['total']}) -> {output}")
    emit({"type": "done", "summary": summary})
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--output", default="outputs/model.blend")
    ap.add_argument("--max-rounds", type=int, default=25)
    ap.add_argument("--target", type=float, default=85.0)
    ap.add_argument("--strategy", default="auto", choices=["auto", "A", "B"])
    ap.add_argument("--experiment", action="store_true")
    ap.add_argument("--sheet", default=None,
                    help="supplied 2x2 turnaround sheet image (front/side/back/top)")
    ap.add_argument("--confirm-sheet", action="store_true",
                    help="show the reference sheet path and ask before Blender work")
    ap.add_argument("--target-rating", type=float, default=8.0,
                    help="AI rating (0-10) at which the loop stops")
    ap.add_argument("--no-rating", action="store_true",
                    help="disable the AI rating finish line (max rounds / Cancel only)")
    ap.add_argument("--driver-code", action="store_true",
                    help="let Muse Spark write free-form bpy for later rounds")
    ap.add_argument("--segment-prompt", default="person",
                    help="SAM 3.1 concept prompt for segmentation")
    ap.add_argument("--blend-file", default=None,
                    help="work from this existing .blend instead of a new file")
    a = ap.parse_args()

    def confirm(path):
        answer = input(f"Reference sheet: {path}\nStart Blender work? [y/N] ")
        return answer.strip().lower() in ("y", "yes")

    run(a.source, a.output, a.max_rounds, a.target, a.strategy, a.experiment,
        sheet_path=a.sheet, confirm_sheet=confirm if a.confirm_sheet else None,
        target_rating=a.target_rating, rating_enabled=not a.no_rating,
        driver_code=a.driver_code, segment_prompt=a.segment_prompt,
        blend_file=a.blend_file)
