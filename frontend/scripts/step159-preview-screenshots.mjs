/**
 * Step 159 — Owner preview screenshots (fixture mode).
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP159_BASE || "http://127.0.0.1:5173";
const OUT = process.env.STEP159_OUT || "/opt/cursor/artifacts";
const URL = `${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT, { recursive: true });
const out = (n) => path.join(OUT, n);

async function boot(page) {
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 15000 },
  );
  await page.evaluate(() => {
    if (typeof go === "function") go("inbox");
  });
  await new Promise((r) => setTimeout(r, 500));
}

async function measureHeaderGap(page) {
  return page.evaluate(() => {
    const wrap = document.querySelector(".v36-inbox-sheetwrap");
    const th = document.querySelector("table.v36-inbox-sheet thead th");
    if (!wrap || !th) return { ok: false };
    const wr = wrap.getBoundingClientRect();
    const hr = th.getBoundingClientRect();
    const gap = Math.round(hr.top - wr.top);
    const cs = getComputedStyle(th);
    return {
      ok: true,
      gapPx: gap,
      stickyTop: cs.top,
      thBg: cs.backgroundColor,
      claimsLive:
        /Gateway Accurate/i.test(document.body.innerText) &&
        /preview-fixture/i.test(document.body.innerText) &&
        !/SIMULASI\/FIXTURE/i.test(
          document.getElementById("v50-source-status")?.textContent || "",
        ),
      hasQuickbar: !!document.querySelector(".v3-quickbar") &&
        getComputedStyle(document.querySelector(".v3-quickbar")).display !== "none",
      kpiCols: getComputedStyle(document.querySelector(".v159-kpi-row") || document.body)
        .gridTemplateColumns,
      toolbarOk: !!document.querySelector(".v36-inbox-toolbar"),
    };
  });
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

const errors = [];
const page = await browser.newPage();
page.on("pageerror", (e) => errors.push(String(e.message || e)));

// Desktop 1440
await page.setViewport({ width: 1440, height: 1100 });
await boot(page);
const gap1440 = await measureHeaderGap(page);
await page.screenshot({ path: out("step159-inbox-full-1440.png"), fullPage: true });
const headerEl = await page.$("table.v36-inbox-sheet thead");
if (headerEl) await headerEl.screenshot({ path: out("step159-header-closeup-1440.png") });

await page.evaluate(() => {
  const CR = window.V3ColumnResize;
  if (!CR) return;
  CR.saveColumnWidths("epv3:colw:inbox", { id: 250, name: 280 });
  if (typeof render === "function") render();
});
await new Promise((r) => setTimeout(r, 400));
await page.screenshot({ path: out("step159-resize-1440.png"), fullPage: false });

await page.evaluate(() => {
  const wrap = document.querySelector(".v36-inbox-sheetwrap");
  if (wrap) wrap.scrollLeft = 480;
});
await new Promise((r) => setTimeout(r, 200));
await page.screenshot({ path: out("step159-hscroll-1440.png"), fullPage: false });

await page.evaluate(() => {
  const id = window.orders?.[0]?.id || "SO/PREVIEW-MIX-001";
  if (typeof v49PODetail === "function") v49PODetail(id);
});
await page.waitForSelector("#v49-po-detail-back", { timeout: 8000 });
await new Promise((r) => setTimeout(r, 300));
await page.screenshot({ path: out("step159-detail-po-1440.png"), fullPage: false });
await page.evaluate(() => v49Close && v49Close());

await page.evaluate(() => go("schedule"));
await new Promise((r) => setTimeout(r, 600));
await page.screenshot({ path: out("step159-jadwal-1440.png"), fullPage: true });

// Viewport 1366
await page.setViewport({ width: 1366, height: 900 });
await boot(page);
const gap1366 = await measureHeaderGap(page);
await page.screenshot({ path: out("step159-inbox-full-1366.png"), fullPage: true });
const headerEl2 = await page.$("table.v36-inbox-sheet thead");
if (headerEl2) await headerEl2.screenshot({ path: out("step159-header-closeup-1366.png") });

const report = {
  url: URL,
  gap1440,
  gap1366,
  jsErrors: errors.slice(0, 20),
  files: fs.readdirSync(OUT).filter((f) => f.startsWith("step159-")),
};
fs.writeFileSync(out("step159-preview-report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
if ((gap1440.gapPx ?? 99) > 4 || (gap1366.gapPx ?? 99) > 4) process.exitCode = 3;
if (errors.some((e) => !/history/i.test(e))) process.exitCode = 2;
