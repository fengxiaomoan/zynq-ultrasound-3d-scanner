# 数据与证据

**所有数据分三级，文件名/JSON 字段/README 都标了 provenance**：

| 目录 | 等级 | 内容 |
|---|---|---|
| `real/` | `real-measurement` | 板上实测：帧率、回读、三层/六层模型、重复性、姿态、HTTP |
| `reference/` | `synthetic` | 四件数字体模、异常检测参考结果 |
| `demo/` | `synthetic` / 演示 | 4096 点演示视频、旧版全流程视频、点云 jsonl |
| `figures/` | 混合 | 报告/视频可复用的图（控制流、模型、时序、接线） |

---

## 1. `real/` 关键文件

| 文件 | 说明 |
|---|---|
| `_m2b_ps_rate.log` | PL 自主触发 90.84–91.05 fps |
| `_m2b_rate.log` | PS 连续读 90.93 fps、`missed=0` |
| `dsp_hw_compare.json` | 同帧 40 位字与参考逐位一致，170.7× |
| `dsp_hw_final1/2.log` | 四轮上板逐位证据中的两轮 |
| `_m2b_3layer_signed.json` | 三层模型：72/71、144/192、z −2…+2 |
| `_m2b_6layer.json` | 六层模型：141/131、288/480、z −8…+2 |
| `_m2b_std_repeat_20261027_171830.json` | 3 圈/层重复性：σ=0.4505 mm、69 格 |
| `f1_pose_samples.txt` / `f1_summary.txt` | 姿态 716.6 Hz、65 次 I2C 错误、未丢样 |
| `_m2b_http_state.json` / `_m2b_http_page.html` | 板上 `/state` 60,544 B、页面 22,211 B |
| `_m2b_ping.log` | 60 次 ping / 45 s 零失败 |
| `incomplete/` | 8/10 层不完整快照，**不能当模型证据** |

## 2. `reference/` 关键文件

| 文件 | 说明 |
|---|---|
| `bench/summary.json` | 四件 4096 点：MAE 0.189–0.190 mm |
| `bench/<shape>/mesh.ply` | 6048/5856 面的开放网格（PLY 头带 synthetic） |
| `anomaly/summary.json` | 8/8、0 误报、噪声底 0.043 mm |
| `anomaly/<shape>/residual.png` | 残差热图 + 检出框 + 真值十字 |

## 3. `demo/` 说明

| 文件 | 说明 |
|---|---|
| `demo_full_workflow_1080p.mp4` | 3 分 50 秒旧版全流程演示，**合成示例，不是实测验收** |
| `demo_4096_cylinder.mp4` 等 4 个 | 四件 4096 点合成点云演示 |
| `points_*.jsonl` | 体模逐点数据（bench/anomaly 的输入） |
| `demo_full_workflow.srt` | 旧版字幕，可作新视频脚本参考 |

## 4. 使用规则

- 引用 `real/` 的数字，必须带文件名；
- 引用 `reference/` 的数字，必须写“数字体模/仿真”；
- 不把 `demo/` 的视频帧当“实测截图”；
- 不删 `incomplete/`，它解释了“为什么没有 8/10 层证据”。

逐条映射见 `../report/05_evidence_index.md`。
