"""Morphological anomaly detection on the four V3-P targets.

The four shapes are the *standard* parts; clay bumps are added to a second
synthetic scan to make the *test* parts.  The detector compares the test scan
with the standard scan, thresholds the radius residual and clusters it.

This is a simulation of the detection algorithm (provenance=synthetic).  The
same script runs on real scans by pointing ``--real <run_dir>`` at two acquire
directories later.

    python anomaly/run_anomaly.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT.parents[1]
POINTS = PKG / "data" / "demo"
OUT = PKG / "build" / "output" / "anomaly"

T_EFF_GEN = 9.15
T_EFF_MEAS = 9.40       # same uncalibrated anchor as the benchmark; cancels in the residual
C_MM_US = 1.48
A = 12.5
AXIS_Y = 100.0
PROBE_Y = 27.31
DZ = 0.5                # layer spacing, mm
DAZ = 360.0 / 64.0      # azimuth bin, deg

# ground-truth clay bumps: (z, az_deg, height_mm, sigma_z_mm, sigma_az_deg)
BUMPS = {
    "cylinder": [(83.0, 90.0, +0.55, 2.5, 9.0), (75.0, 250.0, -0.35, 2.0, 7.0)],
    "cone1":    [(80.0, 120.0, +0.50, 2.4, 9.0), (72.0, 300.0, -0.32, 2.0, 7.0)],
    "cone2":    [(78.0, 60.0, +0.60, 2.4, 9.0), (88.0, 200.0, -0.40, 2.2, 8.0)],
    "step":     [(76.0, 150.0, +0.50, 2.0, 8.0), (92.0, 30.0, -0.30, 1.8, 7.0)],
}


def radius_of(t: float, t_eff: float = T_EFF_MEAS) -> float | None:
    path = (t - t_eff) * C_MM_US
    inner = (path / 2.0) ** 2 - A * A
    if inner <= 0:
        return None
    return AXIS_Y - PROBE_Y - math.sqrt(inner)


def path_mm(r: float) -> float:
    m = AXIS_Y - r - PROBE_Y
    return 2.0 * math.sqrt(A * A + m * m)


def bump_value(shape: str, z: float, az: float) -> float:
    v = 0.0
    for zc, ac, h, sz, sa in BUMPS[shape]:
        daz = (az - ac + 180.0) % 360.0 - 180.0
        v += h * math.exp(-((z - zc) / sz) ** 2 - (daz / sa) ** 2)
    return v


def load_standard(shape: str) -> list[dict]:
    path = POINTS / f"points_{shape}.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for p in rows:
        p["r_meas"] = radius_of(p["t"]) if p.get("accepted") else None
    return rows


def make_test(rows: list[dict], seed: int, shape: str, with_bumps: bool = True) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for p in rows:
        q = dict(p)
        r_true = p["r_true"] + (bump_value(shape, p["z"], p["az"]) if with_bumps else 0.0)
        q["r_true"] = r_true
        q["t"] = T_EFF_GEN + path_mm(r_true) / C_MM_US + rng.normal(0, 0.04)
        q["snr"] = p["snr"] + rng.normal(0, 0.4)
        q["accepted"] = bool(p["accepted"]) and q["snr"] >= 10.0
        q["r_meas"] = radius_of(q["t"]) if q["accepted"] else None
        out.append(q)
    return out


def grid_maps(ref: list[dict], test: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    nz, naz = 64, 64
    rmap = np.full((nz, naz), np.nan)
    tmap = np.full((nz, naz), np.nan)
    for a, b in zip(ref, test):
        if a["r_meas"] is None or b["r_meas"] is None:
            continue
        zi = int(a["layer"])
        ai = int(round(a["az"] / DAZ)) % naz
        rmap[zi, ai] = b["r_meas"] - a["r_meas"]
        tmap[zi, ai] = b["r_meas"]
    return rmap, tmap


def median3(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if np.isnan(m[i, j]):
                continue
            vals = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    v = m[(i + di) % m.shape[0], (j + dj) % m.shape[1]]
                    if not np.isnan(v):
                        vals.append(v)
            out[i, j] = float(np.median(vals)) if vals else np.nan
    return out


def components(mask: np.ndarray, min_bins: int = 4) -> list[dict]:
    nz, naz = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for i in range(nz):
        for j in range(naz):
            if not mask[i, j] or seen[i, j]:
                continue
            stack = [(i, j)]
            seen[i, j] = True
            cells = []
            while stack:
                a, b = stack.pop()
                cells.append((a, b))
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    x, y = (a + da) % nz, (b + db) % naz
                    if mask[x, y] and not seen[x, y]:
                        seen[x, y] = True
                        stack.append((x, y))
            if len(cells) >= min_bins:
                comps.append({"cells": cells, "n": len(cells)})
    return comps


def analyse(shape: str, threshold: float = 0.15) -> dict:
    ref = load_standard(shape)
    test = make_test(ref, seed=777 + len(shape), shape=shape, with_bumps=True)
    rmap, tmap = grid_maps(ref, test)
    smooth = rmap            # no smoothing: a 3x3 median erases 1-2 bin bumps
    mask = np.zeros_like(smooth, dtype=bool)
    valid = ~np.isnan(smooth)
    mask[valid] = np.abs(smooth[valid]) >= threshold

    comps = components(mask)
    detections = []
    for c in comps:
        zs, azs, ws = [], [], []
        for (i, j) in c["cells"]:
            v = smooth[i, j]
            z = 67.0 + i * DZ
            az = j * DAZ
            zs.append(z)
            azs.append(az)
            ws.append(abs(v))
        w = np.array(ws)
        zc = float(np.average(zs, weights=w))
        ang = np.radians(azs)
        azc = math.degrees(math.atan2(float(np.average(np.sin(ang), weights=w)),
                                      float(np.average(np.cos(ang), weights=w)))) % 360.0
        height = float(max(w)) * (1 if smooth[int((zc - 67) / DZ) % 64,
                                             int(round(azc / DAZ)) % 64] >= 0 else -1)
        r_here = 14.0
        area = c["n"] * DZ * math.radians(DAZ) * r_here
        detections.append({"z_mm": round(zc, 2), "az_deg": round(azc, 1),
                           "height_mm": round(height, 3), "area_mm2": round(area, 1),
                           "bins": c["n"]})

    # match to ground truth
    gt = BUMPS[shape]
    used = set()
    matches = []
    for d in detections:
        best, bi = 1e9, None
        for i, (zc, ac, h, sz, sa) in enumerate(gt):
            if i in used:
                continue
            daz = abs((d["az_deg"] - ac + 180) % 360 - 180)
            dist = math.hypot(d["z_mm"] - zc, daz * math.radians(1) * 14.0)
            if dist < best:
                best, bi = dist, i
        if bi is not None and best < 14.0:
            used.add(bi)
            zc, ac, h, sz, sa = gt[bi]
            daz = abs((d["az_deg"] - ac + 180) % 360 - 180)
            matches.append({"shape": shape, "gt_z": zc, "gt_az": ac, "gt_h": h,
                            **d, "center_err_mm": round(math.hypot(d["z_mm"] - zc, 0), 2),
                            "az_err_deg": round(daz, 1),
                            "height_err_mm": round(d["height_mm"] - h, 3)})
    missed = [gt[i] for i in range(len(gt)) if i not in used]

    # false-positive control: same standard, new noise, no bumps
    ctrl = make_test(ref, seed=999 + len(shape), shape=shape, with_bumps=False)
    cmap, _ = grid_maps(ref, ctrl)
    cs = cmap
    cmask = np.zeros_like(cs, dtype=bool)
    cv = ~np.isnan(cs)
    cmask[cv] = np.abs(cs[cv]) >= threshold
    fpc = components(cmask)

    out = Path(OUT) / shape
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "anomaly-sim/1",
        "provenance": "synthetic",
        "shape": shape,
        "threshold_mm": threshold,
        "bumps_gt": [{"z": z, "az": a, "h": h} for z, a, h, _, _ in gt],
        "detections": detections,
        "matches": matches,
        "missed": [{"z": z, "az": a, "h": h} for z, a, h, _, _ in missed],
        "false_positive_bins": sum(c["n"] for c in fpc),
        "noise_floor_mm": round(float(np.nanstd(cmap)), 4),
    }
    (out / "anomaly_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    return report, rmap, tmap, smooth, mask


def plot(shape: str, rmap, smooth, mask, detections, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 4.8))
    im = ax.imshow(smooth, aspect="auto", origin="lower", cmap="RdBu_r",
                   vmin=-0.6, vmax=0.6, extent=[0, 360, 67, 99])
    for i in range(mask.shape[0]):
        for j in range(mask.shape[1]):
            if mask[i, j]:
                ax.add_patch(plt.Rectangle((j * DAZ, 67 + i * DZ), DAZ, DZ,
                                           fill=False, ec="k", lw=0.6))
    for zc, ac, h, _, _ in BUMPS[shape]:
        ax.plot(ac, zc, "k+", ms=12, mew=2)
    ax.set_xlabel("azimuth / deg")
    ax.set_ylabel("z / mm")
    ax.set_title(f"{shape}: radius residual (test - standard), threshold 0.15 mm")
    fig.colorbar(im, ax=ax, label="mm")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for shape in BUMPS:
        rep, rmap, tmap, smooth, mask = analyse(shape)
        plot(shape, rmap, smooth, mask, rep["detections"], Path(OUT) / shape / "residual.png")
        ok = len(rep["matches"])
        summary.append({
            "shape": shape,
            "gt": len(rep["bumps_gt"]),
            "detected": len(rep["detections"]),
            "matched": ok,
            "missed": len(rep["missed"]),
            "false_positive_bins": rep["false_positive_bins"],
            "noise_floor_mm": rep["noise_floor_mm"],
            "center_err_max_mm": max([m["center_err_mm"] for m in rep["matches"]], default=None),
            "az_err_max_deg": max([m["az_err_deg"] for m in rep["matches"]], default=None),
            "height_err_max_mm": max([abs(m["height_err_mm"]) for m in rep["matches"]], default=None),
        })
        print(f"{shape:9s} gt={len(rep['bumps_gt'])} detected={len(rep['detections'])} "
              f"matched={ok} missed={len(rep['missed'])} fp_bins={rep['false_positive_bins']} "
              f"noise={rep['noise_floor_mm']:.3f} mm")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    import csv
    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    print(f"written -> {OUT}")


if __name__ == "__main__":
    main()

