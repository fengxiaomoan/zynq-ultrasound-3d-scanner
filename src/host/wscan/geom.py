"""Bistatic geometry, time calibration and the standard-sphere self check.

The localization rule follows the validated module
``suanfa/ultrasound-flow/scan_geometry.py``: one bistatic time only constrains
an ellipsoid, so a point is produced only on an independently known ray.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import profile


@dataclass(frozen=True)
class Calibration:
    t_eff_us: float
    sound_speed_m_s: float = profile.SOUND_SPEED_M_S
    ident: str = "unverified"
    residual_us: float = float("nan")
    holdout_error_mm: float = float("nan")
    provisional: bool = True

    def peak_to_path_mm(self, t_peak_us: float) -> float:
        return self.sound_speed_m_s / 1000.0 * (t_peak_us - self.t_eff_us)


def plate_path_mm(distance_mm: float, spacing_mm: float = profile.PROBE_SPACING_MM) -> float:
    return 2.0 * math.sqrt(distance_mm ** 2 + (spacing_mm / 2.0) ** 2)


def fit_calibration(peaks_us, distances_mm, sound_speed_m_s=profile.SOUND_SPEED_M_S,
                    ident="plate") -> Calibration:
    """Fix c, estimate t_eff as the median offset (robust to one bad frame)."""
    if len(peaks_us) != len(distances_mm) or len(peaks_us) < 3:
        raise ValueError("need at least three calibration pairs")
    offsets = np.array([t - plate_path_mm(d) / (sound_speed_m_s / 1000.0)
                        for t, d in zip(peaks_us, distances_mm)])
    t_eff = float(np.median(offsets))
    return Calibration(t_eff, sound_speed_m_s, ident,
                       residual_us=float(np.std(offsets)))


def path_length(point, tx, rx) -> float:
    p = np.asarray(point, float)
    return float(np.linalg.norm(p - np.asarray(tx, float)) +
                 np.linalg.norm(p - np.asarray(rx, float)))


def solve_ray(path_mm: float, tx, rx, origin, direction,
              maximum_mm: float = 200.0, iterations: int = 70) -> np.ndarray:
    tx, rx = np.asarray(tx, float), np.asarray(rx, float)
    origin = np.asarray(origin, float)
    d = np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    if float(np.dot(origin - tx, d)) < -1e-9 or float(np.dot(origin - rx, d)) < -1e-9:
        raise ValueError("ray may contain two bistatic solutions")
    if not path_length(origin, tx, rx) < path_mm < path_length(
            origin + maximum_mm * d, tx, rx):
        raise ValueError("path outside the constrained ray segment")
    lo, hi = 0.0, float(maximum_mm)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if path_length(origin + mid * d, tx, rx) < path_mm:
            lo = mid
        else:
            hi = mid
    return origin + 0.5 * (lo + hi) * d


def ray_sphere_hit(origin, direction, center=profile.SPHERE_CENTER,
                   radius: float = profile.SPHERE_RADIUS) -> np.ndarray:
    o = np.asarray(origin, float) - np.asarray(center, float)
    d = np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    b = 2.0 * float(np.dot(o, d))
    c = float(np.dot(o, o)) - radius * radius
    disc = b * b - 4.0 * c
    if disc < 0:
        raise ValueError("ray misses the sphere")
    root = math.sqrt(disc)
    candidates = [(-b - root) / 2.0, (-b + root) / 2.0]
    positive = [t for t in candidates if t > 0]
    if not positive:
        raise ValueError("sphere is behind the ray origin")
    return np.asarray(origin, float) + min(positive) * d


def fit_arc(points, radius: float | None = None) -> dict:
    """Circle fit in the YZ plane; with a fixed radius it is a translation fit."""
    pts = np.asarray(points, float)
    if pts.shape[0] < 3:
        raise ValueError("need at least three points")
    y, z = pts[:, 1], pts[:, 2]
    if radius is None:
        a = np.column_stack([2.0 * y, 2.0 * z, np.ones(len(y))])
        sol, *_ = np.linalg.lstsq(a, y * y + z * z, rcond=None)
        cy, cz = float(sol[0]), float(sol[1])
        r = math.sqrt(max(sol[2] + cy * cy + cz * cz, 0.0))
    else:
        cy, cz, r = float(np.mean(y)), float(np.mean(z)), float(radius)
        for _ in range(40):
            dy, dz = cy - y, cz - z
            dist = np.hypot(dy, dz)
            keep = dist > 1e-9
            if not keep.any():
                break
            res = dist[keep] - r
            jac = np.column_stack([dy[keep] / dist[keep], dz[keep] / dist[keep]])
            step, *_ = np.linalg.lstsq(jac, -res, rcond=None)
            cy += float(step[0])
            cz += float(step[1])
            if float(np.hypot(*step)) < 1e-12:
                break
    residual = np.hypot(y - cy, z - cz) - r
    return {"center_mm": [float(np.mean(pts[:, 0])), cy, cz], "radius_mm": r,
            "rms_mm": float(np.sqrt(np.mean(residual ** 2))),
            "points": int(len(pts))}


def arc_verdict(points, reference_center=None, tol_mm: float = 1.0,
                radius_tol_mm: float = 2.0) -> dict:
    if points is None or len(points) < 3:
        return {"ok": None, "points": 0 if points is None else len(points),
                "reasons": ["fewer than three sphere points; not evaluated"]}
    free = fit_arc(points)
    fixed = fit_arc(points, radius=profile.SPHERE_RADIUS)
    cy, cz = fixed["center_mm"][1], fixed["center_mm"][2]
    ref = reference_center or (profile.SPHERE_CENTER[1], profile.SPHERE_CENTER[2])
    err = math.hypot(cy - ref[0], cz - ref[1])
    r_err = free["radius_mm"] - profile.SPHERE_RADIUS
    reasons = []
    if err > tol_mm:
        reasons.append(f"arc centre {err:.2f} mm from reference (tol {tol_mm})")
    if abs(r_err) > radius_tol_mm:
        reasons.append(f"arc radius error {r_err:+.2f} mm (tol {radius_tol_mm})")
    return {"ok": not reasons, "reasons": reasons, "points": len(points),
            "center_mm": [round(v, 4) for v in fixed["center_mm"]],
            "radius_mm": round(free["radius_mm"], 4),
            "center_error_mm": round(err, 4),
            "radius_error_mm": round(r_err, 4),
            "rms_mm": round(fixed["rms_mm"], 4)}
