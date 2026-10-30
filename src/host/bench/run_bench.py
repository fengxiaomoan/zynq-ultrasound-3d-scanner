"""Synthetic benchmark for the four V3-P targets.

Reads the digital-phantom scans in ``hd_demo/points_<shape>.jsonl`` and writes
the same artifacts a real run would produce (profile.csv, mesh.ply, error
table), with an explicit ``provenance=synthetic`` marker in every file and in
the README.

    python bench/run_bench.py

This is a simulation/verification dataset: the point timings are generated from
a known radius, not measured from the tank.  It is meant for the
"sim/verification" section of the submission, not as measured output.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
from wscan import vertical  # noqa: E402

SHAPES = {
    "cylinder": "圆柱 Ø28",
    "cone1": "圆锥 Ø32→Ø28",
    "cone2": "圆锥 Ø32→Ø16",
    "step": "台阶轴 Ø28/Ø18",
}
T_EFF = 9.40   # +0.25 us calibration bias left in on purpose
C_MM_US = 1.48
A = 12.5
AXIS_Y = 100.0
PROBE_Y = 27.31


def radius_of(t: float) -> float | None:
    path = (t - T_EFF) * C_MM_US
    inner = (path / 2.0) ** 2 - A * A
    if inner <= 0:
        return None
    return AXIS_Y - PROBE_Y - math.sqrt(inner)


def load(shape: str) -> list[dict]:
    path = PKG / "data" / "demo" / f"points_{shape}.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for p in rows:
        p["r_meas"] = radius_of(p["t"]) if p.get("accepted") else None
    return rows


def layers(rows: list[dict]) -> list[dict]:
    by: dict[int, list[dict]] = {}
    for p in rows:
        by.setdefault(int(p["layer"]), []).append(p)
    out = []
    for li in sorted(by):
        g = by[li]
        acc = [p for p in g if p.get("accepted") and p.get("r_meas") is not None]
        r_true = float(np.median([p["r_true"] for p in g]))
        if not acc:
            out.append({"layer": li, "z": float(np.mean([p["z"] for p in g])), "n": 0,
                        "r_meas": None, "r_true": r_true, "err": None, "spread": None})
            continue
        r = [p["r_meas"] for p in acc]
        med = float(np.median(r))
        out.append({"layer": li, "z": float(np.mean([p["z"] for p in g])), "n": len(acc),
                    "r_meas": med, "r_true": r_true, "err": med - r_true,
                    "spread": float(max(r) - min(r))})
    return out


def write_ply(path: Path, mesh: dict) -> None:
    v, f = mesh["vertices"], mesh["faces"]
    lines = ["ply", "format ascii 1.0",
             "comment synthetic_digital_phantom - not measured data",
             f"element vertex {len(v)}",
             "property float x", "property float y", "property float z",
             f"element face {len(f)}",
             "property list uchar int vertex_indices", "end_header"]
    lines += [f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in v]
    lines += [f"3 {a} {b} {c}" for a, b, c in f]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(shape: str) -> dict:
    rows = load(shape)
    lay = layers(rows)
    good = [r for r in lay if r["r_meas"] is not None]
    per_point = [(p["r_meas"] - p["r_true"]) for p in rows
                 if p.get("accepted") and p.get("r_meas") is not None]
    mae = float(np.mean([abs(r["err"]) for r in good])) if good else float("nan")
    rmse = float(np.sqrt(np.mean(np.square([r["err"] for r in good])))) if good else float("nan")
    maxerr = float(np.max([abs(r["err"]) for r in good])) if good else float("nan")
    prms = float(np.sqrt(np.mean(np.square(per_point)))) if per_point else float("nan")
    coverage = float(len(good)) / len(lay) if lay else 0.0

    mesh_rows = [{"height_mm": r["z"], "radius_vertical_mm": r["r_meas"]} for r in good]
    mesh = vertical.build_lathe(mesh_rows, segments=48) if len(mesh_rows) >= 2 else None

    out = PKG / "build" / "output" / "bench" / shape
    out.mkdir(parents=True, exist_ok=True)

    with (out / "profile.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# provenance=synthetic_digital_phantom",
                    "shape=" + shape, "t_eff_us=%.3f" % T_EFF, "c_mm_us=%.3f" % C_MM_US])
        w.writerow(["z_mm", "accepted_points", "r_meas_median_mm",
                    "r_true_median_mm", "error_mm", "spread_mm"])
        for r in lay:
            w.writerow([f"{r['z']:.2f}", r["n"],
                        "" if r["r_meas"] is None else f"{r['r_meas']:.3f}",
                        f"{r['r_true']:.3f}",
                        "" if r["err"] is None else f"{r['err']:+.3f}",
                        "" if r["spread"] is None else f"{r['spread']:.3f}"])

    with (out / "error_table.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# provenance=synthetic_digital_phantom"])
        w.writerow(["layer", "z_mm", "n", "r_meas_mm", "r_true_mm", "error_mm", "spread_mm"])
        for r in lay:
            w.writerow([r["layer"], f"{r['z']:.2f}", r["n"],
                        "" if r["r_meas"] is None else f"{r['r_meas']:.3f}",
                        f"{r['r_true']:.3f}",
                        "" if r["err"] is None else f"{r['err']:+.3f}",
                        "" if r["spread"] is None else f"{r['spread']:.3f}"])

    with (out / "points.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# provenance=synthetic_digital_phantom"])
        w.writerow(["seq", "z_mm", "az_deg", "snr_db", "accepted", "r_meas_mm", "r_true_mm", "err_mm"])
        for p in rows:
            w.writerow([p["seq"], f"{p['z']:.3f}", f"{p['az']:.3f}", f"{p['snr']:.2f}",
                        int(bool(p.get("accepted"))),
                        "" if p.get("r_meas") is None else f"{p['r_meas']:.3f}",
                        f"{p['r_true']:.3f}",
                        "" if p.get("r_meas") is None else f"{p['r_meas']-p['r_true']:+.3f}"])

    if mesh:
        write_ply(out / "mesh.ply", mesh)

    report = {
        "schema": "bench-synthetic/1",
        "provenance": "synthetic_digital_phantom",
        "disclaimer": "Generated from a known radius model; NOT measured data.",
        "shape": shape,
        "label": SHAPES[shape],
        "calibration": {"t_eff_us": T_EFF, "sound_speed_m_s": 1480.0, "method": "fixed anchor + 0.25 us bias (uncalibrated setup)"},
        "counts": {"points": len(rows),
                   "accepted": sum(1 for p in rows if p.get("accepted")),
                   "layers": len(lay), "layers_with_data": len(good)},
        "coverage": round(coverage, 4),
        "summary": {"mae_mm": mae, "rmse_layer_mm": rmse, "max_abs_layer_error_mm": maxerr,
                    "point_rms_mm": prms},
        "mesh": None if mesh is None else mesh["stats"],
        "limits": [
            "synthetic point timings, generated from the nominal radius + seeded errors",
            "radius uses the vertical-wall inversion and a fixed t_eff",
            "not evidence of acoustic performance, calibration or repeatability",
        ],
    }
    (out / "scan_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return report


def main() -> None:
    out = PKG / "build" / "output" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for shape in SHAPES:
        rep = run(shape)
        summary.append({
            "shape": shape, "label": SHAPES[shape],
            "points": rep["counts"]["points"], "accepted": rep["counts"]["accepted"],
            "pass_rate": round(rep["counts"]["accepted"] / rep["counts"]["points"], 4),
            "layers": rep["counts"]["layers"], "coverage": rep["coverage"],
            "mae_mm": round(rep["summary"]["mae_mm"], 4),
            "rmse_mm": round(rep["summary"]["rmse_layer_mm"], 4),
            "max_err_mm": round(rep["summary"]["max_abs_layer_error_mm"], 4),
            "point_rms_mm": round(rep["summary"]["point_rms_mm"], 4),
            "triangles": 0 if not rep["mesh"] else rep["mesh"]["triangles"],
        })
        print(f"{shape:9s} points={rep['counts']['points']} accepted={rep['counts']['accepted']} "
              f"layers={rep['counts']['layers_with_data']}/{rep['counts']['layers']} "
              f"MAE={rep['summary']['mae_mm']:.3f} mm  max={rep['summary']['max_abs_layer_error_mm']:.3f} mm")

    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(f"written -> {out}")


if __name__ == "__main__":
    main()

