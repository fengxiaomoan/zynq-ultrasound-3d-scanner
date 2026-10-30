# 提交材料与赛题要求对照

本文把 2026 FPGA 创新设计赛道 AMD 自主选题指南 3.3.5 的要求，与仓库中的实际内容逐项对应，并列出已经交付和尚未覆盖的部分。

- 赛题指南：工程包 / 技能包 / 设计报告 / 目录结构 / 评测指标（3.3.5）
- 仓库：<https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner>
- 提交截止：2026-11-04 18:00（以官网通知为准）

---

## 1. 提交材料清单

| 材料 | 规格 | 对应文件 | 说明 |
|---|---|---|---|
| 作品名称 | 文本 | — | 超声扫描三维建模与异常检测系统 |
| 技术文档 | PDF，≤50 MB | [`report/export/technical_document.pdf`](export/technical_document.pdf) | 17 页，2.2 MB，按官方模板 |
| 全部代码 | RAR，≤200 MB | 提交页压缩包 | 归档根目录为 `ultrasound_3d_scanner/`，解压即见 `src / sim / build / board / data / skill / report` |
| 演示视频 | MP4/H.264，≤3 分钟，≤300 MB | 尚未制作 | 仓库与 [Release `v1.0-assets`](https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner/releases/tag/v1.0-assets) 提供 5 个过程演示（合成示例，不等同验收录像） |
| 参赛作品承诺及使用授权书 | PDF，≤50 MB | 签字盖章件 | 不随仓库分发 |
| 作品全貌图 | JPG/PNG，≤10 MB，1 张 | [`submission/board_full_view.jpg`](../submission/board_full_view.jpg) | 装置全貌 |
| 开发板照片 | JPG/PNG，≤10 MB，≤4 张 | [`submission/board_photos/`](../submission/board_photos/) | 正面、俯视、电路、接线 |
| 三个关键词 | 3 个短词 | [`submission/keywords.txt`](../submission/keywords.txt) | 超声三维重建 / FPGA 板上 DSP / 手背姿态交互 |
| GitHub 链接 | 文本 | 本仓库 | 源码、仿真、构建报告、证据与文档 |

## 2. 赛题 3.3.5 要求对照

### 2.1 工程包（3.3.5.1）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 工程文件与源码（RTL、HLS、PS 侧软件） | `src/rtl/`（RTL）、`src/ps/`（PS C 与构建脚本）、`src/host/`（Python 主机） | 已提供；未使用 HLS，原因见设计报告 §3 |
| 仿真与验证结果 | `sim/tb/`（3 组 testbench）、`sim/results/`（重跑日志）、[`05_evidence_index.md`](05_evidence_index.md) | 已提供 |
| 综合与实现报告（资源、时序、关键指标） | `build/reports/`、[`01_design_report.md`](01_design_report.md) §4–5 | 已提供 |
| 上板工程、运行脚本、实测输出与参考结果比对 | `board/`（位流、XSA、加载与扫描脚本、实测日志）、`data/real/` | 已提供；四件全高与凸起检测的完整流程见演示视频 |
| 可复现的构建脚本 | `build/build_ps_m3_pkg.tcl`、`build/build_dsp_pkg.tcl`、`src/ps/build_m2b.py`、`build/build_all.ps1` | 已提供，使用仓库内相对路径 |

### 2.2 技能包（3.3.5.2）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 位于 `skill/`，含 `README.md` | `skill/README.md` + 9 个 `SKILL.md` | 已提供 |
| 说明适用范围、使用方法、失效条件 | 每个 `SKILL.md` 固定章节 | 已提供 |
| 写明已验证效果与来源（失败、观察） | 各 `SKILL.md` 的“已验证效果”“来源” | 已提供 |
| 可复用性：陌生队伍能否直接使用 | [`03_skill_extraction.md`](03_skill_extraction.md) §6 自检 | 已自检 |
| PYNQ 通用技能单独加分 | `skill/07_pynq_overlay_io` | PYNQ API 未在 PYNQ 板上执行，文中已标注 |

### 2.3 设计报告（3.3.5.3）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 选题背景与创新点（为什么选、解决什么、前人工作） | [`01_design_report.md`](01_design_report.md) §1 | 已提供 |
| 设计原理与功能框图 | §2，图 1、图 2 | 已提供 |
| 软硬件划分依据与接口设计 | §3（AXI 寄存器表、帧记录、姿态窗口） | 已提供 |
| 优化过程与优化前后对比 | §5、图 4、资源表 | 已提供 |
| 大模型协作记录（提示词、回答、纠错、工作流） | [`02_llm_collaboration.md`](02_llm_collaboration.md) | 已提供 |
| 技能包提炼过程（失败、观察、验证、边界） | [`03_skill_extraction.md`](03_skill_extraction.md) | 已提供 |
| 从零复现说明 | [`04_reproduction.md`](04_reproduction.md) | 已提供 |

### 2.4 目录结构（3.3.5.4）

| 要求 | 实际情况 | 结论 |
|---|---|---|
| `README.md`：简介与复现步骤 | 根 `README.md` | 已提供 |
| `src/`：设计源码 | `src/rtl`、`src/constraints`、`src/ps`、`src/host` | 已提供 |
| `sim/`：仿真脚本与结果 | `sim/tb`、`sim/run_*.ps1`、`sim/results` | 已提供 |
| `build/`：构建脚本与实现报告 | `build/*.tcl`、`build/reports` | 已提供 |
| `board/`：上板工程与实测输出 | `board/bitstream`、`board/tcl`、`board/logs`、`board/firmware` | 已提供 |
| `data/`：测试数据与参考结果 | `data/real`、`data/reference`、`data/demo`、`data/figures` | 已提供 |
| `skill/`、`report/` | 同名目录 | 已提供 |
| 目录与文件名为小写英文，无中文、空格、特殊字符 | 全仓库检查通过（`verify_package.py`） | 符合 |
| 中文只出现在正文内容 | 文件名为英文，正文为中文 | 符合 |

## 3. 评测指标与项目自评

| 评分项 | 权重 | 本项目支撑 | 边界说明 |
|---|---:|---|---|
| 创新性与应用价值 | 30 | 确定性采集、板上出结果、位姿硬件锁存、姿态交互、手术观测场景 | 创新在系统级而非新算法，报告中说明了与“数据搬运”的差别 |
| 性能与资源优化效果 | 20 | 回读 171–202×、数据量 68,000:1、90.9 fps、资源与时序表 | 整机端到端加速约 30%，不宜引用 190× 作为整机指标 |
| 功能正确性与设计完整性 | 20 | 三级验证链、真实三层/六层模型、RTL 逐位一致 | 四件全高与凸起检测以演示视频为准；量化表只引用已留证据的部分 |
| 大模型协作与技能包 | 15 | 9 个技能包（5 个方法类、4 个通用类）与协作记录 | PYNQ 技能未在 PYNQ 板上执行 |
| 文档质量与可复现性 | 15 | 报告、复现说明、证据索引、构建脚本、哈希清单 | 未完成项在报告与本文中如实标注 |

## 4. 合规检查结论

| 检查项 | 结果 |
|---|---|
| 目录与文件命名（小写英文、无空格与特殊字符） | 通过 |
| 内部相对链接可达 | 通过（`python verify_package.py`，断链 0） |
| `manifest.json` 的 SHA256 与实际文件一致 | 通过 |
| 位流、XSA、ELF 哈希与 `build/reports/resource_summary.md` 一致 | 通过（5/5） |
| 脚本中无本机绝对路径 | 通过（`upstream/` 下的历史脚本除外，已标注） |
| 技术文档与设计报告无学校、姓名、指导教师信息 | 通过 |
| 许可证 | MIT，版权人 `2026 linzhiye` |

## 5. 尚未覆盖的范围

| 项目 | 现状 |
|---|---|
| 比赛要求的 ≤3 分钟演示视频 | 未制作；现有 5 个过程演示为合成示例 |
| 真实四件全高扫描与真实凸起检出 | 流程有录屏素材，量化结论未纳入本文 |
| 绝对尺寸标定 | 未做；半径按名义 Ø28 锚定，仅比较相对差异 |
| 20:14 位流 | 716.6 Hz 在 18:51 同源构建上测得，20:14 版未复测 |
| PYNQ 通用技能 | 未在 PYNQ 板上执行 |
| 参赛作品承诺及使用授权书 | 签字盖章后单独提交 |

以上缺口均在设计报告 §7 与 [`05_evidence_index.md`](05_evidence_index.md) 中标注，不以仿真结果替代实测。
