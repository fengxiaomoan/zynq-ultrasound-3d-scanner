"""Run report: Markdown for the record, a self-contained HTML page for review."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path

from . import profile


def _fmt(value, unit=""):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}{unit}"
    return f"{value}{unit}"


def stage_table(report) -> list[tuple[str, str, str]]:
    counts = report["counts"]
    budget = report["timing"]["budget"]
    return [
        ("1 规划", f"{report['plan']['points']} 点 × {report['plan']['frames_per_point']} 帧", "ok"),
        ("2 运动", f"升降+旋转，命令步数（开环）", "ok"),
        ("3 发射/采集", "5 MSPS，819 有效点，163.8 µs 窗", "ok"),
        ("4 传输/解码", "ILA CSV → ADC 码 → 带符号差值", "ok"),
        ("5 质量门", f"{counts['eligible']}/{counts['points']} 合格", "ok" if counts["eligible"] else "warn"),
        ("6 声程", "标定后的 path_mm", "ok"),
        ("7 定位", "已知射线 + 椭球求交", "ok"),
        ("8 网格", (report.get("mesh") or {}).get("triangles", "-"), "ok" if report.get("mesh") else "warn"),
        ("9 输出", "points.csv / mesh.ply / mesh.stl", "ok"),
    ]


def render(report: dict, observations, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    counts = report["counts"]
    mesh = (report.get("mesh") or {}).get("stats", {})
    arc = report.get("self_check") or {}
    budget = report["timing"]["budget"]

    md = ["# 全自动超声扫描运行报告", "",
          f"- 生成时间：{report['generated_at']}",
          f"- 数据源：`{report['source']}`",
          f"- 网格：{report['plan']['points']} 点 × {report['plan']['frames_per_point']} 帧",
          f"- 合格：{counts['eligible']}/{counts['points']}",
          f"- 网格：{mesh.get('triangles', 0)} 三角形，{mesh.get('vertices', 0)} 顶点", ""]
    if arc:
        md += ["## 标准球自检", "",
               f"- 圆心：{arc.get('center_mm')} mm",
               f"- 圆心偏差：{arc.get('center_error_mm')} mm",
               f"- 半径：{arc.get('radius_mm')} mm（误差 {arc.get('radius_error_mm')} mm）",
               f"- rms：{arc.get('rms_mm')} mm", ""]
    md += ["## 计时预算", "",
           "| 项 | 秒 |", "|---|---:|"]
    for key in ("move_s", "lift_s", "rot_s", "settle_s", "readout_s", "total_s"):
        md.append(f"| {key} | {budget.get(key, 0):.1f} |")
    md += ["", "## 拒收原因", ""]
    if report["reasons"]:
        md += [f"- `{k}`：{v}" for k, v in report["reasons"].items()]
    else:
        md.append("- 无")
    md += ["", "## 边界", ""] + [f"- {x}" for x in report["limits"]]
    if report.get("truth_check"):
        md += ["", "## 与合成真值对比", "", f"```\n{json.dumps(report['truth_check'], ensure_ascii=False)}\n```"]
    (out / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    rows = "".join(
        f"<tr><td>{o.latitude_deg:+.0f}</td><td>{o.azimuth_deg:.0f}</td>"
        f"<td>{_fmt(o.t_peak_us)}</td><td>{_fmt(o.path_mm)}</td>"
        f"<td>{_fmt(o.snr_db)}</td><td>{'✓' if o.eligible else '×'}</td>"
        f"<td>{html.escape(';'.join(o.reasons))}</td></tr>"
        for o in observations[:60])

    stage_rows = "".join(
        f"<tr><td>{html.escape(a)}</td><td>{html.escape(str(b))}</td>"
        f"<td class=\"{'ok' if c == 'ok' else 'warn'}\">{c}</td></tr>"
        for a, b, c in stage_table(report))

    page = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>全自动超声扫描运行报告</title>
<style>
body{{font-family:system-ui,Segoe UI,Microsoft YaHei,sans-serif;margin:24px;color:#1d2733;background:#f6f8fb}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px}}
table{{border-collapse:collapse;background:#fff;box-shadow:0 1px 3px #0001;margin-top:8px}}
th,td{{border:1px solid #dde3ea;padding:6px 10px;font-size:13px;text-align:left}}
th{{background:#eef2f7}} .ok{{color:#1a7f37;font-weight:600}} .warn{{color:#b35900;font-weight:600}}
code{{background:#eef2f7;padding:1px 4px;border-radius:3px}}
.grid{{display:flex;gap:18px;flex-wrap:wrap}} .card{{background:#fff;padding:14px 18px;border-radius:8px;box-shadow:0 1px 3px #0001;min-width:190px}}
.big{{font-size:24px;font-weight:700}}
</style></head><body>
<h1>全自动超声扫描运行报告</h1>
<p>生成时间 {report['generated_at']} · 数据源 <code>{html.escape(str(report['source']))}</code></p>
<div class="grid">
<div class="card"><div>合格点</div><div class="big">{counts['eligible']}/{counts['points']}</div></div>
<div class="card"><div>三角形</div><div class="big">{mesh.get('triangles', 0)}</div></div>
<div class="card"><div>圆心偏差 mm</div><div class="big">{arc.get('center_error_mm', '-')}</div></div>
<div class="card"><div>预计耗时</div><div class="big">{budget.get('total_s', 0)/60:.0f} min</div></div>
</div>
<h2>流水线状态</h2>
<table><tr><th>阶段</th><th>内容</th><th>状态</th></tr>{stage_rows}</table>
<h2>输出文件</h2>
<ul>
<li><a href="points.csv">points.csv</a> — 每个扫描点的位姿、声程、坐标、质量</li>
<li><a href="observations.jsonl">observations.jsonl</a> — 逐点原始记录</li>
<li><a href="mesh.ply">mesh.ply</a> / <a href="mesh.stl">mesh.stl</a> — 建模数据</li>
<li><a href="scan_report.json">scan_report.json</a> — 机器可读报告</li>
</ul>
<h2>前 60 个点</h2>
<table><tr><th>纬度</th><th>方位</th><th>峰值 µs</th><th>声程 mm</th><th>SNR dB</th><th>合格</th><th>原因</th></tr>{rows}</table>
<h2>边界</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in report['limits'])}</ul>
</body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")

