# 复现说明：从零到一次完整扫描

**目标**：让一个没有参与过本项目的队伍，在一台 Windows 机器上，按本文顺序复现“仿真 → 构建 → 上板 → 扫描 → 建模 → 异常检测”的主链路。

**先说明三类复现**：

| 类型 | 需要什么 | 能复现什么 |
|---|---|---|
| A. 纯软件 | Python 3.12+ | 全流程仿真、报告插图 |
| B. 仿真 | Vivado 2025.1 | 峰值 DSP、AXI 帧/姿态、F1 姿态三组 tb |
| C. 上板 | Zynq-7020 板 + ADC/探头/电机/水槽 | 90.9 fps 采集、三层/六层模型、姿态联动 |

本文把 A/B 写成“可照着敲”，C 写成“检查点 + 判据”，因为上板受硬件状态影响，不能保证一次成功。

---

## 0. 环境

### 0.1 软件

| 工具 | 版本 | 用途 |
|---|---|---|
| Vivado | 2025.1（Build 6140274） | 综合/实现/仿真/xsdb |
| Vitis | 2025.1 | PS BSP/固件（可选，包内已有 ELF/BIN） |
| Python | 3.12+（本项目验证 3.12.14 / 3.14.7） | 主机算法、报告图 |
| Node.js | 18+ | 页面离线冒烟（可选） |
| PowerShell | 7 或 5.1 | 脚本入口 |

Python 依赖只有两个：

```
numpy>=1.24,<3
matplotlib>=3.6,<4
```

安装：

```powershell
cd <package>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING='utf-8'
$env:MPLBACKEND='Agg'
```

### 0.2 硬件（上板才需要）

| 件 | 型号/参数 | 说明 |
|---|---|---|
| 主板 | 正点原子启明星 ZYNQ7020（XC7Z020CLG400-2I） | PL 50 MHz，PS ARM A9 |
| ADC | ATK-MO1030D V1.2，双路 10 bit，5 MSPS | 两路相减得 11 bit diff |
| 模拟前端 | AD8331 可变增益 | 接收链 |
| 发射驱动 | TC4420 | 1 MHz、8 周期 |
| 探头 | 1 MHz 水浸，一发一收 | V 形布置 |
| 电机 | 28BYJ-48 ×2 + ULN2003 | 旋转 + 升降 |
| 姿态 | MPU6050（GY-521） | I2C 400 kHz，3.3 V |
| 水槽/目标 | 圆柱 Ø28×32、锥台、台阶轴 | 3D 打印件 |

> 接线以 `src/constraints/*.xdc` 为准；I2C 是 `scl T10`、`sda T11`，`sys_clk U18`、`sys_rst_n N16`。上电前先断电接线，确认 3.3 V 与共地。

---

## 1. 纯软件复现（10 分钟，不需要板子）

### 1.1 报告插图

```powershell
python report\assets\make_figures.py
```

会重新生成 `report/assets/fig_*.png`。需要 `Microsoft YaHei` 或 `SimHei` 字体（Windows 自带）。

### 1.2 全流程仿真（108 点）

```powershell
python src\host\run_workflow.py simulate --out build\output\sim_full
python src\host\run_workflow.py axisym --object cylinder --out build\output\cyl
```

期望：108/108 合格、576 三角面、自检圆心偏差 0.035 mm（合成）。这些数字只证明流程，不证明真实声学。

---

## 2. 仿真复现（Vivado 2025.1）

三个脚本都在 `sim/`，默认路径已改成包内相对路径；Vivado 路径可用 `$env:VIVADO_BIN` 覆盖。

### 2.1 峰值 DSP 回归

```powershell
pwsh -File sim\run_sim.ps1
```

期望：

```
EXPECT  : word=0x8001A503F5 ...
PEAK_WORD=8001a503f5 FRAME=0 IDX=421 AMP=1013
STROBES=1 WORD_AT_END=8001a503f5 WORD_STABLE=1
CENT_IDX=413 ... CENT_STROBES=1
```

**判据**：`PEAK_WORD == EXPECT`、`STROBES=1`、`WORD_STABLE=1`。输入是 `sim/vectors/frame.csv`（真实 ILA 帧）。

### 2.2 AXI 帧 + 姿态窗口

```powershell
pwsh -File sim\run_axi_tb.ps1
```

期望最后：

```
TB_PASS
AXI_TB_PASS
```

覆盖：触发节奏、SEQ、missed、ACK、payload 逐位、姿态窗口一致读、disarm/re-arm、丢帧计数。

### 2.3 F1 姿态三组 tb

```powershell
pwsh -File sim\run_f1_sim.ps1
```

期望最后：

```
SAMPLES=130 MISMATCHES=0 LATENCY_MIN=51 LATENCY_MAX=51 CYCLES=51
POSE_FUSION_PASS n=130 latency=51 cycles
SIM_ALL_PASS  (tb_f1, tb_i2c_recovery, tb_pose_fusion)
```

**判据**：`MISMATCHES=0`、`LATENCY=51`、`I2C_RECOVERY_PASS`。

### 2.4 本次包内实测记录

2026-10-27 20:58–20:59 在三组脚本上重跑，日志在 `sim/results/pkg_*.log`：

| 脚本 | 结果 |
|---|---|
| `run_sim.ps1` | `PEAK_WORD=8001a503f5`，`STROBES=1`，`WORD_STABLE=1` |
| `run_axi_tb.ps1` | `TB_PASS` / `AXI_TB_PASS`（全部 PASS 1a–4） |
| `run_f1_sim.ps1` | `MISMATCHES=0`，`LATENCY=51`，`SIM_ALL_PASS` |

---

## 3. 构建复现

### 3.1 M3 位流

```powershell
$vivado = 'D:\Xilinx\2025.1\Vivado\bin\vivado.bat'
& $vivado -mode batch -nojournal -notrace `
  -source build\build_ps_m3_pkg.tcl `
  -log build\output\build_m3.log
```

**判据**：

```
M3_BUILD_DONE <package>\build\output\fpga_ps_m3
WNS 1.399
WHS 0.053
M3_PIN_DIFF_OK
=== EXIT CODE: 0 ===
```

产物：`build/output/fpga_ps_m3/ps_m3.runs/impl_1/system_wrapper.bit`、`ps_m3.xsa`、`ps7_init.tcl`、`{utilization,timing,io}.rpt`。

> 不要加 `-nolog`；它会把 `-log` 压掉。构建目录必须不存在；路径不要带中文。

### 3.2 DSP 位流（可选）

```powershell
& $vivado -mode batch -nojournal -notrace -source build\build_dsp_pkg.tcl
```

产物 `build/output/fpga_dsp_v2/merged_top.bit`。这是 M2b 的采集 + DSP 基线。

### 3.3 PS 固件（可选）

包内已有 `board/firmware/m2b_ps.elf/.bin`；要重编：

```powershell
$env:XILINX_ROOT='D:\Xilinx\2025.1'
python src\ps\build_m2b.py
```

需要 Vitis 2025.1 的 `gnu/aarch32/nt/gcc-arm-none-eabi`。产物落到 `build/output/firmware/`。

---

## 4. 上板复现

### 4.1 连接与上电

1. 断电，接好 ADC/探头/电机/MPU6050；
2. 上电，确认 JTAG 能识别 `xc7z020`；
3. PC 以太网设为 `192.168.1.2/24`，网关留空；
4. 不要在同一上电周期反复加载；失败就断电重来。

### 4.2 加载

```powershell
D:\Xilinx\2025.1\Vivado\bin\xsdb.bat -eval "source <package>/board/tcl/load_m3_pkg.tcl"
```

**判据**：

```
M3_PL_PROGRAMMED
M3_PS7_INIT_OK
M3_DDR_OK
M3_BIN_WRITTEN (...)
M3_RUN_STARTED
```

失败信息：`M3_DDR_NOT_WRITABLE` / `M3_RUN_PS_WEDGED` → 断电重来。

### 4.3 验网络

```powershell
ping -S 192.168.1.2 192.168.1.10
curl http://192.168.1.10/api/status
curl http://192.168.1.10/state
curl http://192.168.1.10/
```

**判据**：`ping` 4/4；`/api/status` 返回 `{"ok":true}`；`/state` 是合法 JSON 且 `frames` 每秒涨约 90；`/` 返回约 22 KB 页面。

### 4.4 转一圈

```powershell
D:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -nojournal -nolog -notrace `
  -source <package>\board\tcl\m2b_scan.tcl `
  -tclargs --revs 1 --period 125000 --layers 1
```

**判据**：`/state` 从 1 格变成 24 格，`az` 为 0,15,…,345。

### 4.5 三层 / 六层

```powershell
... -tclargs --revs 1 --period 125000 --layers 3 --lift-delta 4096 --restore
... -tclargs --revs 1 --period 125000 --layers 6 --lift-delta 4096 --restore
```

**判据**：三层 `72 格/71 有效`、`144 顶点/192 面`；六层 `141/131`、`288/480`。如果返回空模型，先查层索引是否按绝对位置量化，再查环形缓冲是否已满。

### 4.6 姿态

```powershell
curl http://192.168.1.10/api/pose
```

**判据**：`ok:1`、`err=0`、`age_ms<=1`；手转模块，页面模型同步旋转，同时 `frames` 继续增长。

> 不要期望 1 kHz：实测 716.6 Hz；页面 20 Hz。

---

## 5. 离线建模与异常检测

### 5.1 从一次扫描到模型

```powershell
python src\host\run_scan.py --run <run_dir> --out <model_dir>
```

或走工作流：

```powershell
python src\host\run_workflow.py ingest --session <session> --group <group> --out <out>
python src\host\run_workflow.py axisym --object cylinder --out <out>
```

产物：`points.csv`、`profile.csv`、`mesh.ply`、`scan_report.json`。

### 5.2 质量门

| 门 | 判据 |
|---|---|
| SNR | ≥ 15 dB |
| 次峰比 | ≤ 0.6 |
| 边缘峰 | 不接受窗边缘 |
| 多帧一致 | ≥ 2/3 帧合格 |
| 重复性 | MAD ≤ 0.6 µs |

不过门的点不定位、不补点；报告里保留拒收原因。

### 5.3 真实凸起检测

拿到“标准件”和“贴凸起件”两次扫描后：

1. 两次的 `t_eff`、增益、水位、探头姿态保持一致；
2. 同件两遍算 σ；
3. `Δr = r_test − r_std`，阈值 `max(3σ, 1.5 mm)`；
4. 连通域聚类，输出中心/高度/面积；
5. 用游标卡尺或 3D 打印真值核对。

真实 10 mm 凸起在旧 10 µs 窗下无签名，说明窗和阈值都要按实测重定。

---

## 6. 常见失败与定位

| 现象 | 先查 | 判据/动作 |
|---|---|---|
| `M3_BUILD_DONE` 没有 | 日志是否存在；`-nolog` 是否压掉 `-log` | 去掉 `-nolog`；看 `impl_1/runme.log` |
| 引脚 diff 打印标题就结束 | `io.rpt` 格式；正则 | 解析不到必须 error，不能当通过 |
| `M3_RUN_PS_WEDGED` | DAP/APU target | 断电重来 |
| `M3_DDR_NOT_WRITABLE` | 旧固件是否还在跑 | 先 `rst -processor`，再 `ps7_init` |
| `ping` 不通 | 网线/IP/PHY | 先 `ping` 再 `curl`；不要继续扫 |
| `/state` 空 | 层索引/环形缓冲 | 看 `layers` 与 `frames` |
| 模型是螺旋 | 24 点环是否闭合 | 每层补 `rot 163` |
| 缺陷看不见 | 窗是否 66–84 µs；连续性滤波 | 放宽窗、关连续性 |
| 姿态字错位 | 字段位宽/拼接 | 先读 `WHO_AM_I`，再逐位比对 |
| 仿真过、上板错 | 是否只喂了一帧 | 喂 >65,536 样本，查回绕 |

---

## 7. 复现边界

- A/B 类可以在没有硬件的情况下完整重跑；本文的数字来自 2026-10-27 的包内实测/仿真。
- C 类依赖探头、水位、目标、机械状态；同一命令在不同装置上不会得到同样的半径。
- 真实四件全高度扫描、真实凸起检出尚未纳入本仓库；绝对尺寸标定仍未完成，不要用仿真数字替代。
- 包内位流是 20:14 重建版；姿态 716.6 Hz 是在 18:51 同源构建上测的，20:14 版未复测。
