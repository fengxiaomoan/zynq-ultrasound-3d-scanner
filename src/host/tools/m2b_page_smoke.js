/* Headless smoke test for tools/live_model_page.html against a state.json that
 * the PS firmware produced (fpga/ps/sw/host/state_main.c).
 *
 * There is no browser and no jsdom here, so this stubs exactly the DOM surface
 * the page uses and then runs its real script: tick() fetches the JSON, render()
 * draws into stub canvases and fills the tables.  Any null dereference,
 * .toFixed() on a missing number or missing array shows up as a thrown
 * exception, which is what we want to catch before the page ever meets a board.
 *
 *   node tools/m2b_page_smoke.js live_run/_m2b_state_std1.json
 *   node tools/m2b_page_smoke.js state.json pose.json     # also exercise /api/pose
 *
 * The optional pose file has the /api/pose schema
 * ({ok,roll,pitch,yaw,gx,gy,gz,seq,tick_ms,age_ms}); with it, the page must
 * actually rotate (F1), not just render.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const statePath = process.argv[2];
if (!statePath) {
  console.error('usage: node m2b_page_smoke.js state.json [pose.json]');
  process.exit(2);
}
const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const posePath = process.argv[3];
const pose = posePath ? JSON.parse(fs.readFileSync(posePath, 'utf8')) : null;
const html = fs.readFileSync(path.join(__dirname, 'live_model_page.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

function ctxStub() {
  const noop = () => {};
  return new Proxy({}, {
    get(t, k) {
      if (k === 'canvas') return { width: 820, height: 340 };
      if (['fillStyle', 'strokeStyle', 'lineWidth', 'font', 'globalAlpha'].includes(k)) return '';
      return noop;
    },
    set() { return true; },
  });
}

const elements = new Map();
function el(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      width: 820,
      height: 340,
      style: {},
      textContent: '',
      innerHTML: '',
      className: '',
      getContext: () => ctxStub(),
    });
  }
  return elements.get(id);
}

const document = {
  getElementById: (id) => el(id),
  querySelector: (sel) => {
    // '#detTable tbody' / '#cellTable tbody'
    return el('sel:' + sel);
  },
  querySelectorAll: () => [],
};

const sandbox = {
  document,
  console,
  Date,
  Math,
  JSON,
  Number,
  Object,
  Array,
  String,
  setInterval: () => 0,
  clearInterval: () => {},
  fetch: async (url) => {
    if (String(url).indexOf('pose') >= 0) {
      return pose ? { ok: true, json: async () => pose } : { ok: false, json: async () => ({}) };
    }
    return { ok: true, json: async () => state };
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
(async () => {
  try {
    vm.runInContext(script + '\n;globalThis.__render = render;globalThis.__tick = tick;',
                    sandbox, { timeout: 5000 });
  } catch (e) {
    console.error('PAGE_SMOKE_FAIL: script threw:', e.message);
    process.exit(1);
  }
  try {
    await sandbox.__tick();     /* fetch + render, exactly what the page does */
    sandbox.__render();         /* and once more from the cached state */
    if (pose) {
      /* F1: a fresh sample must actually turn the model, and a model WITHOUT a
       * mesh must show the labelled placeholder rather than an empty canvas. */
      await sandbox.__f1p.pollPose();
      sandbox.__f1p.poseStep();
      sandbox.__f1p.syncPoseUI();
      const R = sandbox.__f1p.poseMatrix();
      const off = Math.abs(R[0] - 1) + Math.abs(R[4] - 1) + Math.abs(R[8] - 1) +
                  Math.abs(R[1]) + Math.abs(R[3]);
      if (sandbox.__f1p.poseFresh() !== true) throw new Error('pose sample not accepted');
      if (!(off > 1e-6)) throw new Error('pose did not rotate the model');
      const ph = sandbox.__f1p.placeholderMesh();
      if (ph.stats.placeholder !== true) throw new Error('placeholder not available');
    }
  } catch (e) {
    console.error('PAGE_SMOKE_FAIL: render() threw:', e.message);
    process.exit(1);
  }
  const poseTxt = el('ppose').textContent;
  console.log(`PAGE_SMOKE_PASS frames=${el('pframes').textContent} cells=${el('pcells').textContent} ` +
              `valid=${el('pvalid').textContent} rate=${el('prate').textContent} ` +
              `phase=${el('phase').textContent} mode=${el('pmode').textContent} ` +
              `pose=${poseTxt || '—'}`);
})();
