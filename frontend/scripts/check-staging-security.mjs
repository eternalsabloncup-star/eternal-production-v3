#!/usr/bin/env node
/** Slice 1C: Private Staging frontend security wiring check. */
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const errors = [];

function read(rel) {
  const p = join(root, rel);
  if (!existsSync(p)) {
    errors.push(`missing ${rel}`);
    return "";
  }
  return readFileSync(p, "utf8");
}

const production = read("public/production.html");
const live = read("public/live-runtime.js");
const app = read("src/App.tsx");
const client = read("src/api/client.ts");

if (!/id=["']v3-auth-gate["']/.test(production)) {
  errors.push("production.html missing early v3-auth-gate");
}
if (!/v3-auth-pending/.test(production)) {
  errors.push("production.html missing auth-pending hide");
}
const gateAt = production.indexOf("v3-auth-gate");
const rootAt = production.indexOf('<div id="root"');
if (!(gateAt >= 0 && rootAt > gateAt)) {
  errors.push("auth gate must appear before #root");
}

if (!/\/auth\/me/.test(live)) errors.push("live-runtime must call /auth/me");
if (!/verifySession/.test(live)) errors.push("live-runtime missing verifySession");
if (!/location\.replace\(\s*["']\/["']\s*\)/.test(live)) {
  errors.push("live-runtime must redirect to login on auth failure");
}
if (!/mode\s*!==\s*["']live["']/.test(live)) {
  errors.push("live-runtime must reject non-live Accurate payloads");
}
if (!/V3_API_BASE\s*\|\|\s*["']\/api\/v1["']/.test(live)) {
  errors.push("live-runtime must default to /api/v1");
}
if (/127\.0\.0\.1:8000|:8000\/api/.test(live)) {
  errors.push("live-runtime must not target ERP V1 :8000");
}
if (!/function publishOrders\s*\(/.test(live)) {
  errors.push("live-runtime missing publishOrders shared-state helper");
}
if (!/var orders=\[\]/.test(production)) {
  errors.push("production.html must use var orders (shared with window.orders)");
}
if (/let orders=\[\]/.test(production)) {
  errors.push("production.html must not use let orders (breaks window.orders sync)");
}
for (const hook of ["v3OpenWorkflow", "v50RefreshInbox", "v3Logout"]) {
  if (!live.includes(hook)) errors.push(`live-runtime missing ${hook}`);
}

if (!/\/auth\/login/.test(app)) errors.push("App.tsx missing login API");
if (!/epv3_access_token/.test(app)) errors.push("App.tsx missing token key");
if (/DEFAULT_BASE\s*=\s*["'][^"']*8000/.test(client)) {
  errors.push("api client must not default to port 8000");
}

if (errors.length) {
  console.error("Staging security check FAILED:");
  for (const e of errors) console.error(" -", e);
  process.exit(1);
}
console.log("Staging security check PASS");
