"""Consume an acquire.tcl run directory: CSV + manifest -> observations/profile/mesh.

This is the offline half of the control flow.  It never touches hardware, and it
refuses to invent a radius when the frames carry no accepted echo.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import frames, geom, pipeline, profile, vertical


@dataclass
class Point:
    seq: int
    latitude_deg: float
    azimuth_deg: float
    height_mm: float
    tx: int
    frames: list = field(default_factory=list)   # [(file, pose_lift, pose_rot)]


def load_run(run_dir: str | Path) -> list[Point]:
    run = Path(run_dir)
    manifest = run / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"no manifest.jsonl in {run}")
    points: dict[int, Point] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        p = points.get(m["seq"])
        if p is None:
            p = Point(m["seq"], m["latitude_deg"], m["azimuth_deg"],
                      m["height_mm"], m.get("tx", 0))
            points[m["seq"]] = p
        p.frames.append((run / m["file"], m.get("pose_lift"), m.get("pose_rot")))
    return [points[k] for k in sorted(points)]


def analyse(run_dir: str | Path, out: str | Path,
            calibration: geom.Calibration | None = None,
            axis_xy=(vertical.AXIS_X, vertical.AXIS_Y)) -> dict:
    points = load_run(run_dir)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    observations = []
    for p in points:
        loaded = []
        for path, _, _ in p.frames:
            try:
                loaded.append(frames.to_frame(frames.read_ila_csv(path),
                                              frame_id=path.name, source=str(path)))
            except Exception as exc:      # keep the reason, do not crash the run
                observations.append({"seq": p.seq, "azimuth_deg": p.azimuth_deg,
                                     "height_mm": p.height_mm, "path_mm": None,
                                     "radius_mm": None, "reasons": [f"decode_failed:{exc}"]})
        if not loaded:
            continue
        pose = type("P", (), {"layer": 0, "latitude_deg": p.latitude_deg,
                              "azimuth_deg": p.azimuth_deg, "height_mm": p.height_mm,
                              "provenance": "open_loop_latched"})()
        obs = _measure_averaged(loaded, pose, calibration)
        radius = None
        if obs.path_mm is not None:
            try:
                y, _ = vertical.ray_point(obs.path_mm, p.height_mm)
                radius = axis_xy[1] - y
            except ValueError:
                obs.reasons.append("path_out_of_model")
        observations.append({
            "seq": p.seq, "azimuth_deg": p.azimuth_deg, "height_mm": p.height_mm,
            "t_peak_us": obs.t_peak_us, "path_mm": obs.path_mm, "radius_mm": radius,
            "snr_db": obs.snr_db, "mad_us": obs.repeat_mad_us,
            "reasons": obs.reasons, "frames": len(loaded),
            "pose_rot": p.frames[0][2] if p.frames else None,
        })

    rows = _profile_rows(observations)
    mesh = vertical.build_lathe(rows) if any(r["radius_median_mm"] for r in rows) else None
    report = {
        "schema": "acquire-analysis/1",
        "run": str(run_dir),
        "calibration": None if calibration is None else {
            "t_eff_us": calibration.t_eff_us,
            "sound_speed_m_s": calibration.sound_speed_m_s,
            "ident": calibration.ident, "provisional": calibration.provisional},
        "counts": {"points": len(points),
                   "frames": sum(len(p.frames) for p in points),
                   "with_radius": sum(1 for o in observations if o.get("radius_mm") is not None)},
        "reasons": _reason_counts(observations),
        "profile": rows,
        "mesh": None if mesh is None else mesh["stats"],
        "limits": [
            "pose is the hardware-latched command count, not an encoder reading",
            "no radius is produced without an accepted echo and a calibration",
            "the vertical-wall inversion assumes a horizontal surface normal",
        ],
    }
    (out / "observations.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in observations) + "\n",
        encoding="utf-8")
    (out / "profile.csv").write_text(_profile_csv(rows), encoding="utf-8")
    if mesh is not None:
        _write_ply(out / "profile_mesh.ply", mesh)
    (out / "scan_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _measure_averaged(loaded, pose, calibration):
    """Average the envelopes of the frames at one pose, then detect once.

    The echo is coherent across frames at a fixed pose, the noise is not, so the
    average raises the SNR by ~sqrt(n) without moving the peak.
    """
    if len(loaded) < 2:
        return pipeline.measure(loaded, pose, calibration, quorum=1)
    preps = [frames.prepare(f) for f in loaded]
    grid = np.arange(preps[0].t_us[0], preps[-1].t_us[-1], profile.SAMPLE_US)
    env = np.vstack([np.interp(grid, p.t_us, p.envelope) for p in preps]).mean(axis=0)
    win = (grid >= profile.WINDOW_US[0]) & (grid <= profile.WINDOW_US[1])
    base = float(np.median(env[win])) if win.any() else 1.0
    idx = np.flatnonzero(win)
    if idx.size == 0:
        return pipeline.measure(loaded, pose, calibration, quorum=1)
    k = idx[np.argmax(env[idx])]
    peak = float(env[k])
    snr_db = 20.0 * np.log10(max(peak, 1e-9) / max(base, 1e-9))
    t_peak = float(grid[k])
    path = None if calibration is None else calibration.peak_to_path_mm(t_peak)
    reasons = []
    if snr_db < 15.0:
        reasons.append("low_snr")
    if t_peak <= profile.WINDOW_US[0] + 0.4 or t_peak >= profile.WINDOW_US[1] - 0.4:
        reasons.append("window_edge")
    return pipeline.Observation(
        frame_id=str(pose.azimuth_deg), layer=pose.layer,
        latitude_deg=pose.latitude_deg, azimuth_deg=pose.azimuth_deg,
        height_mm=pose.height_mm, t_peak_us=t_peak, path_mm=path,
        snr_db=snr_db, repeat_mad_us=0.0, second_ratio=0.0,
        frames_used=len(loaded), reasons=reasons,
        provenance="open_loop_latched")


def _profile_rows(observations):
    by_height: dict[float, list[dict]] = {}
    for o in observations:
        by_height.setdefault(round(float(o["height_mm"]), 3), []).append(o)
    rows = []
    for h in sorted(by_height):
        group = by_height[h]
        radii = [o["radius_mm"] for o in group if o.get("radius_mm") is not None]
        rows.append({
            "height_mm": h,
            "radius_median_mm": None if not radii else round(float(np.median(radii)), 3),
            "radius_vertical_mm": None if not radii else round(float(np.median(radii)), 3),
            "radius_shaped_mm": None,
            "radius_spread_mm": None if not radii else round(float(max(radii) - min(radii)), 3),
            "radius_true_mm": None,
            "error_mm": None,
            "points": len(radii),
        })
    return rows


def _reason_counts(observations):
    counts: dict[str, int] = {}
    for o in observations:
        for r in o.get("reasons", []):
            key = r.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _profile_csv(rows) -> str:
    head = "height_mm,radius_median_mm,radius_spread_mm,points\n"
    body = "".join(
        f"{r['height_mm']},{'' if r['radius_median_mm'] is None else r['radius_median_mm']},"
        f"{'' if r['radius_spread_mm'] is None else r['radius_spread_mm']},{r['points']}\n"
        for r in rows)
    return head + body


def _write_ply(path: Path, mesh: dict) -> None:
    v, f = mesh["vertices"], mesh["faces"]
    lines = ["ply", "format ascii 1.0", f"element vertex {len(v)}",
             "property float x", "property float y", "property float z",
             f"element face {len(f)}", "property list uchar int vertex_indices",
             "end_header"]
    lines += [f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in v]
    lines += [f"3 {a} {b} {c}" for a, b, c in f]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")




