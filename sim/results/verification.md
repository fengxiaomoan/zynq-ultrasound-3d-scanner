# 包内仿真复跑记录

**时间**：2026-10-27 20:58–20:59（Asia/Shanghai）  
**工具**：Vivado Simulator 2025.1（xsim v2025.1，SW Build 6140274）  
**位置**：`<package>/sim`，路径已改成包内相对路径。

---

## 1. 峰值 DSP

命令：

```powershell
pwsh -File sim\run_sim.ps1
```

结果：

```
frame   : sim\vectors\frame.csv
samples : 560  first=28 max=244 min=-251
EXPECT  : word=0x8001A503F5  frame=0  idx=421  amp=1013  t=84.2 us
CENT_EXPECT : idx=413 sum_w=26764 sum_kw=11077061  t=82.6 us  base=431
...
PEAK_WORD=8001a503f5 FRAME=0 IDX=421 AMP=1013
STROBES=1 WORD_AT_END=8001a503f5 WORD_STABLE=1
CENT_IDX=413 CENT_SUM_W=26764 CENT_SUM_KW=11077061 CENT_STROBES=1
```

判据全部满足：`PEAK_WORD == EXPECT`、`STROBES=1`、`WORD_STABLE=1`、`CENT_STROBES=1`。日志：`results/pkg_peak_dsp.log`。

> 这次用的 `sim/vectors/frame.csv` 与 2026-10-25 记录的 `0x80011B07E0` 不是同一帧；`EXPECT` 由同一份 CSV 的参考模型算出，逐位一致才是判据。

---

## 2. AXI 帧 + 姿态窗口

命令：

```powershell
pwsh -File sim\run_axi_tb.ps1
```

结果（节选）：

```
PASS 1a: sel_ext=1 tx_en=1
PASS 1b: trigger cadence ~100 cycles (10 ms)
PASS 2a: SEQ is the last captured frame index
PASS 2b: unacknowledged frames are counted (5)
PASS 2b2: ACK clears pending, keeps cumulative missed_cnt=5
PASS 2c-e: payload bit-exact (peak 40b, cent 56b, pose 32b)
PASS 2f: pose window coherent and independent of the frame latch
PASS 2f2: pose channel updates (seq 8)
PASS 3a: disarmed stops triggering
PASS 3c: re-arm resets the cumulative miss counter
PASS 3b: re-arm resumes triggering
PASS 4: lost frames are counted and flagged
TB_PASS
AXI_TB_PASS
```

日志：`results/pkg_axi_tb.log`。

---

## 3. F1 姿态三组 tb

命令：

```powershell
pwsh -File sim\run_f1_sim.ps1
```

结果（节选）：

```
LINE_CHECK_HIGH: scl=1 sda=1
WHO_OK: 0x68 at pc=8
DATA_OK: ax=0x1234
PASS: who=0x68 ax=1234 ... samples=1
TIMEOUT_SEEN rises=0 busy=1
RECOVERY_DONE pulses=10 (>=9) err=1 busy=0 scl_oe=0 sda_oe=0
I2C_RECOVERY_PASS pulses=11
SAMPLES=130 MISMATCHES=0 LATENCY_MIN=51 LATENCY_MAX=51 CYCLES=51
POSE_FUSION_PASS n=130 latency=51 cycles
SIM_ALL_PASS  (tb_f1, tb_i2c_recovery, tb_pose_fusion)
```

日志：`results/pkg_f1_sim.log`。

---

## 4. 说明

- 三组脚本均已改为包内相对路径；Vivado 可用 `$env:VIVADO_BIN` 覆盖。
- `run_sim.ps1` 现在同时编译 `peak_dsp.sv` 与 `peak_centroid.sv`，因为 tb 例化了质心模块。
- 仿真通过 ≠ 上板通过；上板判据见 `board/README.md`。
