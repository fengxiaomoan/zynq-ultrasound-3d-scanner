"""Write a synthetic acquire.tcl run (13号 CSV + manifest) for offline testing.

    python make_fake_run.py --out out/fake_run --object cylinder

The CSVs use exactly the column names and radices of the real ILA export, so
the same decoder handles both.  Nothing here is hardware data.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from wscan import frames, profile, vertical

COLUMNS = ["Sample in Buffer", "Sample in Window", "TRIGGER", "sample1[9:0]",
           "sample2[9:0]", "diff[10:0]", "status_2[4:3]", "tx_burst_OBUF",
           "capture_start", "status_3[2:2]", "frame_index[12:0]",
           "status_4[5:5]", "status[0:0]"]
RADICES = ["UNSIGNED", "UNSIGNED", "UNSIGNED"] + ["HEX"] * 10
TRIGGER_ROW = 512


def synth(obj, height: float, seed: int) -> np.ndarray:
    """ADC diff samples on the decoder's grid: t = 0.2*i - 10.24 us."""
    n = profile.ADC_SAMPLES
    t = np.arange(n) * profile.SAMPLE_US - TRIGGER_ROW / 10 * profile.SAMPLE_US
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 6.0, n)
    gate = (t >= 51.2) & (t < 59.2)
    x[gate] += 1300.0 * np.sin(2 * np.pi * (t[gate] - 51.2))
    _, path = vertical.specular_hit(obj, height)
    t_echo = 8.6 + path / (profile.SOUND_SPEED_M_S / 1000.0)
    x += 240.0 * np.exp(-0.5 * ((t - t_echo) / 1.5) ** 2) * np.sin(2 * np.pi * (t - t_echo))
    return x


def write_csv(path: Path, diff_samples: np.ndarray, tx: bool) -> None:
    rows = []
    valid_at = {10 * i: i for i in range(len(diff_samples))}
    tx_rises = {TRIGGER_ROW + 1 + 50 * k for k in range(8)}
    for row in range(profile.ILA_ROWS):
        idx = valid_at.get(row)
        if idx is None:
            s1 = s2 = 0
            d = 0
            valid = 0
        else:
            d = int(round(diff_samples[idx]))
            d = max(-1023, min(1023, d))
            s1 = 512 + int(round(d / 2))
            s2 = s1 - d
            s1 = max(0, min(1023, s1))
            s2 = max(0, min(1023, s2))
            d = s1 - s2
            valid = 1
        tx_bit = 0
        if tx:
            for rise in tx_rises:
                if rise <= row < rise + 25:
                    tx_bit = 1
                    break
        start = 1 if row == TRIGGER_ROW else 0
        rows.append([str(row), str(row), "0", format(s1, "03x"), format(s2, "03x"),
                     format(d & 0x7FF, "03x"), "0", str(tx_bit), str(start), "0",
                     "0000", str(valid), "1"])
    text = ",".join(COLUMNS) + "\n" + ",".join(
        "Radix - " + r if r == "HEX" else r for r in RADICES) + "\n"
    text += "\n".join(",".join(r) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/fake_run")
    ap.add_argument("--object", choices=["cylinder", "cone"], default="cylinder")
    ap.add_argument("--heights", default="59,75,91")
    ap.add_argument("--azimuths", default="0,90,180,270")
    ap.add_argument("--tx", type=int, default=1)
    args = ap.parse_args()

    if args.object == "cylinder":
        obj = vertical.Cylinder(radius_mm=14.0, z0_mm=58.0, z1_mm=92.0)
    else:
        obj = vertical.Cone(r_bottom_mm=16.0, r_top_mm=14.0, z0_mm=58.0, z1_mm=92.0)

    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    heights = [float(h) for h in args.heights.split(",")]
    azimuths = [float(a) for a in args.azimuths.split(",")]
    seq = 0
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as man:
        for h in heights:
            for az in azimuths:
                name = f"raw/p{seq:03d}_f00.csv"
                write_csv(out / name, synth(obj, h, seq), bool(args.tx))
                man.write(json.dumps({
                    "seq": seq, "frame": 0, "file": name,
                    "latitude_deg": 0.0, "azimuth_deg": az, "height_mm": h,
                    "tx": args.tx, "pose_lift": 0, "pose_rot": int(round(az / 0.0879)),
                }, ensure_ascii=False) + "\n")
                seq += 1
    print(f"fake run -> {out}  points={seq}  object={obj.kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
