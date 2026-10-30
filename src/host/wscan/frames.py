"""Frame decoding (ILA CSV -> samples) and the exploratory DSP chain."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import profile

# Column names exactly as exported by the 13号 ILA (profile_13.json).
COLUMNS = {
    "sample": "Sample in Buffer",
    "adc1": "sample1[9:0]",
    "adc2": "sample2[9:0]",
    "diff": "diff[10:0]",
    "otr": "status_2[4:3]",
    "tx": "tx_burst_OBUF",
    "start": "capture_start",
    "valid": "status_4[5:5]",
    "reset": "status[0:0]",
}
# Optional columns: older exports may not carry them.
OPTIONAL_COLUMNS = {"frame_index": "frame_index[12:0]"}
RADIX_BASE = {"HEX": 16, "BINARY": 2, "UNSIGNED": 10, "SIGNED": 10}


@dataclass
class Frame:
    t_us: np.ndarray
    diff: np.ndarray
    frame_id: str
    tx_on: bool
    source: str = ""
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.diff.size)

    def at(self, t_us: float) -> float:
        return float(np.interp(t_us, self.t_us, self.diff))


def read_ila_csv(path: str | Path) -> dict:
    """Parse one ILA CSV export into raw columns (validates shape and values)."""
    rows = [r for r in csv.reader(Path(path).read_text(encoding="utf-8-sig").splitlines()) if r]
    if len(rows) < 3:
        raise ValueError("CSV too short")
    names, radices = rows[0], rows[1]
    if len(names) != len(radices):
        raise ValueError("column/radix count mismatch")
    if len(rows) - 2 != profile.ILA_ROWS:
        raise ValueError(f"expected {profile.ILA_ROWS} rows, got {len(rows) - 2}")
    out = {}
    for role, name in COLUMNS.items():
        if name not in names:
            raise ValueError(f"missing column {name}")
        i = names.index(name)
        radix = radices[i].replace("Radix - ", "").strip()
        base = RADIX_BASE.get(radix)
        if base is None:
            raise ValueError(f"unsupported radix {radix}")
        out[role] = np.array([int(r[i], base) for r in rows[2:]], dtype=np.int64)
    for role, name in OPTIONAL_COLUMNS.items():
        if name in names:
            i = names.index(name)
            radix = radices[i].replace("Radix - ", "").strip()
            base = RADIX_BASE.get(radix)
            if base is not None:
                out[role] = np.array([int(r[i], base) for r in rows[2:]], dtype=np.int64)
    return out


def to_frame(raw: dict, frame_id: str = "", source: str = "") -> Frame:
    """Validate a raw capture and keep only the ADC-rate samples."""
    cols = raw
    if not np.all(np.diff(cols["sample"]) == 1):
        raise ValueError("ILA sample index is not continuous")
    for key in ("valid", "start", "tx", "reset"):
        if not np.all(np.isin(cols[key], [0, 1])):
            raise ValueError(f"{key} is not a logic bit")
    start = np.flatnonzero(cols["start"])
    if start.size != 1:
        raise ValueError("expected exactly one capture_start")
    if np.any(cols["otr"]):
        raise ValueError("ADC over-range flag is set")
    if not np.all(cols["reset"] == 1):
        raise ValueError("core reset was not released")

    valid = cols["valid"] == 1
    indices = cols["sample"][valid]
    cadence = profile.ILA_CLOCK_HZ // profile.ADC_RATE_HZ
    if indices.size < 64 or not np.all(np.diff(indices) == cadence):
        raise ValueError("ADC update cadence is not 10 ILA ticks")

    bits = profile.ADC_BITS
    s1, s2 = cols["adc1"][valid], cols["adc2"][valid]
    if np.any((s1 < 0) | (s1 >= 2 ** bits)) or np.any((s2 < 0) | (s2 >= 2 ** bits)):
        raise ValueError("ADC code out of range")
    diff = cols["diff"][valid].astype(np.int64)
    diff[diff >= 2 ** bits] -= 2 ** (bits + 1)
    if not np.all(diff == s1 - s2):
        raise ValueError("signed difference does not match the two ADC codes")

    tx = cols["tx"]
    rises = np.flatnonzero(np.diff(np.r_[0, tx]) == 1)
    falls = np.flatnonzero(np.diff(np.r_[tx, 0]) == -1) + 1
    is_on = bool(np.any(tx))
    if is_on:
        if rises.size != profile.TX_PULSES or falls.size != rises.size:
            raise ValueError("TX pulse count mismatch")
        if not np.all(falls - rises == profile.TX_HIGH_TICKS):
            raise ValueError("TX high width mismatch")
        if not np.all(np.diff(rises) == profile.TX_PERIOD_TICKS):
            raise ValueError("TX period mismatch")

    t_us = (indices - cols["sample"][start[0]]) / profile.ILA_CLOCK_HZ * 1e6
    meta = {"samples": int(indices.size), "tx_pulses": int(rises.size),
            "start_row": int(start[0]), "trigger_sample": int(cols["sample"][start[0]]),
            "indices": indices.copy()}
    if "frame_index" in cols:
        meta["ticks"] = cols["frame_index"][valid].copy()
    return Frame(t_us=t_us, diff=diff.astype(float), frame_id=frame_id or "frame",
                 tx_on=is_on, source=source, meta=meta)


def dsp_samples(raw: dict, n: int = 560, frame_id: str = "") -> list[int]:
    """The first n ADC samples after capture_start, i.e. exactly what peak_dsp sees.

    The ILA labels row ``t`` with the value its probes hold at tick ``t``, and the
    trigger row is the cycle where ``capture_start`` was high.  peak_dsp ignores
    that cycle (capture_start wins over sample_valid) and starts counting at the
    next ADC sample, so the window begins at the first valid row *after* the
    trigger row.  This is the alignment the 2026-10-25 board compare was missing:
    ``argmax(t_us >= 0)`` is off by one sample whenever a valid row lands exactly
    on the trigger row.
    """
    frame = to_frame(raw, frame_id=frame_id)
    indices = frame.meta["indices"]
    sel = indices > frame.meta["trigger_sample"]
    if sel.sum() < n:
        raise ValueError(f"only {int(sel.sum())} post-trigger samples, need {n}")
    ticks = frame.meta.get("ticks")
    if ticks is not None:
        chosen = ticks[sel][:n]
        if not np.all(np.diff(chosen) == profile.ILA_CLOCK_HZ // profile.ADC_RATE_HZ):
            raise ValueError("post-trigger samples are not on the 5 MSPS cadence")
        if chosen[0] <= 0:
            raise ValueError("first post-trigger sample carries tick 0")
    return [int(v) for v in frame.diff[sel][:n]]



# --------------------------------------------------------------------- DSP
@dataclass
class Prepared:
    t_us: np.ndarray
    x: np.ndarray            # baseline-removed difference
    filtered: np.ndarray     # band-passed
    envelope: np.ndarray     # smoothed analytic magnitude
    baseline: float
    noise_sigma: float


def prepare(frame: Frame, band_hz=profile.BANDPASS_HZ) -> Prepared:
    t = frame.t_us
    lo, hi = profile.BASELINE_US
    pre = (t >= lo) & (t < hi)
    if pre.sum() < 8:
        raise ValueError("baseline window has fewer than 8 samples")
    baseline = float(np.mean(frame.diff[pre]))
    x = frame.diff - baseline

    n = x.size
    nfft = 1 << (2 * n - 1).bit_length()
    freq = np.fft.rfftfreq(nfft, 1.0 / profile.ADC_RATE_HZ)
    spec = np.fft.rfft(x, nfft) * ((freq >= band_hz[0]) & (freq <= band_hz[1]))
    filtered = np.fft.irfft(spec, nfft)[:n]

    mult = np.zeros(nfft)
    mult[0] = mult[nfft // 2] = 1.0
    mult[1:nfft // 2] = 2.0
    analytic = np.fft.ifft(np.fft.fft(filtered, nfft) * mult)[:n]
    env = np.convolve(np.abs(analytic), np.ones(3) / 3.0, mode="same")

    quiet = (t < profile.WINDOW_US[0]) | (t > profile.WINDOW_US[1])
    sigma = float(np.median(np.abs(env[quiet] - np.median(env[quiet]))) * 1.4826) if quiet.any() else 0.0
    return Prepared(t, x, filtered, env, baseline, max(sigma, 1e-9))


@dataclass
class Peak:
    t_us: float
    amplitude: float
    snr_db: float
    second_ratio: float
    at_edge: bool


def detect(prep: Prepared, window=profile.WINDOW_US,
           edge_margin_us: float = profile.EDGE_MARGIN * profile.SAMPLE_US) -> Peak | None:
    t, env = prep.t_us, prep.envelope
    lo, hi = window
    mask = (t >= lo) & (t <= hi)
    if mask.sum() < 8:
        return None
    seg_t, seg = t[mask], env[mask]
    k = int(np.argmax(seg))
    amp = float(seg[k])
    base = float(np.median(seg))
    sigma = float(np.median(np.abs(seg - base)) * 1.4826) or 1e-9
    if amp <= base:
        return None
    snr = 20.0 * math.log10(max(amp - base, 1e-12) / sigma)
    guard = 12                       # +-2.4 us, wider than the 1 MHz envelope
    m2 = np.ones(seg.size, bool)
    m2[max(0, k - guard):k + guard + 1] = False
    second = float(seg[m2].max()) if m2.any() else base
    ratio = (second - base) / (amp - base) if amp > base else 1.0

    t_peak = float(seg_t[k])
    if 0 < k < seg.size - 1:          # parabolic refinement
        y0, y1, y2 = seg[k - 1], seg[k], seg[k + 1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-12:
            t_peak += 0.5 * (y0 - y2) / den * profile.SAMPLE_US
    edge = t_peak <= lo + edge_margin_us or t_peak >= hi - edge_margin_us
    return Peak(t_peak, amp, snr, ratio, edge)
