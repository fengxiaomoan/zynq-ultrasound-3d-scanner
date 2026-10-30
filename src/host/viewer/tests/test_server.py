#!/usr/bin/env python3
"""Checks for the F1 viewer server: PLY parsing, mesh invariants, pose CSV.

    python f1_viewer/tests/test_server.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import server  # noqa: E402

checks = 0


def ok(name, cond):
    global checks
    checks += 1
    if not cond:
        print("FAIL " + name)
        raise SystemExit(1)
    print("ok " + name)


for name, spec in server.MODELS.items():
    if not spec["path"].exists():
        print("skip " + name + " (missing)")
        continue
    m = server.build_model(name)
    nv = m["counts"]["vertices"]
    nt = m["counts"]["triangles"]
    ok(f"{name}: positions length", len(m["positions"]) == 3 * nv)
    ok(f"{name}: indices length", len(m["indices"]) == 3 * nt)
    ok(f"{name}: indices in range", min(m["indices"]) >= 0 and max(m["indices"]) < nv)
    ok(f"{name}: triangles non-degenerate-ish", nt > 0)
    norms = [math.hypot(m["normals"][3 * i], m["normals"][3 * i + 1], m["normals"][3 * i + 2])
             for i in range(nv)]
    ok(f"{name}: normals unit", all(abs(v - 1.0) < 1e-3 for v in norms))
    cx = sum(m["positions"][3 * i] for i in range(nv)) / nv
    cy = sum(m["positions"][3 * i + 1] for i in range(nv)) / nv
    cz = sum(m["positions"][3 * i + 2] for i in range(nv)) / nv
    ok(f"{name}: near origin", max(abs(cx), abs(cy), abs(cz)) < 0.25)
    ok(f"{name}: radius sane", 0.5 < m["radius"] < 3.0)

# pose: missing file -> demo
demo = server.read_pose(Path("definitely_missing_pose.csv"))
ok("missing pose -> demo", demo["mode"] == "demo" and "roll" in demo)

# pose: header + last row wins
with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
    f.write("tick_ms,roll,pitch,yaw,seq,valid\n")
    f.write("1000,1,2,3,7,1\n")
    f.write("2000,-4.5,6.25,88.0,8,1\n")
    tmp = Path(f.name)
p = server.read_pose(tmp)
ok("pose mode file", p["mode"] == "file")
ok("pose last row roll", abs(p["roll"] + 4.5) < 1e-9)
ok("pose last row pitch", abs(p["pitch"] - 6.25) < 1e-9)
ok("pose last row yaw", abs(p["yaw"] - 88.0) < 1e-9)
ok("pose seq", p["seq"] == 8)
tmp.unlink()

# pose: positional (no header)
with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
    f.write("1234,10,20,30,42,1\n")
    tmp = Path(f.name)
p = server.read_pose(tmp)
ok("positional pose", p["roll"] == 10 and p["pitch"] == 20 and p["yaw"] == 30 and p["seq"] == 42)
tmp.unlink()

print(f"\nPASS {checks} checks")
