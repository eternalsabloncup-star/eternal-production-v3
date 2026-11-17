/**
 * Reskin Iter1 — Jadwal + Kontrol browser acceptance (test API only).
 * Captures 1440×900 and 1366×768 screenshots; probes sticky/filter/KPI DOM.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_RESKIN_STATIC_PORT || 4182);
const OUT = process.env.V3_RESKIN_OUT || "/opt/cursor/artifacts";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

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

async function runViewport(width, height, tag) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument((token) => {
    localStorage.setItem("epv3_access_token", token);
    window.V3_API_BASE = "/api/v1";
  }, access_token);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 30000 },
  );
  await page.evaluate(() => window.go && window.go("schedule"));
  await page
    .waitForFunction(
      () =>
        document.getElementById("v3-kontrol-qty") ||
        /Memuat Jadwal|Gagal memuat|Jadwal Produksi/i.test(document.body.innerText || ""),
      { timeout: 20000 },
    )
    .catch(() => {});
  await sleep(800);
  await page.evaluate(async () => {
    const semua = [...document.querySelectorAll("[data-ops='sched-bucket']")].find((b) =>
      /^Semua$/i.test((b.textContent || "").trim()),
    );
    if (semua) {
      semua.click();
      await new Promise((r) => setTimeout(r, 700));
    }
  });
  await sleep(900);

  // Screenshot on bucket Semua (before HOLD interaction probe).
  const shot = path.join(OUT, `fase3-reskin-iter1-jadwal-${tag}.png`);
  await page.screenshot({ path: shot, fullPage: false });

  const probe = await page.evaluate(async () => {
    const out = {
      title: (document.querySelector(".heading h1") || {}).textContent || "",
      sectionClass: (document.getElementById("v3-app") || {}).className || "",
      kontrolCards: document.querySelectorAll("#v3-kontrol-qty .final-kpi").length,
      statusKerja: (document.getElementById("v3-status-kerja") || {}).textContent || "",
      sticky: (document.querySelector("table.excel-sheet") || {}).dataset?.v3Sticky || "",
      theadBg: null,
      bucketHold: false,
      bucketSemuaRestored: false,
      search: false,
      pageBodyScrollX: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2,
      sheetScrollX: false,
      sortBtn: false,
      colMenu: false,
      kpiLabels: [...document.querySelectorAll("#v3-kontrol-qty .final-kpi small")].map((el) => (el.textContent || "").trim()),
    };
    const th = document.querySelector(
      'table.excel-sheet thead tr:not(.sheet-group-row) th[data-column="id"]',
    );
    if (th) out.theadBg = getComputedStyle(th).backgroundColor;
    const wrap = document.querySelector(".sheetwrap");
    if (wrap) {
      out.sheetScrollX = wrap.scrollWidth > wrap.clientWidth + 2;
      const x0 = th ? th.getBoundingClientRect().x : null;
      wrap.scrollLeft = Math.min(wrap.scrollWidth, wrap.scrollLeft + 160);
      await new Promise((r) => setTimeout(r, 40));
      const th2 = document.querySelector(
        'table.excel-sheet thead tr:not(.sheet-group-row) th[data-column="id"]',
      );
      out.stickyLeftAfter = th2 ? th2.getBoundingClientRect().x : null;
      out.stickyHold = x0 != null && out.stickyLeftAfter != null && Math.abs(out.stickyLeftAfter - x0) < 3;
      wrap.scrollLeft = 0;
    }
    const hold = [...document.querySelectorAll("[data-ops='sched-bucket']")].find((b) =>
      /HOLD/i.test(b.textContent || ""),
    );
    if (hold) {
      hold.click();
      out.bucketHold = true;
      await new Promise((r) => setTimeout(r, 350));
    }
    const semua = [...document.querySelectorAll("[data-ops='sched-bucket']")].find((b) =>
      /^Semua$/i.test((b.textContent || "").trim()),
    );
    if (semua) {
      semua.click();
      out.bucketSemuaRestored = true;
      await new Promise((r) => setTimeout(r, 350));
    }
    const q = document.getElementById("v3-sched-q");
    if (q) {
      q.value = "SMOKE";
      q.dispatchEvent(new Event("input", { bubbles: true }));
      out.search = true;
    }
    out.sortBtn = !!document.querySelector(".sheet-filter-trigger, [data-sort], th .sheet-th");
    out.colMenu = !!document.querySelector("details.v40-columns-menu, [data-column-visibility]");
    return out;
  });
  await page.close();
  return { viewport: { width, height }, probe, shot, errors: errors.slice(0, 8) };
}

const results = {
  ok: false,
  viewports: [],
};

results.viewports.push(await runViewport(1440, 900, "1440x900"));
results.viewports.push(await runViewport(1366, 768, "1366x768"));

await browser.close();
server.close();

results.ok = results.viewports.every(
  (v) =>
    /Jadwal Produksi/i.test(v.probe.title) &&
    v.probe.kontrolCards >= 5 &&
    v.probe.sticky === "id,name" &&
    v.probe.pageBodyScrollX === true &&
    v.probe.sectionClass.includes("section-schedule"),
);

console.log(JSON.stringify(results, null, 2));
process.exit(results.ok ? 0 : 1);
