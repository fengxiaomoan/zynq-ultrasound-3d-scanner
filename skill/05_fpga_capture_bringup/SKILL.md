---
name: fpga_capture_bringup
description: 'Use when bringing up a new FPGA board with an external ADC or high-speed capture, and when the build itself must be auditable: prove clock/reset, ADC timing, frame state machine, ILA alignment, then gate the build on timing, DRC, pin diff and bitstream hash. Covers the traps: sampling the old ADC word, treating ILA depth as frame length, -nolog swallowing -log, and a pin-diff gate that passes on an empty table.'
---

# FPGA 采集 bring-up 与可复现构建

## 适用范围

- 新板卡第一次接外部 ADC（单路/双路），要证明“采到的是真实样本”；
- 采集核有帧状态机（帧长、触发、TX、OTR），需要证明帧号连续、窗口对齐；
- 作品要提交源码、构建脚本、报告和位哈希，需要“这份位流 = 这份源码”；
- 适用于任何“ADC + FPGA + 帧缓冲”的采集，不限于超声。

## 输入

- 板卡原理图/引脚表：`sys_clk`、复位、ADC 数据/时钟/OTR；
- ADC 手册：位宽、采样率、输出时序（tOD）、时钟极性；
- 采集核参数：`FRAME_CYCLES`、每样本分频、TX 周期数、锁定时间；
- 一个可写、纯 ASCII 的构建目录。

## 使用方法

### 1. 先证明时钟和复位

1. 约束 `sys_clk` 到实际晶振频率（本项目 50 MHz，U18）；
2. 复位异步断言、两级同步释放；
3. 用 ILA 看 `sys_clk` 与 `rst_n`；不要先看 ADC 数据。

**判据**：`rst_n` 在 2 个时钟内稳定为 1。

### 2. 让 ADC 时钟自由跑

1. ADC 时钟由 `sys_clk` 分频（本项目 50 MHz / 10 = 5 MSPS，`adc_phase` 0..9）；
2. 在 `adc_phase==0` 采**上一拍**的 ADC 输出（新数据在 tOD 之后才有效）；
3. 先不发射，只抓静态噪声。

**判据**：原始码不是全 0/全 1023；`diff` 有 ±几个 count 噪声；OTR=0。

### 3. 加帧状态机

1. `capture_start` 只在 `ctrl[0]` 上升沿、且 `!frame_active && !tx_busy` 时发一拍；
2. `frame_index` 0..`FRAME_CYCLES-1`，到顶 `frame_done` 一拍；
3. `frame_count` 每帧 +1，和帧内索引分开；
4. TX 锁定时间 > 帧长（本项目 500,000 拍 = 10 ms）。

**判据**：连续 20 帧，`frame_count` 严格 +1，`rejected=0`。

### 4. 对齐 TX 与采样窗

1. `tx_burst` 在 `capture_start` 同拍/下一拍启动；
2. 记录“TX 起点到第一个有效样本”的固定拍数；
3. 峰值窗用样本号表示，`t_us = idx × 0.2`（5 MSPS）。

**判据**：同一配置下拍数每次相同；窗口覆盖预期回波。

### 5. 用 ILA 导出并离线复算

1. 探针顺序固定：`sample1, sample2, diff, otr, tx_burst, capture_start, frame_active, frame_index, sample_valid, rst_n`；
2. 导出 CSV 后先查：有效行、`frame_index` 单调、`otr` 全 0；
3. 用同一解码脚本复算 `diff = ad1 - ad2`，逐行比。

**判据**：有效样本数 = 帧长/分频（本项目 8192/10 ≈ 819）；`diff` 逐行一致。

### 6. 最后才谈“声学”

数字链路通过 ≠ 收到回波。先做“无目标/有目标”对照：移走目标，窗内峰值应显著下降；再把探头对准平板，峰值位置应随距离移动。

### 7. 构建门

| 门 | 判据 | 失败动作 |
|---|---|---|
| 构建完成 | `M3_BUILD_DONE` | 看 `impl_1/runme.log` |
| 时序 | WNS/WHS ≥ 0，失败端点 0 | 不改约束凑过，先查路径 |
| DRC | 0 error；Critical Warning 逐条看 | 记录，不忽略 |
| 引脚 | 与基线比，只多预期脚，无 LOST/换脚 | 解析不到就 `error` |
| 哈希 | 位流 SHA256 写进报告 | 重算并核对 |

**命令要点**：

```powershell
# 不要同时用 -nolog 和 -log：-nolog 会把 -log 压掉
vivado -mode batch -nojournal -notrace -source build_ps_m3_pkg.tcl -log build_m3.log
```

`io.rpt` 在 2025.1 是管道表格式：

```
| T10 | scl | High Range | ... |
```

正则要匹配 `^\|\s*([A-Z]+\d+)\s*\|\s*(\S+)\s*\|`；解析不到任何行就 `error`，不能把空表当“没有差异”。

## 已验证效果

- 本项目 50 MHz、5 MSPS、8192 拍/帧，一帧 819 个有效样本；
- 连续触发 20 帧，`FRAME_STEP_MISSES=0`；
- M3：6,921 LUT / 8,214 FF / 12.5 BRAM / 18 DSP；WNS +1.399 / WHS +0.053 ns，0 失败端点；
- 引脚 168→170，只多 `scl T10`/`sda T11`；
- 位流 SHA256 `254C3AA6…5E0F1459C`。

## 失效条件

- **采样沿选错**：在 `adc_phase==0` 同拍采新数据，会拿到上一拍旧值。
- **把 ILA 深度当帧长**：ILA 8192 样本、帧 819 样本，直接按 ILA 行数算会错 10 倍。
- **OTR 不看**：削顶样本会让后面所有峰值不可信。
- **`-nolog`**：日志不生成，证据消失。
- **空表当通过**：diff 解析不到却打印“no differences”，等于没验。
- **只看 WNS 不看 WHS**：hold 失败在板上偶发，很难复现。
- **数字通过就写“测到目标”**：没有声学对照，这是过度表述。

## 来源

- 13 号采集核“能出 CSV 但全是 0/常量”，根因是采样沿/时钟相位；
- 合并工程把 ILA 深度当成帧长，`frame_index` 与窗口对不上；
- `build_m3.log` 不生成：`-nolog` 压掉 `-log`；
- 引脚 diff 正则匹配不到 2025.1 格式，静默通过；
- 布线中途 `WHS=-1.226`，由 Post Hold Fix 修到 +0.057。

## 边界

本技能不覆盖模拟前端（增益、匹配、探头）和声学标定；它只保证“数字样本是真的、帧是连续的、构建是可核对的”。模拟链路诊断需要示波器/信号源。
