/**
 * Phase 3.1 browser smoke against live API + static V49.
 * Uses system Chrome. Does not invent transaction success.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_SMOKE_STATIC_PORT || 4177);

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  let rel = decodeURIComponent(url.pathname);
  if (rel === "/") rel = "/production.html";
  const file = path.join(publicDir, rel.replace(/^\//, ""));
  if (!file.startsWith(publicDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404);
    res.end("missing");
    return;
  }
  res.writeHead(200, { "Content-Type": contentType(file) });
  fs.createReadStream(file).pipe(res);
});

await new Promise((resolve) => server.listen(STATIC_PORT, "127.0.0.1", resolve));

const login = await fetch(API + "/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "smoke.lead", password: "secret-pass" }),
});
if (!login.ok) {
  console.error("LOGIN_FAIL", login.status, await login.text());
  process.exit(2);
}
const { access_token } = await login.json();

const puppeteerMod = process.env.PUPPETEER_CORE_PATH
  ? await import(process.env.PUPPETEER_CORE_PATH)
  : await import(
      "/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js"
    );
const puppeteer = puppeteerMod.default || puppeteerMod;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.evaluateOnNewDocument(
  (token, api) => {
    localStorage.setItem("epv3_access_token", token);
    window.V3_API_BASE = api;
  },
  access_token,
  API,
);

const errors = [];
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
await page.waitForFunction(() => typeof window.v3Api === "object", {
  timeout: 15000,
});

const probes = await page.evaluate(async () => {
  const out = {
    hasEscape: typeof window.v3Api.escapeHtml === "function",
    escapeOk:
      window.v3Api.escapeHtml('<img src=x onerror=alert(1)>') ===
      "&lt;img src=x onerror=alert(1)&gt;",
    demoAdvanceBlocked: false,
    createIsExplicit: typeof window.v3EnsureJob === "function",
  };
  if (typeof window.advance === "function") {
    const r = window.advance("SO/X", "schedule");
    out.demoAdvanceBlocked = r === false;
  }
  // Opening detail must not POST create — lookup only.
  const before = await fetch(
    (window.V3_API_BASE || "/api/v1") + "/production/jobs/by-so/" + encodeURIComponent("SO/SMOKE/NONE"),
    { headers: { Authorization: "Bearer " + localStorage.getItem("epv3_access_token") } },
  );
  out.lookup404 = before.status === 404;
  return out;
});

await browser.close();
server.close();

const ok =
  probes.hasEscape &&
  probes.escapeOk &&
  probes.demoAdvanceBlocked &&
  probes.createIsExplicit &&
  probes.lookup404 &&
  errors.length === 0;

console.log(JSON.stringify({ ok, probes, errors }, null, 2));
process.exit(ok ? 0 : 1);
