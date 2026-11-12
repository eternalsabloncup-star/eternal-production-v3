/**
 * Step 158 — capture real Cursor preview screenshots (fixture mode).
 * Usage: node ./scripts/step158-preview-screenshots.mjs
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP158_BASE || "http://127.0.0.1:5173";
const OUT = process.env.STEP158_OUT || "/opt/cursor/artifacts";
const URL = `${BASE}/production.html?epv3_preview=fixture`;

fs.mkdirSync(OUT, { recursive: true });

function out(name) {
  return path.join(OUT, name);
}

async function waitReady(page) {
  await page.waitForSelector("#v3-app, .v36-inbox-sheet, .content", {
    timeout: 20000,
  });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 15000 },
  );
  await new Promise((r) => setTimeout(r, 600));
}

async function jsErrors(page) {
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e && e.message ? e.message : e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errs.push(msg.text());
  });
  return errs;
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--window-size=1440,1100"],
  defaultViewport: { width: 1440, height: 1100 },
});

const page = await browser.newPage();
const errors = await jsErrors(page);

await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
await waitReady(page);

// Ensure inbox section
await page.evaluate(() => {
  if (typeof go === "function") go("inbox");
});
await new Promise((r) => setTimeout(r, 500));

await page.screenshot({
  path: out("step158-inbox-full.png"),
  fullPage: true,
});

const inboxTable = await page.$(".v36-inbox-sheetwrap, table.v36-inbox-sheet");
if (inboxTable) {
  await inboxTable.screenshot({ path: out("step158-inbox-header.png") });
}

// Detail PO
await page.evaluate(() => {
  const id = (window.orders && window.orders[0] && window.orders[0].id) || "SO/PREVIEW-MIX-001";
  if (typeof v49PODetail === "function") v49PODetail(id);
});
await page.waitForSelector("#v49-po-detail-back, .detaildrawer", { timeout: 8000 });
await new Promise((r) => setTimeout(r, 400));
await page.screenshot({
  path: out("step158-detail-po.png"),
  fullPage: false,
});
await page.evaluate(() => {
  if (typeof v49Close === "function") v49Close();
});

// Schedule — print only
await page.evaluate(() => {
  if (typeof go === "function") go("schedule");
});
await new Promise((r) => setTimeout(r, 700));
await page.screenshot({
  path: out("step158-jadwal-print-only.png"),
  fullPage: true,
});

// Resize before/after on inbox
await page.evaluate(() => {
  if (typeof go === "function") go("inbox");
});
await new Promise((r) => setTimeout(r, 500));

const beforeWidths = await page.evaluate(() => {
  const th = document.querySelector('table.v36-inbox-sheet th[data-column="id"]');
  return th ? Math.round(th.getBoundingClientRect().width) : null;
});
await page.screenshot({ path: out("step158-resize-before.png"), fullPage: false });

await page.evaluate(() => {
  const CR = window.V3ColumnResize;
  if (!CR) return;
  CR.saveColumnWidths("epv3:colw:inbox", { id: 240, name: 260, salesName: 160 });
  if (typeof attachOperationalColumnResize === "function") attachOperationalColumnResize();
  else if (typeof render === "function") render();
});
await new Promise((r) => setTimeout(r, 400));
const afterWidths = await page.evaluate(() => {
  const th = document.querySelector('table.v36-inbox-sheet th[data-column="id"]');
  return th ? Math.round(th.getBoundingClientRect().width) : null;
});
await page.screenshot({ path: out("step158-resize-after.png"), fullPage: false });

// Persist after refresh
await page.reload({ waitUntil: "networkidle0" });
await waitReady(page);
await page.evaluate(() => {
  if (typeof go === "function") go("inbox");
});
await new Promise((r) => setTimeout(r, 500));
const persisted = await page.evaluate(() => {
  const stored = window.V3ColumnResize
    ? window.V3ColumnResize.loadColumnWidths("epv3:colw:inbox")
    : {};
  const th = document.querySelector('table.v36-inbox-sheet th[data-column="id"]');
  return {
    stored,
    width: th ? Math.round(th.getBoundingClientRect().width) : null,
  };
});
await page.screenshot({
  path: out("step158-resize-after-refresh.png"),
  fullPage: false,
});

// Filter + horizontal scroll
await page.evaluate(() => {
  if (typeof v36SetInboxSearch === "function") v36SetInboxSearch("Renea");
  else {
    window.v36InboxQuery = "Renea";
    if (typeof render === "function") render();
  }
});
await new Promise((r) => setTimeout(r, 400));
await page.evaluate(() => {
  const wrap = document.querySelector(".v36-inbox-sheetwrap");
  if (wrap) wrap.scrollLeft = 420;
});
await new Promise((r) => setTimeout(r, 300));
await page.screenshot({
  path: out("step158-filter-scroll.png"),
  fullPage: false,
});

// Schedule row audit
const scheduleAudit = await page.evaluate(() => {
  if (typeof go === "function") go("schedule");
  return null;
});
await new Promise((r) => setTimeout(r, 600));
const scheduleInfo = await page.evaluate(() => {
  const rows = Array.from(
    document.querySelectorAll("table.excel-sheet tbody tr, table.sheet tbody tr"),
  );
  const texts = rows.map((r) => (r.innerText || "").replace(/\s+/g, " ").trim());
  const hasLid = texts.some((t) => /Lid Non-Cetak/i.test(t));
  const hasUnk = texts.some((t) => /Belum Terverifikasi|UNK-01/i.test(t));
  const hasCup = texts.some((t) => /Cup PET 16oz Cetak|Cup PP 14oz Cetak/i.test(t));
  const noCariSo = !document.body.innerText.includes("Cari SO");
  const hasRingkasan = document.body.innerText.includes("Ringkasan PO") || true;
  return {
    rowCount: rows.length,
    hasLid,
    hasUnk,
    hasCup,
    sample: texts.slice(0, 5),
    banner: !!document.getElementById("v158-preview-banner"),
    noCariSoCard: !document.querySelector("#v3-inbox-q"),
  };
});

await page.evaluate(() => {
  if (typeof go === "function") go("inbox");
});
await new Promise((r) => setTimeout(r, 400));
const inboxActions = await page.evaluate(() => {
  const txt = document.body.innerText;
  return {
    hasPanelV3Label: /\bPanel V3\b/.test(txt) && /Ringkasan PO|Detail PO/.test(txt),
    hasRingkasanOrDetail: /Ringkasan PO|Detail PO/.test(txt),
    hasV3Button: !!document.querySelector(".v36-inbox-sheet .v3-open-wf"),
    resizeHandles: document.querySelectorAll("[data-col-resize]").length,
  };
});

const report = {
  url: URL,
  beforeWidths,
  afterWidths,
  persisted,
  scheduleInfo,
  inboxActions,
  jsErrors: errors.slice(0, 20),
  files: fs.readdirSync(OUT).filter((f) => f.startsWith("step158-")),
};
fs.writeFileSync(out("step158-preview-report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

await browser.close();

if (errors.length) {
  console.error("JS errors detected:", errors);
  process.exitCode = 2;
}
