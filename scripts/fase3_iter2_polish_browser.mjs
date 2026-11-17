/**
 * Iter2 visual polish acceptance — real browser, unique artifact names.
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
const STATIC_PORT = Number(process.env.V3_POLISH_STATIC_PORT || 4192);
const OUT = process.env.V3_POLISH_OUT || "/opt/cursor/artifacts";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");
const STAMP = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const PREFIX = `epv3_iter2_polish_${STAMP}`;

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
  if (st.size < 5000) throw new Error("too small " + file);
  const buf = fs.readFileSync(file);
  if (buf[0] !== 0x89 || buf[1] !== 0x50) throw new Error("not png " + file);
  const info = execFileSync("file", ["-b", file], { encoding: "utf8" }).trim();
  const m = info.match(/(\d+)\s*x\s*(\d+)/);
  return { bytes: st.size, dims: m ? { w: +m[1], h: +m[2] } : null, info };
}

function isLightBg(rgb) {
  const m = String(rgb || "").match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return false;
  const [r, g, b] = [+m[1], +m[2], +m[3]];
  // treat near-white / light gray-green as bad for dark sidebar inactive items
  return r > 180 && g > 180 && b > 180;
}

async function runViewport(width, height, tag) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument((token) => {
    localStorage.setItem("epv3_access_token", token);
    localStorage.setItem("eternal_v3_sidebar_collapsed_v41", "0");
    window.V3_API_BASE = "/api/v1";
  }, access_token);
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "networkidle0",
    timeout: 90000,
  });
  await sleep(2200);
  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
    if (typeof window.go === "function") window.go("schedule");
  });
  await sleep(1500);

  const shots = {};
  async function shot(key) {
    const file = path.join(OUT, `${PREFIX}_${tag}_${key}.png`);
    await page.screenshot({ path: file, fullPage: false, type: "png" });
    shots[key] = { file, ...verifyPng(file) };
  }

  await shot("01_expanded_jadwal");
  await page.evaluate(() => {
    const k = document.getElementById("v3-kontrol-qty");
    if (k) k.scrollIntoView({ block: "start" });
  });
  await sleep(300);
  await shot("02_header_and_kpi");

  const probe = await page.evaluate(() => {
    const side = document.getElementById("v41-primary-sidebar");
    const btns = [...document.querySelectorAll("#v41-primary-sidebar .navbtn")];
    const nav = btns.map((b) => {
      const cs = getComputedStyle(b);
      const label = b.querySelector(".nav-label");
      const lcs = label ? getComputedStyle(label) : null;
      return {
        title: b.getAttribute("title"),
        active: b.classList.contains("active"),
        bg: cs.backgroundColor,
        color: cs.color,
        labelBg: lcs ? lcs.backgroundColor : null,
      };
    });
    const active = nav.find((n) => n.active);
    const inactiveLight = nav.filter((n) => !n.active && /rgb\(\s*2[0-5]\d/.test(n.bg));
    const kpi = [...document.querySelectorAll("#v3-kontrol-qty .final-kpi strong")].map((el) =>
      (el.textContent || "").replace(/\s+/g, " ").trim()
    );
    const top = document.querySelector("#v3-app .top");
    const topH = top ? Math.round(top.getBoundingClientRect().height) : 0;
    const th = document.querySelector("table.excel-sheet thead th[data-column='id']");
    const x0 = th ? th.getBoundingClientRect().x : null;
    const wrap = document.querySelector(".sheetwrap");
    let stickyOk = false;
    if (wrap && th) {
      wrap.scrollLeft = 220;
      const x1 = th.getBoundingClientRect().x;
      stickyOk = Math.abs(x1 - x0) < 3;
      wrap.scrollLeft = 0;
    }
    const kpiRow = document.querySelector("#v3-kontrol-qty");
    let kpiOneRow = false;
    if (kpiRow) {
      const cards = [...kpiRow.querySelectorAll(".final-kpi")];
      if (cards.length >= 5) {
        const tops = cards.slice(0, 5).map((c) => Math.round(c.getBoundingClientRect().top));
        kpiOneRow = tops.every((t) => Math.abs(t - tops[0]) < 4);
      }
    }
    return {
      sideBg: side ? getComputedStyle(side).backgroundColor : null,
      sideW: side ? Math.round(side.getBoundingClientRect().width) : 0,
      nav,
      activeBg: active ? active.bg : null,
      inactiveLightCount: inactiveLight.length,
      labelLightCount: nav.filter((n) => n.labelBg && /rgb\(\s*2[2-5]\d/.test(n.labelBg)).length,
      topH,
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
      kpi,
      kpiOneRow,
      stickyOk,
      navCount: btns.length,
      handleInside: !!(document.getElementById("v44-sidebar-handle")?.closest(".side")),
    };
  });

  // horizontal scroll shot
  await page.evaluate(() => {
    const wrap = document.querySelector(".sheetwrap");
    if (wrap) wrap.scrollLeft = 260;
  });
  await sleep(200);
  await shot("03_table_hscroll");
  await page.evaluate(() => {
    const wrap = document.querySelector(".sheetwrap");
    if (wrap) wrap.scrollLeft = 0;
  });

  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(false);
  });
  await sleep(500);
  await shot("04_collapsed");

  const collapsed = await page.evaluate(() => {
    const side = document.getElementById("v41-primary-sidebar");
    const ico = document.querySelector("#v41-primary-sidebar .navbtn.active .nav-ico");
    const cs = ico ? getComputedStyle(ico) : null;
    const btn = document.querySelector("#v41-primary-sidebar .navbtn");
    return {
      sideW: side ? Math.round(side.getBoundingClientRect().width) : 0,
      iconFont: cs ? cs.fontSize : null,
      tooltip: btn ? btn.getAttribute("title") : null,
      navigable: true,
    };
  });

  // restore + navigate menus
  await page.evaluate(() => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(true);
  });
  const menus = ["tasks", "paymentMonitor", "shippingSchedule", "settings", "schedule"];
  const menuNav = {};
  for (const id of menus) {
    await page.evaluate((sid) => {
      if (typeof window.go === "function") window.go(sid);
    }, id);
    await sleep(500);
    menuNav[id] = await page.evaluate(
      () => document.querySelector("#v41-primary-sidebar .navbtn.active")?.getAttribute("title") || null
    );
  }

  await page.close();

  const ok =
    probe.sideW >= 210 &&
    probe.sideW <= 240 &&
    probe.activeBg === "rgb(33, 76, 60)" &&
    probe.inactiveLightCount === 0 &&
    probe.labelLightCount === 0 &&
    !probe.overflowX &&
    probe.topH >= 60 &&
    probe.topH <= 72 &&
    probe.kpiOneRow &&
    probe.stickyOk &&
    probe.navCount >= 12 &&
    probe.handleInside &&
    collapsed.sideW >= 55 &&
    collapsed.sideW <= 80 &&
    !!collapsed.tooltip;

  return { tag, width, height, probe, collapsed, menuNav, shots, ok };
}

const results = [];
results.push(await runViewport(1440, 900, "1440x900"));
results.push(await runViewport(1366, 768, "1366x768"));
await browser.close();
server.close();

const summary = {
  prefix: PREFIX,
  ok: results.every((r) => r.ok),
  results,
};
fs.writeFileSync(path.join(OUT, `${PREFIX}_manifest.json`), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
process.exit(summary.ok ? 0 : 1);
