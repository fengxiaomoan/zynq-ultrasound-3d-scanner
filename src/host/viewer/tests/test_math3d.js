/* Node tests for the viewer math.  Run:  node f1_viewer/tests/test_math3d.js */
"use strict";
const assert = require("assert");
const M = require("../math3d.js");

let n = 0;
function ok(name, cond) {
  n++;
  if (!cond) { console.error("FAIL " + name); process.exit(1); }
  console.log("ok " + name);
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
const vnear = (v, w, eps = 1e-6) => v.every((x, i) => near(x, w[i], eps));

function rotate(q, v) {
  const p = [0, v[0], v[1], v[2]];
  const r = M.qMul(M.qMul(q, p), M.qInv(q));
  return [r[1], r[2], r[3]];
}
function matVec(m, v) {
  const x = v[0], y = v[1], z = v[2], w = v[3] === undefined ? 1 : v[3];
  return [
    m[0] * x + m[4] * y + m[8] * z + m[12] * w,
    m[1] * x + m[5] * y + m[9] * z + m[13] * w,
    m[2] * x + m[6] * y + m[10] * z + m[14] * w,
    m[3] * x + m[7] * y + m[11] * z + m[15] * w,
  ];
}
const D = Math.PI / 180;

/* identity */
ok("identity quaternion", vnear(M.qFromEulerYXZ(0, 0, 0), [1, 0, 0, 0]));
ok("identity leaves vector", vnear(rotate(M.qFromEulerYXZ(0, 0, 0), [1, 2, 3]), [1, 2, 3], 1e-9));

/* right-handed conventions, Y-X-Z order */
ok("yaw +90 maps +X to -Z", vnear(rotate(M.qFromEulerYXZ(90 * D, 0, 0), [1, 0, 0]), [0, 0, -1], 1e-9));
ok("pitch +90 maps +Y to +Z", vnear(rotate(M.qFromEulerYXZ(0, 90 * D, 0), [0, 1, 0]), [0, 0, 1], 1e-9));
ok("roll +90 maps +X to +Y", vnear(rotate(M.qFromEulerYXZ(0, 0, 90 * D), [1, 0, 0]), [0, 1, 0], 1e-9));

/* composition: yaw applied before pitch? intrinsic Y then X then Z:
 * q = qy*qx*qz, so the first rotation applied to the vector is qz (roll). */
const q = M.qFromEulerYXZ(90 * D, 0, 90 * D);
ok("roll then yaw: +X -> +Y -> +Y", vnear(rotate(q, [1, 0, 0]), [0, 1, 0], 1e-9));

/* slerp */
const a = M.qFromEulerYXZ(0, 0, 0), b = M.qFromEulerYXZ(90 * D, 0, 0);
ok("slerp t=0", vnear(M.qSlerp(a, b, 0), a, 1e-9));
ok("slerp t=1", vnear(M.qSlerp(a, b, 1), b, 1e-9));
const mid = M.qSlerp(a, b, 0.5);
ok("slerp midpoint is unit", near(Math.hypot(...mid), 1, 1e-9));
ok("slerp midpoint is 45 deg", vnear(rotate(mid, [1, 0, 0]), [Math.SQRT1_2, 0, -Math.SQRT1_2], 1e-9));

/* zero-pose pipeline: display = raw * inverse(raw0); at t0 it is identity */
const raw0 = M.qFromEulerYXZ(20 * D, -10 * D, 5 * D);
const zeroInv = M.qInv(raw0);
const atZero = M.qMul(raw0, zeroInv);
ok("zero pipeline gives identity", vnear(atZero, [1, 0, 0, 0], 1e-9));
const later = M.qMul(raw0, zeroInv);
ok("zero shift identity for the same pose", vnear(later, [1, 0, 0, 0], 1e-9));
const raw0y = M.qFromEulerYXZ(20 * D, 0, 0);
const shown = M.qMul(M.qFromEulerYXZ(60 * D, 0, 0), M.qInv(raw0y));
ok("zero shift keeps 40 deg yaw", vnear(rotate(shown, [1, 0, 0]), rotate(M.qFromEulerYXZ(40 * D, 0, 0), [1, 0, 0]), 1e-9));

/* matrix from quaternion is orthonormal, determinant +1 */
const mq = M.mat4FromQuat(M.qFromEulerYXZ(31 * D, -22 * D, 17 * D));
const cols = [[mq[0], mq[1], mq[2]], [mq[4], mq[5], mq[6]], [mq[8], mq[9], mq[10]]];
const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
ok("columns unit", cols.every((c) => near(dot(c, c), 1, 1e-6)));
ok("columns orthogonal", near(dot(cols[0], cols[1]), 0, 1e-6) && near(dot(cols[0], cols[2]), 0, 1e-6) && near(dot(cols[1], cols[2]), 0, 1e-6));
const det = dot(cols[0], [cols[1][1] * cols[2][2] - cols[1][2] * cols[2][1],
                          cols[1][2] * cols[2][0] - cols[1][0] * cols[2][2],
                          cols[1][0] * cols[2][1] - cols[1][1] * cols[2][0]]);
ok("determinant +1", near(det, 1, 1e-6));
ok("matrix matches quaternion rotation", vnear(matVec(mq, [0.3, -0.4, 0.5, 1]).slice(0, 3),
                                               rotate(M.qFromEulerYXZ(31 * D, -22 * D, 17 * D), [0.3, -0.4, 0.5]), 1e-6));

/* lookAt: the target lands on the -Z axis at distance |eye| */
const eye = [1.2, 0.8, 2.4];
const view = M.mat4LookAt(eye, [0, 0, 0], [0, 1, 0]);
const center = matVec(view, [0, 0, 0]);
ok("lookAt target at -distance Z", near(center[0], 0, 1e-6) && near(center[1], 0, 1e-6) && near(center[2], -Math.hypot(...eye), 1e-6));
const eyeView = matVec(view, eye);
ok("lookAt eye at origin", near(eyeView[0], 0, 1e-6) && near(eyeView[1], 0, 1e-6) && near(eyeView[2], 0, 1e-6));

/* perspective: near plane -> ndc z = -1, far -> +1 */
const P = M.mat4Perspective(45 * D, 1.5, 0.1, 40);
const pn = matVec(P, [0, 0, -0.1]);
ok("near plane ndc -1", near(pn[2] / pn[3], -1, 1e-5));
const pf = matVec(P, [0, 0, -40]);
ok("far plane ndc +1", near(pf[2] / pf[3], 1, 1e-5));

console.log(`\nPASS ${n} checks`);
