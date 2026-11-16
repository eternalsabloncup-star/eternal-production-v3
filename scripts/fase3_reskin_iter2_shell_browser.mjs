/**
 * Reskin Iter2 — Global Shell browser acceptance (test API only).
 * Viewports 1440×900 and 1366×768: sidebar/header/collapse/nav/sticky.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_RESKIN_STATIC_PORT || 4183);
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

const SECTIONS = [
  "schedule",
  "tasks",
  "paymentMonitor",
  "shippingSchedule",
  "settings",
  "inbox",
  "bufferMonitor",
];

async function runViewport(width, height, tag) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument((token) => {
    localStorage.setItem("epv3_access_token", token);
    localStorage.setItem("eternal_v3_sidebar_collapsed_v41", "0");
    window.V3_API_BASE = "/api/v1";
  }, access_token);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "networkidle0",
    timeout: 90000,
  });
  await sleep(2500);

  const before = path.join(OUT, `fase3-iter2-shell-${tag}-expanded.png`);
  await page.screenshot({ path: before, fullPage: false });

  const probe = await page.evaluate(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const side = document.getElementById("v41-primary-sidebar");
    const handle = document.getElementById("v44-sidebar-handle");
    const app = document.getElementById("v3-app");
    const top = document.querySelector("#v3-app .top");
    const cs = side ? getComputedStyle(side) : null;
    const hs = handle ? getComputedStyle(handle) : null;
    const sideRect = side ? side.getBoundingClientRect() : null;
    const handleRect = handle ? handle.getBoundingClientRect() : null;
    const out = {
      sideBg: cs ? cs.backgroundColor : null,
      activeBg: (() => {
        const a = document.querySelector("#v41-primary-sidebar .navbtn.active");
        return a ? getComputedStyle(a).backgroundColor : null;
      })(),
      sideWidth: sideRect ? Math.round(sideRect.width) : null,
      handlePosition: hs ? hs.position : null,
      handleInsideAside: !!(handle && side && side.contains(handle)),
      // absolute right:-13px → handle straddles the sidebar's right edge (not floating mid-content)
      handleAttached:
        !!(sideRect && handleRect) &&
        handleRect.left < sideRect.right &&
        handleRect.right > sideRect.right - 1 &&
        handleRect.left > sideRect.right - handleRect.width - 2,
      topHeight: top ? Math.round(top.getBoundingClientRect().height) : null,
      navCount: document.querySelectorAll("#v41-primary-sidebar .navbtn").length,
      activeBefore: document.querySelector("#v41-primary-sidebar .navbtn.active")?.title || null,
      crumb: document.getElementById("v3-page-crumb")?.textContent || null,
      branchChip: document.querySelector(".v3-branch-chip")?.textContent || null,
      userChip: document.getElementById("v3-user-chip")?.textContent || null,
      gwText: document.getElementById("v3-conn-gw")?.textContent || null,
      sections: {},
      collapsedWidth: null,
      collapsedNavClickable: false,
      stickyOk: false,
      overflowX: false,
      scheduleToolbarOrder: null,
    };

    const go = window.go;
    for (const id of [
      "schedule",
      "tasks",
      "paymentMonitor",
      "shippingSchedule",
      "settings",
      "inbox",
      "bufferMonitor",
    ]) {
      if (typeof go === "function") go(id);
      await sleep(700);
      const active = document.querySelector("#v41-primary-sidebar .navbtn.active");
      out.sections[id] = {
        activeTitle: active?.getAttribute("title") || active?.textContent?.trim() || null,
        crumb: document.getElementById("v3-page-crumb")?.textContent || null,
        hasMain: !!document.querySelector("#v3-app .main .content"),
      };
    }

    if (typeof go === "function") go("schedule");
    await sleep(1200);
    const overview = document.getElementById("scheduleOverview");
    const sheetbar = document.querySelector("#v3-app.section-schedule .sheetbar");
    if (overview && sheetbar) {
      const oy = overview.getBoundingClientRect().top;
      const sy = sheetbar.getBoundingClientRect().top;
      out.scheduleToolbarOrder = oy <= sy ? "overview-before-sheetbar" : "sheetbar-before-overview";
    }
    const th = document.querySelector("table.excel-sheet thead th[data-column='id']");
    const x0 = th ? th.getBoundingClientRect().x : null;
    const wrap = document.querySelector(".sheetwrap");
    if (wrap) {
      wrap.scrollLeft = 180;
      await sleep(200);
      const th2 = document.querySelector("table.excel-sheet thead th[data-column='id']");
      const x1 = th2 ? th2.getBoundingClientRect().x : null;
      out.stickyOk = x0 != null && x1 != null && Math.abs(x1 - x0) < 3;
      wrap.scrollLeft = 0;
    }
    out.overflowX = document.documentElement.scrollWidth > window.innerWidth + 2;

    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(false);
    await sleep(400);
    const side2 = document.getElementById("v41-primary-sidebar");
    out.collapsedWidth = side2 ? Math.round(side2.getBoundingClientRect().width) : null;
    out.collapsedHidden = document.body.classList.contains("v41-nav-collapsed");
    const btn = document.querySelector("#v41-primary-sidebar .navbtn");
    if (btn) {
      btn.click();
      await sleep(500);
      out.collapsedNavClickable = !!document.querySelector("#v3-app .main .content");
    }
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
    await sleep(300);
    return out;
  });

  const afterCollapse = path.join(OUT, `fase3-iter2-shell-${tag}-collapsed-nav.png`);
  // leave expanded for final shot
  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
    if (typeof window.go === "function") window.go("schedule");
  });
  await sleep(800);
  const after = path.join(OUT, `fase3-iter2-shell-${tag}-schedule.png`);
  await page.screenshot({ path: after, fullPage: false });

  // collapsed screenshot
  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(false);
  });
  await sleep(400);
  await page.screenshot({ path: afterCollapse, fullPage: false });

  await page.close();
  return {
    tag,
    width,
    height,
    errors,
    probe,
    shots: { before, after, afterCollapse },
  };
}

const results = [];
results.push(await runViewport(1440, 900, "1440x900"));
results.push(await runViewport(1366, 768, "1366x768"));

await browser.close();
server.close();

const summary = {
  ok: results.every((r) => {
    const p = r.probe;
    return (
      p.sideWidth >= 210 &&
      p.sideWidth <= 240 &&
      /rgb\(\s*16,\s*45,\s*39\s*\)/.test(String(p.sideBg || "")) &&
      /rgb\(\s*33,\s*76,\s*60\s*\)/.test(String(p.activeBg || "")) &&
      p.handleInsideAside &&
      p.handleAttached &&
      p.navCount >= 12 &&
      p.collapsedWidth >= 55 &&
      p.collapsedWidth <= 80 &&
      p.collapsedNavClickable &&
      p.scheduleToolbarOrder === "overview-before-sheetbar" &&
      p.stickyOk &&
      !p.overflowX &&
      p.gwText &&
      !/online/i.test(p.gwText) &&
      Object.keys(p.sections).length >= 7 &&
      r.errors.length === 0
    );
  }),
  results,
};

fs.writeFileSync(path.join(OUT, "fase3-iter2-shell-report.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
process.exit(summary.ok ? 0 : 1);
