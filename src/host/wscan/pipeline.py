"""Scan pipeline: point measurement, quality gates, mesh, run outputs."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import struct
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import frames, geom, profile
from .sources import Pose

MIN_SNR_DB = 15.0
MAX_SECOND_RATIO = 0.6
MAX_REPEAT_US = 0.6          # 3 samples at 5 MSPS
PATH_MIN_MM = 80.0
PATH_MAX_MM = 160.0
LAYER_TOL_MM = 2.0
DRIFT_TOL_MM = 1.0


@dataclass
class Observation:
    frame_id: str
    layer: int
    latitude_deg: float
    azimuth_deg: float
    height_mm: float
    t_peak_us: float | None = None
    path_mm: float | None = None
    point_mm: list[float] | None = None
    snr_db: float | None = None
    second_ratio: float | None = None
    repeat_mad_us: float | None = None
    frames_used: int = 0
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    provenance: str = "open_loop_command"

    @property
    def eligible(self) -> bool:
        return not self.reasons


def _dedup(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def frame_reasons(frame, peak, expect_tx=True) -> list[str]:
    reasons = []
    if expect_tx and not frame.tx_on:
        reasons.append("tx_off_frame")
    if peak is None:
        reasons.append("no_candidate")
        return reasons
    if peak.snr_db < MIN_SNR_DB:
        reasons.append("low_snr")
    if peak.at_edge:
        reasons.append("window_edge")
    if peak.second_ratio > MAX_SECOND_RATIO:
        reasons.append("ambiguous_peak")
    return reasons


def measure(frames_in, pose: Pose, calibration: geom.Calibration | None,
            quorum: int = 2) -> Observation:
    """Three frames -> one observation (median peak, repeat check)."""
    obs = Observation(frame_id="", layer=pose.layer,
                      latitude_deg=pose.latitude_deg, azimuth_deg=pose.azimuth_deg,
                      height_mm=pose.height_mm, provenance=pose.provenance)
    peaks, failed, ids = [], [], []
    for frame in frames_in:
        ids.append(frame.frame_id)
        prep = frames.prepare(frame)
        peak = frames.detect(prep, profile.WINDOW_US)
        rc = frame_reasons(frame, peak)
        if peak is not None and not rc:
            peaks.append(peak.t_us)
            obs.snr_db = peak.snr_db if obs.snr_db is None else max(obs.snr_db, peak.snr_db)
            obs.second_ratio = peak.second_ratio
        else:
            failed.extend(rc)
    obs.frame_id = ids[0] if ids else ""
    obs.frames_used = len(peaks)
    if len(peaks) < quorum:
        obs.reasons = _dedup(failed) or ["insufficient_frames"]
        return obs
    median = float(np.median(peaks))
    mad = float(np.median(np.abs(np.array(peaks) - median))) * 1.4826
    obs.t_peak_us = median
    obs.repeat_mad_us = mad
    if mad > MAX_REPEAT_US:
        obs.reasons.append("repeat_unstable")
    if calibration is None:
        return obs
    obs.path_mm = calibration.peak_to_path_mm(median)
    if not (PATH_MIN_MM <= obs.path_mm <= PATH_MAX_MM):
        obs.reasons.append("path_out_of_model")
    return obs


def localize(obs: Observation) -> None:
    if obs.path_mm is None or obs.reasons:
        return
    layer = profile.make_layer(obs.latitude_deg)
    try:
        obs.point_mm = [round(float(v), 4)
                        for v in geom.solve_ray(obs.path_mm, layer.tx, layer.rx,
                                                layer.origin, layer.direction)]
    except ValueError:
        obs.reasons.append("geometry_inconsistent")


def layer_checks(obs_list: list[Observation]) -> None:
    """Flag isolated path outliers along the azimuth sweep.

    A deviation is a *flag*, not a rejection: a real bump on the target looks
    exactly like this, and hiding it would delete the feature from the model.
    """
    paths = [o.path_mm if o.eligible else None for o in obs_list]
    finite = np.array([p for p in paths if p is not None], float)
    if finite.size < 4:
        return
    sigma = 1.4826 * float(np.median(np.abs(finite - np.median(finite))))
    for i, value in enumerate(paths):
        if value is None:
            continue
        window = [paths[k] for k in (i - 1, i, i + 1)
                  if 0 <= k < len(paths) and paths[k] is not None]
        local = float(np.median(window))
        if abs(value - local) > max(LAYER_TOL_MM, 3 * sigma):
            obs_list[i].flags.append("path_outlier")


def run_scan(source, calibration: geom.Calibration, plan: profile.ScanPlan | None = None,
             out: str | Path | None = None) -> dict:
    plan = plan or profile.DEFAULT_PLAN
    out = Path(out) if out else None
    observations: list[Observation] = []
    started = time.time()
    by_layer: dict[int, list[Observation]] = {}
    for li, lat, ai, az in plan.points():
        layer_frames = [source.capture(li, ai, fi)[0]
                        for fi in range(plan.frames_per_point)]
        pose = Pose(li, lat, az, profile.all_layers()[li].probe_z_mm)
        obs = measure(layer_frames, pose, calibration)
        localize(obs)
        observations.append(obs)
        by_layer.setdefault(li, []).append(obs)

    for rows in by_layer.values():
        layer_checks(rows)

    eligible = [o for o in observations if o.eligible and o.point_mm]
    points = np.array([o.point_mm for o in eligible], float) if eligible else np.zeros((0, 3))
    spread = azimuthal_spread(eligible)
    if len(points) < 4:
        mesh, model = None, "none"
    elif spread < 1.0:
        mesh, model = build_lathe(eligible), "lathe"
    else:
        mesh, model = build_mesh(eligible, len(plan.azimuths)), "grid"
    span = max(plan.latitudes) - min(plan.latitudes)
    arc = (geom.arc_verdict([o.point_mm for o in eligible if not o.flags])
           if len(points) >= 3 and span >= 30.0 else
           {"ok": None, "points": len(points),
            "reasons": [f"latitude span {span:.0f} deg is too short for an arc fit"]})
    truth = getattr(source, "truth", None)
    report = {
        "schema": "full-scan/1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": getattr(source, "name", type(source).__name__),
        "calibration": asdict(calibration),
        "plan": {"latitudes_deg": list(plan.latitudes),
                 "azimuths_deg": list(plan.azimuths),
                 "frames_per_point": plan.frames_per_point,
                 "points": plan.count()},
        "counts": {"points": len(observations), "eligible": len(eligible),
                   "frames": sum(o.frames_used for o in observations)},
        "reasons": _reason_counts(observations),
        "flags": _flag_counts(observations),
        "self_check": arc,
        "target_model": model,
        "mesh": None if mesh is None else {"stats": mesh["stats"]},
        "timing": {"analysis_s": round(time.time() - started, 3),
                   "budget": plan.estimate_s()},
        "limits": [
            "open-loop step counting; no encoder and no electrical limit",
            "pose provenance is a commanded position, not a measured one",
            "geometry is the CAD nominal ray until the sphere check passes",
            "no distance may be published before calibration and acoustic evidence",
        ],
    }
    if truth:
        report["truth_check"] = _truth_check(observations, truth)
    if out is not None:
        write_outputs(out, observations, report, mesh)
    return report


def _flag_counts(observations):
    counts: dict[str, int] = {}
    for o in observations:
        for f in o.flags:
            counts[f] = counts.get(f, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _reason_counts(observations):
    counts: dict[str, int] = {}
    for o in observations:
        for r in o.reasons:
            counts[r] = counts.get(r, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _truth_check(observations, truth) -> dict:
    by_id = {t["frame_id"]: t for t in truth}
    errors = []
    for o in observations:
        if not o.eligible or o.path_mm is None:
            continue
        t = by_id.get(o.frame_id)
        if t:
            errors.append(o.path_mm - t["path_mm"])
    if not errors:
        return {"n": 0}
    a = np.array(errors)
    return {"n": int(a.size), "mean_mm": float(a.mean()),
            "rms_mm": float(np.sqrt(np.mean(a ** 2))), "max_abs_mm": float(np.abs(a).max())}


# ------------------------------------------------------------------- mesh
def azimuthal_spread(observations) -> float:
    """Largest in-layer spread across azimuths; ~0 for an axisymmetric target."""
    groups: dict[float, list[np.ndarray]] = {}
    for o in observations:
        if o.point_mm:
            groups.setdefault(round(o.latitude_deg, 6), []).append(np.array(o.point_mm))
    spread = 0.0
    for pts in groups.values():
        if len(pts) < 2:
            continue
        arr = np.array(pts)
        centre = arr.mean(axis=0)
        spread = max(spread, float(np.max(np.linalg.norm(arr - centre, axis=1))) * 2.0)
    return spread


def meridian_profile(observations):
    """One (x, y, z) point per latitude, median over azimuths."""
    groups: dict[float, list[np.ndarray]] = {}
    for o in observations:
        if o.point_mm:
            groups.setdefault(round(o.latitude_deg, 6), []).append(np.array(o.point_mm))
    rows = []
    for lat in sorted(groups):
        arr = np.array(groups[lat])
        rows.append((lat, float(np.median(arr[:, 0])), float(np.median(arr[:, 1])),
                     float(np.median(arr[:, 2]))))
    return rows


def build_lathe(observations, axis_xy=(75.0, 100.0), segments: int = 36) -> dict:
    """Surface of revolution from the meridian profile (axisymmetric target)."""
    rows = meridian_profile(observations)
    cx, cy = axis_xy
    verts: list[list[float]] = []
    ring: list[list[int]] = []
    for _, x, y, z in rows:
        radius = math.hypot(x - cx, y - cy)
        if radius < 1e-6:
            ring.append([len(verts), len(verts), len(verts)])
            verts.append([cx, cy, z])
            continue
        idx = []
        for k in range(segments):
            theta = 2.0 * math.pi * k / segments
            idx.append(len(verts))
            verts.append([cx + radius * math.sin(theta), cy + radius * math.cos(theta), z])
        ring.append(idx)
    faces = []
    for lower, upper in zip(ring, ring[1:]):
        for k in range(segments):
            a, b = lower[k], lower[(k + 1) % segments]
            c, d = upper[k], upper[(k + 1) % segments]
            for tri in ([a, b, c], [b, d, c]):
                if tri[0] == tri[1] or tri[1] == tri[2] or tri[0] == tri[2]:
                    continue
                faces.append(tri)
    edges: dict[tuple[int, int], int] = {}
    for f in faces:
        for i in range(3):
            e = tuple(sorted((f[i], f[(i + 1) % 3])))
            edges[e] = edges.get(e, 0) + 1
    return {
        "vertices": np.array(verts, float).reshape(-1, 3),
        "faces": faces,
        "stats": {"model": "lathe", "meridian_points": len(rows),
                  "segments": segments, "vertices": len(verts),
                  "triangles": len(faces), "nonmanifold_edges": 0,
                  "boundary_edges": sum(v == 1 for v in edges.values()),
                  "closed": False, "caps_added": False,
                  "note": "surface of revolution through the measured meridian"},
    }


def build_mesh(observations, azimuth_count: int) -> dict:
    """Triangulate adjacent grid cells; never bridge a missing corner."""
    slots: dict[tuple[float, int], int] = {}
    verts = []
    for o in observations:
        slot = int(round((o.azimuth_deg % 360.0) / (360.0 / azimuth_count))) % azimuth_count
        key = (round(o.latitude_deg, 6), slot)
        if key in slots:
            continue
        slots[key] = len(verts)
        verts.append(o.point_mm)
    lats = sorted({k[0] for k in slots})
    faces = []
    skipped = 0
    for lower, upper in zip(lats, lats[1:]):
        for j in range(azimuth_count):
            keys = [(lower, j), (lower, (j + 1) % azimuth_count),
                    (upper, j), (upper, (j + 1) % azimuth_count)]
            if not all(k in slots for k in keys):
                skipped += 1
                continue
            a, b, c, d = (slots[k] for k in keys)
            for tri in ([a, b, c], [b, d, c]):
                p = np.array([verts[i] for i in tri])
                n = np.cross(p[1] - p[0], p[2] - p[0])
                if np.linalg.norm(n) < 1e-9:
                    skipped += 1
                    continue
                outward = p.mean(axis=0).copy()
                outward[2] = 0.0
                if float(np.dot(n, outward)) < 0:
                    tri = [tri[0], tri[2], tri[1]]
                faces.append(tri)
    edges: dict[tuple[int, int], int] = {}
    for f in faces:
        for i in range(3):
            e = tuple(sorted((f[i], f[(i + 1) % 3])))
            edges[e] = edges.get(e, 0) + 1
    return {
        "vertices": np.array(verts, float).reshape(-1, 3),
        "faces": faces,
        "stats": {"vertices": len(verts), "triangles": len(faces),
                  "skipped_cells": skipped,
                  "boundary_edges": sum(v == 1 for v in edges.values()),
                  "nonmanifold_edges": sum(v > 2 for v in edges.values()),
                  "closed": bool(faces) and all(v == 2 for v in edges.values())},
    }


def write_ply(path: Path, mesh: dict) -> None:
    v, f = mesh["vertices"], mesh["faces"]
    lines = ["ply", "format ascii 1.0", f"element vertex {len(v)}",
             "property float x", "property float y", "property float z",
             f"element face {len(f)}", "property list uchar int vertex_indices", "end_header"]
    lines += [f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in v]
    lines += [f"3 {a} {b} {c}" for a, b, c in f]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stl(path: Path, mesh: dict) -> None:
    v, f = mesh["vertices"], mesh["faces"]
    with path.open("wb") as handle:
        handle.write(b"binary STL, mm, bistatic scan".ljust(80, b" "))
        handle.write(struct.pack("<I", len(f)))
        for a, b, c in f:
            p0, p1, p2 = v[a], v[b], v[c]
            n = np.cross(p1 - p0, p2 - p0)
            ln = np.linalg.norm(n)
            n = n / ln if ln else n
            handle.write(struct.pack("<3f", *n))
            for p in (p0, p1, p2):
                handle.write(struct.pack("<3f", *p))
            handle.write(struct.pack("<H", 0))


# ----------------------------------------------------------------- outputs
def write_outputs(out: Path, observations: list[Observation], report: dict,
                  mesh: dict | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "observations.jsonl").open("w", encoding="utf-8") as handle:
        for o in observations:
            handle.write(json.dumps(asdict(o), ensure_ascii=False) + "\n")
    with (out / "points.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["latitude_deg", "azimuth_deg", "height_mm", "path_mm",
                    "t_peak_us", "x_mm", "y_mm", "z_mm", "snr_db",
                    "eligible", "reasons"])
        for o in observations:
            p = o.point_mm or [None, None, None]
            w.writerow([o.latitude_deg, o.azimuth_deg, o.height_mm, o.path_mm,
                        o.t_peak_us, p[0], p[1], p[2], o.snr_db,
                        int(o.eligible), ";".join(o.reasons)])
    if mesh is not None:
        write_ply(out / "mesh.ply", mesh)
        write_stl(out / "mesh.stl", mesh)
    (out / "scan_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def file_manifest(out: Path) -> dict:
    files = {}
    for p in sorted(out.iterdir()):
        if p.is_file():
            files[p.name] = {"bytes": p.stat().st_size,
                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    return files





