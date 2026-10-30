"""Analyse an acquire.tcl run: CSV + manifest -> observations / profile / mesh.

    python run_scan.py --from-acquire D:/run --out D:/run/result [--t-eff-us 8.6]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wscan import acquire, geom


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-acquire", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--t-eff-us", type=float, default=None,
                        help="effective delay from the plate calibration; without it "
                             "no path, no radius, no mesh is produced")
    parser.add_argument("--sound-speed", type=float, default=1480.0)
    args = parser.parse_args()

    calibration = None
    if args.t_eff_us is not None:
        calibration = geom.Calibration(args.t_eff_us, args.sound_speed,
                                       ident="plate_manual", provisional=True)
    report = acquire.analyse(args.from_acquire, args.out, calibration)
    print(f"points={report['counts']['points']} frames={report['counts']['frames']} "
          f"with_radius={report['counts']['with_radius']}")
    print(f"reasons={report['reasons']}")
    for row in report["profile"]:
        print(f"  z={row['height_mm']:7.2f}  r={row['radius_median_mm']}  "
              f"spread={row['radius_spread_mm']}  points={row['points']}")
    if report["mesh"]:
        print(f"mesh={report['mesh']}")
    else:
        print("mesh: none (no accepted radius)")
    print(f"output -> {Path(args.out) / 'scan_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
