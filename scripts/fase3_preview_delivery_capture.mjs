/**
 * Preview delivery capture — real browser PNGs for Cursor chat artifacts.
 * Writes uniquely named files under /opt/cursor/artifacts (do not overwrite).
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_PREVIEW_STATIC_PORT || 4191);
const OUT = process.env.V3_PREVIEW_OUT || "/opt/cursor/artifacts";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");
const STAMP = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const PREFIX = `epv3_iter2_preview_${STAMP}`;

fs.mkdirSync(OUT, { recursive: true });

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  if (url.pathname.startsWith("/api/")) {
    try {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      const init = {
        method: req.method || "GET",
        headers: {
          authorization: req.headers.authorization || "",
          accept: "application/json",
        },
      };
      if (req.headers["content-type"]) init.headers["content-type"] = req.headers["content-type"];
      const body = Buffer.concat(chunks);
      if (!["GET", "HEAD"].includes(init.method) && body.length) init.body = body;
      const upstream = await fetch(API_ORIGIN + url.pathname + url.search, init);
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") || "application/json",
      });
      res.end(buf);
    } catch (e) {
      res.writeHead(502);
      res.end(String(e));
    }
    return;
  }
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

await new Promise((r) => server.listen(STATIC_PORT, "127.0.0.1", r));

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

const puppeteerMod = await import(
  process.env.PUPPETEER_CORE_PATH ||
    "/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js"
);
const puppeteer = puppeteerMod.default || puppeteerMod;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function verifyPng(file) {
  const st = fs.statSync(file);
  if (st.size < 5000) throw new Error("PNG too small: " + file + " " + st.size);
  const buf = fs.readFileSync(file);
  if (buf[0] !== 0x89 || buf[1] !== 0x50 || buf[2] !== 0x4e || buf[3] !== 0x47) {
    throw new Error("Not PNG magic: " + file);
  }
  let dims = null;
  try {
    const out = execFileSync("file", ["-b", file], { encoding: "utf8" }).trim();
    const m = out.match(/(\d+)\s*x\s*(\d+)/);
    if (m) dims = { w: Number(m[1]), h: Number(m[2]) };
  } catch (_) {}
  return { bytes: st.size, dims };
}

async function waitReady(page) {
  await page.waitForFunction(
    () => {
      const app = document.getElementById("v3-app");
      if (!app) return false;
      const text = (app.innerText || "").toLowerCase();
      if (text.includes("memuat jadwal produksi dari postgresql")) return false;
      return true;
    },
    { timeout: 45000 }
  );
  await sleep(1200);
}

async function captureViewport(width, height, tag) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument((token) => {
    localStorage.setItem("epv3_access_token", token);
    localStorage.setItem("eternal_v3_sidebar_collapsed_v41", "0");
    window.V3_API_BASE = "/api/v1";
  }, access_token);
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "networkidle0",
    timeout: 90000,
  });
  await waitReady(page);

  const shots = [];

  async function shot(name, prep) {
    if (prep) await prep();
    await sleep(600);
    const file = path.join(OUT, `${PREFIX}_${tag}_${name}.png`);
    await page.screenshot({ path: file, fullPage: false, type: "png" });
    const meta = verifyPng(file);
    const probe = await page.evaluate(() => {
      const app = document.getElementById("v3-app");
      const side = document.getElementById("v41-primary-sidebar");
      const active = document.querySelector("#v41-primary-sidebar .navbtn.active");
      const bodyText = (app?.innerText || "").slice(0, 240);
      return {
        section: document.getElementById("v3-app")?.className || "",
        crumb: document.getElementById("v3-page-crumb")?.textContent || "",
        active: active?.getAttribute("title") || active?.textContent?.trim() || "",
        sideW: side ? Math.round(side.getBoundingClientRect().width) : 0,
        collapsed: document.body.classList.contains("v41-nav-collapsed"),
        hasKontrol: !!document.getElementById("v3-kontrol-qty"),
        blank: !(app && (app.innerText || "").trim().length > 40),
        bodySnippet: bodyText,
      };
    });
    if (probe.blank) throw new Error("Blank UI for " + name);
    shots.push({ name, file, ...meta, probe, pageErrors: pageErrors.slice() });
  }

  // 1 sidebar expanded on schedule
  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
    if (typeof window.go === "function") window.go("schedule");
  });
  await waitReady(page);
  await shot("01_jadwal_sidebar_expanded");

  // 2 kontrol produksi (same schedule page, ensure KPI visible)
  await shot("02_kontrol_produksi", async () => {
    await page.evaluate(() => {
      const el = document.getElementById("v3-kontrol-qty") || document.getElementById("scheduleOverview");
      if (el) el.scrollIntoView({ block: "start" });
    });
  });

  // 3 tugas tim
  await shot("03_tugas_tim", async () => {
    await page.evaluate(() => {
      if (typeof window.go === "function") window.go("tasks");
    });
    await sleep(1500);
  });

  // 4 monitoring penerimaan
  await shot("04_monitoring_penerimaan", async () => {
    await page.evaluate(() => {
      if (typeof window.go === "function") window.go("paymentMonitor");
    });
    await sleep(1500);
  });

  // 5 sidebar collapsed (on schedule)
  await shot("05_sidebar_collapsed", async () => {
    await page.evaluate(() => {
      if (typeof window.go === "function") window.go("schedule");
      if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(false);
    });
    await sleep(800);
  });

  // 6 sidebar expanded again (explicit)
  await shot("06_sidebar_expanded_again", async () => {
    await page.evaluate(() => {
      if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
    });
    await sleep(500);
  });

  await page.close();
  return { tag, width, height, shots, pageErrors };
}

const results = [];
results.push(await captureViewport(1440, 900, "1440x900"));
results.push(await captureViewport(1366, 768, "1366x768"));

await browser.close();
server.close();

const manifest = {
  prefix: PREFIX,
  out: OUT,
  branch: "cursor/epv3-production-schedule-83bf",
  worktree: root,
  results,
  ok: results.every((r) => r.shots.every((s) => s.bytes > 5000 && !s.probe.blank)),
};
const manifestPath = path.join(OUT, `${PREFIX}_manifest.json`);
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
console.log(JSON.stringify({ ok: manifest.ok, manifestPath, files: results.flatMap((r) => r.shots.map((s) => ({ file: s.file, bytes: s.bytes, dims: s.dims, name: s.name, tag: r.tag }))) }, null, 2));
process.exit(manifest.ok ? 0 : 1);
