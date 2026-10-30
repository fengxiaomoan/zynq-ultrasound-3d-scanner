"""Turn a real DSP manifest.jsonl into the flat CSV the C harness reads.

The C port must be judged on the *same numbers* Python sees, so every value is
written with repr()/17 significant digits: parsing the CSV back with strtod
yields the identical binary64 the manifest carried, and any difference the gate
reports is a difference in the algorithm, not in the parsing.

    python tools/m2b_frames.py --run live_run/p12_std1 --out live_run/_m2b_frames_std1.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run dir holding manifest.jsonl")
    ap.add_argument("--manifest", default="manifest.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    man = Path(args.run) / args.manifest
    rows = [json.loads(l) for l in man.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["z_mm", "pose_rot", "t_us", "amp", "valid"])
        for r in rows:
            if r.get("t_us") is None:
                continue
            if args.limit and n >= args.limit:
                break
            w.writerow([repr(float(r["height_mm"])), int(r["pose_rot"]),
                        repr(float(r["t_us"])), repr(float(r.get("amp", 0))),
                        int(r.get("valid", 1))])
            n += 1
    print(f"{n} frames -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
