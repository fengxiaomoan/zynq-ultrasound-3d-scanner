"""Bin a continuous (never-stopping) scan by the encoder pose, into the same
``points.csv`` that ``tools/robust_scan.py`` writes.

Why this exists
---------------
In a step scan every point has its own stop-settle-4-frames cycle: 3.04 s/point
on the DSP path, of which only 0.43 s is the 15 deg move.  A continuous scan
rotates once per layer and triggers frames while the stage is moving; the angle
of every frame comes from ``pose_rot`` (latched by the FPGA on ``capture_start``
and written into the manifest), not from a commanded point index.  That removes
settle (0.6 s), the fixed +400 ms move margin and the per-point VIO traffic.

What it does
------------
1. calibrate pose_rot -> azimuth, per layer when the manifest still carries the
   nominal ``azimuth_deg`` (step scans do; continuous ones do not);
2. assign every frame to a ``--bin-deg`` cell;
3. per cell: robust estimate (DSP: median of the board's per-frame value;
   ILA: median envelope -> window centroid), plus a MAD-based scatter;
4. apply the same 3-cell circular continuity, the same nominal-14 mm t_eff
   anchor and the same ``points.csv`` schema as robust_scan, so
   ``tools/scan_diff.py`` works unchanged.

    # a continuous run (DSP path, after C1 is on the board)
    python tools/continuous_scan.py --run live_run/cont_std1 --out live_run/cont_std1_bin

    # the same tool on an existing step scan: the bins must reproduce the points
    python tools/continuous_scan.py --run live_run/cyl_full_dsp \
        --out live_run/cyl_full_dsp_bin --selftest

Important: the bin centres are snapped to the fixed ``--bin-deg`` grid (0, 15,
30, ...), never to the measured mean angle.  That is what lets scan_diff match
cells between the standard and the defect run.

``summary.json`` records how the angle was recovered and how big the calibration
residual was, so the report can state the angular uncertainty instead of hiding
it.  For a step scan the per-layer residual also reveals the known 23x171 vs
4096 closure error (163 counts = 14.3 deg per layer).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from robust_scan import (A, AXIS_Y, C_MM_US, PROBE_Y, point_estimates,  # noqa: E402
                         radius_of)

CPR_DEFAULT = 4096          # counts per revolution (measured: 171 counts = 15 deg)
BIN_DEFAULT = 15.0


# ------------------------------------------------------------------ loading
def load_manifest(run: Path, name: str = "manifest.jsonl") -> list[dict]:
    path = run / name
    if not path.exists():
        raise SystemExit(f"missing {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"empty manifest: {path}")
    return rows


def source_of(rows: list[dict]) -> str:
    if "t_us" in rows[0] or "idx" in rows[0]:
        return "dsp"
    if "file" in rows[0]:
        return "ila"
    raise SystemExit("manifest has neither DSP fields (idx/t_us) nor ILA fields (file)")


def load_ila_envelopes(run: Path, rows: list[dict]) -> None:
    """Fill row['t']/row['env'] in place (only for the ILA path)."""
    from wscan import frames  # imported late: the DSP path does not need it

    cache: dict[str, dict] = {}
    for r in rows:
        name = r["file"]
        if name not in cache:
            f = frames.to_frame(frames.read_ila_csv(run / name), name)
            p = frames.prepare(f)
            cache[name] = {"t": p.t_us, "env": p.envelope}
        r["t"] = cache[name]["t"]
        r["env"] = cache[name]["env"]


# --------------------------------------------------------------- calibration
def wrap180(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def circ_mean_deg(angles: list[float]) -> float:
    """Mean of angles in degrees, correct across the 0/360 seam.

    The arithmetic mean of 359.5 and 0.5 is 180 -- the opposite side of the
    circle.  That is exactly the artefact that made ``az_meas`` read ~180 deg for
    the 0 deg bin in every layer (found 2026-10-26).  Average the unit vectors.
    """
    if not angles:
        return float("nan")
    a = np.radians(np.asarray(angles, dtype=float))
    return math.degrees(math.atan2(float(np.sin(a).mean()),
                                   float(np.cos(a).mean()))) % 360.0


def calibrate(rows: list[dict], cpr: int, per_layer: bool,
              rot0_arg: float | None) -> tuple[dict[float, float], dict]:
    """Return {z: rot0_counts} plus a report of the residuals (degrees)."""
    by_z: dict[float, list[dict]] = {}
    for r in rows:
        by_z.setdefault(float(r["height_mm"]), []).append(r)

    have_nominal = all(r.get("azimuth_deg") is not None for r in rows)
    report: dict = {"mode": None, "counts_per_rev": cpr, "per_layer": {}}

    if have_nominal:
        report["mode"] = "from-nominal-azimuth"
        out: dict[float, float] = {}
        groups = by_z.items() if per_layer else [("global", rows)]
        for z, grp in groups:
            # delta = measured angle - nominal angle, wrapped to +-180 deg
            deltas = []
            for r in grp:
                meas = (float(r["pose_rot"]) % cpr) * 360.0 / cpr
                deltas.append(wrap180(meas - float(r["azimuth_deg"])))
            med = float(np.median(deltas))
            resid = [wrap180(d - med) for d in deltas]
            key = z
            out[key] = (med % 360.0) * cpr / 360.0
            report["per_layer"][str(z)] = {
                "rot0_counts": round(out[key], 2),
                "rot0_deg": round(med % 360.0, 3),
                "residual_max_deg": round(max(abs(d) for d in resid), 3),
                "residual_sd_deg": round(float(np.std(resid)), 3),
                "frames": len(grp),
            }
        return out, report

    report["mode"] = "from-rot0-argument"
    rot0 = 0.0 if rot0_arg is None else float(rot0_arg)
    report["per_layer"] = {"all": {"rot0_counts": rot0, "residual_max_deg": None,
                                   "residual_sd_deg": None, "frames": len(rows)}}
    return {z: rot0 for z in by_z}, report


# ------------------------------------------------------------------ binning
def assign(rows: list[dict], rot0: dict[float, float], cpr: int, bin_deg: float) -> None:
    nbin = int(round(360.0 / bin_deg))
    for r in rows:
        z = float(r["height_mm"])
        az = ((float(r["pose_rot"]) - rot0[z]) % cpr) * 360.0 / cpr
        b = int(round(az / bin_deg)) % nbin
        r["az_meas"] = az % 360.0
        r["bin"] = b
        r["bin_az"] = (b * bin_deg) % 360.0


def mad_sd(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    med = float(np.median(vals))
    mad = float(np.median([abs(v - med) for v in vals]))
    return 1.4826 * mad


def estimate_cell_dsp(grp: list[dict], amp_min: float) -> dict:
    ok = [r for r in grp if int(r.get("valid", 1)) == 1 and float(r.get("amp", 0)) >= amp_min]
    all_t = [float(r["t_us"]) for r in grp]
    use = [float(r["t_us"]) for r in ok] or all_t
    t = float(np.median(use))
    amps = [float(r.get("amp", 0)) for r in grp]
    return {"n": len(grp), "used": len(ok), "fallback": 0 if ok else 1,
            "peak_med": float(np.median(amps)) if amps else 0.0,
            "peak_max": float(max(amps)) if amps else 0.0,
            "t": t, "lead": t, "sd": mad_sd(use)}


def estimate_cell_ila(grp: list[dict], lo: float, hi: float, thr: float) -> dict:
    e = point_estimates([{"t": r["t"], "env": r["env"]} for r in grp],
                        lo, hi, thr, pick="window")
    e["sd"] = None
    return e


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run dir with manifest.jsonl")
    ap.add_argument("--manifest", default="manifest.jsonl", help="manifest file name inside --run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cpr", type=int, default=CPR_DEFAULT, help="encoder counts per revolution")
    ap.add_argument("--bin-deg", type=float, default=BIN_DEFAULT)
    ap.add_argument("--rot0", type=float, default=None,
                    help="pose_rot count at azimuth 0 (continuous runs without nominal az)")
    ap.add_argument("--calib", choices=("auto", "per-layer", "global"), default="auto",
                    help="auto: per-layer when nominal azimuth exists, else rot0 argument")
    ap.add_argument("--source", choices=("auto", "dsp", "ila"), default="auto")
    ap.add_argument("--amp-min", type=float, default=0.0)
    ap.add_argument("--lo", type=float, default=73.84, help="ILA only: object window start, us")
    ap.add_argument("--hi", type=float, default=83.84, help="ILA only: object window end, us")
    ap.add_argument("--threshold", type=float, default=0.0, help="ILA only: frame acceptance")
    ap.add_argument("--continuity", type=float, default=1.5, help="us; circular median gate")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    run, out = Path(args.run), Path(args.out)
    rows = load_manifest(run, args.manifest)
    src = source_of(rows) if args.source == "auto" else args.source
    if src == "ila":
        load_ila_envelopes(run, rows)

    per_layer = (args.calib == "per-layer") or (args.calib == "auto" and
                 all(r.get("azimuth_deg") is not None for r in rows))
    meta = {}
    meta_path = run / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # A continuous run has no nominal azimuth.  Its angle convention is "the pose
    # at the start of the move is azimuth 0", so rot_start from meta.json is the
    # right rot0; an explicit --rot0 still wins.
    rot0_arg = args.rot0
    if rot0_arg is None and not all(r.get("azimuth_deg") is not None for r in rows):
        rot0_arg = meta.get("rot_start")
    rot0, calib = calibrate(rows, args.cpr, per_layer, rot0_arg)
    if args.calib == "global" and args.rot0 is not None:
        rot0 = {z: float(args.rot0) for z in rot0}
        calib["mode"] = "global-rot0-argument"
    assign(rows, rot0, args.cpr, args.bin_deg)

    cells: dict[tuple[float, float], list[dict]] = {}
    for r in rows:
        cells.setdefault((float(r["height_mm"]), float(r["bin_az"])), []).append(r)

    pts = []
    for (z, baz), grp in sorted(cells.items()):
        e = (estimate_cell_dsp(grp, args.amp_min) if src == "dsp"
             else estimate_cell_ila(grp, args.lo, args.hi, args.threshold))
        pts.append({"z": z, "az": baz, "az_meas": circ_mean_deg([r["az_meas"] for r in grp]),
                    "n": e["n"], "used": e["used"], "fallback": e["fallback"],
                    "peak_med": e["peak_med"], "t": e["t"], "lead": e["lead"],
                    "sd": e.get("sd")})

    # circular continuity per layer, exactly like robust_scan
    for z in sorted({p["z"] for p in pts}):
        layer = sorted([p for p in pts if p["z"] == z], key=lambda p: p["az"])
        tvals = [p["t"] for p in layer]
        n = len(layer)
        for i, p in enumerate(layer):
            p["t_circ"] = float(np.median([tvals[(i - 1) % n], tvals[i], tvals[(i + 1) % n]]))
            p["outlier"] = abs(p["t"] - p["t_circ"]) > args.continuity

    good = [p for p in pts if not p["fallback"] and not p["outlier"]]
    med_t = float(np.median([p["t"] for p in good])) if good else float(np.median([p["t"] for p in pts]))
    path14 = 2.0 * math.sqrt(A * A + (AXIS_Y - PROBE_Y - 14.0) ** 2)
    t_eff = med_t - path14 / C_MM_US
    for p in pts:
        p["r"] = radius_of(p["t"], t_eff)
        p["valid"] = (not p["fallback"]) and (not p["outlier"])

    out.mkdir(parents=True, exist_ok=True)
    with (out / "points.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["z_mm", "az_deg", "frames", "frames_used", "fallback", "peak_med",
                    "peak_max", "t_centroid_us", "t_lead_us", "t_circ_median_us",
                    "outlier", "r_mm", "valid", "az_meas_deg", "per_frame_sd_us"])
        for p in sorted(pts, key=lambda q: (q["z"], q["az"])):
            w.writerow([f"{p['z']:+.0f}", f"{p['az']:.0f}", p["n"], p["used"],
                        int(p["fallback"]), f"{p['peak_med']:.1f}",
                        f"{p['peak_med']:.1f}", f"{p['t']:.3f}", f"{p['lead']:.3f}",
                        f"{p['t_circ']:.3f}", int(p["outlier"]), f"{p['r']:.3f}",
                        int(p["valid"]), f"{p['az_meas']:.2f}",
                        "" if p["sd"] is None else f"{p['sd']:.3f}"])

    with (out / "frame_azimuths.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["seq", "frame", "z_mm", "pose_rot", "az_meas_deg", "bin_az_deg",
                    "t_us", "amp", "valid"])
        for r in rows:
            w.writerow([r.get("seq"), r.get("frame"), r.get("height_mm"), r.get("pose_rot"),
                        f"{r['az_meas']:.2f}", f"{r['bin_az']:.0f}",
                        r.get("t_us", ""), r.get("amp", ""), r.get("valid", "")])

    summary = {
        "schema": "continuous-scan/1", "provenance": "real-measurement",
        "run": str(run), "source": src, "bin_deg": args.bin_deg,
        "counts_per_rev": args.cpr, "t_eff_us": round(t_eff, 3),
        "continuity_us": args.continuity, "calibration": calib,
        "frames": len(rows), "cells": len(pts),
        "valid": sum(1 for p in pts if p["valid"]),
        "quarantined": sum(1 for p in pts if p["fallback"] or p["outlier"]),
        "per_layer": {},
    }

    # pose diagnostics: a continuous layer must sweep a full revolution.  The
    # span is the *commanded* counter, so it cannot see a skipped step, but it
    # does catch a move that was cut short or a frame loop that ended early.
    expected_span = args.cpr * int(meta.get("revs", 1)) if meta else None
    pose = {"expected_span_counts": expected_span, "per_layer": {}, "monotonic": True,
            "meta": meta}
    for z in sorted({float(r["height_mm"]) for r in rows}):
        pr = [float(r["pose_rot"]) for r in rows if float(r["height_mm"]) == z]
        span = max(pr) - min(pr)
        mono = all(b >= a for a, b in zip(pr, pr[1:]))
        pose["per_layer"][f"{z:+.0f}"] = {
            "frames": len(pr), "span_counts": span,
            "span_deg": round(span * 360.0 / args.cpr, 2),
            "expected_counts": expected_span,
            "short": bool(expected_span is not None and span < 0.95 * expected_span),
        }
        pose["monotonic"] = pose["monotonic"] and mono
    summary["pose"] = pose

    for z in sorted({p["z"] for p in pts}):
        g = [p for p in pts if p["z"] == z and p["valid"]]
        allg = [p for p in pts if p["z"] == z]
        sds = [p["sd"] for p in allg if p["sd"] is not None]
        summary["per_layer"][f"{z:+.0f}"] = {
            "cells": len(allg), "valid": len(g),
            "frames_per_cell_median": float(np.median([p["used"] for p in allg])),
            "r_median": round(float(np.median([p["r"] for p in g])), 3) if g else None,
            "r_spread": round(float(max(p["r"] for p in g) - min(p["r"] for p in g)), 3) if g else None,
            "r_sd": round(float(np.std([p["r"] for p in g])), 3) if g else None,
            "per_frame_sd_us_median": round(float(np.median(sds)), 3) if sds else None,
        }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    print(f"source {src}, frames {len(rows)}, cells {len(pts)}, valid {summary['valid']}, "
          f"t_eff {t_eff:.2f} us")
    for z, s in summary["per_layer"].items():
        print(f"  z={z}: valid {s['valid']}/{s['cells']}  r={s['r_median']}  "
              f"spread={s['r_spread']}  frames/cell={s['frames_per_cell_median']:.0f}")
    for z, p in pose["per_layer"].items():
        eta = f" expected {p['expected_counts']}" if p["expected_counts"] else ""
        print(f"  pose z={z}: {p['frames']} frames, span {p['span_counts']} counts "
              f"({p['span_deg']:.1f} deg){eta}")
        if p["short"]:
            print(f"  WARN: z={z} swept only {p['span_counts']} counts; the move was cut "
                  f"short or the frame loop exited early")
    if not pose["monotonic"]:
        print("  WARN: pose_rot is not monotonic - the stage reversed or the counter jumped")
    if calib["mode"] == "from-nominal-azimuth":
        worst = max(v["residual_max_deg"] for v in calib["per_layer"].values())
        print(f"calibration: from nominal azimuth, worst residual {worst:.2f} deg")

    if args.selftest:
        return selftest(rows, pts, args, calib, src)
    return 0


def selftest(rows: list[dict], pts: list[dict], args, calib: dict, src: str) -> int:
    """On a step scan the bins must reproduce the commanded points exactly."""
    problems = []
    if calib["mode"] != "from-nominal-azimuth":
        problems.append("selftest needs a manifest with nominal azimuth_deg")
    else:
        worst = max(v["residual_max_deg"] for v in calib["per_layer"].values())
        if worst > 1.0:
            problems.append(f"calibration residual {worst:.2f} deg > 1.0")
        # every frame of a nominal point must land in that point's bin
        for r in rows:
            if abs(wrap180(r["az_meas"] - float(r["azimuth_deg"]))) > 0.5 * args.bin_deg:
                problems.append(f"frame seq={r.get('seq')} az {r['az_meas']:.2f} "
                                f"vs nominal {r['azimuth_deg']}")
                break
        # and the per-cell value must equal the per-point median (DSP only: the
        # ILA cell value is a median-envelope centroid, not a median of per-frame
        # centroids, so it is not comparable this way)
        if src == "dsp":
            by_pt: dict[tuple[float, float], list[float]] = {}
            for r in rows:
                key = (float(r["height_mm"]), float(r["azimuth_deg"]))
                if r.get("valid", 1) and r.get("t_us") is not None:
                    by_pt.setdefault(key, []).append(float(r["t_us"]))
            for p in pts:
                exp = by_pt.get((p["z"], p["az"]))
                if exp is None:
                    # nominal az may be off-grid for the last point of a layer
                    problems.append(f"no nominal point for cell z={p['z']} az={p['az']}")
                    break
                if abs(float(np.median(exp)) - p["t"]) > 1e-6:
                    problems.append(f"cell z={p['z']} az={p['az']}: median {np.median(exp):.3f} "
                                    f"vs cell {p['t']:.3f}")
                    break
    if problems:
        for m in problems[:5]:
            print(f"SELFTEST_FAIL: {m}")
        return 1
    print("SELFTEST_PASS: bins reproduce the commanded points and the angle calibration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
