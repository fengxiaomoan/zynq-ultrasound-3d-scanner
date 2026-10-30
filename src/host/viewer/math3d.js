/* Minimal 3D math shared by the F1 viewer and its Node tests.
 * Quaternions are [w, x, y, z]; matrices are column-major Float32Array(16).
 */
(function (root) {
  "use strict";
  const Q_ID = [1, 0, 0, 0];

  const qMul = (a, b) => [
    a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
    a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
    a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
    a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
  ];
  const qInv = (q) => [q[0], -q[1], -q[2], -q[3]];
  const qNorm = (q) => {
    const n = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
  };

  /* Intrinsic Y-X-Z, matching three.js Euler order 'YXZ':
   * yaw about Y, then pitch about X, then roll about Z. */
  function qFromEulerYXZ(yaw, pitch, roll) {
    const cy = Math.cos(yaw / 2), sy = Math.sin(yaw / 2);
    const cx = Math.cos(pitch / 2), sx = Math.sin(pitch / 2);
    const cz = Math.cos(roll / 2), sz = Math.sin(roll / 2);
    const qy = [cy, 0, sy, 0], qx = [cx, sx, 0, 0], qz = [cz, 0, 0, sz];
    return qNorm(qMul(qMul(qy, qx), qz));
  }

  function qSlerp(a, b, t) {
    let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
    let bb = b;
    if (d < 0) { d = -d; bb = [-b[0], -b[1], -b[2], -b[3]]; }
    if (d > 0.9995) {
      return qNorm([
        a[0] + (bb[0] - a[0]) * t, a[1] + (bb[1] - a[1]) * t,
        a[2] + (bb[2] - a[2]) * t, a[3] + (bb[3] - a[3]) * t,
      ]);
    }
    const th = Math.acos(Math.min(1, d));
    const s = Math.sin(th);
    const w1 = Math.sin((1 - t) * th) / s;
    const w2 = Math.sin(t * th) / s;
    return [a[0] * w1 + bb[0] * w2, a[1] * w1 + bb[1] * w2,
            a[2] * w1 + bb[2] * w2, a[3] * w1 + bb[3] * w2];
  }

  function mat4Perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ]);
  }

  function mat4LookAt(eye, center, up) {
    let z = [eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]];
    let l = Math.hypot(z[0], z[1], z[2]) || 1;
    z = z.map((v) => v / l);
    let x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]];
    l = Math.hypot(x[0], x[1], x[2]) || 1;
    x = x.map((v) => v / l);
    const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -(x[0] * eye[0] + x[1] * eye[1] + x[2] * eye[2]),
      -(y[0] * eye[0] + y[1] * eye[1] + y[2] * eye[2]),
      -(z[0] * eye[0] + z[1] * eye[1] + z[2] * eye[2]), 1,
    ]);
  }

  function mat4FromQuat(q) {
    const [w, x, y, z] = q;
    return new Float32Array([
      1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y), 0,
      2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x), 0,
      2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y), 0,
      0, 0, 0, 1,
    ]);
  }

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const api = { Q_ID, qMul, qInv, qNorm, qFromEulerYXZ, qSlerp,
                mat4Perspective, mat4LookAt, mat4FromQuat, clamp };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Math3D = api;
})(typeof window !== "undefined" ? window : globalThis);
