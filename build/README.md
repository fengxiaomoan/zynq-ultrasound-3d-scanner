# 构建

---

## 1. 入口

| 脚本 | 产物 | 说明 |
|---|---|---|
| `build_ps_m3_pkg.tcl` | `output/fpga_ps_m3/` | M3 位流、XSA、`ps7_init.tcl`、资源/时序/引脚报告 |
| `build_dsp_pkg.tcl` | `output/fpga_dsp_v2/` | DSP 位流（M2b 基线） |
| `../src/ps/build_m2b.py` | `output/firmware/` | PS ELF/BIN（需要 Vitis + arm-none-eabi GCC） |
| `build_all.ps1` | 以上全部 | 一键顺序执行，失败即停 |

```powershell
pwsh -File build\build_all.ps1
```

单独跑：

```powershell
& 'D:\Xilinx\2025.1\Vivado\bin\vivado.bat' -mode batch -nojournal -notrace `
  -source build\build_ps_m3_pkg.tcl -log build\output\build_m3.log
```

---

## 2. 门禁

| 门 | 判据 | 失败动作 |
|---|---|---|
| 构建完成 | `M3_BUILD_DONE` | 看 `impl_1/runme.log` |
| 时序 | `WNS >= 0`、`WHS >= 0`、失败端点 0 | 不改约束凑过，先查路径 |
| DRC | 0 error；Critical Warning 逐条看 | 记录，不忽略 |
| 引脚 | 168→170，只多 `scl T10`/`sda T11`，无 LOST/换脚 | `io_pin_diff` 直接 error |
| 位流 | SHA256 写进 `reports/resource_summary.md` | 重算并核对 |

`io_pin_diff.tcl` 解析不到任何行会 `error`，不会把空表当“没有差异”。

---

## 3. 报告

`reports/` 下：

- `m3_utilization.rpt`、`m3_timing.rpt`、`m3_io.rpt`、`m3_drc_routed.rpt`；
- `dsp_utilization.rpt`、`dsp_timing.rpt`、`dsp_drc.rpt`、`dsp_cdc.rpt`；
- `m2_utilization.rpt`、`m2_timing.rpt`、`m2_io.rpt`（基线）；
- `resource_summary.md`：一页看完全部数字与哈希。

---

## 4. 注意

- 构建目录必须不存在；脚本会删/拒绝已存在目录。
- 路径不要有中文/空格；Vivado 需要写 `%APPDATA%\Xilinx`，沙箱里可能停在 `tclapp::load_apps failed`。
- **不要同时用 `-nolog` 和 `-log`**：`-nolog` 会把日志压掉。
- `build_ps_m3_pkg.tcl` 只改了路径根，流程与 `build/upstream/build_ps_m3.tcl` 一致；两者如有差异，以 `upstream/` 为准并同步。
- M3 随包位流是 20:14 重建版（6,921 LUT / WNS 1.399）；18:51 验收版（6,907 / 2.048）已被覆盖。
