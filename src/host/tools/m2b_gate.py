"""M2b gate: the on-board C algorithm must reproduce tools/continuous_scan.py.

For every run given, this script

  1. runs ``tools/continuous_scan.py`` (the Python reference) into a scratch dir;
  2. flattens the same manifest into frames.csv (tools/m2b_frames.py);
  3. runs the C harness (fpga/ps/sw/host/host_main.c + fpga/ps/sw/src/alg.c,
     byte-for-byte the alg.c the PS firmware links);
  4. compares points.csv line by line, and ``t_eff``.

Exit 0 only when all runs are identical.  The comparison is on the file
contents, so a formatting difference counts as a failure too -- the point is
that the two paths cannot disagree about a single cell.

    python tools/m2b_gate.py --run live_run/p12_std1 live_run/p12_std2

Requires a host gcc (msys64 mingw32-w64 is what was used) in PATH.
"""

from __future__ import annotations

import argparse
import contextlib
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
    """M2B_WORK = an existing writable dir; see m2b_state_gate.py for why the DSH
    sandbox needs it (Python-created directories are not writable by Python)."""
    p = os.environ.get("M2B_WORK")
    if p:
        yield Path(p)
        return
    with tempfile.TemporaryDirectory(prefix=prefix) as td:
        yield Path(td)


def find_gcc() -> str:
    """A host compiler for the harness.

    M2B_GCC wins; otherwise PATH, otherwise the msys64 install this project's
    other host builds use.  We do NOT put msys64 on PATH for the whole script:
    it shadows the Python that has numpy.
    """
    cand = os.environ.get("M2B_GCC") or shutil.which("gcc")
    if cand:
        return cand
    for p in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(p).exists():
            return p
    raise SystemExit("no host gcc found (set M2B_GCC)")


def build_harness(out_dir: Path) -> Path:
    exe = out_dir / ("m2b_alg.exe" if sys.platform == "win32" else "m2b_alg")
    cmd = [find_gcc(), "-O2", "-std=c99", "-Wall", "-Wextra", f"-I{SW / 'src'}",
           str(SW / "host" / "host_main.c"), str(SW / "src" / "alg.c"),
           "-lm", "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("host harness build failed")
    return exe


def rot0_of(run: Path) -> float:
    meta = run / "meta.json"
    if meta.exists():
        return float(json.loads(meta.read_text(encoding="utf-8")).get("rot_start", 0))
    return 0.0


def check(run: Path, exe: Path, work: Path) -> list[str]:
    problems: list[str] = []
    ref_dir = work / (run.name + "_py")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "continuous_scan.py"),
                        "--run", str(run), "--out", str(ref_dir)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"{run.name}: python reference failed: {r.stdout[-400:]} {r.stderr[-400:]}"]
    frames = work / (run.name + "_frames.csv")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "m2b_frames.py"),
                        "--run", str(run), "--out", str(frames)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"{run.name}: frame extraction failed: {r.stderr[-400:]}"]
    c_out = work / (run.name + "_c.csv")
    r = subprocess.run([str(exe), str(frames), str(c_out), str(rot0_of(run)),
                        "4096", "15", "1.5", "0"], capture_output=True, text=True)
    if r.returncode != 0:
        return [f"{run.name}: C harness failed: {r.stdout} {r.stderr}"]

    py = (ref_dir / "points.csv").read_text(encoding="utf-8").splitlines()
    cc = c_out.read_text(encoding="utf-8").splitlines()
    if py != cc:
        n = 0
        for i, (a, b) in enumerate(zip(py, cc)):
            if a != b:
                problems.append(f"{run.name}: line {i + 1}\n  py: {a}\n  c : {b}")
                n += 1
                if n >= 3:
                    break
        if len(py) != len(cc):
            problems.append(f"{run.name}: line count {len(py)} vs {len(cc)}")
    # t_eff is in summary.json, not in points.csv; compare it as well
    summ = json.loads((ref_dir / "summary.json").read_text(encoding="utf-8"))
    c_line = [l for l in r.stdout.splitlines() if l.startswith("frames=")]
    if c_line:
        t_eff_c = float(c_line[0].split("t_eff=")[1])
        if abs(t_eff_c - summ["t_eff_us"]) > 1e-3:
            problems.append(f"{run.name}: t_eff {t_eff_c} vs {summ['t_eff_us']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", required=True)
    ap.add_argument("--keep", action="store_true", help="keep the scratch files")
    args = ap.parse_args()

    all_problems: list[str] = []
    with scratch_dir("m2b_gate_") as work:
        exe = build_harness(work)
        for name in args.run:
            run = (ROOT / name).resolve() if not Path(name).is_absolute() else Path(name)
            if not run.exists():
                all_problems.append(f"{name}: no such run")
                continue
            probs = check(run, exe, work)
            if probs:
                all_problems.extend(probs)
                print(f"FAIL {name}")
            else:
                print(f"PASS {name}")
            if args.keep:
                keep = ROOT / "live_run" / ("_m2b_" + run.name)
                keep.mkdir(parents=True, exist_ok=True)
                for f in work.glob(run.name + "*"):
                    if f.is_file():
                        (keep / f.name).write_bytes(f.read_bytes())

    if all_problems:
        for p in all_problems[:20]:
            print("M2B_ALG_FAIL:", p)
        return 1
    print(f"M2B_ALG_PASS: {len(args.run)} run(s) bit-identical to continuous_scan.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
