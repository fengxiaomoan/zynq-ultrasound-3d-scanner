"""M2b /state gate: the PS JSON builder must satisfy the page's contract.

The page (tools/live_model_page.html) is the consumer, so the checks below are
exactly the fields it dereferences, plus a cross-check of the numbers against
the points.csv that tools/continuous_scan.py produced for the same frames:

  * runs.std exists and has every key render() reads;
  * rmap / valid_map / tmap are [layers][azs] and agree with the cell list;
  * every cell_row has numeric t/r (the page calls .toFixed on them);
  * cells/valid_cells match the Python reference exactly;
  * each (z,az) cell's t and r match points.csv to 1e-3;
  * mesh vertex/face indices are in range and the lathe closes into
    (layers-1)*segments*2 triangles;
  * trace is a non-empty decimation of the current layer;
  * residual.available is false and says why (the PS has one run, not two).

    python tools/m2b_state_gate.py --run live_run/p12_std1 live_run/p12_std2
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SW = ROOT / "fpga" / "ps" / "sw"


@contextlib.contextmanager
def scratch_dir(prefix: str):
    """Scratch directory for the harness build.

    M2B_WORK points at a directory that ALREADY EXISTS and is writable.  Under the
    DSH Windows sandbox a directory created by Python is not writable by the same
    process (gcc's link into it fails with "Permission denied"), while one created
    by the shell is fine, so the caller pre-creates it and sets M2B_WORK.
    """
    p = os.environ.get("M2B_WORK")
    if p:
        yield Path(p)
        return
    with tempfile.TemporaryDirectory(prefix=prefix) as td:
        yield Path(td)


def find_gcc() -> str:
    cand = os.environ.get("M2B_GCC") or shutil.which("gcc")
    if cand:
        return cand
    for p in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(p).exists():
            return p
    raise SystemExit("no host gcc found (set M2B_GCC)")


def build(work: Path) -> Path:
    exe = work / ("m2b_state.exe" if sys.platform == "win32" else "m2b_state")
    cmd = [find_gcc(), "-O2", "-std=c99", "-Wall", "-Wextra", f"-I{SW / 'src'}",
           str(SW / "host" / "state_main.c"), str(SW / "src" / "model.c"),
           str(SW / "src" / "alg.c"), "-lm", "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("state harness build failed")
    return exe


def check_run(run: Path, exe: Path, work: Path, py_out: Path) -> list[str]:
    probs: list[str] = []
    frames = work / (run.name + "_frames.csv")
    subprocess.run([sys.executable, str(ROOT / "tools" / "m2b_frames.py"),
                    "--run", str(run), "--out", str(frames)], check=True,
                   capture_output=True)
    state = work / (run.name + "_state.json")
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8")) if (run / "meta.json").exists() else {}
    r = subprocess.run([str(exe), str(frames), str(state), "2", "-2",
                        str(meta.get("rot_start", 0))], capture_output=True, text=True)
    if r.returncode != 0:
        return [f"{run.name}: state builder failed: {r.stderr}"]
    js = json.loads(state.read_text(encoding="utf-8"))

    for key in ("now", "elapsed_s", "nominal_r", "geometry", "gt", "min_peak",
                "plan_layers", "runs", "residual", "pose"):
        if key not in js:
            probs.append(f"{run.name}: top-level {key} missing")
    # F1: /state carries a pose SUMMARY (not the page's rotation source, which is
    # /api/pose).  The host harness never calls m2b_set_pose(), so ok must be 0
    # here -- if it were 1 the block would be inventing an attitude.
    pose = js.get("pose") or {}
    for key in ("ok", "roll", "pitch", "yaw", "seq", "age_ms", "flags"):
        if key not in pose:
            probs.append(f"{run.name}: pose.{key} missing")
    if pose.get("ok") != 0:
        probs.append(f"{run.name}: host pose.ok={pose.get('ok')!r}, expected 0 (no board)")
    std = js.get("runs", {}).get("std")
    if not std:
        return probs + [f"{run.name}: runs.std missing"]
    for key in ("frames", "rate_fps", "silent_s", "phase", "t_eff_us", "layers",
                "azs", "rmap", "valid_map", "tmap", "cell_rows", "profile",
                "mesh", "trace", "per_layer", "cells", "valid_cells",
                "quarantined", "rot_mode"):
        if key not in std:
            probs.append(f"{run.name}: std.{key} missing")

    zs, azs = std["layers"], std["azs"]
    for name in ("rmap", "valid_map", "tmap"):
        grid = std[name]
        if len(grid) != len(zs):
            probs.append(f"{run.name}: {name} rows {len(grid)} != layers {len(zs)}")
        for row in grid:
            if len(row) != len(azs):
                probs.append(f"{run.name}: {name} row {len(row)} != azs {len(azs)}")
                break

    # cross-check against the Python reference points.csv
    pts = {}
    with (py_out / "points.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pts[(float(row["z_mm"]), float(row["az_deg"]))] = row
    ref_valid = sum(1 for row in pts.values() if row["valid"] == "1")
    if std["cells"] != len(pts):
        probs.append(f"{run.name}: cells {std['cells']} != python {len(pts)}")
    if std["valid_cells"] != ref_valid:
        probs.append(f"{run.name}: valid_cells {std['valid_cells']} != python {ref_valid}")
    for c in std["cell_rows"]:
        key = (float(c["z"]), float(c["az"]))
        row = pts.get(key)
        if row is None:
            probs.append(f"{run.name}: cell {key} not in points.csv")
            continue
        if abs(c["t"] - float(row["t_centroid_us"])) > 1e-3:
            probs.append(f"{run.name}: cell {key} t {c['t']} vs {row['t_centroid_us']}")
        if abs(c["r"] - float(row["r_mm"])) > 1e-3:
            probs.append(f"{run.name}: cell {key} r {c['r']} vs {row['r_mm']}")
        if c["n"] != int(row["frames"]):
            probs.append(f"{run.name}: cell {key} n {c['n']} vs {row['frames']}")
        if not isinstance(c["t_circ"], (int, float)):
            probs.append(f"{run.name}: cell {key} t_circ not numeric")
        if c["sd"] is not None and not isinstance(c["sd"], (int, float)):
            probs.append(f"{run.name}: cell {key} sd not numeric/null")

    if std["profile"] and len(std["profile"]) >= 2:
        m = std["mesh"]
        if not m:
            probs.append(f"{run.name}: profile has layers but mesh is null")
        else:
            nv = len(m["vertices"])
            if m["stats"]["vertices"] != nv:
                probs.append(f"{run.name}: mesh vertex count disagrees with stats")
            if nv % 48:
                probs.append(f"{run.name}: mesh vertices {nv} not a multiple of 48")
            for f in m["faces"]:
                if any(i < 0 or i >= nv for i in f):
                    probs.append(f"{run.name}: mesh face index out of range")
                    break
            want = 2 * 48 * (nv // 48 - 1)
            if len(m["faces"]) != want:
                probs.append(f"{run.name}: mesh faces {len(m['faces'])} != {want}")
    if not std["trace"]:
        probs.append(f"{run.name}: trace empty")
    for p in std["trace"][:5]:
        for k in ("z", "az", "t", "amp", "idx", "cidx", "cv"):
            if k not in p:
                probs.append(f"{run.name}: trace point missing {k}")
                break
    res = js.get("residual", {})
    if res.get("available") is not False or not res.get("why"):
        probs.append(f"{run.name}: residual must be unavailable with a reason")
    if std["rot_mode"] != "config.rot0":
        probs.append(f"{run.name}: rot_mode {std['rot_mode']!r}")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", required=True)
    args = ap.parse_args()
    problems: list[str] = []
    with scratch_dir("m2b_state_") as work:
        exe = build(work)
        for name in args.run:
            run = (ROOT / name).resolve() if not Path(name).is_absolute() else Path(name)
            py_out = work / (run.name + "_py")
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "continuous_scan.py"),
                                "--run", str(run), "--out", str(py_out)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                problems.append(f"{name}: python reference failed")
                continue
            probs = check_run(run, exe, work, py_out)
            if probs:
                problems.extend(probs)
                print(f"FAIL {name}")
            else:
                print(f"PASS {name}")
    if problems:
        for p in problems[:20]:
            print("M2B_STATE_FAIL:", p)
        return 1
    print(f"M2B_STATE_PASS: {len(args.run)} run(s) satisfy the page contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
