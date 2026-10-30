---
name: rtl_dsp_pipeline
description: 'Use when a per-frame fixed-point DSP must move from Python/C into RTL and its result must cross to a PS without tearing: freeze the word format, make the DSP self-contained per frame, prove bit-exact equivalence against a Python integer model, add a counter-wrap regression, then carry the result over AXI with SEQ double-read, ACK and a ring buffer. Covers the traps: state that is never cleared, a one-cycle strobe a slow debug bus never sees, and ACKing a record before it was fully read.'
---

# 定点 DSP 上板 + AXI 帧记录

## 适用范围

- 已有 Python/C 定点参考，想把一段流式 DSP（解调、滤波、包络、找峰/质心）放进 FPGA；
- 每帧自包含（输入一帧、输出一个定长字），PS 通过 AXI 读结果；
- 需要证明“板端字 = 参考字”，并且连续跑不丢帧、不撕裂；
- 适用于超声/雷达/振动等任何“窗内统计 + 锁存 + 回读”的流水线。

## 输入

- 参考模型：定点格式、舍入、饱和、每帧复位点；
- 一帧真实输入样本（不是合成正弦）；
- 输出字格式：valid/frame/idx/amp 等字段的位宽与顺序；
- 记录布局、跨时钟域关系、帧率上限。

## 使用方法

### 1. 冻结“字格式”，再写 RTL

```
40 bit = {valid(1), frame(13), idx(10), amp(16)}
```

两边各写一份常量/注释；改格式必须同时改测试向量。先在文档里吵清楚，再写代码。

### 2. 让 RTL 每帧自包含

1. `capture_start` 复位 NCO 相位、DC 阻断、滑动窗、峰值寄存器；
2. 峰值窗走完 `active <= 0`，停止搜索；
3. 下一帧重新武装；
4. 锁存字保持到下一帧。

**判据**：一帧一个 `peak_strobe`；帧后继续喂样本，字不变。

### 3. 写 Python 逐位参考

用整数运算复刻每一步：同 Q 格式、同截位/舍入、同窗边界、同复位初值、同 `frame_count` 位宽。

**判据**：同一帧样本，Python 与 xsim 的 40 位字完全相同。

### 4. 用真实帧做 tb，并喂过计数器位宽

1. 先喂 560 个真实 `diff` 样本，比字；
2. **再喂 66,000 个变化样本**，要求 `STROBES=1`、`WORD_STABLE=1`。

很多 bug 只在计数器回绕后出现：本项目 `sid` 16 位，65,536 样本 = 13.1 ms 回绕一次；只喂 560 点永远碰不到。

### 5. 上板同帧验证

1. 发一次脉冲，读板端 40 位字；
2. 同时上传同一帧 ILA CSV；
3. 用 Python 参考复算该帧；
4. 比较 `frame/idx/amp`，要求 `idx_delta=0`、`amp_delta=0`。

**判据**：`FRAME_MATCH=1` 且 `MATCH: True`。不是“接近”。

### 6. AXI 帧记录：SEQ 双读、后 ACK

记录自带序号和有效位：

```
{seq, pose_rot, pose_lift, peak_word, cent_word}
```

读法：STATUS → SEQ → payload → 再读 SEQ；两次相同才采用，才写 ACK。SEQ 不同就不 ACK、不消费，等下一轮。

跨时钟域用 toggle：PL 在 `frame_done` 锁 payload 并翻转 `tog`；AXI 侧两级同步 `tog`，看到翻转后再等 2 拍采 payload。payload 在翻转前已稳定。

**判据**：连续 30 s，`seq` 差 / 时间 = 帧率，`missed=0`；无重复帧。

### 7. 环形缓冲与启动顺序

- 8192 帧 ≈ 90 s @ 90 fps；满后覆盖最旧，`frames` 停在 8192 是正常行为；
- 先 `net_init`（约 2 s PHY 自协商），再 `arm`；先 arm 会白丢约 200 帧；
- 改周期先 disarm，再写 period，再 arm。

### 8. 中断不确定时，先轮询兜底

MAC 收到、ISR 挂着、lwIP 队列空——本项目实测 GIC 投递不确定。关掉该 IRQ，主循环直接调用外设中断处理函数；60 次 ping / 45 s 零失败后，再回头查 GIC 根因。

## 已验证效果

- `peak_dsp`：239 LUT / 190 FF / 6 DSP / 41 SRL；
- 真实帧上 Python 参考 `0x8001C105CD` 与 xsim 逐位相同；
- 上板四轮 `0x8005220783`、`0x8005A30849`、`0x8005900BE6`、`0x80051B07E0` 全部 `MATCH: True`；
- 回读 2.48–2.80 ms vs ILA 477–555 ms，171–202×；
- 90.84–91.05 fps，PS 30 s `missed=0`；C 与 Python 在 4 个真实 run 上 `points.csv` 逐字节相等；
- 帧后 66,000 样本回归：`STROBES=1`、`WORD_STABLE=1`。

## 失效条件

- **`active` 不清零**：`sid` 回绕后每 13.1 ms 重新锁存，字被反复改写。
- **单拍 strobe 被慢速总线采样**：VIO 几乎抓不到 1 拍脉冲；要么展宽到下一帧，要么用 valid 保持位。
- **仿真只喂一帧**：碰不到回绕、DC 收敛、NCO 漂移。
- **先 ACK 后读**：payload 可能已被下一帧覆盖。
- **只读一次 SEQ**：帧在读取中途到达，payload 半新半旧。
- **依赖不确定的 GIC**：轮询是可靠兜底，不是退而求其次。
- **把逐位一致当声学准确**：只证明“板和 PC 算得一样”。

## 来源

- 峰值 DSP 回绕 bug（仿真绿、参考对、ILA 逐拍对，最后定位 `active`）；
- `peak_strobe` 卡高（停机后进不去清零分支）；
- 姿态/帧两通道共用锁存会互相覆盖；
- 启动丢 200 帧（arm 早于 net_init）；
- 网口时通时不通（GIC 投递不确定）。

## 边界

本技能不覆盖定点选型（Q 格式/位宽/饱和）和声学精度；它只保证“同一帧、同一算法、同一字，且能被 PS 完整读走”。帧率 >1 kHz 或 payload >4 KB 时应改用 DMA + 描述符，而不是 AXI4-Lite 逐字读。
