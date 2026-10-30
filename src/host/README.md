# 主机侧（Python）

> 运行方式：在包根目录把 `src\host` 加入 `PYTHONPATH`，或先 `cd src\host`。
> 纯软件流程不需要板子、Vivado 或 Vitis。

## 1. 目录

| 路径 | 作用 |
|---|---|
| `wscan/` | 采集解码、几何、质量门、旋转体重建、报告（库） |
| `run_workflow.py` | CLI：plan / simulate / axisym / ingest |
| `run_scan.py` | 单次扫描入口 |
| `auto_measure.py` | 批量测量 |
| `sim_scan.py` | 无板仿真扫描 |
| `make_report_page.py` | 生成自包含 HTML 报告 |
| `tools/` | 最终链路工具：DSP 参考、硬件比对、稳健扫描、建模等 |
| `viewer/` | MPU6050 姿态驱动网页（WebGL，纯标准库） |
| `live_view.py` + `live_page.html` | 边扫边看：tail 采集目录并增量显示 |
| `make_fake_run.py` | 造一份假采集目录，离线调试前端 |
| `tests/test_workflow.py` | 工作流单元测试（profile/geom/pipeline） |

## 2. 快速自检

```powershell
cd src\host
python -m unittest tests.test_workflow -v
```

## 3. 常用命令（在包根目录）

```powershell
$env:PYTHONPATH = "src\host"
python src\host\viewer\server.py --port 8780
python src\host\live_view.py --run <采集目录> --port 8770
```

`live_view.py` 只读采集目录里的 `raw/*.csv` 与 `manifest.jsonl`，不碰硬件，也不会凭空给半径；
没有标定时页面只显示飞行时间。

## 4. 边界

- `viewer/` 的模型来自 `data/demo/models/`，是四个合成演示模型，页面已标注；
- 实时姿态链路见 `src/rtl/f1/` 与 `sim/tb/tb_f1.sv`；
- 一次性分析脚本没有放进 `tools/`，以免与最终实现混淆。
