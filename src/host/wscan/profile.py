"""Project profile: the 13号 diagnostic layout plus the mechanical scan geometry.

Facts are taken from:
  * AAA-running/tools/ila_lab/profile_13.json      (acquisition layout)
  * 3Dprinter/design_v3_printed/反射姿态参考表.csv (mechanical poses)
  * 11_motor_control_20261019                       (stepper behaviour)

Anything marked "assumption" must be replaced by a measurement before a real
distance or a real 3D point is published.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ----------------------------------------------------------------- acquisition
ILA_CLOCK_HZ = 50_000_000          # nominal, not measured with a counter
ADC_RATE_HZ = 5_000_000            # one ADC update every 10 ILA ticks
ADC_BITS = 10
ILA_ROWS = 8192
ADC_SAMPLES = 819                  # 8192 rows / 10, floor
SAMPLE_US = 1e6 / ADC_RATE_HZ      # 0.2 us per ADC sample
TX_PULSES = 8
TX_PERIOD_TICKS = 50               # 1 MHz
TX_HIGH_TICKS = 25
BASELINE_US = (-10.0, 0.0)         # pre-trigger window
BANDPASS_HZ = (500_000.0, 1_500_000.0)

# The trigger sits at row 512, so 10.24 us of pre-trigger data exists.
TRIGGER_ROW = 512

# ------------------------------------------------------------------- mechanics
SCREW_LEAD_MM = 2.0
STEPS_PER_REV_DEFAULT = 4096       # 28BYJ-48 class value; TO BE CALIBRATED
PROBE_SPACING_MM = 25.0
SOUND_SPEED_M_S = 1480.0

SPHERE_CENTER = (75.0, 100.0, 75.0)
SPHERE_RADIUS = 25.0

# 3Dprinter/design_v3_printed/反射姿态参考表.csv
CAD_ROWS = (
    (-20.0, -48.537, 48.537, 13.550, -22.357, 17.643, 52.114, 56.438),
    (-15.0, -49.248, 49.248, 9.922, -16.310, 23.690, 58.406, 54.004),
    (-10.0, -49.769, 49.769, 6.497, -10.647, 29.353, 64.231, 52.060),
    (-5.0, -50.087, 50.087, 3.213, -5.246, 34.754, 69.724, 50.514),
    (0.0, -50.194, 50.194, 0.0, 0.0, 40.0, 75.0, 49.301),
    (5.0, -50.087, 50.087, -3.213, 5.187, 45.187, 80.157, 48.381),
    (10.0, -49.769, 49.769, -6.497, 10.402, 50.402, 85.280, 47.733),
    (15.0, -49.248, 49.248, -9.922, 15.733, 55.733, 90.449, 47.358),
    (20.0, -48.537, 48.537, -13.550, 21.270, 61.270, 95.741, 47.280),
)

# Search window in time from capture_start.  Direct coupling is ~51.2 us,
# the equatorial sphere echo ~66.6 us.  56..104 us covers a path of
# 82.9..153.9 mm at 1480 m/s.  The frame itself runs to about 153 us.
WINDOW_US = (60.0, 104.0)
EDGE_MARGIN = 4                    # samples, 0.8 us

# ---------------------------------------------------------------------- input
@dataclass(frozen=True)
class AxisSpec:
    key: str
    unit: str
    steps_per_rev: int
    units_per_rev: float
    soft_min: float
    soft_max: float
    backlash_steps: int
    start_rate_sps: float
    max_rate_sps: float
    clk_hz: float = ILA_CLOCK_HZ

    @property
    def units_per_step(self) -> float:
        return self.units_per_rev / float(self.steps_per_rev)

    def to_steps(self, units: float) -> int:
        return int(round(units / self.units_per_step))


def lift_axis(steps_per_rev: int = STEPS_PER_REV_DEFAULT) -> AxisSpec:
    return AxisSpec("lift", "mm", steps_per_rev, SCREW_LEAD_MM,
                    51.5, 96.5, 400, 80.0, 400.0)


def rot_axis(steps_per_rev: int = STEPS_PER_REV_DEFAULT) -> AxisSpec:
    return AxisSpec("rot", "deg", steps_per_rev, 360.0,
                    -15.0, 375.0, 24, 120.0, 600.0)


@dataclass
class Layer:
    latitude_deg: float
    probe_z_mm: float
    single_path_mm: float
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    tx: tuple[float, float, float]
    rx: tuple[float, float, float]
    target_nominal: tuple[float, float, float]


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    if n <= 0:
        raise ValueError("zero vector")
    return tuple(x / n for x in v)


def make_layer(lat_deg: float, spacing_mm: float = PROBE_SPACING_MM) -> Layer:
    """Nominal per-latitude ray reconstructed from the CAD single-path column.

    The probe midpoint is placed on the X=75 vertical so that
    |Q-TX| = |Q-RX| = single_path.  This is NOMINAL geometry; a real scan must
    replace it after the standard-sphere check.
    """
    row = next((r for r in CAD_ROWS if r[0] == lat_deg), None)
    if row is None:
        raise ValueError(f"latitude {lat_deg} not in the CAD table")
    z = row[6]
    l1 = row[7]
    c = SPHERE_CENTER
    r = SPHERE_RADIUS
    phi = math.radians(lat_deg)
    target = (c[0], c[1] - r * math.cos(phi), c[2] + r * math.sin(phi))
    half = spacing_mm / 2.0
    m = math.sqrt(max(l1 * l1 - half * half, 1e-9))
    dz = target[2] - z
    if m * m - dz * dz <= 0:
        raise ValueError("latitude geometry unreachable")
    y_mid = target[1] - math.sqrt(m * m - dz * dz)
    origin = (c[0], y_mid, z)
    direction = _unit((0.0, target[1] - y_mid, target[2] - z))
    return Layer(lat_deg, z, l1, origin, direction,
                 (origin[0] - half, origin[1], origin[2]),
                 (origin[0] + half, origin[1], origin[2]), target)


def all_layers() -> list[Layer]:
    return [make_layer(r[0]) for r in CAD_ROWS]


# ----------------------------------------------------------------------- plan
@dataclass
class ScanPlan:
    latitudes: tuple[float, ...] = tuple(r[0] for r in CAD_ROWS)
    azimuths: tuple[float, ...] = tuple(30.0 * i for i in range(12))
    frames_per_point: int = 3
    settle_s: float = 0.6
    readout_s: float = 3.5          # one ILA upload + CSV export, estimate
    move_rate_sps: float = 200.0

    def points(self):
        for li, lat in enumerate(self.latitudes):
            order = list(range(len(self.azimuths)))
            if li % 2:
                order.reverse()          # serpentine: one reversal per layer
            for j in order:
                yield li, lat, j, self.azimuths[j]

    def count(self) -> int:
        return len(self.latitudes) * len(self.azimuths)

    def lift_steps_between(self, a_mm: float, b_mm: float) -> int:
        return int(round(abs(b_mm - a_mm) / (SCREW_LEAD_MM / STEPS_PER_REV_DEFAULT)))

    def rot_steps_between(self, a_deg: float, b_deg: float) -> int:
        return int(round(abs(b_deg - a_deg) / (360.0 / STEPS_PER_REV_DEFAULT)))

    def estimate_s(self) -> dict:
        layers = all_layers()
        lift = 0.0
        prev_z = layers[0].probe_z_mm
        for layer in layers:
            lift += self.lift_steps_between(prev_z, layer.probe_z_mm) / self.move_rate_sps
            prev_z = layer.probe_z_mm
        rot = 0.0
        for li, _ in enumerate(self.latitudes):
            order = list(range(len(self.azimuths)))
            if li % 2:
                order.reverse()
            prev = self.azimuths[order[0]]
            for j in order[1:]:
                rot += self.rot_steps_between(prev, self.azimuths[j]) / self.move_rate_sps
                prev = self.azimuths[j]
        settle = self.count() * self.settle_s
        readout = self.count() * self.frames_per_point * self.readout_s
        move = lift + rot
        return {"move_s": move, "lift_s": lift, "rot_s": rot, "settle_s": settle,
                "readout_s": readout, "total_s": move + settle + readout}


DEFAULT_PLAN = ScanPlan()
