#!/usr/bin/env python3
"""Bit-exact PC model of fpga/f1/pose_fusion.sv (E6: "the board's number can be
recomputed on a PC, bit for bit").

Every integer step here is the same integer step the RTL does, in the same order:

  sqrt  : 16 digit-by-digit steps, rem/root/trial exactly as in the RTL
  atan2 : 15 CORDIC vectoring rotations, atan table in counts, quadrant fix-up
          from the input signs
  blend : counts = gyro_acc + ((accel_angle - gyro_acc) >> 5)   (alpha = 31/32)
  wrap  : into [-32768, +32768)

Angle unit: 90 deg = 16384 counts (1 count = 0.005493 deg), the same 16-bit field
the pose word uses ("degrees x 182.044").

  python tools/f1_pose_ref.py --selftest                     # vs float atan2
  python tools/f1_pose_ref.py --vectors fpga/f1/pose_vectors.txt

The vectors file is read by fpga/f1/tb_pose_fusion.sv ($fscanf); one sample per
line, decimal:  ax ay az gx gy gz dt exp_roll exp_pitch exp_yaw
`dt` is in 50 MHz ticks (the TB runs its own 32-bit tick counter, so no field has
to wrap at 16 bits).
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass

DT_MIN = 10_000
DT_MAX = 200_000
WARMUP = 32
GYRO_K = 3820
GYRO_S = 36

ATAN = [8192, 4836, 2555, 1297, 651, 326, 163, 81, 41, 20, 10, 5, 3, 1, 0]
COUNTS_PER_DEG = 16384.0 / 90.0

G = 8192           # +-4 g -> 8192 LSB/g
GYRO_1DPS = 65.5   # +-500 dps -> 65.5 LSB/(deg/s)


# ------------------------------------------------------------------- helpers ---
def wrap32(v: int) -> int:
    if v >= 32768:
        return v - 65536
    if v < -32768:
        return v + 65536
    return v


def sat16(v: int) -> int:
    return 32767 if v > 32767 else (-32768 if v < -32768 else v)


def sext16(v: int) -> int:
    """16-bit signed -> python int (what $signed() gives the RTL)."""
    return v - 65536 if v >= 32768 else v


def isqrt_digitwise(x: int) -> int:
    """16-step digit-by-digit floor(sqrt(x)) for 0 <= x < 2^32 (as in the RTL)."""
    rem = 0
    root = 0
    for i in range(16):
        rem = ((rem << 2) | ((x >> (30 - 2 * i)) & 3)) & 0x7FFFF
        trial = (root << 2) | 1
        if rem >= trial:
            rem -= trial
            root = (root << 1) | 1
        else:
            root = root << 1
    return root & 0xFFFF


def atan2_cordic(y: int, x: int) -> int:
    """atan2(y,x) in counts, exactly as the RTL does it, range [-32768, 32768]."""
    sx = 1 if x < 0 else 0
    sy = 1 if y < 0 else 0
    cx, cy = abs(x), abs(y)
    cz = 0
    for i in range(15):
        if cy >= 0:
            cx, cy, cz = cx + (cy >> i), cy - (cx >> i), cz + ATAN[i]
        else:
            cx, cy, cz = cx - (cy >> i), cy + (cx >> i), cz - ATAN[i]
    phi = cz if cz >= 0 else -cz
    if not sx and not sy:
        theta = phi
    elif not sx and sy:
        theta = -phi
    elif sx and not sy:
        theta = 32768 - phi
    else:
        theta = -(32768 - phi)
    return theta


@dataclass
class Pose:
    roll: int = 0
    pitch: int = 0
    yaw: int = 0
    seq: int = 0
    warm: int = 0
    acc_roll: int = 0
    acc_pitch: int = 0
    acc_yaw: int = 0
    warmup: int = WARMUP

    def step(self, dt: int, ax: int, ay: int, az: int,
             gx: int, gy: int, gz: int) -> tuple[int, int, int]:
        ax, ay, az = sext16(ax), sext16(ay), sext16(az)
        gx, gy, gz = sext16(gx), sext16(gy), sext16(gz)
        dt = DT_MIN if dt < DT_MIN else (DT_MAX if dt > DT_MAX else dt)

        mag = isqrt_digitwise(ay * ay + az * az)
        roll_a = sat16(atan2_cordic(ay, az))
        pitch_a = sat16(atan2_cordic(-ax, mag))

        for axis, g in enumerate((gx, gy, gz)):
            d = (g * dt * GYRO_K) >> GYRO_S       # arithmetic shift == floor
            if axis == 0:
                self.acc_roll = wrap32(self.acc_roll + d)
            elif axis == 1:
                self.acc_pitch = wrap32(self.acc_pitch + d)
            else:
                self.acc_yaw = wrap32(self.acc_yaw + d)

        if self.warm < self.warmup:
            self.roll, self.pitch, self.yaw = roll_a, pitch_a, 0
            self.acc_roll, self.acc_pitch, self.acc_yaw = roll_a, pitch_a, 0
            self.warm += 1
        else:
            self.roll = sat16(wrap32(self.acc_roll +
                                     (wrap32(roll_a - self.acc_roll) >> 5)))
            self.pitch = sat16(wrap32(self.acc_pitch +
                                      (wrap32(pitch_a - self.acc_pitch) >> 5)))
            self.yaw = sat16(self.acc_yaw)
            self.acc_roll = wrap32(self.acc_roll +
                                   (wrap32(roll_a - self.acc_roll) >> 5))
            self.acc_pitch = wrap32(self.acc_pitch +
                                    (wrap32(pitch_a - self.acc_pitch) >> 5))
        self.seq = (self.seq + 1) & 0xFF
        return self.roll, self.pitch, self.yaw


# ---------------------------------------------------------------- scenarios ---
def tilt_gravity(roll_deg: float, pitch_deg: float) -> tuple[int, int, int]:
    """What the accelerometer reads at rest for this attitude (Z up, g along -Z)."""
    r, p = math.radians(roll_deg), math.radians(pitch_deg)
    ax = -G * math.sin(p)
    ay = G * math.sin(r) * math.cos(p)
    az = G * math.cos(r) * math.cos(p)
    return int(round(ax)), int(round(ay)), int(round(az))


def scenario_rows() -> list[dict]:
    """A deterministic, reproducible sample stream.  The sim replays exactly this."""
    rows: list[dict] = []

    def add(dt, roll_deg, pitch_deg, gx=0, gy=0, gz=0):
        ax, ay, az = tilt_gravity(roll_deg, pitch_deg)
        rows.append(dict(dt=dt, ax=ax, ay=ay, az=az, gx=gx, gy=gy, gz=gz))

    for _ in range(12):                       # flat, at rest
        add(50000, 0, 0)
    for k in range(20):                       # roll ramp 0..38 deg
        add(50000, 2.0 * k, 0)
    for k in range(20):                       # pitch ramp -20..+18
        add(50000, 38.0, -20.0 + 2.0 * k)
    for _ in range(30):                       # yaw spin, 100 deg/s
        add(50000, 38, 18, gz=int(round(100 * GYRO_1DPS)))
    for k in range(10):                       # dt jitter 0.5 / 2 ms
        add(25000 if k % 2 else 100000, 38, 18, gz=int(round(100 * GYRO_1DPS)))
    for _ in range(10):                       # roll near +180
        add(50000, 179.0, 0)
    for _ in range(8):                        # upside down
        add(50000, -179.0, 0)
    for k in range(10):                       # pitch +-85 (no gimbal lock)
        add(50000, 0, 85.0 if k % 2 else -85.0)
    for _ in range(10):                       # gyro only, accel unchanged
        add(50000, 10, 5, gx=int(round(-50 * GYRO_1DPS)))
    return rows


def run(rows: list[dict]) -> list[tuple[int, int, int]]:
    p = Pose()
    out = []
    for r in rows:
        out.append(p.step(r["dt"], r["ax"], r["ay"], r["az"],
                          r["gx"], r["gy"], r["gz"]))
    return out


def write_vectors(path: str, rows: list[dict]) -> None:
    exp = run(rows)
    with open(path, "w", encoding="ascii") as f:
        for r, (ro, pi, ya) in zip(rows, exp):
            f.write("%d %d %d %d %d %d %d %d %d %d\n" % (
                r["ax"], r["ay"], r["az"], r["gx"], r["gy"], r["gz"],
                r["dt"], ro, pi, ya))
    print(f"wrote {len(rows)} vectors -> {path}")


# ------------------------------------------------------------------ selftest ---
def selftest() -> int:
    worst_a, n = 0.0, 0
    for yd in range(-180, 181, 5):
        for xd in range(-180, 181, 5):
            if xd == 0 and yd == 0:
                continue
            cx = int(round(xd * COUNTS_PER_DEG))
            cy = int(round(yd * COUNTS_PER_DEG))
            got = atan2_cordic(cy, cx)
            ref = math.degrees(math.atan2(yd, xd)) * COUNTS_PER_DEG
            if abs(ref) > 16383.5:            # +-180 boundary is saturated on purpose
                continue
            worst_a = max(worst_a, abs(got - ref))
            n += 1
    worst_s = 0
    for x in (0, 1, 2, 3, 4, 15, 16, 999, 12345, 2_147_000_000, 2 * 32767 * 32767):
        got = isqrt_digitwise(x)
        if got * got > x or (got + 1) * (got + 1) <= x:
            print(f"SQRT_FAIL x={x} got={got}")
            return 1
        worst_s = max(worst_s, abs(got - math.isqrt(x)))
    print(f"ATAN_MAX_ERR_COUNTS={worst_a:.1f} ({worst_a / COUNTS_PER_DEG:.4f} deg) over {n} points")
    print(f"SQRT_MAX_ERR={worst_s} LSB")

    p = Pose()
    for _ in range(40):
        p.step(50000, *tilt_gravity(30, -10), 0, 0, 0)
    want_r = 30.0 * COUNTS_PER_DEG
    want_p = -10.0 * COUNTS_PER_DEG
    print(f"PIPE roll={p.roll} want~{want_r:.0f} ({p.roll - want_r:+.1f} LSB)  "
          f"pitch={p.pitch} want~{want_p:.0f} ({p.pitch - want_p:+.1f} LSB)")
    ok = worst_a < 12 and abs(p.roll - want_r) < 60 and abs(p.pitch - want_p) < 60
    print("SELFTEST_PASS" if ok else "SELFTEST_FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--vectors", metavar="PATH")
    ap.add_argument("--rows", type=int, default=0, help="limit rows (debug)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.vectors:
        rows = scenario_rows()
        if a.rows:
            rows = rows[:a.rows]
        write_vectors(a.vectors, rows)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
