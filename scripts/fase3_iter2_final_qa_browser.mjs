/**
 * Iter2 final QA — toolbar reachability + sticky geometry (real browser).
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
const STATIC_PORT = Number(process.env.V3_FINAL_QA_PORT || 4193);
const OUT = process.env.V3_FINAL_QA_OUT || "/opt/cursor/artifacts";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");
const STAMP = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const PREFIX = `epv3_iter2_finalqa_${STAMP}`;

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
  if (st.size < 4000) throw new Error("png small " + file);
  const info = execFileSync("file", ["-b", file], { encoding: "utf8" }).trim();
  return { bytes: st.size, info };
}

async function runCase(width, height, tag, collapsed) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument((token, col) => {
    localStorage.setItem("epv3_access_token", token);
    localStorage.setItem("eternal_v3_sidebar_collapsed_v41", col ? "1" : "0");
    window.V3_API_BASE = "/api/v1";
  }, access_token, collapsed);
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "networkidle0",
    timeout: 90000,
  });
  await sleep(2200);
  await page.evaluate((col) => {
    if (typeof window.v3ToggleNav === "function") window.v3ToggleNav(!col);
    if (typeof window.go === "function") window.go("schedule");
  }, collapsed);
  await sleep(1500);

  const probe = await page.evaluate(() => {
    const vw = window.innerWidth;
    const sheetbar = document.querySelector("#v3-app.section-schedule .sheetbar");
    const wrap = document.querySelector("#v3-app.section-schedule .sheetwrap");
    const table = document.querySelector("table.excel-sheet, table.v3-schedule-sheet");
    const buttons = sheetbar
      ? [...sheetbar.querySelectorAll("button, summary, input, select")].map((el) => {
          const r = el.getBoundingClientRect();
          const label = (el.textContent || el.getAttribute("aria-label") || el.placeholder || el.tagName)
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 40);
          const fullyVisible =
            r.width > 0 &&
            r.height > 0 &&
            r.left >= -1 &&
            r.right <= vw + 1 &&
            r.top >= 0 &&
            r.bottom <= window.innerHeight + 2;
          const inBar =
            !!sheetbar &&
            r.left >= sheetbar.getBoundingClientRect().left - 2 &&
            r.right <= sheetbar.getBoundingClientRect().right + 2;
          return {
            label,
            left: Math.round(r.left),
            right: Math.round(r.right),
            width: Math.round(r.width),
            fullyVisible,
            clippedByViewport: r.right > vw + 1 || r.left < -1,
            inBar,
          };
        })
      : [];

    const bar = sheetbar ? sheetbar.getBoundingClientRect() : null;
    const barCs = sheetbar ? getComputedStyle(sheetbar) : null;
    const barScrollable =
      !!sheetbar && sheetbar.scrollWidth > sheetbar.clientWidth + 2;
    const barOverflowX = barCs ? barCs.overflowX : null;

    function stickyAt(scrollLeft) {
      if (!wrap || !table) return null;
      wrap.scrollLeft = scrollLeft;
      // Leaf header row only — group-row th[data-column=id] spans IDENTITAS (false overlap).
      const leaf = table.querySelector("thead tr:not(.sheet-group-row)");
      const thId = leaf && leaf.querySelector('th[data-column="id"]');
      const thName = leaf && leaf.querySelector('th[data-column="name"]');
      const tdId = table.querySelector('tbody td[data-column="id"]');
      const tdName = table.querySelector('tbody td[data-column="name"]');
      const nextLeaf =
        (leaf && leaf.querySelector('th[data-column="assignmentDate"]')) ||
        (leaf &&
          [...leaf.querySelectorAll("th")].find(
            (th) => !th.classList.contains("v40-col-hidden") && th.dataset.column !== "id" && th.dataset.column !== "name"
          ));
      function info(el) {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return {
          x: Math.round(r.x * 10) / 10,
          left: cs.left,
          pos: cs.position,
          z: cs.zIndex,
          w: Math.round(r.width),
          text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 24),
        };
      }
      const a = info(thId);
      const b = info(thName);
      const c = info(tdId);
      const d = info(tdName);
      const n = info(nextLeaf);
      const stickyAttr = table.dataset.v3Sticky || "";
      const holds =
        a &&
        b &&
        a.pos.includes("sticky") &&
        b.pos.includes("sticky") &&
        Math.abs(a.x - (c ? c.x : a.x)) < 2 &&
        Math.abs(b.x - (d ? d.x : b.x)) < 2;
      // Prefer body cells for overlap (stable widths); leaf headers as fallback.
      const leftCell = c || a;
      const rightCell = d || b;
      const noOverlap = leftCell && rightCell && leftCell.x + leftCell.w <= rightCell.x + 2;
      // next leaf only counted when still in view (x >= name)
      const nextClear =
        !n || n.x < (b ? b.x : 0) ? true : !!(b && n && b.x + b.w <= n.x + 2);
      return {
        scrollLeft,
        stickyAttr,
        thId: a,
        thName: b,
        tdId: c,
        tdName: d,
        nextTh: n,
        holds,
        noOverlap,
        nextClear,
        headerBodyAlign: !!(a && c && Math.abs(a.x - c.x) < 2 && b && d && Math.abs(b.x - d.x) < 2),
      };
    }

    const maxScroll = wrap ? Math.max(0, wrap.scrollWidth - wrap.clientWidth) : 0;
    const mid = Math.round(maxScroll / 2);
    const sticky = {
      start: stickyAt(0),
      mid: stickyAt(mid),
      end: stickyAt(maxScroll),
    };
    if (wrap) wrap.scrollLeft = 0;

    const csv = buttons.find((b) => /csv/i.test(b.label));
    const requiredLabels = [/cari|search|so/i, /kolom/i, /status/i, /baris|halaman/i, /bersih/i, /reset/i, /csv/i];
    const missingRequired = requiredLabels.filter(
      (re) => !buttons.some((b) => re.test(b.label))
    ).map((re) => String(re));

    return {
      pageOverflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
      barWidth: bar ? Math.round(bar.width) : 0,
      barScrollable,
      barOverflowX,
      buttons,
      csv,
      missingRequired,
      clippedButtons: buttons.filter((b) => b.clippedByViewport),
      sticky,
      maxScroll,
      wrapOverflowX: wrap ? getComputedStyle(wrap).overflowX : null,
    };
  });

  // screenshots
  const base = `${PREFIX}_${tag}_${collapsed ? "collapsed" : "expanded"}`;
  const shotToolbar = path.join(OUT, `${base}_toolbar.png`);
  await page.screenshot({ path: shotToolbar, fullPage: false });
  verifyPng(shotToolbar);

  await page.evaluate(() => {
    const wrap = document.querySelector("#v3-app.section-schedule .sheetwrap");
    if (wrap) wrap.scrollLeft = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
  });
  await sleep(250);
  const shotSticky = path.join(OUT, `${base}_sticky_end.png`);
  await page.screenshot({ path: shotSticky, fullPage: false });
  verifyPng(shotSticky);

  await page.close();

  const stickyOk =
    probe.sticky.start?.holds &&
    probe.sticky.mid?.holds &&
    probe.sticky.end?.holds &&
    probe.sticky.start?.noOverlap &&
    probe.sticky.mid?.noOverlap &&
    probe.sticky.end?.noOverlap &&
    probe.sticky.start?.headerBodyAlign &&
    probe.sticky.mid?.headerBodyAlign &&
    probe.sticky.end?.headerBodyAlign &&
    probe.sticky.start?.nextClear &&
    probe.sticky.mid?.nextClear &&
    probe.sticky.end?.nextClear &&
    /id,name/.test(probe.sticky.start?.stickyAttr || "");

  const toolbarOk =
    !probe.pageOverflowX &&
    probe.missingRequired.length === 0 &&
    probe.clippedButtons.length === 0 &&
    !!probe.csv &&
    !probe.csv.clippedByViewport &&
    (probe.csv.fullyVisible || (probe.barScrollable && /auto|scroll/.test(String(probe.barOverflowX || ""))));

  return {
    tag,
    collapsed,
    toolbarOk,
    stickyOk,
    ok: toolbarOk && stickyOk,
    probe,
    shots: { toolbar: shotToolbar, stickyEnd: shotSticky },
  };
}

const cases = [
  [1440, 900, "1440x900", false],
  [1440, 900, "1440x900", true],
  [1366, 768, "1366x768", false],
  [1366, 768, "1366x768", true],
];

const results = [];
for (const c of cases) results.push(await runCase(...c));

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
