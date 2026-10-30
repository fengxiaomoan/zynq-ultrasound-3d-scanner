/* Static DOM contract: every element id used by app.js must exist in index.html.
 * Run: node f1_viewer/tests/test_dom.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");

let checks = 0;
function ok(name, cond) {
  checks++;
  if (!cond) { console.error("FAIL " + name); process.exit(1); }
  console.log("ok " + name);
}

const ids = [...app.matchAll(/\$\("([^"]+)"\)/g)].map((m) => m[1]);
const uniq = [...new Set(ids)].sort();
const missing = uniq.filter((id) => !html.includes(`id="${id}"`));
ok("all JS ids exist in HTML", missing.length === 0);
if (missing.length) console.error("missing: " + missing.join(", "));

ok("math3d loaded before app.js",
   html.indexOf("/math3d.js") >= 0 &&
   html.indexOf("/math3d.js") < html.indexOf("/app.js"));
ok("canvas element present", html.includes('id="view"'));
ok("model select present", html.includes('id="model"'));
ok("provenance chip present", html.includes('id="m-prov"'));
ok("status element present", html.includes('id="status"'));

console.log(`\nPASS ${checks} checks`);
