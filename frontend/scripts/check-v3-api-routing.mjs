#!/usr/bin/env node
/**
 * Slice 1B: fail if frontend routing still points at ERP V1 (:8000).
 * Scans source + production build assets only (active runtime paths).
 */
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const banned = /127\.0\.0\.1:8000|:8000\/api|http:\/\/[^"'`\s]*:8000/;
const errors = [];

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

function checkFile(path, { allowCommentBan = true } = {}) {
  const text = readFileSync(path, "utf8");
  const rel = relative(frontendRoot, path);
  if (path.endsWith("vite.config.ts")) {
    if (!/target:\s*["']http:\/\/127\.0\.0\.1:8100["']/.test(text)) {
      errors.push(`${rel}: Vite /api proxy must target http://127.0.0.1:8100`);
    }
    if (/target:\s*["'][^"']*:8000["']/.test(text)) {
      errors.push(`${rel}: Vite proxy must not target :8000`);
    }
    return;
  }
  if (path.endsWith("client.ts")) {
    if (!/DEFAULT_BASE\s*=\s*["']\/api\/v1["']/.test(text)) {
      errors.push(`${rel}: DEFAULT_BASE must be /api/v1`);
    }
    if (/DEFAULT_BASE\s*=\s*["'][^"']*:8000[^"']*["']/.test(text)) {
      errors.push(`${rel}: DEFAULT_BASE must not use :8000`);
    }
    return;
  }
  if (path.endsWith("live-runtime.js")) {
    if (!/V3_API_BASE\s*\|\|\s*["']\/api\/v1["']/.test(text)) {
      errors.push(`${rel}: live-runtime default must be /api/v1`);
    }
  }
  if (banned.test(text) && allowCommentBan) {
    // Dist/runtime: any active :8000 URL is forbidden.
    if (rel.startsWith("dist/") || path.endsWith("live-runtime.js")) {
      errors.push(`${rel}: contains ERP V1 :8000 reference`);
    }
  }
}

checkFile(join(frontendRoot, "vite.config.ts"));
checkFile(join(frontendRoot, "src/api/client.ts"));
checkFile(join(frontendRoot, "public/live-runtime.js"));

for (const file of walk(join(frontendRoot, "dist"))) {
  if (/\.(js|css|html|map)$/.test(file)) checkFile(file);
}

if (errors.length) {
  console.error("V3 API routing check FAILED:");
  for (const e of errors) console.error(" -", e);
  process.exit(1);
}
console.log("V3 API routing check PASS (same-origin /api/v1, Vite → :8100, no :8000 in dist)");
