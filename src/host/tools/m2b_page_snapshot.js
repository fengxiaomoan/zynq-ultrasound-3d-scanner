/* Headless PNG snapshot of the two 3D canvases in tools/live_model_page.html.
 *
 * Why this exists: the sandbox cannot start a browser (Chrome/Edge need mojo
 * named pipes), and "render() did not throw" is a weak gate -- it says nothing
 * about whether the model actually appears, or in which orientation.  So the
 * page's own draw commands are recorded through a canvas-2D stub and the
 * filled triangles are rasterised here, painter's order preserved.  The result
 * is the same picture the browser would paint for those triangles.
 *
 *   node tools/m2b_page_snapshot.js <state.json> [out.png] [pose.json]
 *
 * With no pose.json the page is in auto-spin mode (no /api/pose).  Text is not
 * rasterised (the PNG is geometry only); the HTML hints still carry the labels.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');

const statePath = process.argv[2];
const outPath = process.argv[3] || path.join(__dirname, '..', 'live_run', '_f1p', 'snapshot.png');
const posePath = process.argv[4];
if (!statePath) {
  console.error('usage: node m2b_page_snapshot.js state.json [out.png] [pose.json]');
  process.exit(2);
}
const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const pose = posePath ? JSON.parse(fs.readFileSync(posePath, 'utf8')) : null;

const W = 820, H = 340;
const WANT = new Set(['meshStd', 'meshTest']);

/* ------------------------------------------------------------ canvas stub -- */
function parseColor(s) {
  if (typeof s !== 'string') return [0, 0, 0, 1];
  s = s.trim();
  let m = s.match(/^rgba?\(([^)]+)\)$/i);
  if (m) {
    const p = m[1].split(',').map(Number);
    return [p[0] | 0, p[1] | 0, p[2] | 0, p.length > 3 ? p[3] : 1];
  }
  m = s.match(/^#([0-9a-f]{6})$/i);
  if (m) {
    const v = parseInt(m[1], 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255, 1];
  }
  return [0, 0, 0, 1];
}

class Rec {
  constructor(id) { this.id = id; this.ops = []; this.width = W; this.height = H; }
  getContext() { return this; }
  set fillStyle(v) { this._fill = v; }   get fillStyle() { return this._fill; }
  set strokeStyle(v) { this._stroke = v; } get strokeStyle() { return this._stroke; }
  clearRect() { this.ops.push({ t: 'clear' }); }
  beginPath() { this.ops.push({ t: 'begin' }); this._path = []; }
  moveTo(x, y) { this._cur = [[x, y]]; this._path.push(this._cur); }
  lineTo(x, y) { (this._cur || (this._cur = [[0, 0]])).push([x, y]); }
  closePath() { this._closed = true; }
  fill() { this.ops.push({ t: 'fill', polys: (this._path || []).slice(),
                           color: parseColor(this.fillStyle) }); }
  stroke() { this.ops.push({ t: 'stroke', polys: (this._path || []).slice(),
                             color: parseColor(this.strokeStyle) }); }
  fillRect(x, y, w, h) { this.ops.push({ t: 'rect', x, y, w, h,
                             color: parseColor(this.fillStyle) }); }
  strokeRect() {}
  fillText() {}
  arc() {}
}
const canvases = new Map();
function el(id) {
  if (!canvases.has(id)) canvases.set(id, new Rec(id));
  return canvases.get(id);
}
const document = {
  getElementById: (id) => (WANT.has(id) ? el(id)
    : { style: {}, textContent: '', innerHTML: '', className: '',
        getContext: () => new Proxy({}, { get: () => () => {}, set: () => true }) }),
  querySelector: () => ({ innerHTML: '', textContent: '' }),
  querySelectorAll: () => [],
};

/* ---------------------------------------------------------------- run page -- */
const html = fs.readFileSync(path.join(__dirname, 'live_model_page.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const sandbox = {
  document, console, Date, Math, JSON, Number, Object, Array, String,
  setInterval: () => 0, clearInterval: () => {},
  fetch: async (url) => (String(url).indexOf('pose') >= 0
    ? { ok: !!pose, json: async () => pose || {} }
    : { ok: true, json: async () => state }),
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script + '\n;globalThis.__tick = tick;globalThis.__render = render;', sandbox,
                { timeout: 5000 });

(async () => {
  await sandbox.__tick();
  if (pose) {
    sandbox.__f1p.setPose(pose);
    sandbox.__f1p.poseStep();
    sandbox.__f1p.poseStep();          /* let the slerp settle */
    sandbox.__f1p.poseStep();
  } else {
    sandbox.__f1p.poseStep();
  }
  sandbox.__render();

  /* ------------------------------------------------ rasterise meshStd only */
  const rec = canvases.get('meshStd');
  const img = Buffer.alloc(W * H * 3, 0xf2);   /* page background-ish */
  const put = (x, y, c, a) => {
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const i = (y * W + x) * 3;
    img[i]     = Math.round(img[i]     * (1 - a) + c[0] * a);
    img[i + 1] = Math.round(img[i + 1] * (1 - a) + c[1] * a);
    img[i + 2] = Math.round(img[i + 2] * (1 - a) + c[2] * a);
  };
  const tri = (p, c, a) => {
    const xs = p.map(q => q[0]), ys = p.map(q => q[1]);
    const x0 = Math.max(0, Math.floor(Math.min(...xs))), x1 = Math.min(W - 1, Math.ceil(Math.max(...xs)));
    const y0 = Math.max(0, Math.floor(Math.min(...ys))), y1 = Math.min(H - 1, Math.ceil(Math.max(...ys)));
    const [ax, ay] = p[0], [bx, by] = p[1], [cx, cy] = p[2];
    const d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
    if (Math.abs(d) < 1e-12) return;
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const l1 = ((by - cy) * (x + 0.5 - cx) + (cx - bx) * (y + 0.5 - cy)) / d;
        const l2 = ((cy - ay) * (x + 0.5 - cx) + (ax - cx) * (y + 0.5 - cy)) / d;
        const l3 = 1 - l1 - l2;
        if (l1 >= -1e-9 && l2 >= -1e-9 && l3 >= -1e-9) put(x, y, c, a);
      }
    }
  };
  for (const op of rec.ops) {
    if (op.t === 'clear') { img.fill(0xf2); }
    else if (op.t === 'rect') {
      const x0 = Math.max(0, Math.floor(op.x)), y0 = Math.max(0, Math.floor(op.y));
      const x1 = Math.min(W - 1, Math.ceil(op.x + op.w)), y1 = Math.min(H - 1, Math.ceil(op.y + op.h));
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) put(x, y, op.color, op.color[3]);
    } else if (op.t === 'fill') {
      for (const poly of op.polys) {
        for (let i = 1; i + 1 < poly.length; i++) tri([poly[0], poly[i], poly[i + 1]], op.color, op.color[3]);
      }
    }
  }

  /* --------------------------------------------------------- write the PNG */
  const raw = Buffer.alloc((W * 3 + 1) * H);
  for (let y = 0; y < H; y++) {
    raw[y * (W * 3 + 1)] = 0;
    img.copy(raw, y * (W * 3 + 1) + 1, y * W * 3, (y + 1) * W * 3);
  }
  const crcTable = (() => {
    const t = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c;
    }
    return t;
  })();
  const crc32 = (buf) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, png);

  const tris = rec.ops.filter(o => o.t === 'fill').length;
  console.log(`SNAPSHOT_OK ${outPath} ${W}x${H} fills=${tris} ` +
              `pose=${pose ? `${pose.roll}/${pose.pitch}/${pose.yaw}` : 'auto'}`);
})().catch(e => {
  console.error('SNAPSHOT_FAIL:', e && e.message);
  process.exit(1);
});
