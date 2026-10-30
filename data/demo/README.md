# 演示数据

本目录保存 4096 点建模演示用的点云与姿态网页用的四个模型。全部为合成数据，不用于精度结论。

| 文件 | 内容 |
|---|---|
| `points_cylinder.jsonl`、`points_cone1.jsonl`、`points_cone2.jsonl`、`points_step.jsonl` | 四件演示点云，物体坐标系，单位 mm |
| `models/cylinder.ply`、`models/cone1.ply`、`models/cone2.ply`、`models/step.ply` | 姿态网页的四个模型（合成几何） |

## 用途

- 点云用于复核 `src/host/run_workflow.py` 的剖面与旋转体网格；`points_*.jsonl` 每行一个观测，带 `r_true`、`t`、`snr` 与 `accepted` 字段；
- 模型用于 `src/host/viewer/` 的模型下拉框，页面角标标为“演示模型”。

## 边界

- 全部为**合成示例**，用于演示数据链，不代表实测声学结果；
- 绝对尺寸未标定，半径按名义 Ø28 锚定，只能比较相对差异；
- 网格为开放侧壁，未测端面不封盖；分段是插值，不是新增测点。
