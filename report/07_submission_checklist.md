# 提交清单与合规检查

**依据**：2026 FPGA 创新设计赛道 AMD 自主选题指南 3.3.5（工程包 / 技能包 / 设计报告 / 目录结构 / 评测指标），以及“作品强烈要求在 GitHub/Gitee 开源”的说明。  
**提交截止**：2026-11-04 18:00（以官网最终通知为准）。  
**本包状态**：代码包已按 3.3.5.4 整理为 `ultrasound_3d_scanner/`（`README.md / src / sim / build / board / data / skill / report`）；**GitHub 已推送**（<https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner>，私有）；演示视频未拍（旧版 5 个已放 Release `v1.0-assets`）。

---

## 0. 提交页实际要求（按图 6/7/8）

提交页不是“交一个压缩包就完事”，而是分项上传。逐项对照：

| 提交项 | 格式/限制 | 本包应提交的文件 | 状态 |
|---|---|---|---|
| 作品名称 | 文本 | 超声扫描三维建模与异常检测系统 | ✅ |
| 演示视频 | MP4 / H.264 / **≤3 分钟** / **≤300 MB** | 按 `report/06_video_shooting_guide.md` 拍 `demo_final_3min.mp4` | ⬜ 待拍 |
| 技术文档 | PDF / ≤50 MB | `report/export/technical_document.pdf` | ✅ 17 页 / 2.2 MB，已按模板 |
| 全部代码 | **RAR** / ≤200 MB | `..\..\upload\all_code.rar`（0.6 MB，01–08 步） | ✅ 已生成 |
| 参赛作品承诺及使用授权书 | PDF / ≤50 MB | 从提交页下载模板，签字/盖章后扫描 | ⬜ 待办 |
| 作品海报（选填） | PDF 或 PPT / ≤50 MB | 可用 `report/export/design_report.pdf` 首页或另做一页 | ⬜ 可选 |
| GitHub 链接 | 文本 | <https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner> | ✅ 已推送（私有，验收后转公开） |
| 作品全貌图 | JPG/PNG / ≤10 MB / 最多 1 张 | `report/assets/photo_rig_front.jpg`（或正面+俯视合成） | ✅ 可用 |
| 开发板重要角度照片 | JPG/PNG / ≤10 MB / 最多 4 张 | `photo_rig_front.jpg`、`photo_rig_top.jpg`、`photo_electronics.jpg`、`diagram_wiring.png` | ✅ 可用 |
| 三个关键词 | 3 个短词 | 超声三维重建 / FPGA 板上 DSP / 手背姿态交互 | ✅ 建议 |

> 提交页明确“不能出现学校、指导教师姓名等与作品无关的信息”。技术文档、视频、图片、代码注释都要查一遍。

### 0.1 建议提交顺序

1. **技术文档**：先用 `report/export/technical_document.pdf` 上传，确认 ≤50 MB、无学校信息；
2. **演示视频**：按 3 分钟版拍完、导出、自看两遍，再上传；
3. **全部代码**：把 `..\upload\ultrasound_3d_scanner\` 整目录压成 RAR，归档根目录保留 `ultrasound_3d_scanner/`；**不要只压 src，也不要按 01–08 步骤分**；
4. **承诺书**：下载模板 → 签字/盖章 → 扫描成 PDF；
5. **图片**：全貌图 1 张 + 开发板照片最多 4 张；
6. **GitHub**：先私有仓库检查，再公开；提交页填链接；
7. **三个关键词**：超声三维重建 / FPGA 板上 DSP / 手背姿态交互；
8. 最后 24 小时再整体检查一遍，留一次回滚。

---

## 1. 赛题要求逐条对照

### 3.3.5.1 工程包

| 要求 | 本包对应 | 状态 |
|---|---|---|
| 工程文件与源码（RTL、HLS、PS 侧软件，按实际实现方式） | `src/rtl/`（RTL）、`src/ps/`（PS C + 构建）、`src/host/`（Python 主机） | ✅ 本队未用 HLS，报告中已说明 |
| 仿真/验证结果，说明功能正确性如何确认 | `sim/`（3 组 tb + 日志）、`report/05_evidence_index.md` | ✅ |
| 综合与实现报告，含资源占用、时钟频率、关键性能指标 | `build/reports/`、`report/01_design_report.md` §4–5 | ✅ |
| 上板工程、运行脚本、实测输出与参考结果比对 | `board/`（位流、XSA、加载/扫描脚本、实测日志）、`data/real/` | ✅（四件/凸起完整流程见视频） |
| 可复现的构建脚本 | `build/build_ps_m3_pkg.tcl`、`build/build_dsp_pkg.tcl`、`src/ps/build_m2b.py`、`build/build_all.ps1` | ✅（路径已改为包内相对） |

### 3.3.5.2 技能包

| 要求 | 本包对应 | 状态 |
|---|---|---|
| 置于 `skill/`，含 `README.md` | `skill/README.md` + 9 个 `SKILL.md` | ✅ |
| 说明适用范围、使用方法、失效条件 | 每个 SKILL 固定章节 | ✅ |
| 写明已验证效果、从哪些失败/观察中总结 | 每个 SKILL 的“已验证效果”“来源” | ✅ |
| 评价标准是可复用性（陌生队伍能否直接用） | `report/03_skill_extraction.md` §6 自检 | ✅ |
| 通用 PYNQ Skill 单独加分 | `skill/07_pynq_overlay_io` | ⚠ 部分验证（PYNQ API 未在本队板上执行，已如实标注） |

### 3.3.5.3 设计报告

| 要求 | 本包对应 | 状态 |
|---|---|---|
| 选题背景与创新点：为什么选、解决什么、前人做过什么 | `report/01_design_report.md` §1 | ✅ |
| 设计原理与功能框图 | §2 + 图 1/2 | ✅ |
| 软硬件划分依据与接口设计 | §3（含 AXI 寄存器表、帧记录、姿态窗口） | ✅ |
| 优化过程，含优化前后性能/资源对比表 | §5 + 图 4 + 资源表 | ✅ |
| 大模型协作记录：提示词、回答、纠错轨迹、工作流 | `report/02_llm_collaboration.md` | ✅ |
| 技能包提炼过程：失败/观察、验证、边界 | `report/03_skill_extraction.md` | ✅ |
| 复现说明：从零开始完整执行步骤 | `report/04_reproduction.md` | ✅ |

### 3.3.5.4 推荐目录结构

| 要求 | 本包 | 状态 |
|---|---|---|
| `README.md`：项目简介 + 复现步骤 | 根 `README.md` | ✅ |
| `src/`：设计源码 | `src/rtl`、`src/constraints`、`src/ps`、`src/host` | ✅ |
| `sim/`：仿真/验证脚本与结果 | `sim/tb`、`sim/run_*.ps1`、`sim/results` | ✅ |
| `build/`：可复现构建脚本 + 综合实现报告 | `build/*.tcl`、`build/reports` | ✅ |
| `board/`：上板工程、运行脚本与实测输出 | `board/bitstream`、`board/tcl`、`board/logs`、`board/firmware` | ✅ |
| `data/`：测试数据与参考结果 | `data/real`、`data/reference`、`data/demo`、`data/figures` | ✅ |
| `skill/`：技能包 + README.md | `skill/` | ✅ |
| `report/`：设计报告 + 大模型协作记录 | `report/` | ✅ |
| 目录/文件名纯英文（小写、数字、下划线或连字符），无中文/空格/特殊字符 | 全包已检查 | ✅ |
| 如采用其他组织方式，README 给目录对照 | 本包采用推荐结构；README 仍给了对照表 | ✅ |
| 中文只出现在正文内容 | 文件名全英文，正文中文 | ✅ |

### 3.3.5.5 评测指标与权重

| 评分项 | 权重 | 本包支撑 | 自评风险 |
|---|---:|---|---|
| 创新性与应用价值 | 30 | 确定性采集 + 板上结果 + 位姿锁存 + 姿态交互；手术观测场景 | 创新是系统级，不是新算法；需在报告中讲清“为什么不是普通数据搬运” |
| 性能与资源优化效果 | 20 | 171–202× 回读、68,000:1、90.9 fps、资源表 | 整机加速只有约 30%，不要写 190× |
| 功能正确性与设计完整性 | 20 | 三级验证链、真实三层/六层、逐位一致 | 四件/凸起的完整流程见视频；本文量化表以已留证据为主 |
| 大模型协作与技能包 | 15 | 9 个技能包（5 个方法 + 4 个通用）、协作记录 | PYNQ 技能未在 PYNQ 板上执行，加分有限 |
| 文档质量与可复现性 | 15 | 报告、复现说明、证据索引、构建脚本、哈希 | 需要把“未完成”写清楚，避免评委误解 |

---

## 2. GitHub 上传（已执行，2026-10-30）

> 状态：仓库 <https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner> 已推送 `main`（1 个 commit，322 文件 / 60.6 MB），当前**私有**。
> 演示视频（58 MB）未入库，已放 Release [`v1.0-assets`](https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner/releases/tag/v1.0-assets)。
> 剩下要人工点的两步：① 验收后 Settings → Danger Zone → Change visibility → Public；② 把链接填进提交页。

### 2.1 仓库准备（存档）

```powershell
cd ultrasound_3d_scanner
git init -b main
git add .
git commit -m "Initial commit: real-time ultrasound 3D scanning and shape-anomaly detection on AMD Zynq-7020"
git remote add origin https://github.com/fengxiaomoan/zynq-ultrasound-3d-scanner.git
git push -u origin main
```

### 2.2 仓库命名与描述

- 建议名：`zynq-ultrasound-3d-scanner`（小写、连字符）；
- 描述：`Real-time ultrasound 3D scanning and shape-anomaly detection on AMD Zynq-7020 (XC7Z020). RTL + bare-metal PS + Python host.`
- Topics：`fpga`, `zynq`, `ultrasound`, `3d-reconstruction`, `verilog`, `embedded`, `amd-xilinx`。

### 2.3 大文件

包内约 75 MB，主要是：

- `board/bitstream/*.bit`（各 4 MB）
- `data/demo/*.mp4`（约 60 MB）

GitHub 单文件 100 MB 限制内，但仓库会偏大。两种做法：

1. **直接提交**：简单，克隆慢；
2. **Git LFS**：`git lfs track "*.mp4" "*.bit"`，把 `.gitattributes` 一起提交；评委需要装 LFS 才能拉全。

建议：视频放 GitHub Release 或外部网盘，仓库里只留封面/字幕/说明；位流可以留，因为 4 MB 不算大。README 里给下载链接。

### 2.4 许可证

- 推荐 MIT（赛题推荐 MIT/Apache-2.0）；
- `LICENSE` 已放 MIT 模板，把 `<year>`/`<copyright holder>` 替换成实际信息；
- 第三方代码/工具（Vivado、Vitis、PYNQ）不打包，只在文档里引用；
- 视频背景音乐用自生成/无版权，避免 Content ID。

### 2.5 README 必填

- 一句话项目是什么；
- 硬件清单与接线入口；
- 5 分钟快速复现（纯软件 + 仿真）；
- 目录对照表；
- 证据等级说明；
- 已知限制（绝对尺寸未标定、>8 层、20:14 版未复测；四件/凸起见视频）；
- 许可证与引用。

---

## 3. 演示视频清单

| 项 | 要求 | 状态 |
|---|---|---|
| 时长 | **≤3 分钟**（提交页硬要求） | ⬜ 待拍 |
| 分辨率/帧率 | 1920×1080，25/30 fps | ⬜ |
| 编码 | MP4 / H.264 + AAC，**≤300 MB** | ⬜ |
| 内容 | 实物、框图、DSP 证据、90.9 fps、真实模型、姿态、异常（标仿真） | ⬜ |
| 标注 | 实测/仿真/RTL 仿真角标 | ⬜ |
| 字幕 | 中文 burn-in | ⬜ |
| 隐私 | 无患者/工牌/用户名路径 | ⬜ |
| 版权 | 音乐/素材可商用 | ⬜ |

拍摄脚本与分镜见 `report/06_video_shooting_guide.md`。

---

## 3.1 技术文档清单

| 项 | 要求 | 状态 |
|---|---|---|
| 模板 | 按提交页下载的 `2658aa94-…docx` 结构：作品名称/摘要/第一部分/第二部分/第三部分/第四部分/参考文献 | ✅ 按模板写 |
| 格式 | PDF，≤50 MB | ✅ `report/export/technical_document.pdf` |
| 内容 | 功能、应用、技术特点、指标、创新点、设计流程、硬件/机械/电路、软件、成果、测试、总结 | ✅ |
| 图片 | 实物、机械、接线、模型、残差 | ✅ p1–p5 + 报告图 |
| 隐私 | 无学校/姓名/指导教师 | ⬜ 提交前再查 |
| 页数 | 无硬性上限；建议 15–25 页 | ✅ 当前 17 页 |

---

## 4. 提交前 32 项检查

### 4.1 内容

- [ ] 1. 报告里的每个数字能在 `report/05_evidence_index.md` 找到文件；
- [ ] 2. 没有“1 kHz 姿态”“整机 190×”“检出 8 mm 缺陷”“临床可用”；
- [ ] 3. 仿真图表都有“仿真/数字体模”标注；
- [ ] 4. 真实模型标注“相对半径、未标定、开放网格”；
- [ ] 5. 四件/凸起标注为“见演示视频”，绝对标定/>8 层/20:14 未复测写清楚；
- [ ] 6. 构建谱系（18:51 vs 20:14）写清楚；
- [ ] 7. 技能包 9 个都有“适用范围/用法/失效条件/验证/来源/边界”；
- [ ] 8. 协作记录有提示词、回答、纠错、工作流；
- [ ] 9. 复现说明区分“纯软件/仿真/上板”；
- [ ] 10. README 有目录对照与快速开始。

### 4.2 文件与命名

- [ ] 11. 所有目录/文件名小写英文、数字、下划线/连字符；
- [ ] 12. 没有中文文件名、空格、`（）`、`Ø`；
- [ ] 13. 没有 `__pycache__`、`.venv`、`xsim.dir`、`.Xil`、临时 `.jou/.log`；
- [ ] 14. 没有绝对路径 `D:\daxue\...` 出现在脚本/文档（示例命令除外）；
- [ ] 15. `.gitignore` 覆盖构建产物/缓存/大日志；
- [ ] 16. `LICENSE` 年份/署名已替换；
- [ ] 17. 包内 `manifest.json` 的 SHA256 与实际文件一致；
- [ ] 18. 位流/XSA/ELF 哈希与 `build/reports/resource_summary.md` 一致。

### 4.3 可复现

- [ ] 19. 纯软件：`bench`/`anomaly` 两条命令能跑出同样数字；
- [ ] 20. 仿真：三组 `run_*.ps1` 能出 `PEAK_WORD`/`TB_PASS`/`SIM_ALL_PASS`；
- [ ] 21. 构建：`build_ps_m3_pkg.tcl` 能从包内相对路径构建；
- [ ] 22. 上板：`load_m3_pkg.tcl` 路径指向包内位流/固件；
- [ ] 23. `requirements.txt` 只含必要依赖；
- [ ] 24. Python 版本/工具版本写清楚。

### 4.4 提交

- [ ] 25. GitHub 仓库公开可访问，README 首屏能看懂；
- [ ] 26. 全部代码 RAR ≤200 MB：由 `..\upload\ultrasound_3d_scanner\` 整目录压缩，归档根目录 `ultrasound_3d_scanner/`；
- [ ] 27. 视频 MP4/H.264、≤3 分钟、≤300 MB；
- [ ] 28. 技术文档 PDF ≤50 MB，无学校/指导教师/姓名；
- [ ] 29. 参赛作品承诺及使用授权书 PDF 已签字/盖章；
- [ ] 30. 作品全貌图 1 张 + 开发板照片 ≤4 张，JPG/PNG ≤10 MB；
- [ ] 31. 三个关键词已填：超声三维重建 / FPGA 板上 DSP / 手背姿态交互；
- [ ] 32. 截止前 24 小时完成上传，留一次回滚。

---

## 5. 当前明确的缺口

| 缺口 | 影响 | 建议 |
|---|---|---|
| 演示视频未拍 | 提交必需 | 按 `06_video_shooting_guide.md` 拍 2:50–3:00 版 |
| GitHub 未上传 | 提交必需 | 先私有仓库，检查完再公开 |
| 视频需包含四件全高段 | 完整性 | 按 06 节拍拍到四件；没有就只放已完成的圆柱三层/六层 |
| 视频需包含凸起 A/B 段 | 完整性 | 至少拍一次标准件/贴凸起件对照；结果如实标 |
| 绝对尺寸标定 | 精度 | 平板标定 + 标准球自检 |
| PYNQ 通用技能未在 PYNQ 板执行 | 加分 | 有 PYNQ 板就补一次 `Overlay` 冒烟 |
| 20:14 位流未复测 | 一致性 | 上板复测 716.6 Hz 或直接用 18:51 版（若还能找回） |

---

## 6. 一句话

先把“能复现的”做扎实，再把“没做的”写清楚；不要为了让材料好看，把仿真写成实测。评审看得出区别，证据链也兜不住。
