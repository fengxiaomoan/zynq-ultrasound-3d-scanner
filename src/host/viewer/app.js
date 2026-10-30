/* F1 pose-driven 3D viewer.
 * No external libraries: tiny math + WebGL1 + PLY served as JSON by server.py.
 * Pose comes from /api/pose (demo / replay / live); the page falls back to a
 * local synthetic motion when the API is unreachable.
 */
"use strict";

/* ------------------------------------------------------------------ math */
const { Q_ID, qMul, qInv, qNorm, qFromEulerYXZ, qSlerp,
        mat4Perspective, mat4LookAt, mat4FromQuat, clamp } = window.Math3D;

/* --------------------------------------------------------------- WebGL */
const canvas = document.getElementById("view");
const gl = canvas.getContext("webgl", { antialias: true, alpha: false, depth: true });
let meshProg = null, lineProg = null;
let mesh = null;          // {vbo, ibo, count, radius}
let lineGeo = null;       // {vbo, count}

const MESH_VS = `
attribute vec3 aPos; attribute vec3 aNrm;
uniform mat4 uProj, uView, uModel;
varying vec3 vN, vP;
void main(){
  vec4 p = uModel * vec4(aPos, 1.0);
  vP = p.xyz; vN = mat3(uModel) * aNrm;
  gl_Position = uProj * uView * p;
}`;
const MESH_FS = `
precision mediump float;
varying vec3 vN, vP;
uniform vec3 uEye, uA, uB;
void main(){
  vec3 N = normalize(vN), V = normalize(uEye - vP);
  vec3 L1 = normalize(vec3(0.55, 0.85, 0.5));
  vec3 L2 = normalize(vec3(-0.7, 0.25, -0.45));
  float d1 = max(dot(N, L1), 0.0), d2 = max(dot(N, L2), 0.0);
  vec3 H = normalize(L1 + V);
  float spec = pow(max(dot(N, H), 0.0), 42.0);
  float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);
  float h = clamp(vP.y * 0.55 + 0.5, 0.0, 1.0);
  vec3 base = mix(uA, uB, h);
  vec3 col = base * (0.20 + 0.72 * d1 + 0.20 * d2)
           + vec3(1.0) * spec * 0.22
           + vec3(0.30, 0.62, 0.85) * rim * 0.30;
  gl_FragColor = vec4(col, 1.0);
}`;
const LINE_VS = `
attribute vec3 aPos; attribute vec3 aCol;
uniform mat4 uProj, uView;
varying vec3 vC;
void main(){ vC = aCol; gl_Position = uProj * uView * vec4(aPos, 1.0); }`;
const LINE_FS = `
precision mediump float; varying vec3 vC;
void main(){ gl_FragColor = vec4(vC, 1.0); }`;

function compile(vs, fs) {
  const mk = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(s) || "shader");
    }
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, mk(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(p) || "link");
  }
  return p;
}

function initGL() {
  meshProg = compile(MESH_VS, MESH_FS);
  lineProg = compile(LINE_VS, LINE_FS);

  // ground grid + axis triad
  const grid = [];
  const y = -1.55, n = 10, step = 0.24;
  for (let i = -n; i <= n; i++) {
    const t = i * step;
    grid.push(-n * step, y, t, 0.10, 0.15, 0.19);
    grid.push(n * step, y, t, 0.10, 0.15, 0.19);
    grid.push(t, y, -n * step, 0.10, 0.15, 0.19);
    grid.push(t, y, n * step, 0.10, 0.15, 0.19);
  }
  const axes = [
    0, 0, 0, 0.95, 0.30, 0.25, 0.9, 0, 0, 0.95, 0.30, 0.25,
    0, 0, 0, 0.35, 0.85, 0.55, 0, 0.9, 0, 0.35, 0.85, 0.55,
    0, 0, 0, 0.30, 0.60, 0.95, 0, 0, 0.9, 0.30, 0.60, 0.95,
  ];
  const buf = new Float32Array(grid.concat(axes));
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, buf, gl.STATIC_DRAW);
  lineGeo = { vbo, count: buf.length / 6 };
}

function uploadMesh(m) {
  const n = m.positions.length / 3;
  const inter = new Float32Array(n * 6);
  for (let i = 0; i < n; i++) {
    inter[i * 6 + 0] = m.positions[i * 3 + 0];
    inter[i * 6 + 1] = m.positions[i * 3 + 1];
    inter[i * 6 + 2] = m.positions[i * 3 + 2];
    inter[i * 6 + 3] = m.normals[i * 3 + 0];
    inter[i * 6 + 4] = m.normals[i * 3 + 1];
    inter[i * 6 + 5] = m.normals[i * 3 + 2];
  }
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, inter, gl.STATIC_DRAW);

  const use32 = n > 65535;
  const idx = use32 ? new Uint32Array(m.indices) : new Uint16Array(m.indices);
  const ibo = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);

  if (mesh) { gl.deleteBuffer(mesh.vbo); gl.deleteBuffer(mesh.ibo); }
  mesh = { vbo, ibo, count: m.indices.length, radius: m.radius || 1, use32 };
}

/* ----------------------------------------------------------- app state */
const state = {
  qRaw: Q_ID.slice(), qZeroInv: Q_ID.slice(), qTarget: Q_ID.slice(), qCur: Q_ID.slice(),
  pose: null, mode: "demo", paused: false, wireframe: false,
  cam: { yaw: 0.72, pitch: 0.30, dist: 3.3 },
  model: null, modelMeta: null,
  lastPoseFetch: 0, fps: 0, frames: 0, fpsT: performance.now(),
  online: false,
};

const $ = (id) => document.getElementById(id);

function setStatus(text, cls) {
  const el = $("status");
  el.textContent = text;
  el.className = "status " + (cls || "");
}

function clientDemoPose(t) {
  return {
    mode: "local-demo",
    roll: 10 * Math.sin(0.70 * t),
    pitch: 16 * Math.sin(0.45 * t + 1.0),
    yaw: 42 * Math.sin(0.25 * t),
    seq: Math.floor(t * 100) & 0xffff,
    valid: 1,
    age_ms: 0,
  };
}

async function fetchPose() {
  if (state.paused) return;
  try {
    const r = await fetch("/api/pose", { cache: "no-store" });
    if (!r.ok) throw new Error("http " + r.status);
    const p = await r.json();
    state.pose = p;
    state.mode = p.mode || "file";
    state.online = true;
  } catch (e) {
    state.pose = clientDemoPose(performance.now() / 1000);
    state.mode = "local-demo";
    state.online = false;
  }
  updateTargetFromPose();
}

function updateTargetFromPose() {
  const p = state.pose;
  if (!p) return;
  const d = Math.PI / 180;
  const q = qFromEulerYXZ((p.yaw || 0) * d, (p.pitch || 0) * d, (p.roll || 0) * d);
  state.qRaw = q;
  state.qTarget = qNorm(qMul(q, state.qZeroInv));
}

function zeroPose() {
  state.qZeroInv = qNorm(qInv(state.qRaw));
  state.qTarget = qNorm(qMul(state.qRaw, state.qZeroInv));
  state.qCur = state.qTarget.slice();
}

function resetView() {
  const r = state.modelMeta ? state.modelMeta.radius : 1.3;
  state.cam = { yaw: 0.72, pitch: 0.30, dist: clamp(r * 3.1, 2.8, 8.5) };
}

/* ------------------------------------------------------------- loading */
async function loadModels() {
  try {
    const r = await fetch("/api/models", { cache: "no-store" });
    const j = await r.json();
    const sel = $("model");
    sel.innerHTML = "";
    for (const m of j.models) {
      const o = document.createElement("option");
      o.value = m.name; o.textContent = m.label;
      sel.appendChild(o);
    }
    const preferred = j.models.find((m) => m.name === "cylinder") || j.models[0];
    if (preferred) { sel.value = preferred.name; await loadModel(preferred.name); }
  } catch (e) {
    setStatus("模型列表不可用：先启动 server.py", "bad");
  }
}

async function loadModel(name) {
  setStatus("加载模型…", "");
  try {
    const r = await fetch("/api/model?name=" + encodeURIComponent(name), { cache: "no-store" });
    if (!r.ok) throw new Error("http " + r.status);
    const m = await r.json();
    uploadMesh(m);
    state.modelMeta = m;
    $("m-name").textContent = m.label;
    $("m-prov").textContent = m.provenance === "real-measurement" ? "实测" : "数字体模";
    $("m-prov").className = "chip " + (m.provenance === "real-measurement" ? "real" : "synth");
    $("m-count").textContent = `${m.counts.vertices} 点 / ${m.counts.triangles} 面`;
    const lim = (m.limits || []).slice(0, 3).map((x) => "• " + x).join("\n");
    $("m-limits").textContent = lim;
    resetView();
    zeroPose();
    state.qCur = Q_ID.slice();
    setStatus("就绪", "ok");
  } catch (e) {
    setStatus("模型加载失败：" + e.message, "bad");
  }
}

/* -------------------------------------------------------------- render */
function draw() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(0.039, 0.063, 0.082, 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);
  // Scanner meshes do not always have consistent winding, so draw both sides.
  gl.disable(gl.CULL_FACE);

  const proj = mat4Perspective(45 * Math.PI / 180, w / Math.max(h, 1), 0.05, 60);
  const c = state.cam;
  const eye = [
    Math.sin(c.yaw) * Math.cos(c.pitch) * c.dist,
    Math.sin(c.pitch) * c.dist + 0.15,
    Math.cos(c.yaw) * Math.cos(c.pitch) * c.dist,
  ];
  const view = mat4LookAt(eye, [0, 0, 0], [0, 1, 0]);
  const model = mat4FromQuat(state.qCur);

  if (mesh) {
    gl.useProgram(meshProg);
    gl.uniformMatrix4fv(gl.getUniformLocation(meshProg, "uProj"), false, proj);
    gl.uniformMatrix4fv(gl.getUniformLocation(meshProg, "uView"), false, view);
    gl.uniformMatrix4fv(gl.getUniformLocation(meshProg, "uModel"), false, model);
    gl.uniform3fv(gl.getUniformLocation(meshProg, "uEye"), eye);
    gl.uniform3f(gl.getUniformLocation(meshProg, "uA"), 0.24, 0.62, 0.86);
    gl.uniform3f(gl.getUniformLocation(meshProg, "uB"), 0.98, 0.55, 0.28);

    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.vbo);
    const aPos = gl.getAttribLocation(meshProg, "aPos");
    const aNrm = gl.getAttribLocation(meshProg, "aNrm");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(aNrm);
    gl.vertexAttribPointer(aNrm, 3, gl.FLOAT, false, 24, 12);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.ibo);
    if (state.wireframe) {
      for (let i = 0; i < mesh.count; i += 3) {
        gl.drawElements(gl.LINE_LOOP, 3, mesh.use32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, i * (mesh.use32 ? 4 : 2));
      }
    } else {
      gl.drawElements(gl.TRIANGLES, mesh.count, mesh.use32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, 0);
    }
  }

  // grid + axes
  gl.useProgram(lineProg);
  gl.uniformMatrix4fv(gl.getUniformLocation(lineProg, "uProj"), false, proj);
  gl.uniformMatrix4fv(gl.getUniformLocation(lineProg, "uView"), false, view);
  gl.bindBuffer(gl.ARRAY_BUFFER, lineGeo.vbo);
  const lPos = gl.getAttribLocation(lineProg, "aPos");
  const lCol = gl.getAttribLocation(lineProg, "aCol");
  gl.enableVertexAttribArray(lPos);
  gl.vertexAttribPointer(lPos, 3, gl.FLOAT, false, 24, 0);
  gl.enableVertexAttribArray(lCol);
  gl.vertexAttribPointer(lCol, 3, gl.FLOAT, false, 24, 12);
  gl.drawArrays(gl.LINES, 0, lineGeo.count);
}

let lastT = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - lastT) / 1000);
  lastT = now;
  if (!state.paused) {
    const k = 1 - Math.exp(-dt * 14);
    state.qCur = qSlerp(state.qCur, state.qTarget, k);
  }
  draw();
  state.frames++;
  if (now - state.fpsT > 500) {
    state.fps = Math.round(state.frames * 1000 / (now - state.fpsT));
    state.frames = 0; state.fpsT = now;
    try { updateHud(); } catch (e) { /* never let HUD text kill the render loop */ }
  }
  requestAnimationFrame(frame);
}

/* ----------------------------------------------------------------- HUD */
function updateHud() {
  const p = state.pose || {};
  $("roll").textContent = (p.roll ?? 0).toFixed(1) + "°";
  $("pitch").textContent = (p.pitch ?? 0).toFixed(1) + "°";
  $("yaw").textContent = (p.yaw ?? 0).toFixed(1) + "°";
  $("fps").textContent = state.fps;
  $("mode").textContent =
    state.mode === "file" ? "文件回放" :
    state.mode === "demo" ? "服务器演示" :
    state.mode === "local-demo" ? "本地演示（离线）" : state.mode;
  $("age").textContent = (p.age_ms != null ? p.age_ms.toFixed(0) : "—") + " ms";
  $("seq").textContent = p.seq != null ? p.seq : "—";
}

/* ------------------------------------------------------------ controls */
function bindUI() {
  $("zero").onclick = zeroPose;
  $("reset").onclick = resetView;
  $("wire").onclick = () => { state.wireframe = !state.wireframe; $("wire").classList.toggle("on", state.wireframe); };
  $("pause").onclick = () => { state.paused = !state.paused; $("pause").classList.toggle("on", state.paused); $("pause").textContent = state.paused ? "继续" : "暂停"; };
  $("model").onchange = (e) => loadModel(e.target.value);

  window.addEventListener("keydown", (e) => {
    if (e.key === "z" || e.key === "Z") zeroPose();
    else if (e.key === "r" || e.key === "R") resetView();
    else if (e.key === "w" || e.key === "W") $("wire").click();
    else if (e.key === " ") { e.preventDefault(); $("pause").click(); }
  });

  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    state.cam.yaw -= dx * 0.008;
    state.cam.pitch = clamp(state.cam.pitch + dy * 0.008, -1.35, 1.35);
  });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("pointercancel", () => { drag = null; });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    state.cam.dist = clamp(state.cam.dist * (1 + Math.sign(e.deltaY) * 0.08), 1.4, 9);
  }, { passive: false });
  canvas.addEventListener("dblclick", resetView);

  window.addEventListener("resize", () => draw());
}

/* ------------------------------------------------------------------ go */
async function main() {
  if (!gl) { setStatus("浏览器不支持 WebGL", "bad"); return; }
  try { initGL(); } catch (e) { setStatus("WebGL 初始化失败：" + e.message, "bad"); return; }
  bindUI();
  setStatus("连接服务器…", "");
  await loadModels();
  await fetchPose();
  requestAnimationFrame(frame);
  setInterval(fetchPose, 60);
}

main();
