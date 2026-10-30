"""Point-by-point comparison of two ``robust_scan`` runs -> repeatability / noise floor.

This is the gate tool for P1.2: it answers "given two scans of the *same* object,
how much does the measured radius move at an unchanged pose?"  That number is the
noise floor an anomaly detector has to beat.

    python tools/scan_diff.py --a live_run/anom_std1_robust \
                              --b live_run/anom_std2_robust \
                              --out live_run/std_diff --label-a std1 --label-b std2

Inputs are the ``points.csv`` / ``summary.json`` written by ``tools/robust_scan.py``.
Only points that are valid in **both** runs enter the residual statistics; the
per-run acceptance rate is reported separately.

Outputs (in ``--out``)
    diff.csv    every (z, az) cell: both radii, both valid flags, the residual
    diff.json   counts, sd / max / median, t_eff drift, per-layer stats, verdict
    diff.md     short human-readable table (handoff / report snippet)

Residual convention: ``dr = r_b - r_a`` in mm.  It is computed with each run's
own ``t_eff`` (robust_scan estimates one per run on purpose): that removes any
common-mode acoustic drift between the two sessions and leaves the genuinely
pose-dependent part.  The drift itself is reported separately, both in µs and
in mm, because a global delay shift is *not* a shape difference but it does
consume the detector's dynamic range.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from robust_scan import A, AXIS_Y, C_MM_US, PROBE_Y, radius_of  # noqa: E402


# ---------------------------------------------------------------- sensitivity
def mm_per_us(r_mm: float = 14.0) -> float:
    """|dr/dt| at a given radius, mm/µs; used to express t_eff drift in mm."""
    m = AXIS_Y - r_mm - PROBE_Y
    u = math.sqrt(A * A + m * m)
    return (u / math.sqrt(u * u - A * A)) * (C_MM_US / 2.0)


# ------------------------------------------------------------------- loading
def load_points(run: Path) -> dict[tuple[float, float], dict]:
    csv_path = run / "points.csv"
    if not csv_path.exists():
        raise SystemExit(f"missing {csv_path} (run robust_scan.py first)")
    out: dict[tuple[float, float], dict] = {}
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (float(row["z_mm"]), float(row["az_deg"]))
            out[key] = {
                "r": float(row["r_mm"]),
                "valid": row["valid"] == "1",
                "t": float(row["t_centroid_us"]),
                "frames_used": int(row["frames_used"]),
                "peak_med": float(row["peak_med"]),
            }
    return out


def load_summary(run: Path) -> dict:
    path = run / "summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def rate(n: int, d: int) -> float | None:
    return (n / d) if d else None


def fmt(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="baseline robust_scan output dir")
    ap.add_argument("--b", required=True, help="repeat robust_scan output dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--sd-gate", type=float, default=1.5, help="mm; per-point residual sd")
    ap.add_argument("--max-gate", type=float, default=3.0, help="mm; worst single point")
    ap.add_argument("--valid-gate", type=float, default=0.85, help="per-run acceptance")
    ap.add_argument("--min-common", type=int, default=8,
                    help="below this many co-valid points the statistics are not trustworthy")
    args = ap.parse_args()

    run_a, run_b = Path(args.a), Path(args.b)
    pts_a, pts_b = load_points(run_a), load_points(run_b)
    sum_a, sum_b = load_summary(run_a), load_summary(run_b)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    keys_a, keys_b = set(pts_a), set(pts_b)
    common_keys = sorted(keys_a & keys_b)

    # ---- per-cell table (also records cells present on one side only)
    rows = []
    for key in sorted(keys_a | keys_b):
        a, b = pts_a.get(key), pts_b.get(key)
        both = bool(a and b and a["valid"] and b["valid"])
        dr = (b["r"] - a["r"]) if both else None
        rows.append({
            "z": key[0], "az": key[1],
            "r_a": a["r"] if a else None, "r_b": b["r"] if b else None,
            "valid_a": bool(a and a["valid"]), "valid_b": bool(b and b["valid"]),
            "both": both, "dr": dr,
        })

    with (out / "diff.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["z_mm", "az_deg", "r_a_mm", "r_b_mm", "valid_a", "valid_b",
                    "both_valid", "dr_mm"])
        for r in rows:
            w.writerow([f"{r['z']:+.0f}", f"{r['az']:.0f}",
                        "" if r["r_a"] is None else f"{r['r_a']:.3f}",
                        "" if r["r_b"] is None else f"{r['r_b']:.3f}",
                        int(r["valid_a"]), int(r["valid_b"]), int(r["both"]),
                        "" if r["dr"] is None else f"{r['dr']:+.3f}"])

    drs = [r["dr"] for r in rows if r["dr"] is not None]
    n_valid_a = sum(1 for p in pts_a.values() if p["valid"])
    n_valid_b = sum(1 for p in pts_b.values() if p["valid"])
    n_total_a, n_total_b = len(pts_a), len(pts_b)

    # population sd (ddof=0) on purpose: matches np.std in robust_scan's summary.json
    # and the numbers already quoted in P1_2_GATE / P1_2_DATA_REQUEST.
    sd = statistics.pstdev(drs) if len(drs) >= 2 else None
    mean = statistics.fmean(drs) if drs else None
    absmax = max(abs(d) for d in drs) if drs else None
    worst = max((r for r in rows if r["dr"] is not None), key=lambda r: abs(r["dr"]), default=None)
    common_mode = statistics.median(drs) if drs else None
    detr = [d - common_mode for d in drs] if common_mode is not None else []
    sd_detr = statistics.pstdev(detr) if len(detr) >= 2 else None
    rms = math.sqrt(statistics.fmean([d * d for d in drs])) if drs else None

    # ---- layers
    layers: dict[float, dict] = {}
    for z in sorted({k[0] for k in keys_a | keys_b}):
        dz = [r["dr"] for r in rows if r["z"] == z and r["dr"] is not None]
        layers[z] = {
            "cells": sum(1 for r in rows if r["z"] == z),
            "common": len(dz),
            "sd": round(statistics.pstdev(dz), 3) if len(dz) >= 2 else None,
            "dr_median": round(statistics.median(dz), 3) if dz else None,
            "dr_max": round(max(abs(d) for d in dz), 3) if dz else None,
        }

    # ---- acceptance / drift
    acc_a = rate(n_valid_a, n_total_a)
    acc_b = rate(n_valid_b, n_total_b)
    t_eff_a, t_eff_b = sum_a.get("t_eff_us"), sum_b.get("t_eff_us")
    dt = (t_eff_b - t_eff_a) if (t_eff_a is not None and t_eff_b is not None) else None
    sens = mm_per_us()
    dt_mm = dt * sens if dt is not None else None

    # ---- first harmonic (tilt / centring) per layer
    # A lean or a lateral offset between the two sessions shows up as one full
    # sine over 360 deg, not as a local bump.  Fitting it separates the two.
    harmonics: dict[float, dict] = {}
    for z in sorted(layers):
        pts = [(r["az"], r["dr"]) for r in rows if r["z"] == z and r["dr"] is not None]
        if len(pts) < 6:
            continue
        ang = np.radians([p[0] for p in pts])
        y = np.array([p[1] for p in pts], dtype=float)
        design = np.column_stack([np.ones(ang.size), np.cos(ang), np.sin(ang)])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        fit = design @ coef
        amp = float(np.hypot(coef[1], coef[2]))
        phase = float(np.degrees(np.arctan2(coef[2], coef[1])) % 360.0)
        harmonics[z] = {
            "n": len(pts),
            "offset_mm": round(float(coef[0]), 2),
            "amplitude_mm": round(amp, 2),
            "phase_deg": round(phase, 0),
            "sd_after_removal_mm": round(float(np.std(y - fit)), 2),
            "explained_ratio": (round(1.0 - float(np.var(y - fit) / np.var(y)), 2)
                                if np.var(y) > 0 else None),
        }

    # ---- verdict
    checks = {
        "residual_sd": {"value": sd, "gate": args.sd_gate, "unit": "mm",
                        "pass": sd is not None and sd <= args.sd_gate},
        "residual_max": {"value": absmax, "gate": args.max_gate, "unit": "mm",
                         "pass": absmax is not None and absmax <= args.max_gate},
        "acceptance_a": {"value": acc_a, "gate": args.valid_gate, "unit": "ratio",
                         "pass": acc_a is not None and acc_a >= args.valid_gate},
        "acceptance_b": {"value": acc_b, "gate": args.valid_gate, "unit": "ratio",
                         "pass": acc_b is not None and acc_b >= args.valid_gate},
    }
    enough = len(drs) >= args.min_common
    n_fail = sum(1 for c in checks.values() if not c["pass"])
    if not enough:
        verdict = "INCONCLUSIVE"
        reason = (f"only {len(drs)} co-valid points (< {args.min_common}); "
                  "two runs do not cover enough of the same grid")
    elif n_fail == 0:
        verdict = "PASS"
        reason = "repeatability within all gates"
    elif sd is None or sd > 2.5:
        verdict = "FAIL"
        reason = "noise floor too high for a 6-8 mm defect — check bubbles/tilt before scanning"
    else:
        verdict = "WARN"
        reason = "repeatability marginal: raise the defect size and report the measured noise floor"

    report = {
        "schema": "scan-diff/1",
        "provenance": "real-measurement",
        "inputs": {"a": str(run_a), "b": str(run_b),
                   "label_a": args.label_a, "label_b": args.label_b},
        "geometry": {"t_eff_a_us": t_eff_a, "t_eff_b_us": t_eff_b,
                     "t_eff_drift_us": round(dt, 3) if dt is not None else None,
                     "dr_dt_mm_per_us": round(sens, 4),
                     "t_eff_drift_mm": round(dt_mm, 3) if dt_mm is not None else None},
        "counts": {"cells_a": n_total_a, "cells_b": n_total_b,
                   "valid_a": n_valid_a, "valid_b": n_valid_b,
                   "acceptance_a": None if acc_a is None else round(acc_a, 3),
                   "acceptance_b": None if acc_b is None else round(acc_b, 3),
                   "co_valid": len(drs)},
        "residual_mm": {
            "sd": None if sd is None else round(sd, 3),
            "mean": None if mean is None else round(mean, 3),
            "median_common_mode": None if common_mode is None else round(common_mode, 3),
            "rms": None if rms is None else round(rms, 3),
            "abs_max": None if absmax is None else round(absmax, 3),
            "sd_after_common_mode": None if sd_detr is None else round(sd_detr, 3),
            "worst": None if worst is None else
                     {"z": worst["z"], "az": worst["az"], "dr": round(worst["dr"], 3)},
        },
        "per_layer": {f"{z:+.0f}": v for z, v in layers.items()},
        "harmonic": {f"{z:+.0f}": v for z, v in harmonics.items()},
        "gates": {k: {"value": None if v["value"] is None else round(v["value"], 3),
                      "gate": v["gate"], "unit": v["unit"], "pass": v["pass"]}
                  for k, v in checks.items()},
        "verdict": verdict,
        "reason": reason,
        "notes": [
            "dr = r_B - r_A with each run's own t_eff (common-mode drift removed on purpose)",
            "a 6-8 mm radial bump is detectable only if it is >= 3x the residual sd",
            f"dr/dt at r=14 mm is {sens:.3f} mm/us: a 2.6 us drift is ~{2.6 * sens:.1f} mm",
        ],
    }
    (out / "diff.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- markdown
    md = [
        f"# 两次扫描重复性对比：{args.label_a} vs {args.label_b}",
        "",
        f"`provenance=real-measurement` · 残差 `dr = r_{{{args.label_b}}} - r_{{{args.label_a}}}`（各用自身 t_eff）",
        "",
        "| 指标 | 值 | 门槛 | 判定 |",
        "|---|---|---|---|",
        f"| 逐点半径差 sd | **{fmt(sd)} mm** | ≤{args.sd_gate} mm | {'✅' if checks['residual_sd']['pass'] else '❌'} |",
        f"| 逐点半径差 max | **{fmt(absmax)} mm** | ≤{args.max_gate} mm | {'✅' if checks['residual_max']['pass'] else '❌'} |",
        f"| 有效点率 {args.label_a} | {fmt(None if acc_a is None else acc_a * 100, 1)}% | ≥{args.valid_gate * 100:.0f}% | {'✅' if checks['acceptance_a']['pass'] else '❌'} |",
        f"| 有效点率 {args.label_b} | {fmt(None if acc_b is None else acc_b * 100, 1)}% | ≥{args.valid_gate * 100:.0f}% | {'✅' if checks['acceptance_b']['pass'] else '❌'} |",
        f"| 共有效点数 | {len(drs)} | ≥{args.min_common} | {'✅' if enough else '❌'} |",
        "",
        f"- t_eff：{args.label_a} `{fmt(t_eff_a)} µs` / {args.label_b} `{fmt(t_eff_b)} µs`，"
        f"漂移 `{fmt(dt)} µs` ≈ **{fmt(dt_mm)} mm**（共模，已由各自 t_eff 吸收）",
        f"- 共模中位数 `{fmt(common_mode)} mm`，去共模后 sd `{fmt(sd_detr)} mm`",
        f"- 最差点：z={fmt(None if worst is None else worst['z'], 0)} mm、"
        f"az={fmt(None if worst is None else worst['az'], 0)}°、"
        f"dr={fmt(None if worst is None else worst['dr'])} mm",
        "",
        "| 层 z / mm | 点数 | 共有效 | dr 中位 | dr sd | dr max |",
        "|---|---|---|---|---|---|",
    ]
    for z, s in layers.items():
        md.append(f"| {z:+.0f} | {s['cells']} | {s['common']} | {fmt(s['dr_median'])} | "
                  f"{fmt(s['sd'])} | {fmt(s['dr_max'])} |")
    if harmonics:
        md += ["", "**一次谐波（倾斜/对中漂移）**", "",
               "| 层 z / mm | 幅度 | 相位 | 扣除后 sd | 解释比例 |", "|---|---|---|---|---|"]
        for z, h in harmonics.items():
            md.append(f"| {z:+.0f} | {h['amplitude_mm']} mm | {h['phase_deg']:.0f}° | "
                      f"{h['sd_after_removal_mm']} mm | {h['explained_ratio']} |")
        md += ["", "谐波幅度远大于局部残差 ⇒ 两遍之间是**整体倾斜/偏心**，不是某处有缺陷。"]
    md += ["", f"**判定：{verdict}** — {reason}", ""]
    (out / "diff.md").write_text("\n".join(md), encoding="utf-8")

    # ---- console
    print(f"{args.label_a} vs {args.label_b}: co-valid {len(drs)}/{len(common_keys)} cells")
    print(f"  acceptance {args.label_a} {fmt(None if acc_a is None else acc_a * 100, 1)}%  "
          f"{args.label_b} {fmt(None if acc_b is None else acc_b * 100, 1)}%")
    print(f"  dr sd {fmt(sd)} mm   max {fmt(absmax)} mm   median {fmt(common_mode)} mm   "
          f"rms {fmt(rms)} mm")
    print(f"  t_eff drift {fmt(dt)} us = {fmt(dt_mm)} mm   (dr/dt {sens:.3f} mm/us)")
    for z, s in layers.items():
        print(f"  z={z:+.0f}: cells {s['cells']}, co-valid {s['common']}, "
              f"dr sd {fmt(s['sd'])}, median {fmt(s['dr_median'])}")
    for z, h in harmonics.items():
        print(f"  z={z:+.0f} first harmonic: amplitude {h['amplitude_mm']} mm at "
              f"{h['phase_deg']:.0f} deg, sd after removal {h['sd_after_removal_mm']} mm "
              f"(explains {h['explained_ratio']})")
    print(f"  VERDICT {verdict} - {reason}")
    print(f"written -> {out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
