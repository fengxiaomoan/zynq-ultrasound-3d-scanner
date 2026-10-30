# -*- coding: utf-8 -*-
"""Verify the delivery package and (optionally) write manifest.json.

    python verify_package.py
    python verify_package.py --write-manifest

Checks:
  * required files/dirs exist;
  * every path segment is lowercase ASCII (README.md / SKILL.md / LICENSE allowed);
  * all .json files parse (except data/real/incomplete, which is intentionally partial);
  * relative Markdown links resolve;
  * shipped bitstream/XSA/firmware hashes match the report;
  * no absolute D:\\daxue paths in executable scripts outside upstream/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".git", ".venv", "__pycache__", "build/output", ".Xil", "xsim.dir", ".edge-tmp"}
ALLOW_NAMES = {"README.md", "SKILL.md", "LICENSE", ".gitignore"}

REQUIRED = [
    "README.md", "LICENSE", "requirements.txt",
    "src/rtl/merged_top.sv", "src/rtl/peak_dsp.sv", "src/rtl/acq_axi_regs.v",
    "src/ps/sw/src/acq.c", "src/ps/sw/src/alg.c", "src/ps/sw/src/model.c", "src/ps/sw/src/net.c",
    "sim/tb/tb_peak_dsp.sv", "sim/tb/tb_acq_axi_regs.sv",
    "build/build_ps_m3_pkg.tcl", "build/reports/resource_summary.md",
    "board/bitstream/ps_m3_system_wrapper.bit", "board/xsa/ps_m3.xsa",
    "board/firmware/m2b_ps.bin",
    "data/real/_m2b_3layer_signed.json", "data/real/_m2b_6layer.json",
    "data/reference/bench/summary.json", "data/reference/anomaly/summary.json",
    "skill/README.md", "skill/01_fpga_capture_bringup/SKILL.md",
    "skill/02_rtl_dsp_pipeline/SKILL.md", "skill/08_mechanical_design_to_print/SKILL.md",
    "report/01_design_report.md", "report/06_video_shooting_guide.md",
    "report/08_technical_document.md", "report/export/technical_document.pdf",
    "report/09_project_walkthrough.md",
    "report/05_evidence_index.md", "report/07_submission_checklist.md",
    "data/mechanical/verification.json",
]

EXPECTED_HASHES = {
    "board/bitstream/ps_m3_system_wrapper.bit":
        "254c3aa69264ac7ea80435549e038d26e2ceb2825749595a929c4935e0f1459c",
    "board/bitstream/dsp_merged_top.bit":
        "0d3d8c0063afbf5c84cfe976c89241b685b39c5fc756fa945be87e3b538ecdd2",
    "board/xsa/ps_m3.xsa":
        "e55e516e823da30b1ba05fe306b87b7072ab18abb7b6db1dc84081a84115a234",
    "board/firmware/m2b_ps.bin":
        "6f89cb999875fca047c03c4d5f6d9f1212694071ac72d0a59cde32a942ef02cc",
    "board/firmware/m2b_ps.elf":
        "e528106ad4ab55235f86f18ffb0ba1cf43e9db80e3572de8c5d0373a63016141",
}

BAD_NAME = re.compile(r"[^a-z0-9._-]")


def walk_files() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = Path(dirpath).relative_to(ROOT).as_posix()
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and not d.startswith(".dsh-office-")
                       and f"{rel}/{d}".strip("/") not in SKIP_DIRS]
        if rel in SKIP_DIRS:
            continue
        for f in filenames:
            out.append(Path(dirpath) / f)
    return sorted(out)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_names(files: list[Path]) -> list[str]:
    bad = []
    for p in files:
        rel = p.relative_to(ROOT)
        for seg in rel.parts:
            if seg in ALLOW_NAMES:
                continue
            if BAD_NAME.search(seg) or seg.startswith("."):
                bad.append(f"{rel}  (segment: {seg})")
                break
    return bad


def check_json(files: list[Path]) -> list[str]:
    bad = []
    for p in files:
        if p.suffix.lower() != ".json":
            continue
        if "incomplete" in p.parts:
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"{p.relative_to(ROOT)}: {e}")
    return bad


def check_links(files: list[Path]) -> list[str]:
    bad = []
    pat = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
    for p in files:
        if p.suffix.lower() != ".md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            target = m.group(1).strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if "<package>" in target or "{" in target:
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = (p.parent / target).resolve()
            if not resolved.exists():
                bad.append(f"{p.relative_to(ROOT)} -> {target}")
    return bad


def check_paths(files: list[Path]) -> list[str]:
    bad = []
    for p in files:
        if p.suffix.lower() not in {".py", ".ps1", ".tcl"}:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if "upstream" in rel or rel == "verify_package.py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "D:\\daxue" in text or "D:/daxue" in text:
            bad.append(rel)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-manifest", action="store_true")
    args = ap.parse_args()

    errors = []
    files = walk_files()

    for req in REQUIRED:
        if not (ROOT / req).exists():
            errors.append(f"missing required: {req}")

    for name, want in EXPECTED_HASHES.items():
        p = ROOT / name
        if p.exists():
            got = sha256(p)
            if got != want:
                errors.append(f"hash mismatch: {name}\n  want {want}\n  got  {got}")

    errors += [f"bad name: {x}" for x in check_names(files)]
    errors += [f"bad json: {x}" for x in check_json(files)]
    errors += [f"broken link: {x}" for x in check_links(files)]
    errors += [f"absolute D:/daxue path in script: {x}" for x in check_paths(files)]

    total = sum(p.stat().st_size for p in files)
    print(f"files: {len(files)}")
    print(f"bytes: {total} ({total/1024/1024:.1f} MB)")
    print(f"errors: {len(errors)}")
    for e in errors:
        print("  -", e)

    if args.write_manifest:
        entries = []
        for p in files:
            if p.name == "manifest.json":
                continue
            entries.append({
                "path": p.relative_to(ROOT).as_posix(),
                "size": p.stat().st_size,
                "sha256": sha256(p),
            })
        manifest = {
            "package": "ultrasound_3d_scanner",
            "generated": "2026-10-27",
            "file_count": len(entries),
            "total_bytes": sum(e["size"] for e in entries),
            "files": entries,
        }
        (ROOT / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print("manifest.json written")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
