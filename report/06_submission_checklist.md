# 赛题要求与实现对照

本文把 2026 FPGA 创新设计赛道 AMD 自主选题指南 3.3.5 的要求，与仓库中的实际内容逐项对应，并列出尚未覆盖的部分。

- 指南：工程包 / 技能包 / 设计报告 / 目录结构 / 评测指标（3.3.5）
- 仓库：<https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner>

## 1. 赛题要求对照

### 1.1 工程包（3.3.5.1）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 工程文件与源码（RTL、HLS、PS 侧软件） | `src/rtl/`（RTL）、`src/ps/`（PS C 与构建脚本）、`src/host/`（Python 主机） | 已提供；未使用 HLS，原因见设计报告 §3 |
| 仿真与验证结果 | `sim/tb/`（3 组 testbench）、`sim/results/`（重跑日志）、[`05_evidence_index.md`](05_evidence_index.md) | 已提供 |
| 综合与实现报告（资源、时序、关键指标） | `build/reports/`、[`01_design_report.md`](01_design_report.md) §4–5 | 已提供 |
| 上板工程、运行脚本、实测输出与参考结果比对 | `board/`（位流、XSA、加载与扫描脚本、实测日志）、`data/real/` | 已提供；四件全高与凸起检测的完整流程见演示视频 |
| 可复现的构建脚本 | `build/build_ps_m3_pkg.tcl`、`build/build_dsp_pkg.tcl`、`src/ps/build_m2b.py`、`build/build_all.ps1` | 已提供，使用仓库内相对路径 |

### 1.2 技能包（3.3.5.2）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 位于 `skill/`，含 `README.md` | `skill/README.md` + 9 个 `SKILL.md` | 已提供 |
| 说明适用范围、使用方法、失效条件 | 每个 `SKILL.md` 固定章节 | 已提供 |
| 写明已验证效果与来源（失败、观察） | 各 `SKILL.md` 的“已验证效果”“来源” | 已提供 |
| 可复用性：陌生队伍能否直接使用 | [`03_skill_extraction.md`](03_skill_extraction.md) §6 自检 | 已自检 |
| PYNQ 通用技能 | `skill/08_pynq_overlay_io` | PYNQ API 未在 PYNQ 板上执行，文中已标注 |

### 1.3 设计报告（3.3.5.3）

| 要求 | 仓库对应位置 | 结论 |
|---|---|---|
| 选题背景与创新点（为什么选、解决什么、前人工作） | [`01_design_report.md`](01_design_report.md) §1 | 已提供 |
| 设计原理与功能框图 | §2，图 1、图 2 | 已提供 |
| 软硬件划分依据与接口设计 | §3（AXI 寄存器表、帧记录、姿态窗口） | 已提供 |
| 优化过程与优化前后对比 | §5、图 4、资源表 | 已提供 |
| 大模型协作记录（提示词、回答、纠错、工作流） | [`07_llm_collaboration.md`](07_llm_collaboration.md) | 已提供 |
| 技能包提炼过程（失败、观察、验证、边界） | [`03_skill_extraction.md`](03_skill_extraction.md) | 已提供 |
| 从零复现说明 | [`04_reproduction.md`](04_reproduction.md) | 已提供 |

### 1.4 目录结构（3.3.5.4）

| 要求 | 实际情况 | 结论 |
|---|---|---|
| `README.md`：简介与复现步骤 | 根 `README.md` | 已提供 |
| `src/`：设计源码 | `src/rtl`、`src/constraints`、`src/ps`、`src/host` | 已提供 |
| `sim/`：仿真脚本与结果 | `sim/tb`、`sim/run_*.ps1`、`sim/results` | 已提供 |
| `build/`：构建脚本与实现报告 | `build/*.tcl`、`build/reports` | 已提供 |
| `board/`：上板工程与实测输出 | `board/bitstream`、`board/tcl`、`board/logs`、`board/firmware` | 已提供 |
| `data/`：测试数据与参考结果 | `data/real`、`data/demo`、`data/mechanical`、`data/figures` | 已提供 |
| `skill/`、`report/` | 同名目录 | 已提供 |
| 目录与文件名为小写英文，无中文、空格、特殊字符 | 全仓库检查通过（`verify_package.py`） | 符合 |
| 中文只出现在正文内容 | 文件名为英文，正文为中文 | 符合 |

## 2. 合规检查结论

| 检查项 | 结果 |
|---|---|
| 目录与文件命名（小写英文、无空格与特殊字符） | 通过 |
| 内部相对链接可达 | 通过（`python verify_package.py`，断链 0） |
| `manifest.json` 的 SHA256 与实际文件一致 | 通过 |
| 位流、XSA、ELF 哈希与 `build/reports/resource_summary.md` 一致 | 通过（5/5） |
| 脚本中无本机用户目录路径 | 通过（历史脚本已统一替换为 `<repo-root>`；命令示例保留 Vivado 安装路径） |
| 技术文档与设计报告无学校、姓名、指导教师信息 | 通过 |
| 许可证 | MIT，版权人 `2026 linzhiye` |

## 3. 尚未覆盖的范围

| 项目 | 现状 |
|---|---|
| 真实四件全高扫描与真实凸起检出 | 流程有录屏素材，量化结论未纳入本仓库文档 |
| 绝对尺寸标定 | 未做；半径按名义 Ø28 锚定，仅比较相对差异 |
| 20:14 位流 | 716.6 Hz 在 18:51 同源构建上测得，20:14 版未复测 |
| PYNQ 通用技能 | 未在 PYNQ 板上执行 |

以上缺口在设计报告 §7 与 [`05_evidence_index.md`](05_evidence_index.md) 中同样标注，不以仿真结果替代实测。
