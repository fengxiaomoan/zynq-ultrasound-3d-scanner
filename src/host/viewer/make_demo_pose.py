#!/usr/bin/env python3
"""Generate a pose CSV for the F1 viewer (replay without hardware).

    python src/host/viewer/make_demo_pose.py --out data/demo/demo_pose.csv
    python src/host/viewer/server.py --pose data/demo/demo_pose.csv

Columns: tick_ms,roll,pitch,yaw,seq,valid   (degrees, epoch milliseconds)
The motion is deliberately asymmetric so all three axes are visible.
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--rate", type=float, default=50.0, help="rows per second")
    ap.add_argument("--loop", action="store_true", help="repeat a 12 s pattern")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n = int(args.seconds * args.rate)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("tick_ms,roll,pitch,yaw,seq,valid\n")
        for i in range(n):
            t = i / args.rate
            tt = (t % 12.0) if args.loop else t
            roll = 12.0 * math.sin(0.80 * tt)
            pitch = 18.0 * math.sin(0.55 * tt + 1.0)
            yaw = 55.0 * math.sin(0.30 * tt)
            tick = (t0 + t) * 1000.0
            f.write(f"{tick:.0f},{roll:.2f},{pitch:.2f},{yaw:.2f},{i & 0xffff},1\n")
    print(f"wrote {n} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
