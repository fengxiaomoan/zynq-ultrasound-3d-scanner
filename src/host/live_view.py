"""Live acquisition dashboard: tail an acquire.tcl run and show it as it grows.

    python live_view.py --run live_run/scan --port 8770 [--calib 8.6] [--static]

The acquisition (Tcl + Vivado) only writes ``raw/*.csv`` and ``manifest.jsonl``.
This process watches those files, decodes each new frame, computes the envelope
and the echo, updates the profile / lathe mesh incrementally, and serves a
self-contained page with A-scan, B-scan, profile and a rotating 3D model.

It never touches hardware and never invents a radius: without a calibration the
page shows time-of-flight only.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from wscan import frames, profile, vertical

N_ENV = 512
WINDOW = profile.WINDOW_US
PAGE = Path(__file__).resolve().with_name("live_page.html")


# --------------------------------------------------------------------- store
class Store:
    def __init__(self, run: Path, calib: float | None, window=WINDOW,
                 t_lo: float = -10.2, t_hi: float = 153.4):
        self.run = run
        self.calib = calib
        self.window = tuple(float(x) for x in window)
        self.grid = np.linspace(t_lo, t_hi, N_ENV)
        self.lock = threading.Lock()
        self.points: dict[int, dict] = {}
        self.frames_seen: set[str] = set()
        self.manifest_pos = 0
        self.error = None
        self.started = time.time()
        self.accepted = 0
        self.rejected = 0
        self.last_frame = None
        self.t_ref = None

    # -- reading -----------------------------------------------------------
    def poll(self) -> None:
        manifest = self.run / "manifest.jsonl"
        if not manifest.exists():
            return
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError:
            return
        lines = [l for l in text.splitlines() if l.strip()]
        for line in lines:
            if line in self.frames_seen:
                continue
            self.frames_seen.add(line)
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._ingest(m)

    def _ingest(self, m: dict) -> None:
        path = self.run / m["file"]
        for _ in range(20):
            if path.exists():
                break
            time.sleep(0.05)
        try:
            fr = frames.to_frame(frames.read_ila_csv(path), frame_id=path.name,
                                 source=str(path))
            prep = frames.prepare(fr)
            peak = frames.detect(prep, self.window)
            env = np.interp(self.grid, prep.t_us, prep.envelope)
            env = env / max(float(env.max()), 1e-9)
        except Exception as exc:                      # decode failure is a datum
            with self.lock:
                p = self.points.setdefault(m["seq"], self._empty(m))
                p["reasons"].append(f"decode:{str(exc)[:60]}")
            return

        env8 = (env * 255).astype(np.uint8)
        with self.lock:
            p = self.points.setdefault(m["seq"], self._empty(m))
            p["_envs"].append(env.astype(float))
            p["frames"].append({
                "f": m.get("frame", 0),
                "file": m["file"],
                "t": None if peak is None else round(peak.t_us, 3),
                "snr": None if peak is None else round(peak.snr_db, 2),
                "amp": None if peak is None else round(peak.amplitude, 1),
                "env": base64.b64encode(env8.tobytes()).decode(),
            })
            p["pose_lift"] = m.get("pose_lift")
            p["pose_rot"] = m.get("pose_rot")
            self.last_frame = p["frames"][-1]
            self._measure(p)

    def _empty(self, m: dict) -> dict:
        return {"seq": m["seq"], "z": m.get("height_mm"), "az": m.get("azimuth_deg"),
                "frames": [], "t": None, "snr": None, "radius": None,
                "reasons": [], "pose_lift": m.get("pose_lift"),
                "pose_rot": m.get("pose_rot"), "_envs": []}

    def _measure(self, p: dict) -> None:
        """Average the frame envelopes, then time the echo by its centroid.

        The averaged envelope suppresses per-frame noise; the centroid of the
        part above 60 % of the peak is much steadier than a single-sample peak
        on a broad, multi-path echo.
        """
        p["reasons"] = [r for r in p["reasons"] if not r.startswith("qc:")]
        p["t"] = p["snr"] = p["radius"] = None
        if not p["_envs"]:
            p["reasons"].append("qc:no_frame")
            return
        avg = np.mean(np.vstack(p["_envs"]), axis=0)
        lo, hi = self.window
        # Once a wall echo has been established, track it in a narrow band so a
        # stronger late multipath cannot steal the pick.
        if self.t_ref is not None:
            lo = max(lo, self.t_ref - 2.5)
            hi = min(hi, self.t_ref + 2.5)
        w = (self.grid >= lo) & (self.grid <= hi)
        if not w.any():
            p["reasons"].append("qc:no_window")
            return
        seg_t, seg = self.grid[w], avg[w]
        k = int(np.argmax(seg))
        peak = float(seg[k])
        late = (self.grid >= max(hi + 8.0, 95.0)) & (self.grid <= 140.0)
        base = float(np.median(avg[late])) if late.any() else float(np.median(seg))
        sigma = float(np.median(np.abs(avg[late] - base)) * 1.4826) if late.any() else 1.0
        sigma = max(sigma, 1e-6)
        snr = 20.0 * np.log10(max(peak - base, 1e-9) / sigma)
        p["snr"] = round(float(snr), 2)
        thr = base + 0.60 * max(peak - base, 0.0)
        sel = seg >= thr
        if sel.any():
            t_peak = float((seg_t[sel] * seg[sel]).sum() / seg[sel].sum())
        else:
            t_peak = float(seg_t[k])
        p["t"] = round(t_peak, 3)
        if t_peak <= lo + 0.6 or t_peak >= hi - 0.6:
            p["reasons"].append("qc:window_edge")
        if snr < 9.0:
            p["reasons"].append("qc:low_snr")
        if self.calib is not None:
            path_mm = (t_peak - self.calib) * profile.SOUND_SPEED_M_S / 1000.0
            try:
                y, _ = vertical.ray_point(path_mm, p["z"])
                p["radius"] = round(vertical.AXIS_Y - y, 3)
            except ValueError:
                p["reasons"].append("qc:path_out_of_model")
        p["accepted"] = not any(r.startswith("qc:") for r in p["reasons"])
        if p["accepted"] and p["t"] is not None:
            ts = [q["t"] for q in self.points.values()
                  if q.get("accepted") and q.get("t") is not None]
            if ts:
                self.t_ref = float(np.median(ts))
        self.accepted = sum(1 for q in self.points.values() if q.get("accepted"))
        self.rejected = sum(1 for q in self.points.values()
                            if q.get("frames") and not q.get("accepted"))

    # -- derived -----------------------------------------------------------
    def profile_rows(self) -> list[dict]:
        with self.lock:
            points = list(self.points.values())
        by_z: dict[float, list[dict]] = {}
        for p in points:
            if p.get("accepted") and p.get("radius") is not None:
                by_z.setdefault(round(float(p["z"]), 2), []).append(p)
        rows = []
        for z in sorted(by_z):
            group = by_z[z]
            radii = [q["radius"] for q in group]
            rows.append({"z": z, "r": round(float(np.median(radii)), 3),
                         "spread": round(float(max(radii) - min(radii)), 3),
                         "n": len(radii),
                         "t": round(float(np.median([q["t"] for q in group])), 2)})
        return rows

    def mesh(self, segments: int = 36) -> dict | None:
        rows = [{"height_mm": r["z"], "radius_vertical_mm": r["r"]}
                for r in self.profile_rows()]
        if len(rows) < 2:
            return None
        m = vertical.build_lathe(rows, segments=segments)
        v = m["vertices"]
        return {"vertices": [[round(float(x), 2) for x in p] for p in v],
                "faces": m["faces"], "stats": m["stats"]}

    def state(self) -> dict:
        with self.lock:
            points = [{k: v for k, v in q.items() if not k.startswith("_")}
                      for q in sorted(self.points.values(), key=lambda x: x["seq"])]
            frames_n = sum(len(p["frames"]) for p in points)
        rows = self.profile_rows()
        return {
            "run": str(self.run),
            "elapsed_s": round(time.time() - self.started, 1),
            "calib_us": self.calib,
            "window": [self.window[0], self.window[1]],
            "t_range": [round(float(self.grid[0]), 2), round(float(self.grid[-1]), 2)],
            "counts": {"points": len(points), "frames": frames_n,
                       "accepted": self.accepted, "rejected": self.rejected},
            "points": points,
            "profile": rows,
            "mesh": self.mesh(),
            "plan": self._plan(),
        }

    def _plan(self) -> dict | None:
        path = self.run / "plan.tcl"
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            return {"z": sorted({float(l.split(" z ")[1].split()[0])
                                 for l in text.splitlines() if " z " in l}),
                    "az": sorted({float(l.split(" az ")[1].split()[0])
                                  for l in text.splitlines() if " az " in l})}
        except Exception:
            return None


# ---------------------------------------------------------------------- html
HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>圆柱超声扫描 · 实时波形与建模</title>
<style>
 :root{--ink:#1d2b36;--muted:#6b7c8c;--line:#d9dee4;--bg:#f4f6f8;--card:#fff;
       --accent:#c0553b;--good:#2f7d5a;--warn:#b07d1f;--bad:#a63a2e}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font-family:"Microsoft YaHei",system-ui,-apple-system,Segoe UI,sans-serif}
 header{background:#20313f;color:#fff;padding:14px 22px;display:flex;
        align-items:baseline;gap:18px;flex-wrap:wrap}
 header h1{font-size:17px;margin:0;font-weight:600}
 header .sub{font-size:12px;opacity:.8}
 .pill{font:12px ui-monospace,Consolas,monospace;background:#31485c;
       padding:3px 9px;border-radius:999px}
 main{padding:14px 18px;display:grid;gap:14px;
      grid-template-columns:repeat(12,1fr);max-width:1500px;margin:auto}
 section{background:var(--card);border:1px solid var(--line);border-radius:10px;
         padding:12px 14px;min-width:0}
 section h2{font-size:13px;margin:0 0 8px;color:#3d5568;font-weight:600;
            display:flex;justify-content:space-between;align-items:baseline}
 .span6{grid-column:span 6}.span4{grid-column:span 4}.span8{grid-column:span 8}
 .span12{grid-column:span 12}.span3{grid-column:span 3}
 canvas{width:100%;display:block;background:#fbfcfd;border-radius:6px}
 .stat{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}
 .kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;
     font:12.5px ui-monospace,Consolas,monospace}
 .kv b{color:var(--muted);font-weight:400}
 .bar{height:6px;background:#e6eaee;border-radius:3px;overflow:hidden;margin-top:8px}
 .bar>i{display:block;height:100%;background:var(--good);width:0;transition:width .3s}
 table{border-collapse:collapse;width:100%;font:12px ui-monospace,Consolas,monospace}
 th,td{padding:3px 6px;border-bottom:1px solid #eef1f4;text-align:right}
 th{color:var(--muted);font-weight:600}
 td:first-child,th:first-child{text-align:left}
 .ok{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
 .scroll{max-height:190px;overflow:auto}
</style></head><body>
<header>
 <h1>圆柱 Ø28 超声扫描 · 实时波形与建模</h1>
 <span class="sub" id="run"></span>
 <span class="pill" id="pcount">0 点</span>
 <span class="pill" id="pframes">0 帧</span>
 <span class="pill" id="paccept">接受 0</span>
 <span class="pill" id="ptime">0 s</span>
</header>
<main>
 <section class="span8">
  <h2><span>A 扫描 · 当前点 <span class="stat" id="cur"></span></span>
      <span class="stat" id="peakinfo"></span></h2>
  <canvas id="ascan" width="900" height="280"></canvas>
 </section>
 <section class="span4">
  <h2>进度与质量</h2>
  <div class="bar"><i id="prog"></i></div>
  <div class="kv" id="summary" style="margin-top:10px"></div>
  <div class="kv" id="planinfo" style="margin-top:8px"></div>
 </section>
 <section class="span6">
  <h2>B 扫描 · 方位 × 时间（全部点）</h2>
  <canvas id="bscan" width="720" height="250"></canvas>
 </section>
 <section class="span6">
  <h2>母线剖面 · 高度 → 半径</h2>
  <canvas id="prof" width="720" height="250"></canvas>
 </section>
 <section class="span6">
  <h2>三维模型 · 实时旋转 <span class="stat" id="meshinfo"></span></h2>
  <canvas id="mesh" width="720" height="330"></canvas>
 </section>
 <section class="span6">
  <h2>逐点表</h2>
  <div class="scroll"><table id="tbl">
   <thead><tr><th>#</th><th>z mm</th><th>az °</th><th>t µs</th><th>r mm</th>
   <th>SNR dB</th><th>状态</th></tr></thead><tbody></tbody></table></div>
 </section>
</main>
<script>
const $ = id => document.getElementById(id);
let S = null, sel = 0, spin = 0;

async function tick(){
  try{
    const r = await fetch('state', {cache:'no-store'});
    S = await r.json();
  }catch(e){ return; }
  $('run').textContent = S.run;
  $('pcount').textContent = S.counts.points + ' 点';
  $('pframes').textContent = S.counts.frames + ' 帧';
  $('paccept').textContent = '接受 ' + S.counts.accepted;
  $('ptime').textContent = S.elapsed_s + ' s';
  const nPlan = S.plan ? S.plan.z.length * S.plan.az.length : 0;
  $('prog').style.width = nPlan ? (100*S.counts.points/nPlan).toFixed(1)+'%' : '0%';
  $('summary').innerHTML = kv({
    '已采点/帧': S.counts.points+' / '+S.counts.frames,
    '接受/拒收': S.counts.accepted+' / '+S.counts.rejected,
    '标定 t_eff': S.calib_us==null?'未标定':S.calib_us.toFixed(2)+' µs',
    '回声窗口': S.window[0]+'–'+S.window[1]+' µs'});
  if(S.plan) $('planinfo').innerHTML = kv({
    '计划层数': S.plan.z.length+' 层',
    '计划方位': S.plan.az.length+' 个',
    '计划点数': nPlan});
  drawA(); drawB(); drawP(); drawM();
  fillTable();
}

function kv(o){ return Object.entries(o).map(([k,v])=>`<b>${k}</b><span>${v}</span>`).join(''); }

function tsPoint(){
  if(!S || !S.points.length) return null;
  return S.points[Math.min(sel, S.points.length-1)];
}

function drawA(){
  const c=$('ascan'), ctx=c.getContext('2d'), W=c.width, H=c.height;
  ctx.clearRect(0,0,W,H);
  const p=tsPoint();
  const L=34, R=12, T=10, B=24;
  const x=t=>L+(t-S.t_range[0])/(S.t_range[1]-S.t_range[0])*(W-L-R);
  const y=v=>H-B-v*(H-T-B);
  ctx.fillStyle='#eef5ea';
  ctx.fillRect(x(S.window[0]),T,x(S.window[1])-x(S.window[0]),H-T-B);
  ctx.strokeStyle='#e3e7eb'; ctx.beginPath();
  for(let k=0;k<=4;k++){const yy=T+(H-T-B)*k/4;ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);} ctx.stroke();
  ctx.fillStyle='#8a97a3'; ctx.font='10px Consolas';
  for(let k=0;k<=4;k++){const t=S.t_range[0]+(S.t_range[1]-S.t_range[0])*k/4;
    ctx.fillText(t.toFixed(0), x(t)-6, H-7);}
  if(!p){ ctx.fillStyle='#9aa6b2'; ctx.fillText('等待第一帧…', L+10, T+22); return; }
  const f=p.frames[p.frames.length-1];
  const raw=Uint8Array.from(atob(f.env), c=>c.charCodeAt(0));
  ctx.strokeStyle='#3f6f92'; ctx.lineWidth=1.5; ctx.beginPath();
  for(let k=0;k<raw.length;k++){const t=S.t_range[0]+(S.t_range[1]-S.t_range[0])*k/(raw.length-1);
    const v=raw[k]/255; k?ctx.lineTo(x(t),y(v)):ctx.moveTo(x(t),y(v));}
  ctx.stroke();
  if(f.t!=null){ctx.strokeStyle='#c0553b';ctx.lineWidth=1.4;ctx.setLineDash([4,3]);
    ctx.beginPath();ctx.moveTo(x(f.t),T);ctx.lineTo(x(f.t),H-B);ctx.stroke();ctx.setLineDash([]);}
  $('cur').textContent = `#${p.seq} z=${p.z==null?'—':p.z.toFixed(1)} mm az=${p.az==null?'—':p.az.toFixed(0)}°`;
  $('peakinfo').textContent = f.t==null?'无峰':`t=${f.t.toFixed(2)} µs  SNR=${f.snr.toFixed(1)} dB`;
}

function drawB(){
  const c=$('bscan'), ctx=c.getContext('2d'), W=c.width, H=c.height;
  ctx.clearRect(0,0,W,H);
  const L=40,R=10,T=8,B=20, pts=S.points;
  ctx.strokeStyle='#e3e7eb'; ctx.beginPath();
  for(let k=0;k<=4;k++){const yy=T+(H-T-B)*k/4;ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);} ctx.stroke();
  const t0=S.window[0], t1=S.window[1];
  const x=t=>L+(t-t0)/(t1-t0)*(W-L-R);
  const n=Math.max(pts.length,1);
  const dx=(W-L-R)/Math.max(n,40);
  pts.forEach((p,i)=>{
    if(!p.frames.length) return;
    const raw=Uint8Array.from(atob(p.frames[p.frames.length-1].env), c=>c.charCodeAt(0));
    for(let k=0;k<raw.length;k++){
      const t=S.t_range[0]+(S.t_range[1]-S.t_range[0])*k/(raw.length-1);
      if(t<t0||t>t1) continue;
      const v=raw[k]/255;
      ctx.fillStyle=`rgba(50,110,150,${Math.min(1,v*1.6)})`;
      ctx.fillRect(L+i*dx, H-B-v*(H-T-B), Math.max(dx,1), 2);
    }
    if(p.t!=null){ctx.fillStyle='#c0553b';ctx.fillRect(L+i*dx,T,Math.max(dx,1),H-T-B);}
  });
  ctx.fillStyle='#8a97a3';ctx.font='10px Consolas';
  ctx.fillText('t / µs →', W-70, H-5);
  ctx.fillText(t0.toFixed(0), L-4, H-5);
  ctx.fillText(t1.toFixed(0), W-28, H-5);
}

function drawP(){
  const c=$('prof'), ctx=c.getContext('2d'), W=c.width, H=c.height;
  ctx.clearRect(0,0,W,H);
  const rows=S.profile, L=50,R=14,T=10,B=26;
  if(!rows.length){ctx.fillStyle='#9aa6b2';ctx.font='12px Microsoft YaHei';
    ctx.fillText('还没有可用的半径（需要回波 + 标定）', L, T+20);return;}
  const zs=rows.map(r=>r.z), rs=rows.map(r=>r.r);
  let zmin=Math.min(...zs), zmax=Math.max(...zs);
  if(zmax-zmin<1) zmax=zmin+1;
  const rmin=Math.min(...rs)-0.6, rmax=Math.max(...rs)+0.6;
  const x=z=>L+(z-zmin)/(zmax-zmin)*(W-L-R);
  const y=r=>H-B-(r-rmin)/(rmax-rmin)*(H-T-B);
  ctx.strokeStyle='#e3e7eb';ctx.fillStyle='#8a97a3';ctx.font='10px Consolas';
  for(let k=0;k<=4;k++){const r=rmin+(rmax-rmin)*k/4;
    ctx.beginPath();ctx.moveTo(L,y(r));ctx.lineTo(W-R,y(r));ctx.stroke();
    ctx.fillText(r.toFixed(1), 6, y(r)+3);}
  ctx.strokeStyle='#2f7d5a';ctx.lineWidth=1.8;ctx.beginPath();
  rows.forEach((r,i)=>{i?ctx.lineTo(x(r.z),y(r.r)):ctx.moveTo(x(r.z),y(r.r));});
  ctx.stroke();
  rows.forEach(r=>{ctx.fillStyle='#2f7d5a';ctx.beginPath();ctx.arc(x(r.z),y(r.r),3,0,6.3);ctx.fill();});
  ctx.fillStyle='#8a97a3';
  ctx.fillText('z / mm →', W-64, H-8);
  ctx.fillText(zmin.toFixed(0), L-4, H-8);
  ctx.fillText(zmax.toFixed(0), W-30, H-8);
}

function drawM(){
  const c=$('mesh'), ctx=c.getContext('2d'), W=c.width, H=c.height;
  ctx.clearRect(0,0,W,H);
  const M=S.mesh;
  if(!M){ctx.fillStyle='#9aa6b2';ctx.font='12px Microsoft YaHei';
    ctx.fillText('至少两层有半径后开始建模', 20, 26);$('meshinfo').textContent='';return;}
  const cx=W/2, cy=H/2+10, scale=Math.min(W,H)*0.62/Math.max(1, ...M.vertices.map(v=>v[1]))*2.0;
  const ca=Math.cos(spin), sa=Math.sin(spin);
  const P=M.vertices.map(v=>{
    const x=v[0]-75, y=v[1]-100, z=v[2]-83;
    const rx=x*ca-y*sa, ry=x*sa+y*ca;
    const persp=1/(1+ry/450);
    return [cx+rx*persp*2.2, cy-z*persp*2.2, ry];
  });
  const tris=M.faces.map(f=>{
    const a=P[f[0]],b=P[f[1]],d=P[f[2]];
    return {z:(a[2]+b[2]+d[2])/3, pts:[a,b,d]};
  }).sort((u,v)=>v.z-u.z);
  for(const t of tris){
    const shade=Math.max(0.35,Math.min(1, 0.75-t.z/600));
    ctx.fillStyle=`rgba(120,160,190,${shade})`;
    ctx.strokeStyle='rgba(70,110,140,0.45)';
    ctx.beginPath();ctx.moveTo(t.pts[0][0],t.pts[0][1]);
    ctx.lineTo(t.pts[1][0],t.pts[1][1]);ctx.lineTo(t.pts[2][0],t.pts[2][1]);
    ctx.closePath();ctx.fill();ctx.stroke();
  }
  $('meshinfo').textContent=`${M.stats.triangles} 三角形 · z ${M.stats.z_range_mm[0].toFixed(1)}–${M.stats.z_range_mm[1].toFixed(1)} mm`;
  spin+=0.012;
}

function fillTable(){
  const tb=document.querySelector('#tbl tbody');
  const rows=S.points.slice(-14).reverse();
  tb.innerHTML=rows.map(p=>{
    const cls=p.accepted?'ok':(p.frames.length?'bad':'');
    const st=p.reasons.length?p.reasons[p.reasons.length-1].replace('qc:',''):(p.accepted?'ok':'—');
    return `<tr><td>${p.seq}</td><td>${p.z==null?'—':p.z.toFixed(1)}</td>`+
      `<td>${p.az==null?'—':p.az.toFixed(0)}</td>`+
      `<td>${p.t==null?'—':p.t.toFixed(2)}</td>`+
      `<td>${p.radius==null?'—':p.radius.toFixed(2)}</td>`+
      `<td>${p.snr==null?'—':p.snr.toFixed(1)}</td>`+
      `<td class="${cls}">${st}</td></tr>`;
  }).join('');
}

document.querySelector('#tbl').addEventListener('click', e=>{
  const tr=e.target.closest('tr'); if(!tr) return;
  const seq=+tr.children[0].textContent;
  const i=S.points.findIndex(p=>p.seq===seq); if(i>=0){sel=i;drawA();}
});

setInterval(()=>{ if(S) { drawM(); } }, 90);
setInterval(tick, 1000);
tick();
</script></body></html>
"""


# -------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    store: Store = None

    def log_message(self, *args):        # keep the console quiet
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.read_bytes() if PAGE.exists() else HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/state"):
            try:
                self.store.poll()
                body = json.dumps(self.store.state(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())
            return
        self.send_response(404)
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--calib", type=float, default=None,
                    help="t_eff in µs; without it only times are shown")
    ap.add_argument("--window", default=None,
                    help="echo window t0,t1 in µs (default 60,104)")
    ap.add_argument("--t-ref", type=float, default=None,
                    help="expected wall-echo time in µs; the pick stays within ±2.5 µs")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--static", action="store_true", help="decode once, no polling")
    ap.add_argument("--dump", default=None, help="write state JSON here once and exit")
    args = ap.parse_args()

    run = Path(args.run)
    win = WINDOW
    if args.window:
        a, b = (float(x) for x in args.window.split(","))
        win = (a, b)
    store = Store(run, args.calib, window=win)
    store.t_ref = args.t_ref
    store.poll()
    if args.dump:
        Path(args.dump).write_text(json.dumps(store.state(), ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"state -> {args.dump}  points={store.state()['counts']}")
        return 0
    if args.static:
        print(json.dumps(store.state()["counts"], ensure_ascii=False))
        return 0

    Handler.store = store
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"live view: http://{args.host}:{args.port}/  run={run}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
