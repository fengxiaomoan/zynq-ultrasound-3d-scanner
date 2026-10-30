# 上板工程与实测输出

**板卡**：正点原子启明星 ZYNQ7020（ATK-DF7020 V2.3.2），器件 `XC7Z020CLG400-2`  
**时钟**：PL `sys_clk` 50 MHz（U18），ADC 5 MSPS  
**加载**：JTAG（xsdb），不使用 SD/QSPI。

---

## 1. 随包产物

| 产物 | 路径 | 大小 | SHA256 |
|---|---|---:|---|
| M3 位流 | `bitstream/ps_m3_system_wrapper.bit` | 4,045,690 B | `254C3AA69264AC7EA80435549E038D26E2CEB2825749595A929C4935E0F1459C` |
| M3 探针 | `bitstream/ps_m3_system_wrapper.ltx` | 112,586 B | 见 `manifest.json` |
| DSP 位流 | `bitstream/dsp_merged_top.bit` | 4,045,686 B | `0D3D8C0063AFBF5C84CFE976C89241B685B39C5FC756FA945BE87E3B538ECDD2` |
| DSP 探针 | `bitstream/dsp_merged_top.ltx` | 85,478 B | 见 `manifest.json` |
| 硬件平台 | `xsa/ps_m3.xsa` | 288,813 B | `E55E516E823DA30B1BA05FE306B87B7072AB18ABB7B6DB1DC84081A84115A234` |
| PS 初始化 | `xsa/ps7_init.tcl` | 31,277 B | 见 `manifest.json` |
| PS 固件 ELF | `firmware/m2b_ps.elf` | 1,049,448 B | `E528106AD4AB55235F86F18FFB0BA1CF43E9DB80E3572DE8C5D0373A63016141` |
| PS 固件 BIN | `firmware/m2b_ps.bin` | 231,044 B | `6F89CB999875FCA047C03C4D5F6D9F1212694071AC72D0A59CDE32A942EF02CC` |

> M3 位流是 2026-10-27 20:14 重建版（6,921 LUT / WNS 1.399）。18:51 验收版（6,907 LUT / WNS 2.048 / `549DEC…`）已被覆盖；716.6 Hz 姿态是在 18:51 同源构建上测的，20:14 版未复测。

---

## 2. 加载

```powershell
D:\Xilinx\2025.1\Vivado\bin\xsdb.bat -eval "source <package>/board/tcl/load_m3_pkg.tcl"
```

期望输出：

```
M3_PL_PROGRAMMED
M3_CORE_STOPPED
M3_PS7_INIT_OK
M3_DDR_OK
M3_BIN_WRITTEN (...)
M3_RUN_STARTED
```

失败时：

| 信息 | 含义 | 动作 |
|---|---|---|
| `M3_RUN_PS_WEDGED` | 没有 APU target | 断电重来 |
| `M3_DDR_NOT_WRITABLE` | DDR 写不进去 | 先 `rst -processor` 再 `ps7_init`；仍失败就断电 |
| `M3_RUN_NO_BIT/BIN/PSINIT` | 文件缺失 | 检查包是否完整 |
| `DONE PIN is not HIGH` | 配置失败 | 断电、不要先 `rst -system` |

**规则**：加载前先断电；加载完立刻 `ping`，不通就断电重来，不要在坏状态继续扫。

---

## 3. 验证

```powershell
ping -S 192.168.1.2 192.168.1.10
curl http://192.168.1.10/api/status
curl http://192.168.1.10/state
curl http://192.168.1.10/
```

预期：

- `ping` 4/4；
- `/api/status` → `{"ok":true}`；
- `/state` 合法 JSON，`frames` 每秒涨约 90；
- `/` 约 22 KB 页面；
- `/api/pose` → `ok:1`、`err=0`、`age_ms<=1`。

---

## 4. 扫描

```powershell
D:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -nojournal -nolog -notrace `
  -source <package>\board\tcl\m2b_scan.tcl `
  -tclargs --revs 1 --period 125000 --layers 3 --lift-delta 4096 --restore
```

- `--period 125000` ≈ 35.16°/s；
- `--layers 3` 跑 z=+2/0/−2；
- `--lift-delta 4096` = 2 mm/层；
- `--restore` 结束后回程。

**判据**：

| 项 | 期望 |
|---|---|
| 单层 `/state` | 24 格，`az=0,15,…,345` |
| 三层 | 72 格 / 71 有效；144 顶点 / 192 面 |
| 六层 | 141 格 / 131 有效；288 顶点 / 480 面 |
| 帧率 | 90.8–91.1 fps |
| `missed` | 0 |

---

## 5. 实测输出摘要

| 项 | 值 | 文件 |
|---|---:|---|
| PL 自主触发 | 90.84–91.05 fps | `logs/_m2b_ps_rate.log` |
| PS 连续读 | 90.93 fps，`missed=0` | `logs/_m2b_rate.log` |
| 单帧回读 | 2.48–2.80 ms | `logs/dsp_hw_compare.json` |
| ILA 单帧 | 477–555 ms | 同上 |
| 加速比 | 171–202× | 同上 |
| 三层模型 | 72/71，144/192 | `../data/real/_m2b_3layer_signed.json` |
| 六层模型 | 141/131，288/480 | `../data/real/_m2b_6layer.json` |
| 重复性（3 圈/层） | σ=0.4505 mm | `../data/real/_m2b_std_repeat_20261027_171830.json` |
| 姿态 | 716.6 Hz，51 拍 | `logs/f1_summary.txt` |

---

## 6. 引脚

| 信号 | 引脚 | 说明 |
|---|---|---|
| `sys_clk` | U18 | 50 MHz |
| `sys_rst_n` | N16 | 低有效 |
| `scl` | T10 | MPU6050 I2C，LVCMOS33 |
| `sda` | T11 | MPU6050 I2C，LVCMOS33 |

完整引脚见 `../build/reports/m3_io.rpt`；M2b 基线见 `../build/reports/m2_io.rpt`。M3 相对 M2b 只多 T10/T11，无 LOST、无换脚。

---

## 7. 目录

```
board/
├─ bitstream/      # M3 + DSP 位流/ltx
├─ xsa/            # ps_m3.xsa + ps7_init.tcl
├─ firmware/       # 预编译 ELF/BIN
├─ tcl/
│  ├─ load_m3_pkg.tcl   # 包内相对路径，推荐
│  ├─ m2b_scan.tcl      # 电机扫描（已改为包内路径）
│  └─ upstream/         # 原始脚本（路径已替换为 `<repo-root>`，仅参考）
└─ logs/           # 实测日志副本
```

`upstream/` 里的脚本是现场原始版本，仓库中已把本机绝对路径统一替换为 `<repo-root>`，其余保持原样，用于对照“当时怎么跑的”；不要直接在新机器上执行，用包内 `load_m3_pkg.tcl` 与 `m2b_scan.tcl`。
