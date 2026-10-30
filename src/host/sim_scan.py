"""Generate a realistic scan run (13号 CSV + manifest) from the real noise floor.

The background noise is taken from a frame captured tonight; the echo is
synthesised at the time predicted by the cylinder geometry. Clearly simulated.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from wscan import frames, profile
import make_fake_run as mfr

NOISE_SRC = Path("out/sph_off/raw/p000_f00.csv")
OUT = Path("out/sim_full")
AXIS_M = 72.69          # probe midpoint -> object axis
AXIS_A = profile.PROBE_SPACING_MM / 2.0
T_EFF = 8.6


def main() -> None:
    noise_frame = frames.to_frame(frames.read_ila_csv(NOISE_SRC), frame_id="noise")
    noise = noise_frame.diff.astype(float)
    t = np.arange(noise.size) * profile.SAMPLE_US - 10.24

    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    lines = []
    seq = 0
    az_cur = 0.0
    z_cur = 75.0
    mm_per_step = profile.SCREW_LEAD_MM / profile.STEPS_PER_REV_DEFAULT
    deg_per_step = 360.0 / profile.STEPS_PER_REV_DEFAULT
    rng = np.random.default_rng(20261024)

    heights = [59.0 + 4.0 * i for i in range(9)]
    azimuths = [30.0 * i for i in range(12)]
    for li, z in enumerate(heights):
        order = list(range(len(azimuths)))
        if li % 2:
            order.reverse()
        for j in order:
            az = azimuths[j]
            radius = 14.0 + 0.05 * math.cos(2 * math.radians(az)) + rng.normal(0, 0.01)
            m = AXIS_M - radius
            path = 2.0 * math.sqrt(AXIS_A ** 2 + m ** 2)
            t_echo = T_EFF + path / (profile.SOUND_SPEED_M_S / 1000.0)
            amp = 430.0 * (0.96 + 0.08 * rng.random())
            x = noise * (0.42 + 0.22 * rng.random()) + rng.normal(0, 4.0, noise.size)
            x += amp * np.exp(-0.5 * ((t - t_echo) / 1.4) ** 2) * np.sin(
                2 * np.pi * (t - t_echo))
            name = f"raw/p{seq:03d}_f00.csv"
            mfr.write_csv(OUT / name, x, tx=True)
            lift = int(round((z - z_cur) / mm_per_step))
            rot = int(round((az - az_cur) / deg_per_step))
            z_cur, az_cur = z, az
            lines.append(json.dumps({
                "seq": seq, "frame": 0, "file": name,
                "latitude_deg": 0.0, "azimuth_deg": az, "height_mm": z,
                "tx": 1, "pose_lift": lift, "pose_rot": rot,
            }, ensure_ascii=False))
            seq += 1

    (OUT / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"simulated run -> {OUT}  points={seq}  (noise from {NOISE_SRC})")


if __name__ == "__main__":
    main()



