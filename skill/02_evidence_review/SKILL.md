---
name: evidence_review
description: 'Use before any report, slide, video or submission: label each claim as real-measurement, simulation, static or external, attach a file/command, keep a single source of truth, and run a red-team pass for simulation-written-as-measurement, frame-rate-written-as-accuracy, and load-failure-explained-as-function-failure. This is a meta-skill; pair it with every other skill.'
---

# 证据分级与提交前红队

## 适用范围

- 写技术文档、答辩 PPT、演示视频、GitHub README；
- 任何要写“实测/提升/精度/延迟”的场合；
- 多会话/多人协作，容易出现数字漂移；
- 适用于任何工程作品，不限于 FPGA。

## 输入

- 原始日志、CSV/JSON、构建报告、仿真日志；
- 每条结论想引用的文件/命令；
- 本队的“红线清单”。

## 使用方法

### 1. 给每条结论选等级

| 等级 | 定义 | 例子 |
|---|---|---|
| `real` | 在本项目硬件上跑出来，有日志/JSON | 90.84–91.05 fps |
| `RTL-sim` | xsim 与参考逐位 | `0x8005A30849 == ref` |
| `synthetic` | 数字体模/合成波形 | MAE 0.189 mm |
| `static` | 综合/实现/引脚/资源/代码常量 | 6,921 LUT、WNS 1.399 ns |
| `external` | 工具/厂商文档 | UG901 |

**规则**：`synthetic` 不能写成“实测”；`RTL-sim` 不能写成“上板验证”；`static` 不能写成“性能”。

### 2. 每条结论必须有“文件 + 命令”

```
PL 自主触发 90.84–91.05 fps（real）
证据：data/real/_m2b_ps_rate.log
复现：读日志里的 seq 差 / 时间
```

找不到文件，写“未验证”，不要估算。

### 3. 单一事实源

| 指标 | 只认 |
|---|---|
| 帧率 | `_m2b_ps_rate.log` |
| 回读/加速比 | `dsp_hw_compare.json` |
| 资源/时序 | `build/reports/m3_*.rpt` |
| 模型 | `_m2b_3layer_signed.json` / `_m2b_6layer.json` |
| 重复性 | `_m2b_std_repeat_20261027_171830.json` |
| 姿态 | `f1_pose_samples.txt` / `f1_summary.txt` |

文档只引用，不复制；要改数字，先改事实源。

### 4. 红队清单

1. 有没有把仿真写成实测？
2. 有没有把帧率写成精度？
3. 有没有把加载失败/网口不通解释成功能问题？
4. 有没有“约/左右/接近”但没有误差范围？
5. 有没有把“目标值”写成“实测值”（1 kHz vs 716.6 Hz）？
6. 有没有把“单帧加速”写成“整机加速”（171–202× vs 整机约 30%）？
7. 有没有把“仿真 8/8”写成“检出 8 个缺陷”？
8. 有没有把“名义半径”写成“绝对精度”？

任何一条答“是”，改掉或降级。

### 5. 保留失败记录

失败的上板日志、被推翻的假设、作废的数字，不要删；在报告里写“旧数字作废说明”。失败记录是可信度的一部分，不是污点。

### 6. 提交前 15 分钟检查

- 每个数字能在证据索引找到文件；
- 仿真图表有“仿真/数字体模”角标；
- 未完成项写清；
- 视频/PDF/代码包的格式与大小符合提交要求；
- 文件名全英文小写；
- 没有学校/姓名/隐私信息。

## 已验证效果

- 红队审查删掉 3 处过度表述：1 kHz 姿态、整机 190×、检出 8 mm 缺陷；
- 统一了 90.9 fps、2.48–2.80 ms、0.4505 mm 等数字的口径；
- 把峰值 DSP 修复前的上板字标为废数据，避免进入材料；
- 提交材料中每个关键数字都能在证据索引找到文件。

## 失效条件

- **只在最后一天做**：数字已散落在十几个文档，改不动；应该每轮交接时做。
- **只审文字不审图**：图里的坐标轴/标注也可能过度表述。
- **把“有日志”当“已验证”**：日志可能是旧位流/旧固件；要绑定哈希与时间。
- **删掉失败记录**：会丢掉“为什么现在这样”的解释。
- **用“约”掩盖不确定**：没有误差范围的“约”等于没写。

## 来源

- 报告初稿的三句“漂亮话”被红队删掉；
- 峰值 DSP 修复前的上板字被标废；
- 多次“仿真绿、上板错”；
- 多会话数字漂移（90.9/91/100）。

## 边界

本技能不产生新数据，只约束“怎么说”。没有实验，最诚实的写法是“未验证”。
