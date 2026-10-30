"""Build a self-contained HTML report: live A-scan, B-scan, profile and 3D model."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from wscan import frames, profile

RUN = Path("out/sim_full")
RESULT = RUN / "result"
OUT = RUN / "report.html"
N_SAMPLES = 512


def load_curves():
    rows = [json.loads(l) for l in
            (RESULT / "observations.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = [json.loads(l) for l in
                (RUN / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    curves, meta = [], []
    for r in rows:
        files = [m["file"] for m in manifest if m["seq"] == r["seq"]]
        envs = []
        for f in files:
            fr = frames.to_frame(frames.read_ila_csv(RUN / f), frame_id=f)
            p = frames.prepare(fr)
            envs.append(np.interp(np.linspace(p.t_us[0], p.t_us[-1], N_SAMPLES),
                                  p.t_us, p.envelope))
        env = np.mean(envs, axis=0)
        env = env / max(env.max(), 1e-9)
        curves.append((env * 255).astype(np.uint8))
        meta.append({"z": r["height_mm"], "az": r["azimuth_deg"],
                     "r": r["radius_mm"], "t": r["t_peak_us"], "snr": r["snr_db"]})
    t = np.linspace(frames.prepare(frames.to_frame(
        frames.read_ila_csv(RUN / manifest[0]["file"]), "x")).t_us[0],
                    frames.prepare(frames.to_frame(
        frames.read_ila_csv(RUN / manifest[0]["file"]), "x")).t_us[-1], N_SAMPLES)
    blob = base64.b64encode(np.stack(curves).tobytes()).decode()
    return blob, t, meta


def read_ply(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    nv = nf = 0
    for line in lines:
        if line.startswith("element vertex"):
            nv = int(line.split()[-1])
        elif line.startswith("element face"):
            nf = int(line.split()[-1])
    start = lines.index("end_header") + 1
    verts = np.array([[float(x) for x in l.split()] for l in lines[start:start + nv]])
    faces = [[int(x) for x in l.split()[1:]] for l in lines[start + nv:start + nv + nf]]
    return verts, faces


def render_3d(ply: Path, png: Path) -> None:
    v, f = read_ply(ply)
    fig = plt.figure(figsize=(7, 6))
    ax = fig.add_subplot(111, projection="3d")
    polys = [v[idx] for idx in f]
    coll = Poly3DCollection(polys, alpha=0.85, facecolor="#9fc0d8",
                            edgecolor="#41607a", linewidth=0.2)
    ax.add_collection3d(coll)
    ax.set_xlim(v[:, 0].min(), v[:, 0].max())
    ax.set_ylim(v[:, 1].min(), v[:, 1].max())
    ax.set_zlim(v[:, 2].min(), v[:, 2].max())
    ax.set_box_aspect((1, 1, 1.4))
    ax.set_xlabel("x / mm", fontsize=8)
    ax.set_ylabel("y / mm", fontsize=8)
    ax.set_zlabel("z / mm", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.view_init(elev=18, azim=-62)
    fig.tight_layout()
    fig.savefig(png, dpi=130)
    plt.close(fig)


HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>超声扫描建模报告</title>
<style>
 body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;background:#f6f5f1;color:#26313b}
 header{background:#1f3247;color:#fff;padding:20px 28px}
 header h1{margin:0 0 6px;font-size:20px}
 header p{margin:2px 0;font-size:13px;opacity:.85}
 main{padding:18px 28px;max-width:1180px;margin:auto}
 section{background:#fff;border:1px solid #dcd6c8;border-radius:8px;padding:16px 18px;margin-bottom:18px}
 h2{font-size:15px;margin:0 0 10px;color:#3b5064}
 .row{display:flex;gap:14px;flex-wrap:wrap;align-items:center}
 button{background:#33506b;color:#fff;border:0;border-radius:5px;padding:7px 14px;font-size:13px;cursor:pointer}
 button.ghost{background:#eef2f7;color:#33506b;border:1px solid #c3d0dd}
 input[type=range]{width:320px}
 .stat{font-family:ui-monospace,Consolas,monospace;font-size:13px;color:#4a5a6a}
 canvas{background:#fbfaf7;border:1px solid #e4dfd3;border-radius:5px;width:100%}
 table{border-collapse:collapse;font-size:12.5px;width:100%}
 th,td{border-bottom:1px solid #eee8db;padding:5px 8px;text-align:right}
 th{color:#5a6b7c;font-weight:600}
 td:first-child,th:first-child{text-align:left}
 .note{font-size:12px;color:#7a7266;line-height:1.6}
</style></head><body>
<header>
 <h1>圆柱超声波扫描 · 建模报告（模拟数据）</h1>
 <p>108 点 / 12 方位 × 9 层 · 5 MSPS · 1 MHz 单发 · 位姿由 FPGA 在采集瞬间锁存</p>
 <p>本页数据由真实底噪 + 合成回波生成，用于验证"采集→判读→建模→显示"全链路</p>
</header>
<main>
<section>
 <h2>实时波形（A 扫描）</h2>
 <div class="row">
  <button id="play">播放</button>
  <input type="range" id="idx" min="0" max="__NMAX__" value="0">
  <span class="stat" id="info"></span>
 </div>
 <canvas id="ascan" width="1100" height="300"></canvas>
 <p class="note">纵轴为归一化包络，绿色区为回波窗口 60–104 µs，红色竖线为检测到的峰。</p>
</section>
<section>
 <h2>B 扫描（方位 × 时间）</h2>
 <canvas id="bscan" width="1100" height="260"></canvas>
 <p class="note">横轴为 12 个方位，纵轴为时间；亮点连成的一条线就是圆柱面的回波。</p>
</section>
<section>
 <h2>母线剖面</h2>
 <canvas id="prof" width="1100" height="240"></canvas>
 <p class="note">每个高度取 12 个方位的半径中位数，误差棒为层内跨度。</p>
</section>
<section>
 <h2>三维模型</h2>
 <img src="__MODEL_PNG__" style="width:520px;max-width:100%">
 <p class="note">由 36 条母线旋转成面；文件：result/profile_mesh.ply（可用 MeshLab/Blender 打开）。</p>
</section>
<section>
 <h2>逐层结果</h2>
 <table id="tbl"><thead><tr><th>高度 mm</th><th>半径 mm</th><th>层内跨度 mm</th><th>点数</th></tr></thead><tbody></tbody></table>
</section>
</main>
<script>
const ENV = Uint8Array.from(atob("__BLOB__"), c => c.charCodeAt(0));
const N = __NPOINTS__, LEN = __LEN__;
const T0 = __T0__, T1 = __T1__;
const META = __META__;
const PROFILE = __PROFILE__;
const cvs = document.getElementById('ascan'), ctx = cvs.getContext('2d');
const bcv = document.getElementById('bscan'), bctx = bcv.getContext('2d');
const pcv = document.getElementById('prof'), pctx = pcv.getContext('2d');
let cur = 0, timer = null;

function drawA(i){
  const w = cvs.width, h = cvs.height, pad = 34;
  ctx.clearRect(0,0,w,h);
  const x0 = pad, x1 = w-10, y0 = 12, y1 = h-24;
  const gx = t => x0 + (t-T0)/(T1-T0)*(x1-x0);
  ctx.fillStyle = '#eaf3ea';
  ctx.fillRect(gx(60), y0, gx(104)-gx(60), y1-y0);
  ctx.strokeStyle = '#d8d2c4'; ctx.beginPath();
  for(let k=0;k<=4;k++){ const y=y0+(y1-y0)*k/4; ctx.moveTo(x0,y); ctx.lineTo(x1,y); }
  ctx.stroke();
  ctx.strokeStyle = '#5a7a99'; ctx.lineWidth = 1.4; ctx.beginPath();
  for(let k=0;k<LEN;k++){
    const t = T0 + (T1-T0)*k/(LEN-1);
    const v = ENV[i*LEN+k]/255;
    const x = gx(t), y = y1 - v*(y1-y0);
    k ? ctx.lineTo(x,y) : ctx.moveTo(x,y);
  }
  ctx.stroke();
  const t = META[i].t;
  if(t){
    ctx.strokeStyle = '#c0392b'; ctx.lineWidth = 1.5; ctx.beginPath();
    ctx.moveTo(gx(t), y0); ctx.lineTo(gx(t), y1); ctx.stroke();
  }
  ctx.fillStyle = '#5a6b7c'; ctx.font = '11px Consolas';
  ctx.fillText('µs', x1-16, h-8);
  ctx.fillText(T0.toFixed(0), x0-4, h-8);
  ctx.fillText(T1.toFixed(0), x1-20, h-8);
  document.getElementById('info').textContent =
    `点 ${i+1}/${N} · z=${META[i].z.toFixed(1)} mm · az=${META[i].az.toFixed(0)}° · ` +
    `峰 ${t?t.toFixed(2):'—'} µs · r=${META[i].r?META[i].r.toFixed(2):'—'} mm · SNR ${META[i].snr?META[i].snr.toFixed(1):'—'} dB`;
}

function drawB(){
  const w = bcv.width, h = bcv.height, pad = 40;
  const x0 = pad, x1 = w-10, y0 = 10, y1 = h-22;
  bctx.clearRect(0,0,w,h);
  const bands = 12, cols = N/bands;
  for(let b=0;b<bands;b++){
    for(let k=0;k<LEN;k++){
      let acc = 0;
      for(let j=0;j<cols;j++) acc += ENV[(b*cols+j)*LEN+k];
      const v = acc/cols/255;
      const t = T0 + (T1-T0)*k/(LEN-1);
      if(t < 50 || t > 120) continue;
      const x = x0 + (t-50)/70*(x1-x0);
      const y = y0 + (b+0.5)/bands*(y1-y0);
      bctx.fillStyle = `rgba(192,57,43,${Math.min(1,v*2.2)})`;
      bctx.fillRect(x, y-7, 2, 14);
    }
  }
  bctx.fillStyle = '#5a6b7c'; bctx.font = '11px Consolas';
  bctx.fillText('t / µs →', x1-60, h-6);
  for(let b=0;b<bands;b++){
    bctx.fillText(`${(b*30)}°`, 6, y0 + (b+0.5)/bands*(y1-y0)+4);
  }
}

function drawP(){
  const w = pcv.width, h = pcv.height, pad = 46;
  const x0 = pad, x1 = w-16, y0 = 14, y1 = h-30;
  pctx.clearRect(0,0,w,h);
  const zs = PROFILE.map(r=>r.height_mm), rs = PROFILE.map(r=>r.radius_median_mm);
  const rmin = 13.5, rmax = 14.5;
  const gx = z => x0 + (z-Math.min(...zs))/(Math.max(...zs)-Math.min(...zs))*(x1-x0);
  const gy = r => y1 - (r-rmin)/(rmax-rmin)*(y1-y0);
  pctx.strokeStyle = '#d8d2c4'; pctx.beginPath();
  for(let k=0;k<=4;k++){ const r=rmin+(rmax-rmin)*k/4; pctx.moveTo(x0,gy(r)); pctx.lineTo(x1,gy(r));
    pctx.fillStyle='#8a8478'; pctx.font='10px Consolas'; pctx.fillText(r.toFixed(1), 6, gy(r)+3); }
  pctx.stroke();
  pctx.strokeStyle = '#2f6f4f'; pctx.lineWidth = 1.8; pctx.beginPath();
  PROFILE.forEach((r,i)=>{ i?pctx.lineTo(gx(r.height_mm),gy(r.radius_median_mm)):pctx.moveTo(gx(r.height_mm),gy(r.radius_median_mm)); });
  pctx.stroke();
  pctx.fillStyle = '#2f6f4f';
  PROFILE.forEach(r=>{
    pctx.beginPath(); pctx.arc(gx(r.height_mm), gy(r.radius_median_mm), 3, 0, 6.3); pctx.fill();
    const d = (r.radius_spread_mm||0)/2;
    pctx.beginPath(); pctx.moveTo(gx(r.height_mm), gy(r.radius_median_mm-d));
    pctx.lineTo(gx(r.height_mm), gy(r.radius_median_mm+d)); pctx.stroke();
  });
  pctx.fillStyle='#5a6b7c'; pctx.font='11px Consolas';
  pctx.fillText('z / mm →', x1-60, h-6);
}

const tb = document.querySelector('#tbl tbody');
PROFILE.forEach(r=>{
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${r.height_mm.toFixed(1)}</td><td>${r.radius_median_mm.toFixed(3)}</td>` +
                 `<td>${r.radius_spread_mm.toFixed(3)}</td><td>${r.points}</td>`;
  tb.appendChild(tr);
});

const slider = document.getElementById('idx');
slider.max = N-1;
slider.oninput = e => { cur = +e.target.value; drawA(cur); };
document.getElementById('play').onclick = e => {
  if(timer){ clearInterval(timer); timer=null; e.target.textContent='播放'; }
  else { e.target.textContent='暂停';
    timer = setInterval(()=>{ cur = (cur+1)%N; slider.value = cur; drawA(cur); }, 160); }
};
drawA(0); drawB(); drawP();
</script></body></html>
"""


def main() -> None:
    blob, t, meta = load_curves()
    png = RUN / "model_3d.png"
    render_3d(RESULT / "profile_mesh.ply", png)
    report = json.loads((RESULT / "scan_report.json").read_text(encoding="utf-8"))
    html = (HTML.replace("__BLOB__", blob)
                .replace("__NMAX__", str(len(meta) - 1))
                .replace("__NPOINTS__", str(len(meta)))
                .replace("__LEN__", str(N_SAMPLES))
                .replace("__T0__", f"{t[0]:.3f}")
                .replace("__T1__", f"{t[-1]:.3f}")
                .replace("__META__", json.dumps(meta, ensure_ascii=False))
                .replace("__PROFILE__", json.dumps(report["profile"], ensure_ascii=False))
                .replace("__MODEL_PNG__", png.name))
    OUT.write_text(html, encoding="utf-8")
    print(f"report -> {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
