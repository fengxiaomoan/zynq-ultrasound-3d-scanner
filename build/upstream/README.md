# 原始构建脚本（仅参考）

这些是项目现场使用的原始 Tcl/Python，保留了绝对路径（`D:/daxue/FPGA/...`）。

**不要直接在新机器上执行**。包内可用的是：

- `../build_ps_m3_pkg.tcl`（M3，相对路径）；
- `../build_dsp_pkg.tcl`（DSP，相对路径）；
- `../build_all.ps1`（一键）；
- `../../src/ps/build_m2b.py`（PS 固件，相对路径 + `XILINX_ROOT`）。

保留这些文件是为了对照“当时怎么构建、报告里的数字从哪来”。两边如有流程差异，以 `upstream/` 为准并同步到 `_pkg` 版本。
