# 证据索引

**用途**：报告里的每个数字，都能在下表找到文件；每条“不能写”的说法，也能找到原因。

**等级**：

- `real`：在本项目硬件上跑出来，有日志/JSON；
- `sim`：RTL 仿真或合成波形；
- `static`：综合/实现/引脚/资源/代码常量；
- `external`：工具/厂商文档。

**根目录**：`<package>`。表中的路径都相对于根目录。

---

## 1. 采集与 DSP

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| 一帧 8192 拍 = 163.84 µs，5 MSPS 下 819 点 | static | `src/rtl/ultrasound_test_core.sv`、`src/rtl/peak_dsp.sv` | 读 `FRAME_CYCLES=8192`、`adc_phase==0` 每 10 拍 |
| TX 8 个 1 MHz 周期 | static | `src/rtl/tx_probe_test.sv` | 计数器/半周期常量 |
| 峰值窗 280–539 = 56–107.8 µs | static | `src/rtl/peak_dsp.sv` | `WIN_START/WIN_END` |
| 40 位字 `{valid,frame,idx,amp}` | static | `src/rtl/peak_dsp.sv`、`src/ps/sw/src/acq.c` | 两边位段一致 |
| 板端 40 位字与参考逐位一致 | real | `data/real/dsp_hw_compare.json`、`data/real/dsp_hw_final1.log`、`dsp_hw_final2.log` | `word_match=true`、`idx_delta=0`、`amp_delta=0` |
| 四轮独立采集 | real | 同上 + `dsp_hw_fixed.log`、`dsp_hw_fixed2.log` | 四个字：`0x8005220783`、`0x8005A30849`、`0x8005900BE6`、`0x80051B07E0` |
| 锁存稳定（一次脉冲连读 4 次不变） | real | `data/real/dsp_stable2.log` | 连读 4 次同字；二次脉冲换帧 |
| 回读 2.48–2.80 ms vs ILA 477–555 ms | real | `data/real/dsp_hw_compare.json` | `vio_read_per_call_ms`、`ila_frame_ms`、`speedup_vs_ila` |
| 压缩比约 68,000:1 | static + real | 342,172 B / 5 B | 342172 ÷ 5 = 68,434 |

**复核命令**：

```powershell
python -c "import json;d=json.load(open('data/real/dsp_hw_compare.json'));print(d['hw_word'],d['ref_word'],d['word_match'],d['idx_delta'],d['amp_delta'],d['speedup_vs_ila'])"
```

---

## 2. PS、帧握手与网络

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| PL 自主触发 90.84–91.05 fps | real | `data/real/_m2b_ps_rate.log` | 30 s 内 seq 差 / 时间 |
| PS 连续读 90.93 fps，`missed=0` | real | `data/real/_m2b_rate.log` | `missed` 字段 |
| 启动丢帧 0（修 arm 顺序后） | real | `data/real/_m2b_rate.log` | 第一秒 `missed` |
| 8192 帧环形缓冲 ≈ 90 s | static | `src/ps/sw/src/model.c`、`M2B_RING_CAP` | 常量 |
| C 算法与 Python 逐字节相等 | real | `data/real/_m2b_alg_gate.txt` | `M2B_ALG_PASS` |
| `/state` 每格 t/r/n 差 <1e-3 | real | `data/real/_m2b_state_gate.txt` | `M2B_STATE_PASS` |
| 页面冒烟 | real | `data/real/_m2b_page_smoke.txt` | `PAGE_SMOKE_PASS frames=928 cells=72 valid=63 rate=90.9` |
| `/state` 60,544 B、`/` 22,211 B | real | `data/real/_m2b_http_state.json`、`_m2b_http_page.html` | 文件大小 |
| 60 次 ping / 45 s 零失败 | real | `data/real/_m2b_ping.log` | 统计 `Reply`/`timeout` |
| 网口证据 | real | `data/real/_m2b_net_evidence.txt` | `ping`、`/api/status`、`/state` |

**复核命令**：

```powershell
Select-String -Path data\real\_m2b_ps_rate.log -Pattern 'fps|seq|missed'
Get-Content data\real\_m2b_alg_gate.txt
Get-Content data\real\_m2b_state_gate.txt
(Get-Item data\real\_m2b_http_state.json).Length
```

---

## 3. 三维模型与重复性

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| 单层 24/24 有效 | real | `data/real/_m2b_scan_1rev_state.json` | `valid_map` 全 1 |
| 三层 72 格/71 有效 | real | `data/real/_m2b_3layer_signed.json` | `cells=72`、`valid_cells=71` |
| 三层 144 顶点/192 面 | real | 同上 | `runs.std.mesh.stats` |
| 六层 141/131、288/480 | real | `data/real/_m2b_6layer.json` | 同上 |
| 3 圈/层 σ=0.4505 mm | real | `data/real/_m2b_std_repeat_20261027_171830.json`、`_m2b_stda_20261027_171830.json`、`_m2b_stdb_20261027_171830.json` | `sigma`、`mean`、`rms`、69 格 |
| 1 圈/层 σ=0.77 mm | real | 历史记录/`_m2b_std_repeat` 对照 | 报告写“1 圈 0.77、3 圈 0.45” |
| 层内中位半径 13.8–14.2 mm | real | 三层/六层 `profile` | `profile[].r` |
| 8/10 层未完成 | real | `data/real/incomplete/`、`_m2b_scan8.log`、`_m2b_scan10.log` | 8 层 JSON 只有 1 有效格；10 层 JSON 截断 |

**复核命令**：

```powershell
python -c "import json;d=json.load(open('data/real/_m2b_3layer_signed.json'));s=d['runs']['std'];print(s['cells'],s['valid_cells'],s['mesh']['stats']);print(d['runs']['std']['profile'])"
python -c "import json;d=json.load(open('data/real/_m2b_6layer.json'));s=d['runs']['std'];print(s['cells'],s['valid_cells'],s['mesh']['stats'])"
python -c "import json;d=json.load(open('data/real/_m2b_std_repeat_20261027_171830.json'));print(len(d['cells']),d['sigma'],d['mean'],d['rms'])"
```

---

## 4. 姿态

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| 716.6 Hz、零空窗 | real | `data/real/f1_pose_samples.txt`、`f1_summary.txt` | `seq` 连续；2 s/1973 样本 |
| 融合延迟 51 拍 | sim | `sim/results/pkg_f1_sim.log` | `LATENCY_MIN=51 LATENCY_MAX=51` |
| RTL vs PC 130 向量逐位 | sim | `sim/results/pkg_f1_sim.log` | `MISMATCHES=0` |
| I2C 9 脉冲恢复 | sim | 同上 | `I2C_RECOVERY_PASS` |
| 65 次 I2C 错误未丢样 | real | `data/real/f1_pose_samples.txt`、`f1_summary.txt` | 日志中的 `err` 计数 |
| 页面 20 Hz、`age_ms<=1` | real | `data/real/f1_peek.txt`、`f1_ping.txt` | `/api/pose` 样本 |
| 5 步验收 4.8/5 | real | `data/real/f1_summary.txt` | 汇总 |

**注意**：716.6 Hz 是 18:51 M3 构建；随包 20:14 版未复测。报告里不写 1 kHz、不写零延迟。

---

## 5. 演示与合成数据

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| 108 点/576 面/0.035 mm | sim | 工作流输出 | 重跑 `run_workflow.py axisym` |
| 4096 点演示点云 | sim | `data/demo/points_*.jsonl` | 读文件头 provenance |

**注意**：这些是 `synthetic`，不是实测声学；真实凸起的量化结果未纳入本仓库。

---

## 6. 构建、资源、引脚

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| M3 资源 6,921/8,214/12.5/18 | static | `build/reports/m3_utilization.rpt` | `Slice LUTs` 等行 |
| M3 WNS +1.399 / WHS +0.053 | static | `build/reports/m3_timing.rpt` | 表头 WNS/WHS |
| M3 位流 SHA256 254C… | static | `board/bitstream/ps_m3_system_wrapper.bit` | `Get-FileHash` |
| 引脚 168→170，只多 T10/T11 | static | `build/reports/m2_io.rpt`、`build/reports/m3_io.rpt` | 脚本 `build/io_pin_diff.tcl` |
| DSP v2 3,522/5,029/12/12、WNS 2.888 | static | `build/reports/dsp_*.rpt` | 同上 |
| `peak_dsp` 239 LUT/190 FF/6 DSP | static | `build/reports/dsp_utilization.rpt` | 层次资源 |

**复核命令**：

```powershell
Get-FileHash -Algorithm SHA256 board\bitstream\ps_m3_system_wrapper.bit
Select-String -Path build\reports\m3_timing.rpt -Pattern 'WNS\(ns\)' -Context 0,2
Select-String -Path build\reports\m3_utilization.rpt -Pattern 'Slice LUTs|Slice Registers|Block RAM Tile|DSPs'
```

---

## 7. 仿真

| 结论 | 等级 | 文件 | 怎么复核 |
|---|---|---|---|
| 峰值 DSP 逐位 + 回绕回归 | sim | `sim/results/pkg_peak_dsp.log` | `PEAK_WORD=8001a503f5`、`STROBES=1`、`WORD_STABLE=1` |
| AXI 帧 + 姿态窗口 | sim | `sim/results/pkg_axi_tb.log` | `TB_PASS`、`AXI_TB_PASS` |
| F1 三组 tb | sim | `sim/results/pkg_f1_sim.log` | `MISMATCHES=0`、`LATENCY=51`、`SIM_ALL_PASS` |

**复核命令**：见 `report/04_reproduction.md` 第 2 节。

---

## 8. 明确不能引用的说法

| 说法 | 为什么不能 | 正确写法 |
|---|---|---|
| “1 kHz 姿态” | 实测 716.6 Hz | “716.6 Hz 采样，20 Hz 页面” |
| “整机 190×” | 171–202× 是单帧回读；整机受电机限制约 3.3 s→2.3 s | “单帧回读 171–202×，整机约 30%” |
| “检出 8 mm 缺陷” | 实物 10 mm 凸起在旧窗下无签名，检出未定量 | “真实凸起待定量” |
| “精度 0.19 mm” | 未做绝对尺寸标定 | “相对半径，未标定” |
| “绝对半径 14.0 mm” | 锚定名义 Ø28，未做平板标定 | “相对半径约 14.0 mm” |
| “20:14 位流已复测” | 只改了排程，未上板 | “18:51 版测 716.6 Hz；20:14 未复测” |
| “临床可用” | 水槽/仿体原理验证 | “原理验证平台，非临床设备” |
| 峰值 DSP 修复前的 `idx=356/416/426/481` | 回绕后反复锁存的废数据 | 已作废，不引用 |

---

## 9. 失败与作废记录

保留这些记录，是为了解释“为什么现在的数字是这样”：

| 记录 | 文件/位置 | 说明 |
|---|---|---|
| 峰值 DSP 回绕 | `data/real/dsp_hw_fixed*.log`、`src/rtl/peak_dsp.sv` 注释 | 修复前字被反复改写 |
| 8 层 JSON 只有 1 有效格 | `data/real/incomplete/_m2b_8layer_partial.json` | 快照不完整，不能当 8 层模型 |
| 10 层 JSON 截断 | `data/real/incomplete/_m2b_10layer_truncated.json` | `curl` 被页面轮询打断 |
| 24 点环少 14.34° | `skill/09_scanning_3d_reconstruction/SKILL.md` | 3933 vs 4096 counts |
| GIC 不确定 | `skill/06_rtl_dsp_pipeline/SKILL.md` | 改轮询兜底 |
| 构建日志不生成 | `skill/05_fpga_capture_bringup/SKILL.md` | `-nolog` 压掉 `-log` |

---

## 10. 一键核对（可选）

```powershell
cd <package>
pwsh -File sim\run_sim.ps1
pwsh -File sim\run_axi_tb.ps1
pwsh -File sim\run_f1_sim.ps1
Get-FileHash -Algorithm SHA256 board\bitstream\ps_m3_system_wrapper.bit
```

四条命令对应“DSP、AXI、姿态、位流哈希”四个门；全部通过，再谈上板。
