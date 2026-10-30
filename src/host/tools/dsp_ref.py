"""Bit-exact reference for peak_dsp.sv + test-vector generation.

    python dsp_ref.py <frame.csv> [out_dir] [frame_number]

Writes samples.hex (signed 11-bit, two's complement) for the testbench and
prints the fixed-point peak that the RTL must reproduce.

The 40-bit word is ``{valid, frame[12:0], idx[9:0], amp[15:0]}``.  ``frame`` is
the acquisition frame number (``frame_count`` in the RTL), so the host can prove
that an on-board word and an ILA frame belong to the same acquisition.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wscan import frames  # noqa: E402

COS = [128, 40, -104, -104, 40]
SIN = [0, 122, 75, -75, -122]
WIN_START, WIN_END = 280, 540
N = 560


def pack(frame: int, idx: int, amp: int) -> int:
    return (1 << 39) | ((frame & 0x1FFF) << 26) | ((idx & 0x3FF) << 16) | (amp & 0xFFFF)

def unpack(word: int) -> tuple[int, int, int, int]:
    return ((word >> 39) & 1, (word >> 26) & 0x1FFF, (word >> 16) & 0x3FF, word & 0xFFFF)


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s24(v: int) -> int:
    v &= 0xFFFFFF
    return v - 0x1000000 if v & 0x800000 else v


def s12(v: int) -> int:
    v &= 0xFFF
    return v - 0x1000 if v & 0x800 else v


def reference(diff: list[int], frame: int = 0) -> tuple[int, int, int]:
    dc = 0
    ph = 0
    ibuf = [0] * 10
    qbuf = [0] * 10
    sum_i = 0
    sum_q = 0
    peak_amp = 0
    peak_idx = 0
    word = 0
    sid = 0
    for x in diff[:N]:
        # amplitude from the *registered* sums (one sample behind the datapath)
        ai = -sum_i if sum_i < 0 else sum_i
        aq = -sum_q if sum_q < 0 else sum_q
        mag = ai + aq
        amp = mag >> 6
        if amp > 65535:
            amp = 65535
        take = (WIN_START <= sid < WIN_END) and amp > peak_amp
        best_amp = amp if take else peak_amp
        best_idx = sid if take else peak_idx
        peak_amp, peak_idx = best_amp, best_idx
        if sid == WIN_END - 1:
            word = pack(frame, best_idx, best_amp)
        # datapath update (same order as the RTL non-blocking assignments)
        hp = s12(x - (dc >> 4))
        i_prod = hp * COS[ph]
        q_prod = hp * SIN[ph]
        sum_i = s24(sum_i + i_prod - ibuf[9])
        sum_q = s24(sum_q + q_prod - qbuf[9])
        ibuf = [i_prod] + ibuf[:9]
        qbuf = [q_prod] + qbuf[:9]
        dc = s16(dc + ((x * 16 - dc) >> 6))
        ph = 0 if ph == 4 else ph + 1
        sid += 1
    return word, peak_idx, peak_amp


def envelope_array(diff: list[int]) -> list[int]:
    """Per-sample |I|+|Q| amplitude, bit-identical to the RTL `amp` wire.

    Entry k is the amplitude the peak search sees at sid k, i.e. computed from
    the 10-tap sums covering samples 0..k-1 (same registration as the RTL).
    """
    dc = 0
    ph = 0
    ibuf = [0] * 10
    qbuf = [0] * 10
    sum_i = 0
    sum_q = 0
    out = []
    for x in diff[:N]:
        ai = -sum_i if sum_i < 0 else sum_i
        aq = -sum_q if sum_q < 0 else sum_q
        amp = (ai + aq) >> 6
        out.append(65535 if amp > 65535 else amp)
        hp = s12(x - (dc >> 4))
        i_prod = hp * COS[ph]
        q_prod = hp * SIN[ph]
        sum_i = s24(sum_i + i_prod - ibuf[9])
        sum_q = s24(sum_q + q_prod - qbuf[9])
        ibuf = [i_prod] + ibuf[:9]
        qbuf = [q_prod] + qbuf[:9]
        dc = s16(dc + ((x * 16 - dc) >> 6))
        ph = 0 if ph == 4 else ph + 1
    return out


def reference_edge(diff: list[int], frame: int = 0, frac_num: int = 1,
                   frac_den: int = 2, abs_thr: int = 0) -> tuple[int, int, int]:
    """First-crossing reference: leading edge of the strongest echo.

    thr = max - max*frac  (integer, same as max - (max * frac_num // frac_den))
    or an absolute threshold when abs_thr > 0.  edge = 0 means "no crossing".
    """
    env = envelope_array(diff)
    win = env[WIN_START:WIN_END]
    mx = max(win)
    thr = abs_thr if abs_thr > 0 else mx - (mx * frac_num // frac_den)
    edge = 0
    for i, v in enumerate(win):
        if v >= thr:
            edge = WIN_START + i
            break
    return pack(frame, edge, mx), edge, mx


def frame_samples(csv: Path) -> list[int]:
    """The 560 samples the on-board DSP consumes after capture_start."""
    return frames.dsp_samples(frames.read_ila_csv(csv), N, frame_id=csv.name)


# --------------------------------------------------------------- C1: centroid
SAMPLE_US = 0.2


def centroid_reference(diff: list[int], win_start: int = WIN_START, win_end: int = WIN_END,
                       frac_bits: int = 8, base_mode: str = "mean") -> dict:
    """Fixed-point window centroid over the amplitude stream; the RTL must match bit for bit.

    This replaces the window argmax.  Everything is integer:

        base  = sum(amp[win]) // n            (mean baseline; a median needs a sort)
        w_k   = max(amp_k - base, 0)
        idx_q = (sum(k*w_k) << frac_bits) // sum(w_k)

    Widths the RTL needs (amp is 16 bit, window is 280 samples):
        sum(amp)  <= 280*65535      = 18,349,800  -> 25 bit
        sum(w)    <= same                          -> 25 bit
        sum(k*w)  <= 539*18,349,800 = 9.89e9       -> 34 bit
        numerator = sum(k*w) << 8                  -> 42 bit
    A serial divider producing 18 quotient bits needs 18 clocks, i.e. 0.36 us at
    50 MHz, against 56 us of slack after the window ends at 107.8 us.
    """
    amp = envelope_array(diff)
    seg = amp[win_start:win_end]
    n = len(seg)
    if n == 0:
        return {"valid": 0, "idx_q": 0, "t_us": None, "base": 0, "sum_w": 0, "sum_kw": 0}
    total = sum(seg)
    base = total // n
    sum_w = 0
    sum_kw = 0
    for k, a in enumerate(seg, start=win_start):
        w = a - base
        if w > 0:
            sum_w += w
            sum_kw += k * w
    if sum_w == 0:
        return {"valid": 0, "idx_q": 0, "t_us": None, "base": base, "sum_w": 0, "sum_kw": 0}
    idx_q = (sum_kw << frac_bits) // sum_w
    return {"valid": 1, "idx_q": idx_q,
            "t_us": idx_q * SAMPLE_US / (1 << frac_bits),
            "base": base, "sum_w": sum_w, "sum_kw": sum_kw,
            "frac_bits": frac_bits}


def main() -> None:
    csv = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "fpga" / "tb"
    frame_no = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    out.mkdir(parents=True, exist_ok=True)
    diff = frame_samples(csv)
    (out / "samples.hex").write_text("\n".join(f"{v & 0x7FF:03X}" for v in diff) + "\n",
                                     encoding="ascii")
    word, idx, amp = reference(diff, frame_no)
    # the RTL implements the integer form; Q8 is only for the offline study
    cent = centroid_reference(diff, frac_bits=0)
    print(f"frame   : {csv}")
    print(f"samples : {len(diff)}  first={diff[0]} max={max(diff)} min={min(diff)}")
    print(f"EXPECT  : word=0x{word:010X}  frame={frame_no}  idx={idx}  amp={amp}  t={idx * 0.2:.1f} us")
    print(f"CENT_EXPECT : idx={cent['idx_q']} sum_w={cent['sum_w']} sum_kw={cent['sum_kw']}"
          f"  t={cent['t_us']:.1f} us  base={cent['base']}")
    print(f"hex     : {out / 'samples.hex'}")


if __name__ == "__main__":
    main()
