# 报告

| 文件 | 内容 | 用途 |
|---|---|---|
| `01_design_report.md` | 设计报告：背景、原理、软硬件划分、接口、优化、验证、局限 | 主文档 |
| `02_technical_document.md` | 技术文档的早期 Markdown 草稿；**成品以 `export/technical_document.docx/.pdf` 为准**（含表 3-1、图 3-4~3-6、9 篇参考文献） | 技术文档草稿 |
| `03_skill_extraction.md` | 技能包提炼：失败→技能、验证方法、边界、可复用性自检 | 技能包说明 |
| `04_reproduction.md` | 从零复现：纯软件/仿真/构建/上板/建模 | 复现指南 |
| `05_evidence_index.md` | 每个数字对应的文件与命令；不可引用的说法 | 证据索引 |
| `06_submission_checklist.md` | 赛题 3.3.5 逐条对照、合规检查结果、尚未覆盖的范围 | 要求对照 |
| `07_llm_collaboration.md` | 大模型协作：工作流、提示词、8 个案例、纠错、反思 | 协作记录 |
| `export/design_report.pdf` | 设计报告 PDF（由 `01` 生成，22 页） | 导出件 |
| `export/design_report.docx` | 可编辑 Word 版设计报告 | 导出件 |
| `export/technical_document.pdf` | 技术文档 PDF（17 页） | 导出件 |
| `export/technical_document.docx` | 可编辑 Word 版技术文档 | 导出件 |
| `export/build_docx.py` | Markdown → DOCX 生成脚本（设计报告） | 生成脚本 |
| `export/build_technical_docx.py` | Markdown → DOCX 生成脚本（技术文档） | 生成脚本 |
| `assets/` | 报告插图 + `make_figures.py` | 插图 |

---

## 阅读顺序

1. `01_design_report.md` 的摘要、§1 与 §5；
2. `05_evidence_index.md` 中标注“不可引用”的部分；
3. 复现看 `04_reproduction.md`；
4. 要求与内容的对应关系看 `06_submission_checklist.md`。

## 插图

| 图 | 内容 |
|---|---|
| `assets/fig_system_architecture.png` | 系统总体架构 |
| `assets/fig_frame_timing.png` | 帧内/帧间时序 |
| `assets/fig_optimization.png` | 回读/数据量/帧率前后对比 |
| `assets/fig_resources.png` | M2b vs M3 资源 |
| `assets/fig_real_model.png` | 真实三层/六层模型 |
| `assets/fig_setup_pair.png` | 实测现场与姿态交互概念（合成图） |
| `assets/photo_rig_front.jpg`、`photo_electronics.jpg` | 实物照片 |

重新生成：`python report/assets/make_figures.py`。

## 格式

- Markdown 为源；如需 Word/PDF，导出的 DOCX 见 `export/`；
- 表格较宽，导出 PDF 时用 A4 横向或缩小字号；
- 插图路径相对 `report/`，`assets/` 不要移动。
