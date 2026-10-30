#!/usr/bin/env python3
"""Local stub for tools/live_model_page.html -- the F1 (pose) half, no board.

The real page is served by the PS firmware at http://192.168.1.10/ and reads
/state (60-120 KB, 700 ms) plus, after F1 lands, /api/pose (tiny, 50 ms).
This stub serves the same page from disk so the pose-driven rotation can be
exercised and demonstrated before the PL/F1 bitstream exists:

  python tools\\m2b_page_stub.py                 # 127.0.0.1:8790, mesh=null
  python tools\\m2b_page_stub.py --state mesh    # use a /state that HAS a mesh
  python tools\\m2b_page_stub.py --pose static   # freeze the attitude
  python tools\\m2b_page_stub.py --pose off      # simulate old firmware (404-ish)

What it does NOT do: it does not fake a scan, it does not compute residuals and
it is not evidence of anything on the board.  It exists to look at the motion.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PAGE = HERE / "live_model_page.html"
STATES = {
    # single layer -> mesh=null -> the page must show the labelled placeholder
    "nolmesh": ROOT / "data" / "real" / "_m2b_resid_repeat_20261027_174836.json",
    "mesh": ROOT / "data" / "real" / "_m2b_3layer_signed.json",
}
STATIC_POSE = ROOT / "data" / "real" / "f1_pose_sample.json"

T0 = time.time()


def demo_pose() -> dict:
    """Smooth synthetic attitude + its analytic rate, in the /api/pose schema."""
    t = time.time() - T0
    roll = 22.0 * math.sin(2 * math.pi * 0.20 * t)
    pitch = 12.0 * math.sin(2 * math.pi * 0.13 * t + 1.1)
    yaw = 40.0 * math.sin(2 * math.pi * 0.07 * t)
    return {
        "ok": 1,
        "roll": round(roll, 2),
        "pitch": round(pitch, 2),
        "yaw": round(yaw, 2),
        "gx": round(22.0 * 2 * math.pi * 0.20 * math.cos(2 * math.pi * 0.20 * t), 2),
        "gy": round(12.0 * 2 * math.pi * 0.13 * math.cos(2 * math.pi * 0.13 * t + 1.1), 2),
        "gz": round(40.0 * 2 * math.pi * 0.07 * math.cos(2 * math.pi * 0.07 * t), 2),
        "seq": int((time.time() - T0) * 1000) & 0xFFFFFFFF,
        "tick_ms": int((time.time() - T0) * 1000),
        "age_ms": 2,
        "flags": 3,
        "source": "STUB(synthetic) -- not a measurement",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "m2b_page_stub/1.0"

    def log_message(self, fmt, *args):          # keep the console readable
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj).encode(), "application/json")

    def do_GET(self):                            # noqa: N802  (http.server API)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/state":
            f = STATES[self.server.state_key]
            if not f.exists():
                self._json({"error": f"missing {f}"})
                return
            self._send(200, f.read_bytes(), "application/json")
        elif path == "/api/pose":
            mode = self.server.pose_mode
            if mode == "off":
                self._json({"ok": 0, "why": "stub: pose disabled (simulates pre-F1 firmware)"})
            elif mode == "static":
                self._json(json.loads(STATIC_POSE.read_text(encoding="utf-8")))
            else:
                self._json(demo_pose())
        elif path == "/api/status":
            self._json({"ok": True, "stub": True})
        else:
            self._send(404, b"not found", "text/plain")


def main() -> int:
    ap = argparse.ArgumentParser(description="pose/F1 stub for the live model page")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--state", choices=sorted(STATES), default="nolmesh",
                    help="which recorded /state to serve")
    ap.add_argument("--pose", choices=("demo", "static", "off"), default="demo")
    a = ap.parse_args()

    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    httpd.state_key = a.state
    httpd.pose_mode = a.pose
    print(f"page    http://{a.host}:{a.port}/")
    print(f"state   {STATES[a.state].name}  (mesh={'yes' if a.state == 'mesh' else 'no'})")
    print(f"pose    {a.pose}")
    print("Ctrl+C to stop.  This is a stub: synthetic motion, not a measurement.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
