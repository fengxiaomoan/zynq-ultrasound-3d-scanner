"""Robust per-point estimator for a real scan (median across frames + window +
circular continuity).

The raw frame-to-frame peak of the current rig jumps by 2x at a fixed pose, so
a single frame's max/centroid is not usable.  This script:

1. keeps, per point, the frames whose window peak passes the A/B threshold;
2. takes the **median envelope** of the accepted frames (pulse noise / bubbles
   drop out);
3. measures the centroid inside the object window only;
4. applies a circular 3-point median over azimuth to reject outliers;
5. reports both the naive (max) and the robust result, so the improvement is
   visible.

    python tools/robust_scan.py --run live_run/p0scan --out live_run/p0scan_robust
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wscan import frames  # noqa: E402

A = 12.5
AXIS_Y = 100.0
PROBE_Y = 27.31
C_MM_US = 1.48


def radius_of(t: float, t_eff: float) -> float:
    path = (t - t_eff) * C_MM_US
    inner = (path / 2.0) ** 2 - A * A
    return AXIS_Y - PROBE_Y - math.sqrt(inner) if inner > 0 else float("nan")


def load(run: Path):
    rows = [json.loads(l) for l in (run / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        f = frames.to_frame(frames.read_ila_csv(run / r["file"]), r["file"])
        p = frames.prepare(f)
        out.append({"z": float(r["height_mm"]), "az": float(r["azimuth_deg"]),
                    "t": p.t_us, "env": p.envelope, "file": r["file"]})
    return out


def point_estimates(fs: list[dict], lo: float, hi: float, thr: float,
                    pick: str = "window", half_us: float = 2.0) -> dict:
    n = len(fs)
    peaks = []
    for f in fs:
        m = (f["t"] >= lo) & (f["t"] <= hi)
        peaks.append(float(f["env"][m].max()))
    used = [i for i, p in enumerate(peaks) if p >= thr]
    fallback = False
    if not used:
        used = [int(np.argmax(peaks))]
        fallback = True
    # common grid = first frame inside the window
    t_ref = fs[0]["t"]
    m = (t_ref >= lo) & (t_ref <= hi)
    tt = t_ref[m]
    stack = []
    for i in used:
        f = fs[i]
        stack.append(np.interp(tt, f["t"], f["env"]))
    med = np.median(np.stack(stack), axis=0)
    base = float(np.median(med))
    w = np.clip(med - base, 0, None)
    pk = float(med.max())
    lead = float(tt[np.argmax(med >= base + 0.5 * (pk - base))]) if pk > base else float(tt[0])
    if pick == "track":
        # A defect that adds a few mm of radius moves the echo by several us --
        # wider than the 10 us object window -- so a fixed-window centroid stays
        # put and the bump disappears.  Track the strongest peak instead, then
        # take the centroid in a narrow (+-half_us) neighbourhood of it.
        i = int(np.argmax(med))
        sel = np.abs(tt - tt[i]) <= half_us
        ww = np.clip(med[sel] - base, 0, None)
        centroid = (float((tt[sel] * ww).sum() / ww.sum()) if ww.sum() > 1e-6
                    else float(tt[i]))
        lead = float(tt[i])
    else:
        centroid = float(np.sum(tt * w) / np.sum(w)) if w.sum() > 1e-6 else float(tt[np.argmax(med)])
    return {"n": n, "used": len(used), "fallback": fallback,
            "peak_med": pk, "peak_max": max(peaks), "t": centroid, "lead": lead,
            "env": med}


def circ_median(vals: list[float], i: int) -> float:
    n = len(vals)
    return float(np.median([vals[(i - 1) % n], vals[i], vals[(i + 1) % n]]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lo", type=float, default=73.84)
    ap.add_argument("--hi", type=float, default=83.84)
    ap.add_argument("--threshold", type=float, default=112.1)
    ap.add_argument("--continuity", type=float, default=1.5, help="us; flag deviation from circular median")
    ap.add_argument("--t-eff", type=float, default=None, help="fixed t_eff (use the object scan value for a blank run)")
    ap.add_argument("--pick", choices=("window", "track"), default="window",
                    help="window: centroid over the whole object window (historic default). "
                         "track: argmax in the window, then a centroid within +-half-us of it. "
                         "Required for defects that move the echo by more than a few us.")
    ap.add_argument("--half-us", type=float, default=2.0,
                    help="track mode: half width of the centroid neighbourhood, us")
    args = ap.parse_args()

    run = Path(args.run)
    data = load(run)
    groups: dict[tuple[float, float], list[dict]] = {}
    for f in data:
        groups.setdefault((f["z"], f["az"]), []).append(f)

    pts = []
    for (z, az), fs in sorted(groups.items()):
        e = point_estimates(fs, args.lo, args.hi, args.threshold,
                            pick=args.pick, half_us=args.half_us)
        pts.append({"z": z, "az": az, **{k: e[k] for k in ("n", "used", "fallback", "peak_med", "peak_max", "t", "lead")}})

    # circular continuity per layer
    for z in sorted({p["z"] for p in pts}):
        layer = sorted([p for p in pts if p["z"] == z], key=lambda p: p["az"])
        tvals = [p["t"] for p in layer]
        for i, p in enumerate(layer):
            p["t_circ"] = circ_median(tvals, i)
            p["outlier"] = abs(p["t"] - p["t_circ"]) > args.continuity

    # calibration: use the fixed t_eff for a blank run, else anchor to nominal 14.0
    if args.t_eff is not None:
        t_eff = args.t_eff
    else:
        good = [p for p in pts if not p["fallback"] and not p["outlier"]]
        med_t = float(np.median([p["t"] for p in good])) if good else float(np.median([p["t"] for p in pts]))
        path14 = 2.0 * math.sqrt(A * A + (AXIS_Y - PROBE_Y - 14.0) ** 2)
        t_eff = med_t - path14 / C_MM_US
    for p in pts:
        p["r"] = radius_of(p["t"], t_eff)
        p["valid"] = (not p["fallback"]) and (not p["outlier"])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "points.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["z_mm", "az_deg", "frames", "frames_used", "fallback", "peak_med", "peak_max",
                    "t_centroid_us", "t_lead_us", "t_circ_median_us", "outlier", "r_mm", "valid"])
        for p in pts:
            w.writerow([f"{p['z']:+.0f}", f"{p['az']:.0f}", p["n"], p["used"], int(p["fallback"]),
                        f"{p['peak_med']:.1f}", f"{p['peak_max']:.1f}", f"{p['t']:.2f}",
                        f"{p['lead']:.2f}", f"{p['t_circ']:.2f}", int(p["outlier"]),
                        f"{p['r']:.2f}", int(p["valid"])])

    summary = {"schema": "robust-scan/1", "provenance": "real-measurement",
               "run": str(run), "t_eff_us": round(t_eff, 3),
               "threshold": args.threshold, "object_window_us": [args.lo, args.hi],
               "pick": args.pick, "pick_half_us": args.half_us,
               "points": len(pts), "valid": sum(1 for p in pts if p["valid"]),
               "per_layer": {}}
    for z in sorted({p["z"] for p in pts}):
        g = [p for p in pts if p["z"] == z and p["valid"]]
        allg = [p for p in pts if p["z"] == z]
        summary["per_layer"][f"{z:+.0f}"] = {
            "points": len(allg), "valid": len(g),
            "r_median": round(float(np.median([p["r"] for p in g])), 3) if g else None,
            "r_spread": round(float(max(p["r"] for p in g) - min(p["r"] for p in g)), 3) if g else None,
            "r_sd": round(float(np.std([p["r"] for p in g])), 3) if g else None,
            "t_spread": round(float(max(p["t"] for p in g) - min(p["t"] for p in g)), 3) if g else None,
        }
    summary["quarantined"] = sum(1 for p in pts if p["fallback"] or p["outlier"])
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"points {len(pts)}, valid {summary['valid']}, quarantined {summary['quarantined']}, t_eff {t_eff:.2f}")
    for z, s in summary["per_layer"].items():
        print(f"  z={z}: valid {s['valid']}/{s['points']}  r={s['r_median']}  spread={s['r_spread']}  sd={s['r_sd']}")
    print(f"written -> {out}")


if __name__ == "__main__":
    main()

