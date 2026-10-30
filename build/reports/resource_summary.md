# 构建与资源摘要

**工具**：Vivado 2025.1（Build 6140274，2025-05-22）  
**器件**：`xc7z020clg400-2`（7z020-clg400，-2 speed grade）  
**主时钟**：`sys_clk` 50 MHz（20 ns），ADC 5 MSPS  

---

## 1. 随包位流

| 产物 | 路径 | 大小 | SHA256 |
|---|---|---:|---|
| M3 系统位流 | `board/bitstream/ps_m3_system_wrapper.bit` | 4,045,690 B | `254C3AA69264AC7EA80435549E038D26E2CEB2825749595A929C4935E0F1459C` |
| M3 调试探针 | `board/bitstream/ps_m3_system_wrapper.ltx` | 112,586 B | 见包清单 |
| DSP 位流（M2b 基线） | `board/bitstream/dsp_merged_top.bit` | 4,045,686 B | `0D3D8C0063AFBF5C84CFE976C89241B685B39C5FC756FA945BE87E3B538ECDD2` |
| DSP 调试探针 | `board/bitstream/dsp_merged_top.ltx` | 85,478 B | 见包清单 |
| 硬件平台 | `board/xsa/ps_m3.xsa` | 288,813 B | `E55E516E823DA30B1BA05FE306B87B7072AB18ABB7B6DB1DC84081A84115A234` |
| PS 初始化 | `board/xsa/ps7_init.tcl` | 31,277 B | 见包清单 |
| PS 固件 ELF | `board/firmware/m2b_ps.elf` | 1,049,448 B | `E528106AD4AB55235F86F18FFB0BA1CF43E9DB80E3572DE8C5D0373A63016141` |
| PS 固件 BIN | `board/firmware/m2b_ps.bin` | 231,044 B | `6F89CB999875FCA047C03C4D5F6D9F1212694071AC72D0A59CDE32A942EF02CC` |

> 构建谱系：M3 先在 2026-10-27 18:51 构建（6,907 LUT / 8,182 FF / WNS 2.048 / `549DEC…`），随后为姿态采样排程重建为 20:14 版（本表，`254C…`）。随包以 20:14 版为准；板上 716.6 Hz 姿态是在 18:51 同源构建上测的，20:14 版未重新上板复测。

---

## 2. 资源对比

| 版本 | LUT | FF | BRAM Tile | DSP48 | 说明 |
|---|---:|---:|---:|---:|---|
| 旧合并工程 | 3,179 | 4,633 | 12 | 6 | 仅采集 + 电机 |
| DSP v2 | 3,522 | 5,029 | 12 | 12 | + 峰值 DSP + VIO |
| M2b | 4,788 | 7,011 | 12.5 | 14 | + PS 帧通路 + AXI |
| M3（随包） | 6,921 | 8,214 | 12.5 | 18 | + MPU6050/姿态融合 |

M3 相对 M2b：**LUT +2,133、FF +1,203、BRAM +0、DSP +4**。

`peak_dsp` 单模块：**239 LUT / 190 FF / 6 DSP / 41 SRL**。相对旧合并工程 +343 LUT（+10.8%）、+396 FF、+0 BRAM、+6 DSP。

---

## 3. 时序

| 项 | M3（随包） | DSP v2 |
|---|---:|---:|
| WNS | +1.399 ns | +2.888 ns |
| WHS | +0.053 ns | +0.048 ns |
| WPWS | +8.870 ns | +8.870 ns |
| 失败端点 | 0 | 0 |
| 约束 | `sys_clk` 50 MHz | `sys_clk` 50 MHz |

按 20 ns − 1.399 ns 估算，M3 等效最高时钟约 **53.8 MHz**（估算，不是实测 Fmax）。M3 的 critical path 在姿态融合的 `acc_roll` 乘法链（19 级逻辑，含 2 个 DSP48）。

---

## 4. 引脚

| 版本 | 引脚数 | 相对 M2b 变化 |
|---|---:|---|
| fpga_ps_m2 | 168 | 基线 |
| fpga_ps_m3 | 170 | 只多 `scl T10`、`sda T11`；无 LOST、无换脚 |

`build/reports/m2_io.rpt` 是基线，`build/build_ps_m3_pkg.tcl` 里的 `io_pin_diff` 会在解析不到或出现非预期差异时直接报错。

---

## 5. 构建命令（包内相对路径）

```powershell
# 1) M3 位流 + XSA + 报告（约 10 分钟）
D:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -nojournal -notrace `
  -source build\build_ps_m3_pkg.tcl `
  -log build\output\build_m3.log

# 2) DSP 位流（可选，M2b 基线）
D:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -nojournal -notrace `
  -source build\build_dsp_pkg.tcl `
  -log build\output\build_dsp.log

# 3) PS 固件（需要 Vitis 2025.1 + arm-none-eabi GCC）
python src\ps\build_m2b.py
```

构建脚本只改了路径根，流程与 `src/ps/build_ps_m3.tcl` 一致。构建前确认：

- 构建目录不存在（脚本会删/拒绝已存在目录）；
- 路径无中文/空格；
- Vivado 能写 `%APPDATA%\Xilinx`（沙箱里可能失败）；
- 不要同时用 `-nolog` 和 `-log`。

---

## 6. 报告文件

| 文件 | 内容 |
|---|---|
| `build/reports/m3_utilization.rpt` | M3 资源 |
| `build/reports/m3_timing.rpt` | M3 时序 |
| `build/reports/m3_io.rpt` | M3 引脚 |
| `build/reports/m3_drc_routed.rpt` | M3 DRC |
| `build/reports/dsp_timing.rpt` | DSP v2 时序 |
| `build/reports/dsp_utilization.rpt` | DSP v2 资源 |
| `build/reports/dsp_drc.rpt` | DSP v2 DRC |
| `build/reports/dsp_cdc.rpt` | DSP v2 CDC |
| `build/reports/m2_utilization.rpt` | M2b 基线资源 |
| `build/reports/m2_timing.rpt` | M2b 基线时序 |
| `build/reports/m2_io.rpt` | M2b 基线引脚 |
