"""Axisymmetric-target scan: vertical cylinder and cone.

Why this mode exists
--------------------
A sphere only returns a specular echo at its equator unless the probes are
pitched.  A body whose side wall is vertical (cylinder, cone, stepped shaft)
keeps the specular condition at every height with the probes fixed, so the
scan needs no pitch and no per-layer human step: only lift + rotation move.

Geometry
--------
The two probes sit at the same height h, symmetric about x=75, and look along
+y.  By symmetry the reflection point Q lies in the meridian plane x=75, and
the specular condition reduces to "the surface normal at Q passes through the
probe midpoint M=(y_m, h)".  Writing m=|Q-M|,

    L = |Q-TX| + |Q-RX| = 2*sqrt(a^2 + m^2),   a = spacing/2

For a vertical wall the normal is horizontal, so Q is exactly at height h and
m is directly the stand-off distance: the ray-constrained reconstruction is
exact.  For a cone the normal is tilted, Q sits off the probe height, and the
vertical-wall inversion carries a bias that is quantified here.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import frames, geom, profile
from .sources import SyntheticScan

AXIS_X = 75.0
AXIS_Y = 100.0
PROBE_Y = 27.31          # equator stand-off reconstructed from the CAD table
HALF_SPACING = profile.PROBE_SPACING_MM / 2.0


# ------------------------------------------------------------------ objects
@dataclass
class Cylinder:
    radius_mm: float
    z0_mm: float
    z1_mm: float
    kind: str = "cylinder"

    def radius_at(self, z: float) -> float:
        return self.radius_mm

    def normal(self, z: float) -> tuple[float, float]:
        return (-1.0, 0.0)          # outward, in (y, z)

    def nominal_radius(self, z: float) -> float:
        return self.radius_mm


@dataclass
class Cone:
    r_bottom_mm: float
    r_top_mm: float
    z0_mm: float
    z1_mm: float
    kind: str = "cone"

    def radius_at(self, z: float) -> float:
        t = (z - self.z0_mm) / (self.z1_mm - self.z0_mm)
        return self.r_bottom_mm + t * (self.r_top_mm - self.r_bottom_mm)

    def normal(self, z: float) -> tuple[float, float]:
        k = (self.r_top_mm - self.r_bottom_mm) / (self.z1_mm - self.z0_mm)
        n = np.array([-1.0, -k])
        n /= np.linalg.norm(n)
        return float(n[0]), float(n[1])

    def nominal_radius(self, z: float) -> float:
        return self.radius_at(z)


def specular_hit(obj, h: float) -> tuple[tuple[float, float], float]:
    """Reflection point (y, z) and bistatic path for probes at height h."""
    if isinstance(obj, Cylinder):
        r = obj.radius_mm
        q = (AXIS_Y - r, h)
        m = math.hypot(q[0] - PROBE_Y, 0.0)
        return q, 2.0 * math.hypot(HALF_SPACING, m)

    def residual(z: float):
        r = obj.radius_at(z)
        q = np.array([AXIS_Y - r, z])
        d = q - np.array([PROBE_Y, h])
        n = np.array(obj.normal(z))
        # normal must be parallel to (Q - M)
        return d[0] * n[1] - d[1] * n[0]

    lo, hi = obj.z0_mm, obj.z1_mm
    f_lo, f_hi = residual(lo), residual(hi)
    if f_lo * f_hi > 0:
        z = h
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if residual(lo) * residual(mid) <= 0:
                hi = mid
            else:
                lo = mid
        z = 0.5 * (lo + hi)
    r = obj.radius_at(z)
    q = (AXIS_Y - r, z)
    m = math.hypot(q[0] - PROBE_Y, q[1] - h)
    return q, 2.0 * math.hypot(HALF_SPACING, m)


def ray_point(path_mm: float, h: float) -> tuple[float, float]:
    """Vertical-wall inversion: assume the normal is horizontal at height h."""
    half = path_mm / 2.0
    inner = half * half - HALF_SPACING * HALF_SPACING
    if inner <= 0:
        raise ValueError("path shorter than the probe spacing")
    m = math.sqrt(inner)
    return (PROBE_Y + m, h)


def shaped_inversion(obj, path_mm: float, h: float):
    """Invert a known axisymmetric shape (calibration cone or cylinder).

    The path fixes m=|Q-M|; walking the meridian gives the heights where that
    distance occurs, and the specular branch is the one whose normal points at
    M.  Returns (radius, z_reflection) or None.
    """
    half = path_mm / 2.0
    inner = half * half - HALF_SPACING * HALF_SPACING
    if inner <= 0:
        return None
    m = math.sqrt(inner)
    best = None
    for z in np.linspace(obj.z0_mm, obj.z1_mm, 2001):
        r = obj.radius_at(float(z))
        d = np.array([AXIS_Y - r - PROBE_Y, float(z) - h])
        err = abs(float(np.linalg.norm(d)) - m)
        n = np.array(obj.normal(float(z)))
        align = abs(float(d[0] * n[1] - d[1] * n[0])) / max(float(np.linalg.norm(d)), 1e-9)
        score = err + 0.5 * align
        if best is None or score < best[0]:
            best = (score, float(z), r)
    return (best[2], best[1]) if best else None


# --------------------------------------------------------------------- plan
@dataclass
class RingPlan:
    obj: object
    heights: list[float]
    azimuths: tuple[float, ...] = tuple(30.0 * i for i in range(12))
    frames_per_point: int = 3

    def points(self):
        for ri, h in enumerate(self.heights):
            order = list(range(len(self.azimuths)))
            if ri % 2:
                order.reverse()
            for j in order:
                yield ri, h, j, self.azimuths[j]

    def count(self) -> int:
        return len(self.heights) * len(self.azimuths)


def default_plan(obj) -> RingPlan:
    z0, z1 = max(obj.z0_mm, 55.0), min(obj.z1_mm, 93.0)
    n = 9
    heights = [z0 + (z1 - z0) * i / (n - 1) for i in range(n)]
    return RingPlan(obj, heights)


# ------------------------------------------------------------------ capture
class VerticalSource:
    name = "synthetic_axisymmetric"

    def __init__(self, obj, t_eff_us: float = 8.6, noise: float = 6.0,
                 echo: float = 240.0, clutter: float = 1300.0, seed: int = 11):
        self.obj = obj
        self.t_eff_us = t_eff_us
        self.noise = noise
        self.echo = echo
        self.clutter = clutter
        self.seed = seed
        self.truth: list[dict] = []

    def _t(self):
        return (np.arange(profile.ADC_SAMPLES) - 51) * profile.SAMPLE_US

    def capture(self, ring_index: int, height: float, az_index: int, frame_index: int):
        t = self._t()
        q, path = specular_hit(self.obj, height)
        rng = np.random.default_rng((ring_index * 100 + az_index) * 10 + frame_index)
        x = rng.normal(0.0, self.noise, t.size)
        gate = (t >= 51.2) & (t < 59.2)
        x[gate] += self.clutter * np.sin(2 * np.pi * (t[gate] - 51.2))
        t_echo = self.t_eff_us + path / (profile.SOUND_SPEED_M_S / 1000.0)
        env = np.exp(-0.5 * ((t - t_echo) / 1.5) ** 2)
        x += self.echo * env * np.sin(2 * np.pi * (t - t_echo))
        frame = frames.Frame(t_us=t, diff=x,
                             frame_id=f"R{ring_index:02d}A{az_index:02d}F{frame_index}",
                             tx_on=True, source="synthetic")
        self.truth.append({"frame_id": frame.frame_id, "height_mm": height,
                           "path_mm": path, "q": q,
                           "radius_true_mm": self.obj.radius_at(height)})
        return frame


# -------------------------------------------------------------------- run
@dataclass
class RingResult:
    height_mm: float
    azimuth_deg: float
    t_peak_us: float | None = None
    path_mm: float | None = None
    m_mm: float | None = None
    radius_mm: float | None = None
    radius_shaped_mm: float | None = None
    z_reflection_mm: float | None = None
    radius_true_mm: float | None = None
    snr_db: float | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.reasons


def run(obj, calibration: geom.Calibration, out: Path, plan: RingPlan | None = None,
        source: VerticalSource | None = None, quorum: int = 2) -> dict:
    plan = plan or default_plan(obj)
    source = source or VerticalSource(obj)
    records: list[RingResult] = []
    for ri, h, ai, az in plan.points():
        peaks, failed = [], []
        for fi in range(plan.frames_per_point):
            frame = source.capture(ri, h, ai, fi)
            prep = frames.prepare(frame)
            peak = frames.detect(prep, profile.WINDOW_US)
            if peak is None:
                failed.append("no_candidate")
                continue
            if peak.snr_db < 12.0:
                failed.append("low_snr")
            if peak.at_edge:
                failed.append("window_edge")
            if peak.second_ratio > 0.6:
                failed.append("ambiguous_peak")
            if not (failed and failed[-1] in ("low_snr", "window_edge", "ambiguous_peak")):
                peaks.append(peak)
        rec = RingResult(height_mm=h, azimuth_deg=az)
        if peaks:
            rec.snr_db = float(max(p.snr_db for p in peaks))
        if len(peaks) < quorum:
            rec.reasons = sorted(set(failed)) or ["insufficient_frames"]
        else:
            t_peak = float(np.median([p.t_us for p in peaks]))
            rec.t_peak_us = t_peak
            rec.path_mm = calibration.peak_to_path_mm(t_peak)
            try:
                y, z = ray_point(rec.path_mm, h)
                rec.m_mm = y - PROBE_Y
                rec.radius_mm = AXIS_Y - y
                shaped = shaped_inversion(obj, rec.path_mm, h)
                if shaped:
                    rec.radius_shaped_mm = shaped[0]
                    rec.z_reflection_mm = shaped[1]
            except ValueError:
                rec.reasons.append("path_out_of_model")
            rec.radius_true_mm = obj.radius_at(h)
        records.append(rec)

    profile_rows = profile_table(records, plan)
    mesh = build_lathe(profile_rows)
    report = {
        "schema": "axisym-scan/1",
        "object": {"kind": obj.kind, "nominal": _obj_dict(obj)},
        "plan": {"heights_mm": plan.heights, "azimuths_deg": list(plan.azimuths),
                 "points": plan.count()},
        "calibration": {"t_eff_us": calibration.t_eff_us,
                        "sound_speed_m_s": calibration.sound_speed_m_s},
        "counts": {"points": len(records),
                   "eligible": sum(1 for r in records if r.eligible)},
        "profile": profile_rows,
        "mesh": mesh["stats"],
        "limits": [
            "vertical-wall inversion assumes the surface normal is horizontal",
            "for a cone the reflection point is off the probe height; the bias is reported",
            "pose is a commanded position (no encoder)",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.csv").write_text(_profile_csv(profile_rows), encoding="utf-8")
    _write_ply(out / "profile_mesh.ply", mesh)
    (out / "scan_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def profile_table(records: list[RingResult], plan: RingPlan) -> list[dict]:
    """One row per probe height.

    ``radius_vertical`` is the vertical-wall answer (exact only for a cylinder).
    ``radius_shaped`` is the radius *at the reflection height* z_reflection,
    which is the physically correct assignment for a cone.  Comparing the two
    against the nominal shape shows the bias of the simple assumption.
    """
    rows = []
    obj = plan.obj
    for h in plan.heights:
        ring = [r for r in records if abs(r.height_mm - h) < 1e-9 and r.eligible]
        radii = [r.radius_mm for r in ring if r.radius_mm is not None]
        shaped = [r.radius_shaped_mm for r in ring if r.radius_shaped_mm is not None]
        z_ref = [r.z_reflection_mm for r in ring if r.z_reflection_mm is not None]
        true = next((r.radius_true_mm for r in records
                     if abs(r.height_mm - h) < 1e-9 and r.radius_true_mm is not None), None)
        row = {"height_mm": round(h, 3),
               "radius_vertical_mm": None, "spread_mm": None,
               "z_reflection_mm": None, "radius_shaped_mm": None,
               "radius_true_mm": None if true is None else round(float(true), 3),
               "radius_true_ref_mm": None,
               "error_vertical_mm": None, "error_shaped_mm": None,
               "points": len(radii)}
        if radii:
            med = float(np.median(radii))
            row["radius_vertical_mm"] = round(med, 3)
            row["spread_mm"] = round(float(max(radii) - min(radii)), 3)
            if true is not None:
                row["error_vertical_mm"] = round(med - float(true), 3)
        if shaped and z_ref:
            z_med = float(np.median(z_ref))
            med_s = float(np.median(shaped))
            row["z_reflection_mm"] = round(z_med, 3)
            row["radius_shaped_mm"] = round(med_s, 3)
            row["radius_true_ref_mm"] = round(float(obj.radius_at(z_med)), 3)
            row["error_shaped_mm"] = round(med_s - float(obj.radius_at(z_med)), 3)
        rows.append(row)
    return rows


def build_lathe(rows, segments: int = 36) -> dict:
    """Revolve the measured meridian; for a cone the ring height is z_reflection."""
    verts, ring = [], []
    usable = []
    for row in rows:
        z = row.get("z_reflection_mm") if row.get("radius_shaped_mm") is not None \
            else row.get("height_mm")
        r = row.get("radius_shaped_mm") if row.get("radius_shaped_mm") is not None \
            else row.get("radius_vertical_mm")
        if r is None or z is None:
            usable.append(None)
            continue
        usable.append((float(z), float(r)))
    usable = [u for u in usable if u]
    usable.sort(key=lambda u: u[0])
    for z, r in usable:
        idx = []
        for k in range(segments):
            theta = 2.0 * math.pi * k / segments
            idx.append(len(verts))
            verts.append([AXIS_X + r * math.sin(theta),
                          AXIS_Y + r * math.cos(theta), z])
        ring.append(idx)
    faces = []
    for lower, upper in zip(ring, ring[1:]):
        for k in range(segments):
            a, b = lower[k], lower[(k + 1) % segments]
            c, d = upper[k], upper[(k + 1) % segments]
            faces += [[a, b, c], [b, d, c]]
    return {"vertices": np.array(verts, float).reshape(-1, 3), "faces": faces,
            "stats": {"vertices": len(verts), "triangles": len(faces),
                      "segments": segments, "closed": False,
                      "z_range_mm": [usable[0][0], usable[-1][0]] if usable else None}}



def _write_ply(path: Path, mesh: dict) -> None:
    v, f = mesh["vertices"], mesh["faces"]
    lines = ["ply", "format ascii 1.0", f"element vertex {len(v)}",
             "property float x", "property float y", "property float z",
             f"element face {len(f)}", "property list uchar int vertex_indices",
             "end_header"]
    lines += [f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in v]
    lines += [f"3 {a} {b} {c}" for a, b, c in f]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _profile_csv(rows) -> str:
    head = ("height_mm,radius_vertical_mm,spread_mm,z_reflection_mm,radius_shaped_mm,"
            "radius_true_mm,radius_true_ref_mm,error_vertical_mm,error_shaped_mm,points\n")
    body = "".join(
        f"{r['height_mm']},{_num(r['radius_vertical_mm'])},{_num(r['spread_mm'])},"
        f"{_num(r['z_reflection_mm'])},{_num(r['radius_shaped_mm'])},"
        f"{_num(r['radius_true_mm'])},{_num(r['radius_true_ref_mm'])},"
        f"{_num(r['error_vertical_mm'])},{_num(r['error_shaped_mm'])},"
        f"{r['points']}\n" for r in rows)
    return head + body


def _num(value):
    return "" if value is None else f"{value}"


def _obj_dict(obj) -> dict:
    if isinstance(obj, Cylinder):
        return {"radius_mm": obj.radius_mm, "z0_mm": obj.z0_mm, "z1_mm": obj.z1_mm}
    return {"r_bottom_mm": obj.r_bottom_mm, "r_top_mm": obj.r_top_mm,
            "z0_mm": obj.z0_mm, "z1_mm": obj.z1_mm}





