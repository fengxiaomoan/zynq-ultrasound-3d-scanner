"""Frame sources: synthetic phantom, archived AAA captures, future ILA exports.

A source only produces frames plus (optionally) a pose.  Everything else is
the pipeline's job, so the same analysis runs on simulation and on real data.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import frames, geom, profile


@dataclass
class Pose:
    layer: int
    latitude_deg: float
    azimuth_deg: float
    height_mm: float
    provenance: str = "open_loop_command"


# --------------------------------------------------------------- synthetic
class SyntheticScan:
    """Known phantom: the D50 sphere plus an optional Gaussian bump."""

    name = "synthetic_phantom"

    def __init__(self, t_eff_us: float = 8.6, sound_speed_m_s: float = profile.SOUND_SPEED_M_S,
                 noise: float = 6.0, echo: float = 240.0,
                 clutter: float = 1300.0, seed: int = 7,
                 bump: dict | None = None):
        self.t_eff_us = t_eff_us
        self.c = sound_speed_m_s
        self.noise = noise
        self.echo = echo
        self.clutter = clutter
        self.rng = np.random.default_rng(seed)
        self.bump = bump or {"lat": 10.0, "az": 180.0, "height_mm": 3.0,
                             "sigma_deg": 12.0}
        self.truth: list[dict] = []

    def _t(self) -> np.ndarray:
        # 51 pre-trigger samples, then 768 after the trigger: 163.8 us total.
        return (np.arange(profile.ADC_SAMPLES) - 51) * profile.SAMPLE_US

    def _path_mm(self, layer: profile.Layer, az_deg: float) -> tuple[float, float]:
        hit = geom.ray_sphere_hit(layer.origin, layer.direction)
        base = geom.path_length(hit, layer.tx, layer.rx)
        b = self.bump
        if not b.get("height_mm"):
            return base, 0.0
        dlat = layer.latitude_deg - b["lat"]
        daz = ((az_deg - b["az"] + 180.0) % 360.0) - 180.0
        height = b["height_mm"] * math.exp(
            -0.5 * ((dlat / b["sigma_deg"]) ** 2 + (daz / b["sigma_deg"]) ** 2))
        bump = 2.0 * height * math.cos(math.radians(layer.latitude_deg))
        return base + bump, bump

    def capture(self, layer_index: int, az_index: int, frame_index: int):
        layer = profile.all_layers()[layer_index]
        az = profile.DEFAULT_PLAN.azimuths[az_index]
        t = self._t()
        path, bump = self._path_mm(layer, az)

        rng = np.random.default_rng(
            (layer_index * 1000 + az_index) * 10 + frame_index)
        x = rng.normal(0.0, self.noise, t.size)
        t_cross = 51.2
        width = 8.0
        gate = (t >= t_cross) & (t < t_cross + width)
        x[gate] += self.clutter * np.sin(2 * np.pi * (t[gate] - t_cross))
        t_echo = self.t_eff_us + path / (self.c / 1000.0)
        env = np.exp(-0.5 * ((t - t_echo) / 1.5) ** 2)
        x += self.echo * env * np.sin(2 * np.pi * (t - t_echo))

        frame = frames.Frame(t_us=t, diff=x,
                             frame_id=f"L{layer_index:02d}A{az_index:02d}F{frame_index}",
                             tx_on=True, source="synthetic")
        self.truth.append({"frame_id": frame.frame_id, "path_mm": path,
                           "t_echo_us": t_echo, "bump_mm": bump})
        pose = Pose(layer_index, layer.latitude_deg, az, layer.probe_z_mm)
        return frame, pose

    def plate_capture(self, distance_mm: float, frame_index: int = 0) -> frames.Frame:
        """Flat-plate calibration frame at a known probe-plate distance."""
        t = self._t()
        rng = np.random.default_rng(90000 + int(distance_mm * 10) + frame_index)
        x = rng.normal(0.0, self.noise, t.size)
        gate = (t >= 51.2) & (t < 59.2)
        x[gate] += self.clutter * np.sin(2 * np.pi * (t[gate] - 51.2))
        path = geom.plate_path_mm(distance_mm)
        t_echo = self.t_eff_us + path / (self.c / 1000.0)
        env = np.exp(-0.5 * ((t - t_echo) / 1.5) ** 2)
        x += self.echo * env * np.sin(2 * np.pi * (t - t_echo))
        return frames.Frame(t_us=t, diff=x, frame_id=f"plate_{distance_mm:.0f}_{frame_index}",
                            tx_on=True, source="synthetic_plate")


# ------------------------------------------------------------- real archive
class AAAArchive:
    """Read one group from an AAA-running session, verifying the stored hashes."""

    name = "aaa_archive"

    def __init__(self, session_dir: str | Path, group: str,
                 profile_path: str | Path | None = None):
        self.session = Path(session_dir)
        self.group = group
        self.records: list[Path] = []
        for rec in sorted((self.session / "captures").glob("*/record.json")):
            meta = json.loads(rec.read_text(encoding="utf-8-sig"))
            tag = meta.get("context", {}).get("group", meta.get("target_state"))
            if tag != group:
                continue
            self.records.append(rec)
        if not self.records:
            raise ValueError(f"no captures for group {group} in {self.session}")

    def frames(self):
        for rec in self.records:
            meta = json.loads(rec.read_text(encoding="utf-8-sig"))
            if meta.get("reason") in ("initial_existing", "manual_existing"):
                continue
            csv_path = rec.parent / "capture.csv"
            identity = meta["files"]["capture.csv"]["sha256"]
            if hashlib.sha256(csv_path.read_bytes()).hexdigest() != identity:
                raise ValueError(f"capture.csv hash mismatch: {csv_path}")
            raw = frames.read_ila_csv(csv_path)
            frame = frames.to_frame(raw, frame_id=rec.parent.name, source=str(csv_path))
            yield frame, Pose(-1, float("nan"), float("nan"), float("nan"),
                              provenance="unposed_archive")


# ------------------------------------------------------- future ILA export
def read_export_dir(run_dir: str | Path):
    """Read a CSV directory produced by the acquisition Tcl (future path).

    Expects ``manifest.json``: {"frames": [{"file": "...", "layer": 0,
    "latitude_deg": -20, "azimuth_deg": 0, "height_mm": 52.1, "frame_index": 0}]}
    """
    run = Path(run_dir)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest["frames"]:
        raw = frames.read_ila_csv(run / item["file"])
        frame = frames.to_frame(raw, frame_id=item["file"], source=str(run / item["file"]))
        yield frame, Pose(item.get("layer", -1), item.get("latitude_deg", float("nan")),
                          item.get("azimuth_deg", float("nan")),
                          item.get("height_mm", float("nan")),
                          provenance=item.get("pose_provenance", "open_loop_command"))
