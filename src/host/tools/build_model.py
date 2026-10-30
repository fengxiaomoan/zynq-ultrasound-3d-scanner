"""Build a full cylinder model (mesh.ply / mesh.stl) from a multi-layer real scan.

Input is a ``tools/robust_scan.py`` output directory: one radius per (height,
azimuth) cell.  Output is a triangulated surface in the same machine frame the
rest of the project uses (cylinder axis at x=75, y=100 mm), plus a profile table
and a report.

    python tools/build_model.py --run live_run/cyl_full_robust --out live_run/cyl_model

Two things this has to get right:

* **azimuth drift** -- a 24-point ring only steps 23 times, so every ring is
  rotated by -14.3 deg relative to the previous one (23*171 vs 4096 counts).
  ``--az-per-ring`` removes that, otherwise the mesh comes out as a helix.
* **gaps** -- a weak foil target loses points.  ``--fill linear`` interpolates
  over the missing azimuths *per layer* and the gaps that survive are reported,
  so the mesh is never silently invented.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wscan.pipeline import write_ply, write_stl  # noqa: E402

AXIS_X, AXIS_Y = 75.0, 100.0


def load_layer_grid(run: Path, az_per_ring: float) -> tuple[dict[float, dict[float, float]], dict]:
    path = run / "points.csv"
    if not path.exists():
        raise SystemExit(f"missing {path} (run tools/robust_scan.py first)")
    rows = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    # robust_scan writes z_mm, dsp_scan_report writes z_mm too but with different
    # companion columns; accept either so both paths use one builder
    zkey = "z_mm" if "z_mm" in rows[0] else "height_mm"
    zs = sorted({float(r[zkey]) for r in rows}, reverse=True)
    grid: dict[float, dict[float, float]] = {}
    stats = {"cells": len(rows), "valid": 0, "layers": len(zs)}
    for k, z in enumerate(zs):
        layer = {}
        for r in rows:
            if float(r[zkey]) != z or r["valid"] != "1":
                continue
            az = (float(r["az_deg"]) + k * az_per_ring) % 360.0
            layer[round(az, 2)] = float(r["r_mm"])
        if layer:
            grid[z] = layer
            stats["valid"] += len(layer)
    return grid, stats

def fill_layer(layer: dict[float, float]) -> tuple[dict[float, float], int]:
    """Circular linear interpolation over the missing azimuths of one layer."""
    if len(layer) < 3:
        return dict(layer), 0
    az = np.array(sorted(layer))
    rr = np.array([layer[a] for a in az])
    step = 360.0 / max(1, round(360.0 / float(np.median(np.diff(np.r_[az, az[0] + 360.0])))))
    full = np.arange(0.0, 360.0, step)
    out = {}
    for a in full:
        d = (az - a + 180.0) % 360.0 - 180.0
        i = int(np.argmin(np.abs(d)))
        if abs(d[i]) < 1e-6:
            out[round(float(a), 2)] = float(rr[i])
            continue
        j = (i + (1 if d[i] < 0 else -1)) % az.size
        d0 = d[i]
        d1 = (az[j] - a + 180.0) % 360.0 - 180.0
        if abs(d0 - d1) < 1e-9:
            out[round(float(a), 2)] = float(rr[i])
            continue
        t = d0 / (d0 - d1)
        out[round(float(a), 2)] = float(rr[i] + t * (rr[j] - rr[i]))
    return out, len(full) - len(layer)


def build(grid: dict[float, dict[float, float]], with_caps: bool) -> dict:
    zs = sorted(grid)
    azs = sorted(grid[zs[0]])
    verts, index = [], {}
    for z in zs:
        for a in azs:
            r = grid[z].get(a)
            if r is None:
                continue
            index[(z, a)] = len(verts)
            th = math.radians(a)
            verts.append([AXIS_X + r * math.cos(th), AXIS_Y + r * math.sin(th), z])

    faces, skipped = [], 0
    n = len(azs)
    for iz in range(len(zs) - 1):
        z0, z1 = zs[iz], zs[iz + 1]
        for j in range(n):
            a0, a1 = azs[j], azs[(j + 1) % n]
            keys = [(z0, a0), (z0, a1), (z1, a0), (z1, a1)]
            if not all(k in index for k in keys):
                skipped += 1
                continue
            i0, i1, i2, i3 = (index[k] for k in keys)
            for tri in ([i0, i1, i2], [i1, i3, i2]):
                p = np.array([verts[i] for i in tri])
                nrm = np.cross(p[1] - p[0], p[2] - p[0])
                if np.linalg.norm(nrm) < 1e-9:
                    continue
                radial = p.mean(axis=0) - np.array([AXIS_X, AXIS_Y, 0.0])
                if float(np.dot(nrm, radial)) < 0:
                    tri = [tri[0], tri[2], tri[1]]
                faces.append(tri)

    caps = 0
    if with_caps and len(zs) >= 2:
        for z, up in ((zs[0], True), (zs[-1], False)):
            ring = [(index[(z, a)], a) for a in azs if (z, a) in index]
            if len(ring) < 3:
                continue
            centre = [AXIS_X, AXIS_Y, z]
            ci = len(verts)
            verts.append(centre)
            for t in range(len(ring)):
                i0, a0 = ring[t]
                i1, a1 = ring[(t + 1) % len(ring)]
                tri = [ci, i0, i1]
                p = np.array([verts[i] for i in tri])
                nrm = np.cross(p[1] - p[0], p[2] - p[0])
                if (nrm[2] > 0) != up:
                    tri = [ci, i1, i0]
                faces.append(tri)
                caps += 1

    edges: dict[tuple[int, int], int] = {}
    for f in faces:
        for i in range(3):
            e = tuple(sorted((f[i], f[(i + 1) % 3])))
            edges[e] = edges.get(e, 0) + 1
    return {
        "vertices": np.array(verts, float).reshape(-1, 3),
        "faces": faces,
        "stats": {"vertices": len(verts), "triangles": len(faces),
                  "skipped_cells": skipped, "cap_triangles": caps,
                  "boundary_edges": sum(v == 1 for v in edges.values()),
                  "nonmanifold_edges": sum(v > 2 for v in edges.values()),
                  "closed": bool(faces) and all(v == 2 for v in edges.values())},
    }


def render(path: Path, mesh: dict, grid: dict[float, dict[float, float]], label: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v = mesh["vertices"]
    fig = plt.figure(figsize=(12.5, 5.2))

    ax = fig.add_subplot(1, 2, 1, projection="3d")
    tris = mesh["faces"]
    if tris:
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        # colour each triangle by its mean radius, which is what the scan measures
        rad = np.hypot(v[:, 0] - AXIS_X, v[:, 1] - AXIS_Y)
        rmean = rad[np.array(tris)].mean(axis=1)
        # the cap fans run to the axis, where r=0 is not a measurement: keep them
        # out of the colour scale so the surface's real range stays readable
        on_surface = rad[rad > 1.0]
        lo, hi = (float(on_surface.min()), float(on_surface.max())) if on_surface.size \
            else (float(rad.min()), float(rad.max()))
        norm = plt.Normalize(lo, hi)
        cmap = plt.get_cmap("viridis")
        polys = [v[np.array(t)] for t in tris]
        coll = Poly3DCollection(polys, facecolors=cmap(norm(rmean)),
                                edgecolors=(0, 0, 0, 0.25), linewidths=0.3)
        ax.add_collection3d(coll)
        ax.auto_scale_xyz(v[:, 0], v[:, 1], v[:, 2])
        fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
                     shrink=0.6, label="r / mm")
    else:
        ax.scatter(v[:, 0], v[:, 1], v[:, 2], s=8, color="#2f7d5a")
    ax.set_xlabel("x / mm")
    ax.set_ylabel("y / mm")
    ax.set_zlabel("z / mm")
    ax.set_title(f"{label}: reconstructed surface")
    try:
        ax.set_box_aspect((1, 1, 1.4))
    except Exception:
        pass

    ax2 = fig.add_subplot(1, 2, 2)
    zs = sorted(grid)
    azs = sorted(grid[zs[0]])
    m = np.full((len(zs), len(azs)), np.nan)
    for i, z in enumerate(zs):
        for j, a in enumerate(azs):
            if a in grid[z]:
                m[i, j] = grid[z][a]
    im = ax2.imshow(m, aspect="auto", origin="lower", cmap="viridis",
                    extent=[azs[0], azs[-1], zs[0], zs[-1]])
    ax2.set_xlabel("azimuth / deg (drift-corrected)")
    ax2.set_ylabel("z / mm")
    ax2.set_title("radius map / mm")
    fig.colorbar(im, ax=ax2, label="r / mm")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="robust_scan output dir (multi-layer)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="cylinder")
    ap.add_argument("--az-per-ring", type=float, default=-14.34,
                    help="deg added to layer k's azimuths (24-point ring leaves 14.34 deg)")
    ap.add_argument("--fill", choices=("none", "linear"), default="linear")
    ap.add_argument("--caps", action="store_true", help="close the top and bottom discs")
    ap.add_argument("--render", action="store_true", help="also write model.png")
    args = ap.parse_args()

    run, out = Path(args.run), Path(args.out)
    grid, stats = load_layer_grid(run, args.az_per_ring)
    if not grid:
        raise SystemExit("no valid points")
    filled_total = 0
    if args.fill == "linear":
        for z in list(grid):
            grid[z], nf = fill_layer(grid[z])
            filled_total += nf

    mesh = build(grid, args.caps)
    out.mkdir(parents=True, exist_ok=True)
    write_ply(out / "mesh.ply", mesh)
    write_stl(out / "mesh.stl", mesh)
    if args.render:
        render(out / "model.png", mesh, grid, args.label)

    zs = sorted(grid)
    prof = []
    with (out / "profile.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["z_mm", "valid_azimuths", "r_median_mm", "r_min_mm", "r_max_mm",
                    "out_of_round_mm", "z_from_bottom_mm"])
        for z in zs:
            v = np.array(list(grid[z].values()))
            prof.append({"z": z, "n": int(v.size), "median": float(np.median(v)),
                         "min": float(v.min()), "max": float(v.max())})
            w.writerow([f"{z:+.1f}", v.size, f"{np.median(v):.3f}", f"{v.min():.3f}",
                        f"{v.max():.3f}", f"{v.max() - v.min():.3f}",
                        f"{z - zs[-1]:.1f}"])

    report = {
        "schema": "cylinder-model/1",
        "provenance": "real-measurement",
        "label": args.label,
        "source_run": str(run),
        "frame": {"axis_xy_mm": [AXIS_X, AXIS_Y],
                  "note": "radius measured from the axis; z is the motor height coordinate"},
        "grid": {"layers": len(zs), "azimuths": len(grid[zs[0]]),
                 "height_range_mm": [min(zs), max(zs)],
                 "measured_cells": stats["valid"],
                 "interpolated_cells": filled_total},
        "azimuth_correction_deg_per_layer": args.az_per_ring,
        "profile": [{"z_mm": p["z"], "valid_azimuths": p["n"],
                     "r_median_mm": round(p["median"], 3),
                     "out_of_round_mm": round(p["max"] - p["min"], 3)} for p in prof],
        "mesh": mesh["stats"],
        "limits": [
            "radius is anchored to the nominal radius (relative measurement), "
            "absolute size depends on the calibration",
            "a weak foil target loses points; interpolated cells are counted above",
            "side surface only" if not args.caps else "caps are planar fans, not measured",
        ],
    }
    (out / "model_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{args.label}: {len(zs)} layers x {len(grid[zs[0]])} azimuths, "
          f"z {min(zs):+.0f}..{max(zs):+.0f} mm")
    print(f"  measured {stats['valid']} cells, interpolated {filled_total}")
    print(f"  mesh {mesh['stats']['vertices']} verts, {mesh['stats']['triangles']} tris, "
          f"boundary edges {mesh['stats']['boundary_edges']}, "
          f"closed {mesh['stats']['closed']}")
    for p in prof:
        print(f"  z={p['z']+0:+.0f}: {p['n']:2d} az, r_med {p['median']:6.2f}, "
              f"out-of-round {p['max'] - p['min']:5.2f}")
    print(f"written -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
