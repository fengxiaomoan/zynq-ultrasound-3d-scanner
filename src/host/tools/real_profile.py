"""Turn a robust real scan into the submission artifacts: profile.csv, mesh.ply,
scan_report.json (provenance=real-measurement).

    python tools/real_profile.py --run live_run/foil3_robust --out live_run/real_profile --label foil3
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
from wscan import vertical  # noqa: E402


def load(run: Path) -> list[dict]:
    rows = list(csv.DictReader((run / "points.csv").open(encoding="utf-8")))
    out = []
    for r in rows:
        out.append({"z": float(r["z_mm"]), "az": float(r["az_deg"]),
                    "r": float(r["r_mm"]), "t": float(r["t_centroid_us"]),
                    "valid": r["valid"] == "1", "peak": float(r["peak_med"])})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="real")
    args = ap.parse_args()

    run = Path(args.run)
    pts = load(run)
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    layers = {}
    for p in pts:
        layers.setdefault(p["z"], []).append(p)
    prof = []
    for z in sorted(layers):
        g = [p for p in layers[z] if p["valid"]]
        if not g:
            continue
        rs = [p["r"] for p in g]
        prof.append({"z": z, "n": len(g), "r_med": float(np.median(rs)),
                     "r_min": min(rs), "r_max": max(rs),
                     "spread": max(rs) - min(rs), "sd": float(np.std(rs)),
                     "t_med": float(np.median([p["t"] for p in g]))})

    with (out / "profile.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# provenance=real-measurement", f"label={args.label}",
                    f"t_eff_us={summary['t_eff_us']}"])
        w.writerow(["z_mm", "valid_points", "r_median_mm", "r_min_mm", "r_max_mm",
                    "spread_mm", "sd_mm", "t_median_us"])
        for p in prof:
            w.writerow([f"{p['z']:+.1f}", p["n"], f"{p['r_med']:.2f}", f"{p['r_min']:.2f}",
                        f"{p['r_max']:.2f}", f"{p['spread']:.2f}", f"{p['sd']:.2f}", f"{p['t_med']:.2f}"])

    mesh = None
    if len(prof) >= 2:
        rows = [{"height_mm": p["z"], "radius_vertical_mm": p["r_med"]} for p in prof]
        mesh = vertical.build_lathe(rows, segments=48)
        lines = ["ply", "format ascii 1.0", "comment real_measurement - foil target",
                 f"element vertex {len(mesh['vertices'])}",
                 "property float x", "property float y", "property float z",
                 f"element face {len(mesh['faces'])}",
                 "property list uchar int vertex_indices", "end_header"]
        lines += [f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f}" for v in mesh["vertices"]]
        lines += [f"3 {a} {b} {c}" for a, b, c in mesh["faces"]]
        (out / "mesh.ply").write_text("\n".join(lines) + "\n", encoding="utf-8")

    spread = [p["spread"] for p in prof]
    report = {
        "schema": "real-scan/1",
        "provenance": "real-measurement",
        "label": args.label,
        "target": "Ø28 cylinder wrapped in aluminium foil, on the blue support",
        "calibration": {"t_eff_us": summary["t_eff_us"],
                        "method": "anchor to the nominal Ø28 (relative measurement)"},
        "window_us": summary["object_window_us"],
        "counts": {"points": summary["points"], "valid": summary["valid"],
                   "acceptance": round(summary["valid"] / summary["points"], 3)},
        "per_layer": {p["z"]: {"n": p["n"], "r_median": round(p["r_med"], 3),
                               "spread": round(p["spread"], 3), "sd": round(p["sd"], 3)}
                      for p in prof},
        "uncertainty": {"median_spread_mm": round(float(np.median(spread)), 2) if spread else None,
                        "max_spread_mm": round(float(max(spread)), 2) if spread else None},
        "mesh": None if mesh is None else mesh["stats"],
        "limits": [
            "foil surface is not smooth (wrinkles 1-2 mm): radius scatter ~1-2 mm",
            "absolute radius is anchored to the nominal Ø28, not a plate calibration",
            "3 layers only (2 mm apart); this is a short segment, not the full part",
            "the plastic/foil target is a weak reflector; some points are rejected",
        ],
    }
    (out / "scan_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"{args.label}: layers {len(prof)}, acceptance {report['counts']['acceptance']:.0%}, "
          f"median spread {report['uncertainty']['median_spread_mm']} mm")
    for p in prof:
        print(f"  z={p['z']:+.0f} n={p['n']:2d} r={p['r_med']:.2f} spread={p['spread']:.2f} sd={p['sd']:.2f}")
    print(f"written -> {out}")


if __name__ == "__main__":
    main()
