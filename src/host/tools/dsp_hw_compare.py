"""Compare the on-board 40-bit peak word with the Python reference.

    python tools/dsp_hw_compare.py live_run/dsp_hw.log live_run/dsp_hw/frame.csv [frame]

Reads the numbers printed by fpga/dsp_readback.tcl, recomputes the expected
40-bit word from the same ILA frame with tools/dsp_ref.py and writes
``dsp_hw_compare.json`` next to the log.

Same-frame proof (the 2026-10-25 P1 fix): the word carries the acquisition frame
number, and dsp_readback.tcl also reads the live ``frame_count`` from the
control VIO.  ``frame_match`` is true only when both are equal - i.e. no newer
frame started between the ILA trigger and the word read - so the ILA frame in the
CSV and the latched word are the same acquisition.  The sample window is then
taken with the exact DSP rule (wscan.frames.dsp_samples), not with a guessed
t_us offset.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsp_ref  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wscan import frames  # noqa: E402

KEYS = ("FPGA_PEAK_WORD", "FPGA_PEAK_RAW", "FPGA_PEAK_FRAME", "FPGA_LIVE_FRAME", "FPGA_PEAK_IDX",
        "FPGA_PEAK_AMP", "FPGA_PEAK_T_US", "FPGA_PEAK_VALID", "FPGA_FRAME_MATCH",
        "ILA_FRAME_MS", "VIO_READ_PER_CALL_MS", "SPEEDUP_VS_ILA")


def parse_log(text: str) -> dict:
    out = {}
    for key in KEYS:
        m = re.search(rf"{key}:\s*([0-9A-Fa-fx.]+)", text)
        if m:
            out[key] = m.group(1)
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    log = Path(sys.argv[1])
    csv = Path(sys.argv[2])
    info = parse_log(log.read_text(encoding="utf-8", errors="ignore"))
    if "FPGA_PEAK_WORD" not in info and "FPGA_PEAK_RAW" not in info:
        print("no FPGA_PEAK_WORD in the log; run dsp_readback.tcl with the board powered")
        return 2

    hw_valid = int(info.get("FPGA_PEAK_VALID", "0"))
    hw_frame = int(info.get("FPGA_PEAK_FRAME", "0"))
    hw_idx = int(info.get("FPGA_PEAK_IDX", "0"))
    hw_amp = int(info.get("FPGA_PEAK_AMP", "0"))
    live_frame = int(info.get("FPGA_LIVE_FRAME", "-1"))
    frame_match = (live_frame & 0x1FFF) == (hw_frame & 0x1FFF) if live_frame >= 0 else None
    if "FPGA_FRAME_MATCH" in info:
        frame_match = info["FPGA_FRAME_MATCH"] == "1"

    hw_word = dsp_ref.pack(hw_frame, hw_idx, hw_amp) if hw_valid else 0

    frame_no = int(sys.argv[3]) if len(sys.argv) > 3 else hw_frame
    diff = frames.dsp_samples(frames.read_ila_csv(csv), dsp_ref.N, frame_id=csv.name)
    ref_word, ref_idx, ref_amp = dsp_ref.reference(diff, frame_no)
    _, _, ref_idx, ref_amp = dsp_ref.unpack(ref_word)

    result = {
        "provenance": "board + reference, same frame (frame stamp in the word)",
        "hw_word": f"0x{hw_word:010X}",
        "ref_word": f"0x{ref_word:010X}",
        "word_match": hw_word == ref_word,
        "hw_frame": hw_frame,
        "live_frame": live_frame,
        "frame_match": frame_match,
        "hw_idx": hw_idx, "ref_idx": ref_idx,
        "hw_amp": hw_amp, "ref_amp": ref_amp,
        "idx_delta": hw_idx - ref_idx,
        "amp_delta": hw_amp - ref_amp,
        "ila_frame_ms": info.get("ILA_FRAME_MS"),
        "vio_read_per_call_ms": info.get("VIO_READ_PER_CALL_MS"),
        "speedup_vs_ila": info.get("SPEEDUP_VS_ILA"),
    }
    (log.parent / "dsp_hw_compare.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"hw  word=0x{hw_word:010X}  frame={hw_frame}  idx={hw_idx}  amp={hw_amp}")
    print(f"ref word=0x{ref_word:010X}  frame={frame_no}  idx={ref_idx}  amp={ref_amp}")
    print(f"frame_match: {frame_match} (live frame_count {live_frame})")
    print(f"MATCH: {result['word_match']}   idx_delta={result['idx_delta']}  amp_delta={result['amp_delta']}")
    print(f"ILA frame: {result['ila_frame_ms']} ms   VIO read: {result['vio_read_per_call_ms']} ms   "
          f"speedup: {result['speedup_vs_ila']}x")
    return 0 if (result["word_match"] and frame_match is not False) else 1


if __name__ == "__main__":
    raise SystemExit(main())


