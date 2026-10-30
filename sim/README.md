# 仿真

三组 testbench，分别覆盖“DSP 逐位”“AXI 帧/姿态窗口”“F1 姿态链路”。全部在 Vivado 2025.1 的 xsim 上跑过。

---

## 1. 峰值 DSP：`run_sim.ps1`

- **覆盖**：DC 阻断、1 MHz I/Q、10 点滑动和、`|I|+|Q|`、窗内峰值、40 位锁存、停机、单拍 strobe、质心字。
- **输入**：`vectors/frame.csv`（真实 ILA 帧，342,100 B）。
- **判据**：`PEAK_WORD == EXPECT`、`STROBES=1`、`WORD_STABLE=1`、`CENT_STROBES=1`。
- **回绕回归**：tb 在 560 个真实样本后继续喂 66,000 个变化样本；如果 `active` 不停机，`STROBES` 会远大于 1。

```powershell
pwsh -File sim\run_sim.ps1
```

2026-10-27 重跑结果：`PEAK_WORD=8001a503f5 FRAME=0 IDX=421 AMP=1013`、`STROBES=1`、`WORD_STABLE=1`，日志 `results/pkg_peak_dsp.log`。

---

## 2. AXI 帧 + 姿态窗口：`run_axi_tb.ps1`

- **覆盖**：`sel_ext` 自主触发节奏、SEQ、未 ACK 计数、ACK 清零、payload 逐位、姿态窗口 `0x30..0x3C` 一致读、disarm/re-arm、丢帧计数。
- **判据**：最后打印 `TB_PASS` 与 `AXI_TB_PASS`。

```powershell
pwsh -File sim\run_axi_tb.ps1
```

2026-10-27 重跑：PASS 1a–4 全部通过，日志 `results/pkg_axi_tb.log`。

---

## 3. F1 姿态：`run_f1_sim.ps1`

- **覆盖**：I2C bring-up（`WHO_AM_I=0x68`、14 字节 burst）、9 脉冲总线恢复、定点互补滤波与 PC 模型 130 向量逐位、固定 51 拍延迟。
- **判据**：`I2C_RECOVERY_PASS`、`MISMATCHES=0`、`LATENCY_MIN=LATENCY_MAX=51`、`SIM_ALL_PASS`。

```powershell
pwsh -File sim\run_f1_sim.ps1
```

2026-10-27 重跑：`SAMPLES=130 MISMATCHES=0 LATENCY_MIN=51 LATENCY_MAX=51 CYCLES=51`，日志 `results/pkg_f1_sim.log`。

---

## 4. 目录

```
sim/
├─ tb/              # tb_peak_dsp, tb_acq_axi_regs, F1 四个 tb
├─ vectors/         # frame.csv, samples.hex, pose_vectors.txt, demo_pose.csv
├─ results/         # 本次重跑日志 + 历史日志
└─ run_*.ps1        # 三个一键入口（包内相对路径）
```

## 5. 注意

- `run_sim.ps1` 需要 `src/rtl/peak_dsp.sv` 与 `src/rtl/peak_centroid.sv` 一起编译；tb 例化了质心模块。
- 三个脚本默认 Vivado 在 `D:\Xilinx\2025.1\Vivado\bin`，可用 `$env:VIVADO_BIN` 覆盖。
- 仿真通过 ≠ 上板通过；上板判据见 `board/README.md`。
