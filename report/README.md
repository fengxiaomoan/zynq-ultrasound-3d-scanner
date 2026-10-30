# 报告

| 文件 | 内容 | 建议读者 |
|---|---|---|
| `01_design_report.md` | 设计报告：背景、原理、软硬件划分、接口、优化、验证、局限 | 评委/老师 |
| `02_llm_collaboration.md` | 大模型协作：工作流、提示词、8 个案例、纠错、反思 | 评委/队员 |
| `03_skill_extraction.md` | 技能包提炼：失败→技能、验证方法、边界、可复用性自检 | 评委/下一个队伍 |
| `04_reproduction.md` | 从零复现：纯软件/仿真/构建/上板/建模 | 下一个队伍 |
| `05_evidence_index.md` | 每个数字对应的文件与命令；不能引用的说法 | 评委/写材料的人 |
| `06_video_shooting_guide.md` | 视频分镜、解说、设备、剪辑、合规、检查清单 | 拍摄的人 |
| `07_submission_checklist.md` | 赛题 3.3.5 逐条对照、提交页实际要求、32 项检查 | 提交的人 |
| `08_technical_document.md` | 早期 Markdown 草稿；**最终版以 `export/technical_document.docx/.pdf` 为准**（含表 3-1、图 3-4~3-6、9 篇参考文献） | 评委/提交 |
| `09_project_walkthrough.md` | 从实物到指标的完整讲解稿 + 视频口播顺序 + 评委 Q&A | 拍视频/答辩 |
| `export/design_report.pdf` | 设计报告 PDF（由 `01` 生成，22 页） | 评委/提交 |
| `export/design_report.docx` | 可编辑 Word 版设计报告 | 队员 |
| `export/technical_document.pdf` | 技术文档 PDF（最终版，17 页） | 提交 |
| `export/technical_document.docx` | 可编辑 Word 版技术文档 | 队员 |
| `export/build_docx.py` | Markdown → DOCX 生成脚本（设计报告） | 维护的人 |
| `export/build_technical_docx.py` | Markdown → DOCX 生成脚本（技术文档） | 维护的人 |
| `assets/` | 报告插图 + `make_figures.py` | — |

---

## 阅读顺序

1. 先读 `01_design_report.md` 的摘要 + §1 + §5；
2. 再读 `05_evidence_index.md` 的“不能引用”；
3. 要复现，读 `04_reproduction.md`；
4. 要拍视频，读 `06_video_shooting_guide.md`；
5. 要提交，读 `07_submission_checklist.md`。

## 插图

| 图 | 内容 |
|---|---|
| `assets/fig_system_architecture.png` | 系统总体架构 |
| `assets/fig_frame_timing.png` | 帧内/帧间时序 |
| `assets/fig_optimization.png` | 回读/数据量/帧率前后对比 |
| `assets/fig_resources.png` | M2b vs M3 资源 |
| `assets/fig_real_model.png` | 真实三层/六层模型 |
| `assets/apparatus.jpg` / `electronics.jpg` | 实物照片 |

重新生成：`python report/assets/make_figures.py`。

## 格式

- Markdown 为源；如需 Word/PDF，可按 `07_submission_checklist.md` 的提交页要求转换；
- 表格较宽，导出 PDF 时建议 A4 横向或缩小字号；
- 插图路径相对 `report/`，不要移动 `assets/`。
