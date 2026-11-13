/**
 * Step 161 — sticky scroll + universal resize matrix + screenshots.
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP161_BASE || "http://127.0.0.1:5173";
const OUT = process.env.STEP161_OUT || "/opt/cursor/artifacts";
const URL = `${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT, { recursive: true });
const out = (n) => path.join(OUT, n);

async function boot(page, section) {
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 15000 },
  );
  await page.evaluate((s) => {
    try {
      localStorage.removeItem("epv3:colw:schedule");
    } catch (_) {}
    if (typeof go === "function") go(s);
  }, section);
  await new Promise((r) => setTimeout(r, 800));
}

async function tableMatrix(page) {
  return page.evaluate(() => {
    const tables = [...document.querySelectorAll("#root table, #modal table")];
    return tables
      .filter((t) => t.querySelector("thead th"))
      .map((t) => {
        const handles = t.querySelectorAll("[data-col-resize]").length;
        const ths = t.querySelectorAll(
          "thead tr:not(.sheet-group-row) th, thead tr:last-child th",
        ).length;
        const sticky = [...t.querySelectorAll("th[data-column], td[data-column]")].some(
          (el) => getComputedStyle(el).position === "sticky" && el.style.left,
        );
        const scrollParent =
          t.closest(".sheetwrap, .v36-inbox-sheetwrap, .monitor-scroll, .report-shell, .renea-table-wrap, .flow31-scroll") ||
          t.parentElement;
        return {
          key: t.dataset.v3Colw || t.className || "table",
          className: t.className,
          cols: ths,
          resizeHandles: handles,
          resize: handles > 0 && handles >= Math.max(1, ths - 1),
          persistKey: !!t.dataset.v3Colw,
          sticky,
          scrollX: !!(scrollParent && scrollParent.scrollWidth > scrollParent.clientWidth + 2),
        };
      });
  });
}

async function measureSticky(page) {
  return page.evaluate(() => {
    const wrap = document.querySelector(".sheetwrap");
    const table = document.querySelector("table.excel-sheet");
    if (!wrap || !table) return { ok: false };
    const idTh = table.querySelector('thead tr:not(.sheet-group-row) th[data-column="id"]');
    const nameTh = table.querySelector('thead tr:not(.sheet-group-row) th[data-column="name"]');
    const idTd = table.querySelector('tbody td[data-column="id"]');
    const nameTd = table.querySelector('tbody td[data-column="name"]');
    const before = {
      idL: idTh.getBoundingClientRect().left,
      nameL: nameTh.getBoundingClientRect().left,
      idW: idTh.getBoundingClientRect().width,
      nameBodyL: nameTd.getBoundingClientRect().left,
      gap: nameTh.getBoundingClientRect().left - idTh.getBoundingClientRect().right,
    };
    wrap.scrollLeft = Math.min(wrap.scrollWidth, 600);
    const after = {
      idL: idTh.getBoundingClientRect().left,
      nameL: nameTh.getBoundingClientRect().left,
      nameBodyL: nameTd.getBoundingClientRect().left,
      idBodyL: idTd.getBoundingClientRect().left,
    };
    const group = table.querySelector("tr.sheet-group-row th[data-column='id']");
    const childKeys = (group?.getAttribute("data-group-keys") || "id,name").split(",");
    const kids = childKeys.map((k) =>
      table.querySelector(`thead tr:not(.sheet-group-row) th[data-column="${k}"]`),
    );
    const g = group?.getBoundingClientRect();
    const cL = Math.min(...kids.map((el) => el.getBoundingClientRect().left));
    const cR = Math.max(...kids.map((el) => el.getBoundingClientRect().right));
    return {
      ok: true,
      before,
      after,
      stickyHold:
        Math.abs(after.idL - before.idL) <= 1 &&
        Math.abs(after.nameL - before.nameL) <= 1 &&
        Math.abs(after.nameBodyL - after.nameL) <= 2,
      groupAlign: g ? Math.abs(g.left - cL) <= 2 && Math.abs(g.right - cR) <= 2 : null,
      defaults: {
        id: Math.round(before.idW),
        item: Math.round(
          table.querySelector('th[data-column="item"]')?.getBoundingClientRect().width || 0,
        ),
      },
    };
  });
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e.message || e)));

const matrix = {};
const sections = [
  ["schedule", "Jadwal Produksi"],
  ["inbox", "Inbox Accurate"],
  ["tasks", "Tugas Tim"],
  ["shippingSchedule", "Jadwal Pengiriman"],
  ["bufferMonitor", "Monitoring Buffer"],
  ["contractMonitor", "Monitoring PO Kontrak"],
  ["productionReport", "Laporan Produksi"],
  ["salarySlip", "Slip Gaji"],
];

for (const [sec] of sections) {
  await page.setViewport({ width: 1440, height: 900 });
  await boot(page, sec);
  matrix[sec] = await tableMatrix(page);
}

await boot(page, "schedule");
const sticky = {};
for (const vp of [
  { w: 1366, h: 768, tag: "1366" },
  { w: 1440, h: 900, tag: "1440" },
  { w: 1920, h: 1080, tag: "1920" },
]) {
  await page.setViewport({ width: vp.w, height: vp.h });
  await boot(page, "schedule");
  sticky[vp.tag] = await measureSticky(page);
}

// Screenshots @1440
await page.setViewport({ width: 1440, height: 900 });
await boot(page, "schedule");
await page.screenshot({ path: out("step161-jadwal-default-1440.png"), fullPage: true });

await page.evaluate(() => {
  const wrap = document.querySelector(".sheetwrap");
  if (wrap) wrap.scrollLeft = wrap.scrollWidth;
});
await new Promise((r) => setTimeout(r, 200));
await page.screenshot({ path: out("step161-jadwal-hscroll-right-1440.png") });

await page.evaluate(() => {
  const table = document.querySelector("table.excel-sheet");
  const api = window.V3ColumnResize;
  api.saveColumnWidths("epv3:colw:schedule", {
    id: 200,
    name: 260,
    item: 280,
    assignmentDate: 140,
  });
  api.attachColumnResize(table, {
    storageKey: "epv3:colw:schedule",
    stickyKeys: ["id", "name"],
    lockAll: true,
    onGeometry: () => syncScheduleHeaderGeometry(table),
  });
  const wrap = document.querySelector(".sheetwrap");
  if (wrap) wrap.scrollLeft = 500;
});
await new Promise((r) => setTimeout(r, 250));
await page.screenshot({ path: out("step161-jadwal-resize-scroll-1440.png"), fullPage: true });

await page.evaluate(() => {
  setSheetColumnVisible("operator", false);
  setSheetColumnVisible("qty", false);
});
await new Promise((r) => setTimeout(r, 300));
await page.screenshot({ path: out("step161-jadwal-hide-1440.png"), fullPage: true });

await boot(page, "inbox");
await page.screenshot({ path: out("step161-inbox-regression-1440.png"), fullPage: true });

// Extra layout types
await boot(page, "tasks");
await page.screenshot({ path: out("step161-tasks-resize-1440.png"), fullPage: true });
await boot(page, "productionReport");
await page.screenshot({ path: out("step161-report-1440.png"), fullPage: true });
await boot(page, "bufferMonitor");
await page.screenshot({ path: out("step161-buffer-1440.png"), fullPage: true });

const report = {
  url: URL,
  jsErrors: errors,
  sticky,
  matrix,
  passSticky: Object.values(sticky).every((s) => s.ok && s.stickyHold && s.groupAlign !== false),
};
fs.writeFileSync(out("step161-resize-matrix.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ passSticky: report.passSticky, errors, sticky1440: sticky["1440"] }, null, 2));
await browser.close();
