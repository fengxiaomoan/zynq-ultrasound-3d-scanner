#!/usr/bin/env python3
"""F1 pose viewer server.

Serves a reconstructed mesh (PLY) and the latest MPU6050 pose as JSON, plus the
static viewer.  Read-only: nothing is written to disk.

    python f1_viewer/server.py --port 8780
    # open http://127.0.0.1:8780/

Pose file contract (one row per sample, header optional):
    tick_ms,roll,pitch,yaw,seq,valid
Missing file -> the server synthesises a smooth demo motion, so the page works
before the FPGA stream exists.

Model names are resolved against a small registry; every model carries its
provenance (real-measurement vs synthetic) so the page can label it honestly.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

MODELS = {
    "cylinder": {
        "path": ROOT / "data/demo/models/cylinder.ply",
        "label": "圆柱 Ø28（演示模型）",
        "provenance": "synthetic_demo",
    },
    "cone1": {
        "path": ROOT / "data/demo/models/cone1.ply",
        "label": "圆锥 Ø32→Ø16（演示模型）",
        "provenance": "synthetic_demo",
    },
    "cone2": {
        "path": ROOT / "data/demo/models/cone2.ply",
        "label": "圆锥 Ø32→Ø28（演示模型）",
        "provenance": "synthetic_demo",
    },
    "step": {
        "path": ROOT / "data/demo/models/step.ply",
        "label": "台阶轴 Ø28→Ø18（演示模型）",
        "provenance": "synthetic_demo",
    },
}

MODEL_CACHE: dict[str, dict] = {}


# --------------------------------------------------------------------- PLY
def _ply_header(f):
    header = []
    while True:
        line = f.readline()
        if not line:
            raise ValueError("PLY header ended unexpectedly")
        text = line.decode("ascii", "replace").strip()
        header.append(text)
        if text == "end_header":
            return header


def _triangulate(poly):
    for i in range(1, len(poly) - 1):
        yield poly[0], poly[i], poly[i + 1]


def read_ply(path: Path):
    with open(path, "rb") as f:
        header = _ply_header(f)
        fmt = "ascii"
        nvert = nface = 0
        vprops: list[str] = []
        for line in header:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "format":
                fmt = parts[1]
            elif parts[0] == "element" and len(parts) >= 3:
                if parts[1] == "vertex":
                    nvert = int(parts[2])
                elif parts[1] == "face":
                    nface = int(parts[2])
            elif parts[0] == "property" and len(parts) >= 3 and parts[1] != "list":
                vprops.append(parts[2])

        verts = []
        if fmt == "ascii":
            for _ in range(nvert):
                vals = f.readline().split()
                if not vals:
                    break
                d = dict(zip(vprops, vals))
                verts.append((float(d.get("x", 0)), float(d.get("y", 0)), float(d.get("z", 0))))
            faces = []
            for _ in range(nface):
                vals = f.readline().split()
                if not vals:
                    break
                k = int(vals[0])
                idx = [int(v) for v in vals[1:1 + k]]
                for tri in _triangulate(idx):
                    faces.extend(tri)
        elif fmt == "binary_little_endian":
            fmtmap = {"float": "f", "float32": "f", "double": "d", "uchar": "B",
                      "uint8": "B", "char": "b", "int8": "b", "short": "h",
                      "int16": "h", "ushort": "H", "uint16": "H", "int": "i",
                      "int32": "i", "uint": "I", "uint32": "I"}
            vfmt = "<" + "".join(fmtmap.get(p, "f") for p in vprops)
            vsize = struct.calcsize(vfmt)
            for _ in range(nvert):
                raw = f.read(vsize)
                if len(raw) < vsize:
                    break
                vals = struct.unpack(vfmt, raw)
                d = dict(zip(vprops, vals))
                verts.append((d.get("x", 0.0), d.get("y", 0.0), d.get("z", 0.0)))
            faces = []
            for _ in range(nface):
                kraw = f.read(1)
                if not kraw:
                    break
                k = struct.unpack("B", kraw)[0]
                idx = list(struct.unpack("<" + "i" * k, f.read(4 * k)))
                for tri in _triangulate(idx):
                    faces.extend(tri)
        else:
            raise ValueError(f"unsupported PLY format: {fmt}")
    return verts, faces


def build_model(name: str) -> dict:
    spec = MODELS[name]
    path = spec["path"]
    if not path.exists():
        raise FileNotFoundError(str(path))
    verts, faces = read_ply(path)

    # centre + convert scan frame (x,y plane, z up) to display frame (y up)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    ext = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-6)
    scale = 2.0 / ext

    pos = []
    for x, y, z in verts:
        pos.append(((x - cx) * scale, (z - cz) * scale, -(y - cy) * scale))

    # area-weighted vertex normals
    nrm = [[0.0, 0.0, 0.0] for _ in verts]
    for i in range(0, len(faces), 3):
        a, b, c = faces[i], faces[i + 1], faces[i + 2]
        ax, ay, az = pos[a]
        bx, by, bz = pos[b]
        cx_, cy_, cz_ = pos[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx_ - ax, cy_ - ay, cz_ - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        for k in (a, b, c):
            nrm[k][0] += nx
            nrm[k][1] += ny
            nrm[k][2] += nz
    normals = []
    for nx, ny, nz in nrm:
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        normals.extend((nx / ln, ny / ln, nz / ln))

    radius = max(math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) for p in pos) or 1.0

    report = {}
    if spec.get("report") and spec["report"].exists():
        try:
            report = json.loads(spec["report"].read_text(encoding="utf-8"))
        except Exception:
            report = {}

    provenance = spec.get("provenance") or report.get("provenance", "unknown")
    limits = report.get("limits", [])
    label = spec["label"]
    if report.get("label"):
        label = spec["label"]

    return {
        "name": name,
        "label": label,
        "provenance": provenance,
        "positions": [round(c, 5) for p in pos for c in p],
        "normals": [round(v, 5) for v in normals],
        "indices": faces,
        "radius": round(radius, 5),
        "counts": {
            "vertices": len(verts),
            "triangles": len(faces) // 3,
        },
        "limits": limits,
        "mesh": report.get("mesh", {}),
        "summary": report.get("summary", {}),
    }


def get_model(name: str) -> dict:
    if name not in MODEL_CACHE:
        MODEL_CACHE[name] = build_model(name)
    return MODEL_CACHE[name]


# -------------------------------------------------------------------- pose
def _demo_pose() -> dict:
    t = time.time()
    return {
        "mode": "demo",
        "t": round(t, 3),
        "roll": round(10.0 * math.sin(0.70 * t), 2),
        "pitch": round(16.0 * math.sin(0.45 * t + 1.0), 2),
        "yaw": round(42.0 * math.sin(0.25 * t), 2),
        "seq": int(t * 100) & 0xFFFF,
        "valid": 1,
        "age_ms": 0.0,
        "source": "synthetic-demo",
    }


def read_pose(path: Path) -> dict:
    if not path.exists():
        return _demo_pose()
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            chunk = f.read().decode("utf-8", "replace")
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            return _demo_pose()
        if lines[0].lower().startswith("tick") or ("roll" in lines[0].lower() and "yaw" in lines[0].lower()):
            header = [c.strip().lower() for c in lines[0].split(",")]
            rows = lines[1:]
        else:
            header = ["tick_ms", "roll", "pitch", "yaw", "seq", "valid"]
            rows = lines
        if not rows:
            return _demo_pose()
        vals = [v.strip() for v in rows[-1].split(",")]
        d = dict(zip(header, vals))

        def num(key, default=0.0):
            try:
                return float(d.get(key, default))
            except ValueError:
                return default

        tick = num("tick_ms", num("t", time.time() * 1000.0))
        now = time.time() * 1000.0
        return {
            "mode": "file",
            "t": round(tick / 1000.0, 3),
            "roll": round(num("roll"), 2),
            "pitch": round(num("pitch"), 2),
            "yaw": round(num("yaw"), 2),
            "seq": int(num("seq", 0)),
            "valid": int(num("valid", 1)),
            "age_ms": round(max(0.0, now - tick), 1),
            "source": str(path),
        }
    except Exception as exc:
        out = _demo_pose()
        out["error"] = str(exc)
        return out


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    pose_path: Path = None

    def log_message(self, *args):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
                return
            if url.path == "/app.js":
                self._send(200, (HERE / "app.js").read_bytes(), "application/javascript; charset=utf-8")
                return
            if url.path == "/math3d.js":
                self._send(200, (HERE / "math3d.js").read_bytes(), "application/javascript; charset=utf-8")
                return
            if url.path == "/api/models":
                out = []
                for name, spec in MODELS.items():
                    if spec["path"].exists():
                        out.append({"name": name, "label": spec["label"]})
                self._json({"models": out})
                return
            if url.path == "/api/model":
                name = (qs.get("name") or ["cyl_model"])[0]
                if name not in MODELS:
                    self._json({"error": f"unknown model {name}"}, 404)
                    return
                self._json(get_model(name))
                return
            if url.path == "/api/pose":
                self._json(read_pose(self.pose_path))
                return
            if url.path == "/api/health":
                self._json({"ok": True, "pose": str(self.pose_path), "models": list(MODELS)})
                return
        except Exception as exc:  # keep the page alive with a readable error
            self._json({"error": str(exc)}, 500)
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--pose", default=str(ROOT / "sim/vectors/demo_pose.csv"))
    ap.add_argument("--warm", default="cylinder", help="model to parse at startup (empty to skip)")
    args = ap.parse_args()

    Handler.pose_path = Path(args.pose)
    if args.warm:
        try:
            m = get_model(args.warm)
            print(f"model {args.warm}: {m['counts']['vertices']} verts / {m['counts']['triangles']} tris / {m['provenance']}")
        except Exception as exc:
            print(f"warm model failed: {exc}")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"F1 viewer: http://{args.host}:{args.port}/  pose={Handler.pose_path}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
