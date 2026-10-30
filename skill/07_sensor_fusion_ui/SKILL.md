---
name: sensor_fusion_ui
description: 'Use when an IMU or other sensor must drive a browser/desktop 3D view through an FPGA: I2C bring-up and bus recovery, absolute-tick sampling, fixed-point complementary fusion (CORDIC atan2 + integer sqrt), a 128-bit pose word, a second AXI window independent of the frame channel, coherent seq read, quaternion display. Covers the traps: an 8-bit field shifting the whole word, -0 treated as negative, and claiming 1 kHz when the board measures 716 Hz.'
---

# 传感器融合与三维界面联动

## 适用范围

- MPU6050（或兼容 IMU）经 I2C 接 FPGA，在 PL 内做定点融合；
- 姿态要送到 PS/网页，与另一条高频数据通道（帧记录）共存；
- 姿态只用于显示/交互，不参与测量；
- 可迁移到任何“传感器 → FPGA → 上位机 3D 视图”的作品。

## 输入

- 传感器型号、I2C 地址、寄存器、量程、DLPF；
- 引脚/电平（本项目 3.3 V，T10/T11，400 kHz，上拉）；
- 目标更新率与页面刷新率；
- 姿态字格式与 AXI 窗口偏移。

## 使用方法

### 1. 电气与引脚先过关

1. SDA/SCL 上拉（模块自带或 4.7 kΩ）；
2. 约束到正确 bank/电平；
3. 先读 `WHO_AM_I`（0x75，应为 0x68）。

**判据**：稳定读到 0x68；否则查地址、电平、上拉、线长。

### 2. I2C 主机要能自恢复

从机异常时可能把 SDA 拉低，普通 STOP 救不回来；加“9 个 SCL 脉冲 + STOP”清场；记录 `i2c_err`/`bus_stuck`，不清零；缩短线、加 100 Ω 串阻。

**判据**：手转/插拔后能自恢复，`err_cnt` 增长但 `seq` 不丢样。

### 3. 采样排程用绝对 tick

旧排程“读完再等 1 ms”会把 I2C 传输时间叠加进去，实测只有 716.6 Hz。改成从突发读起点按绝对 tick 排程，把等待与传输重叠。

**判据**：`seq` 2 s 内连续，`age_ms ≤ 1`；报告写实测值，不写目标值。

### 4. 定点互补滤波

- 加速度算 roll/pitch：`atan2(ay, az)`、`atan2(-ax, sqrt(ay²+az²))`；
- 陀螺积分补动态；`α=31/32`（整数移位）；
- CORDIC 算 atan2，整数 sqrt 算模长；
- 输入先取绝对值/符号，避免 `-0` 和带符号数直接进 CORDIC。

**判据**：静止不跳变；手转平滑；与 PC 模型逐位/逐 count 对齐。

### 5. 128 位姿态字与独立 AXI 窗口

```
{magic 0x4D50, seq[7:0], flags[7:0], tick[31:0],
 roll[15:0], pitch[15:0], yaw[15:0], err_cnt[15:0]}
```

- 每个字段位宽写死；不要用 8 位字段零扩展到 16 位——后面所有字段会整体移位；
- `flags`：bit0 valid、bit1 init_done（32 样本）、bit2 i2c_err、bit3 bus_stuck；
- 姿态与帧载荷用**两套独立 toggle/CDC**，不能共用一套锁存。

**判据**：130 组向量逐位相等；姿态与帧同时读写互不覆盖。

### 6. 一致读法与页面

- PS：读 `0x3C` 取 seq → 读 `0x30..0x38` → 再读 `0x3C`，两次 seq 相同才采用；
- 页面 50 ms 拉一次 `/api/pose`，四元数 `q = qFromYPR(yaw,pitch,roll) · q0⁻¹`；
- 模型网格更新时不重置姿态与归零基准；
- 页面 20 Hz 是刻意的，不写“1 kHz 到网页”。

**判据**：手转模块模型同步；页面 30 项数值断言通过；无空窗。

## 已验证效果

- 板上 `seq` 连续 716.6 Hz，零空窗；`/api/pose` 返回 `ok:1`、`err=0`、`age_ms ≤ 1`；
- 融合延迟恒定 51 拍（50 MHz）；
- RTL 与 PC 模型 130 组向量逐位相等，0 失配；
- I2C 卡死 9 脉冲恢复；手转期间累计 65 次错误，未丢样；
- 页面 20 Hz 刷新，模型随手转动，同时 `frames` 照常增长。

## 失效条件

- **字段位宽不匹配**：`err_cnt` 8 位零扩展，整个字右移 8 位；`flags` 7 位拼 8 位会位序错。
- **`-0` 当负数**：静止时差 1 count。
- **CORDIC 输入带符号**：应取 `|ax|`，否则个别姿态差 1 count。
- **I2C 无自恢复**：一次卡死整条链路停摆。
- **共用锁存**：1 kHz 姿态与 90 Hz 帧会互相覆盖。
- **写“1 kHz”**：实测 716.6 Hz；页面 20 Hz。
- **写“零延迟”**：延迟 = 3 ms DLPF + 0.4 ms I2C + 51 拍。

## 来源

- 姿态字整体右移 8 位（`err_cnt` 只有 8 位）；
- 静止 pitch 差 1 count（`-0`）；
- 个别姿态差 1 count（CORDIC 取了带符号 `ax`）；
- 采样 716.6 Hz 而非 1 kHz；
- 手转期间 65 次 I2C 错误。

## 边界

本技能只保证“姿态字一致、链路通、显示跟手”。它**不证明姿态精度**：没有转台/光学基准，不能写“0.x° 精度”。姿态也不进入测量链路，不能拿它做几何补偿。
