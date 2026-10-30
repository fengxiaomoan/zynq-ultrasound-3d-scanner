"""Build the M2b PS firmware end to end, with no Vitis IDE and no xsct.

Vitis 2025.1 has no xsct and its Python `create_platform_component` flow does not
work in this install (the platform wrapper cannot generate the processor list),
so this script drives the same underlying tools directly:

  1. sdtgen (Vivado's copy) turns fpga_ps_m2/ps_m2.xsa into a system device tree;
  2. empyro (Vitis's pyesw) creates a standalone BSP for ps7_cortexa9_0, with
     lwip220 added, and builds it;
  3. empyro creates an empty_application app component, this repo's firmware
     sources are copied in, UserConfig is set to -O2 + lwip220/libm, and built.

Everything lands under --work (default <repo-root>/vitis_m2b) and the ELF is
copied to fpga/ps/build_m2b/m2b_ps.elf.

    python fpga/ps/build_m2b.py                # full rebuild
    python fpga/ps/build_m2b.py --app-only     # after editing src/

Prerequisites (checked by the script):
  * D:/Xilinx/2025.1 (Vitis + Vivado)
  * an arm-none-eabi GCC reachable at Vitis/gnu/aarch32/nt/gcc-arm-none-eabi
  * lopper + sdtgen on PATH (they ship in Vivado/bin; Vitis/bin has a shim)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # fpga/ps
ROOT = HERE.parents[1]                           # full_scan_workflow
SW = HERE / "sw"
XSA = Path(r"<repo-root>\fpga_ps_m2\ps_m2.xsa")
XILINX = Path(r"D:\Xilinx\2025.1")
VITIS = XILINX / "Vitis"
VIVADO = XILINX / "Vivado"
ARM_GCC = VITIS / "gnu" / "aarch32" / "nt" / "gcc-arm-none-eabi" / "bin"
VITIS_PY = VIVADO / "tps" / "win64" / "python-3.13.0" / "python.exe"
CMAKE = VIVADO / "tps" / "win64" / "cmake-3.24.2" / "bin"
EMP_YRO = None  # set in main


def env_for_vitis() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(VITIS / "data" / "embeddedsw" / "scripts" / "pyesw"),
        str(VITIS / "cli" / "python-packages" / "win64"),
        str(VITIS / "cli" / "python-packages" / "site-packages"),
    ])
    env["PATH"] = os.pathsep.join([
        str(ARM_GCC), str(CMAKE), env.get("PATH", ""), str(VIVADO / "bin"),
    ])
    env["XILINX_VITIS"] = str(VITIS)
    env["XILINX_VIVADO"] = str(VIVADO)
    return env


def run(cmd: list[str], env: dict, cwd: Path | None = None, quiet: bool = False) -> None:
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, env=env, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True)
    if not quiet:
        tail = (r.stdout or "") + (r.stderr or "")
        print("\n".join(tail.splitlines()[-8:]), flush=True)
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        raise SystemExit(f"command failed ({r.returncode}): {cmd[:2]}")


def empyro(args: list[str], env: dict, cwd: Path | None = None) -> None:
    run([str(VITIS_PY), str(EMP_YRO)] + args, env, cwd=cwd)


def sdt(out: Path, env: dict) -> None:
    tcl = out.parent / "sdt_gen.tcl"
    tcl.write_text(
        "set outdir [lindex $argv 1]\n"
        "set xsa [lindex $argv 0]\n"
        "file delete -force $outdir\n"
        "set_dt_param -xsa $xsa -dir $outdir\n"
        "generate_sdt\n",
        encoding="ascii")
    run([str(VIVADO / "bin" / "sdtgen.bat"), str(tcl), str(XSA), str(out)], env)


def patch_user_config(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("set(USER_COMPILE_OPTIMIZATION_LEVEL -O0)",
                        "set(USER_COMPILE_OPTIMIZATION_LEVEL -O2)")
    if "lwip220" not in text:
        text = text.replace("set(USER_LINK_LIBRARIES\n)",
                            "set(USER_LINK_LIBRARIES\nlwip220\nm\n)")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    global EMP_YRO
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=r"<repo-root>\vitis_m2b")
    ap.add_argument("--app-only", action="store_true",
                    help="skip sdtgen/BSP (keep the existing BSP) and rebuild the app")
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    EMP_YRO = VITIS / "data" / "embeddedsw" / "scripts" / "pyesw" / "main.py"

    if not VITIS_PY.exists():
        raise SystemExit(f"missing {VITIS_PY}")
    if not (ARM_GCC / "arm-none-eabi-gcc.exe").exists():
        raise SystemExit(f"missing ARM toolchain at {ARM_GCC}")
    if not XSA.exists():
        raise SystemExit(f"missing {XSA} (build fpga_ps_m2 first)")

    env = env_for_vitis()
    sdt_dir = work / "sdt"
    bsp_dir = work / "bsp"
    app_ws = work / "app"
    py_out = HERE / "build_m2b"

    if not args.app_only:
        sdt(sdt_dir, env)
        if (work / ".repo.yaml").exists():
            os.remove(work / ".repo.yaml")
        empyro(["repo", "-st", str(VITIS / "data" / "embeddedsw")], env, cwd=work)
        if bsp_dir.exists():
            shutil.rmtree(bsp_dir)
        empyro(["create_bsp", "-w", str(bsp_dir), "-s", str(sdt_dir / "system-top.dts"),
                "-p", "ps7_cortexa9_0", "-t", "empty_application"], env, cwd=work)
        empyro(["config_bsp", "-d", str(bsp_dir), "-al", "lwip220"], env, cwd=work)
        empyro(["build_bsp", "-d", str(bsp_dir)], env, cwd=work)

    # ---- application --------------------------------------------------------
    src = app_ws / "src"
    if not (src / "CMakeLists.txt").exists():
        src.mkdir(parents=True, exist_ok=True)
        empyro(["create_app", "-w", str(app_ws), "-s", str(src), "-d", str(bsp_dir),
                "-t", "empty_application", "-n", "m2b_ps"], env, cwd=work)
    # the page is generated from the PC viewer's HTML, never hand-copied
    run([sys.executable, str(SW / "tools" / "gen_page.py")], env)
    for f in sorted(SW.glob("src/*")):
        if f.suffix in (".c", ".h"):
            shutil.copy2(f, src / f.name)
    patch_user_config(src / "UserConfig.cmake")
    empyro(["build_app", "-w", str(app_ws)], env, cwd=work)

    elf = app_ws / "build" / "m2b_ps.elf"
    if not elf.exists():
        raise SystemExit(f"no ELF at {elf}")
    py_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(elf, py_out / "m2b_ps.elf")

    # A raw binary as well: on this board `dow` intermittently times out writing
    # 0x100000 and wedges the PS debug APB, while `mwr -bin -file` + `rwr pc`
    # has been reliable (2026-10-27).  m2b_run.tcl uses the .bin.
    objcopy = ARM_GCC / "arm-none-eabi-objcopy.exe"
    bin_path = py_out / "m2b_ps.bin"
    run([str(objcopy), "-O", "binary", str(elf), str(bin_path)], env, quiet=True)
    words = (bin_path.stat().st_size + 3) // 4
    print(f"\nM2B_BUILD_OK {py_out / 'm2b_ps.elf'} ({elf.stat().st_size} bytes)")
    print(f"M2B_BIN {bin_path} ({bin_path.stat().st_size} bytes, {words} words @ 0x100000)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

