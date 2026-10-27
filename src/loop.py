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
from src import blender_host, meta_api, modeling, refs, scorer, segmentation
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


def render_and_score(client, params, strategy, run_dir, round_no, ref_data):
    # Blender is a separate process: never hand it a relative save path.
    rdir = os.path.abspath(os.path.join(run_dir, f"round{round_no:02d}"))
    os.makedirs(rdir, exist_ok=True)
    blend = os.path.join(rdir, "model.blend")
    result = client.execute_code(
        modeling.build_and_render(params, strategy, blend, rdir))
    if "BUILT_AND_SAVED" not in result:
        raise RuntimeError(f"Blender build failed: {result[:400]}")
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
        render = segmentation.analyze(render_path)
        judge = None
        if meta_api.has_key():
            try:
                judge = meta_api.judge_render(ref["path"], render_path)
            except Exception as e:
                log(f"judge {view} unavailable: {e}")
        per_view[view] = scorer.score_view(ref["data"], render, judge)
    total = scorer.total_score(per_view)
    record = {"round": round_no, "strategy": strategy, "total": total,
              "per_view": per_view, "params": {k: params[k] for k in
              ("width_scale", "height_scale", "depth_scale", "aspect", "side_aspect")},
              "blend": blend}
    with open(os.path.join(rdir, "score.json"), "w") as f:
        json.dump(record, f, indent=2)
    return record, rdir


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
        prepared_refs=None):
    def emit(event):
        if on_progress:
            on_progress(event)

    # Absolute paths everywhere: Blender (via MCP) and the headless renderer
    # are separate processes with different working directories, so a
    # relative runs/... path saved fine for us but not for Blender.
    source = os.path.abspath(source)
    output = os.path.abspath(output)
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
    ref_data = {v: {"path": p, "data": segmentation.analyze(p)}
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
        if len(strategies) > 1:
            for s in strategies:
                round_no += 1
                rec, _ = render_and_score(client, dict(params), s, run_dir,
                                          round_no, ref_data)
                log(f"experiment strategy {s}: total {rec['total']} {rec['per_view']}")
                emit({"type": "round", "record": rec, "run_dir": run_dir})
                if best is None or rec["total"] > best["total"]:
                    best, chosen = rec, s
                if _cancelled(cancel):
                    log("cancelled by user; keeping best so far")
                    break
            log(f"experiment winner: strategy {chosen} ({best['total']})")
            params.update(best["params"])
        history = [best["total"]] if best else []
        while round_no < max_rounds and not _cancelled(cancel):
            finished, reasons = scorer.check_finish(
                best["per_view"], best["total"], target) if best else (False, ["no rounds yet"])
            if finished:
                log(f"FINISHED at round {best['round']}: total {best['total']}")
                break
            if len(history) >= 4 and max(history[-3:]) - max(history[:-3] or [0]) < 1.0 \
                    and best and best["round"] >= 3:
                log("plateau: <1 point gain over last 3 rounds; stopping with best")
                break
            round_no += 1
            params = adjust(params, best, ref_data, run_dir) if best else params
            rec, _ = render_and_score(client, params, chosen, run_dir, round_no, ref_data)
            history.append(rec["total"])
            log(f"round {round_no} strategy {chosen}: total {rec['total']} {rec['per_view']}")
            emit({"type": "round", "record": rec, "run_dir": run_dir})
            if best is None or rec["total"] > best["total"]:
                best = rec
    finally:
        client.close()
    if best is None:
        raise RuntimeError("cancelled before any round completed")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    shutil.copyfile(best["blend"], output)
    summary = {"source": source, "output": output, "best_round": best["round"],
               "best_total": best["total"], "strategy": best["strategy"],
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
    a = ap.parse_args()

    def confirm(path):
        answer = input(f"Reference sheet: {path}\nStart Blender work? [y/N] ")
        return answer.strip().lower() in ("y", "yes")

    run(a.source, a.output, a.max_rounds, a.target, a.strategy, a.experiment,
        sheet_path=a.sheet, confirm_sheet=confirm if a.confirm_sheet else None)
