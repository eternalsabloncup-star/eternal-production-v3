/** Step 162 — finalize resize validation + screenshots for 8 tables. */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP162_BASE || "http://127.0.0.1:5174";
const OUT = process.env.STEP162_OUT || "/opt/cursor/artifacts";
const URL = `${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT, { recursive: true });
const out = (n) => path.join(OUT, n);

const SECTIONS = [
  ["schedule", "jadwal", "epv3:colw:schedule"],
  ["inbox", "inbox", "epv3:colw:inbox"],
  ["tasks", "tasks", "epv3:colw:tasks"],
  ["shippingSchedule", "shipping", "epv3:colw:shipping"],
  ["bufferMonitor", "buffer", "epv3:colw:buffer"],
  ["contractMonitor", "kontrak", "epv3:colw:kontrak"],
  ["productionReport", "report", "epv3:colw:report"],
  ["salarySlip", "salary", "epv3:colw:salary"],
];

async function boot(page, section) {
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 15000 },
  );
  await page.evaluate((s) => {
    if (typeof go === "function") go(s);
  }, section);
  await new Promise((r) => setTimeout(r, 850));
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => {
  const m = String(e.message || e);
  if (!/history of #<Window>/.test(m)) errors.push(m);
});
await page.setViewport({ width: 1440, height: 900 });

const matrix = [];

for (const [sec, tag, key] of SECTIONS) {
  await boot(page, sec);
  const before = await page.evaluate(() => {
    const t = document.querySelector("#root table[data-v3-colw], #root table");
    const resetBtn = !!document.querySelector(".v162-reset-lebar");
    const handles = t ? t.querySelectorAll("[data-col-resize]").length : 0;
    const filterBtns = [
      ...document.querySelectorAll(
        ".sheet-filter-trigger, .v43-trigger, .v162-sort-btn",
      ),
    ].filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0).slice(0, 6);
    const filters = filterBtns.map((b) => ({
      text: (b.textContent || "").trim(),
      visible: true,
      color: getComputedStyle(b).color,
      bg: getComputedStyle(b).backgroundColor,
    }));
    const firstKey =
      t?.querySelector("thead tr:not(.sheet-group-row) th[data-column], thead th[data-column]")
        ?.getAttribute("data-column") || "c0";
    const w = (k) => {
      const el = t?.querySelector(
        `thead tr:not(.sheet-group-row) th[data-column="${k}"], thead th[data-column="${k}"]`,
      );
      return el ? Math.round(el.getBoundingClientRect().width) : null;
    };
    return {
      storage: t?.dataset.v3Colw || null,
      resetBtn,
      handles,
      filters,
      firstKey,
      firstW: w(firstKey),
      tip: !!t?.querySelector("[title]"),
    };
  });

  // resize first column
  await page.evaluate((k) => {
    const t = document.querySelector("table[data-v3-colw]");
    if (!t || !window.V3ColumnResize) return;
    const key = t.dataset.v3Colw;
    const first =
      t.querySelector(
        "thead tr:not(.sheet-group-row) th[data-column], thead th[data-column]",
      )?.getAttribute("data-column") || "c0";
    const all = {};
    t.querySelectorAll(
      "thead tr:not(.sheet-group-row) th[data-column], thead th[data-column]",
    ).forEach((th) => {
      if (th.classList.contains("v40-col-hidden")) return;
      all[th.dataset.column] = Math.round(th.getBoundingClientRect().width);
    });
    const neighbor = Object.keys(all).find((x) => x !== first);
    const neighborBefore = neighbor ? all[neighbor] : null;
    all[first] = Math.max(200, (all[first] || 120) + 40);
    window.V3ColumnResize.saveColumnWidths(key, all);
    t.querySelectorAll("[data-col-resize]").forEach((h) => h.remove());
    window.attachAllV3TableResize?.();
    window.__v162_neighbor = {
      first,
      neighbor,
      neighborBefore,
      neighborAfter: neighbor
        ? Math.round(
            t
              .querySelector(`th[data-column="${neighbor}"]`)
              .getBoundingClientRect().width,
          )
        : null,
    };
  }, key);

  await page.screenshot({
    path: out(`step162-${tag}-after-resize-1440.png`),
    fullPage: true,
  });

  // persist reload
  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForFunction(() =>
    document.documentElement.classList.contains("v3-auth-ok"),
  );
  await page.evaluate((s) => go(s), sec);
  await new Promise((r) => setTimeout(r, 800));
  const persisted = await page.evaluate(() => {
    const t = document.querySelector("table[data-v3-colw]");
    const first =
      t?.querySelector(
        "thead tr:not(.sheet-group-row) th[data-column], thead th[data-column]",
      )?.getAttribute("data-column") || "c0";
    const w = Math.round(
      t
        ?.querySelector(`th[data-column="${first}"]`)
        ?.getBoundingClientRect().width || 0,
    );
    return { first, w, storage: localStorage.getItem(t?.dataset.v3Colw || "") };
  });

  // reset lebar
  const liveKey = await page.evaluate(() => document.querySelector("table[data-v3-colw]")?.dataset.v3Colw || null);
  await page.evaluate((k) => {
    if (typeof resetV3ColumnWidths === "function") resetV3ColumnWidths(k);
  }, liveKey || key);
  await new Promise((r) => setTimeout(r, 400));
  const afterReset = await page.evaluate(() => {
    const t = document.querySelector("table[data-v3-colw]");
    const key = t?.dataset.v3Colw;
    return {
      storageEmpty: !localStorage.getItem(key || ""),
      handles: t?.querySelectorAll("[data-col-resize]").length || 0,
    };
  });

  const neighbor = await page.evaluate(() => window.__v162_neighbor || null);
  const filterOk =
    before.filters.length === 0 ||
    before.filters.every((f) => f.visible && f.text.length > 0);
  const pass =
    before.resetBtn &&
    before.handles > 0 &&
    filterOk &&
    afterReset.storageEmpty &&
    afterReset.handles > 0;

  matrix.push({
    section: sec,
    table: before.storage,
    resetBtn: before.resetBtn,
    handles: before.handles,
    filterOk,
    tip: before.tip,
    persistW: persisted.w,
    resetClears: afterReset.storageEmpty,
    neighborStable:
      !neighbor?.neighbor ||
      Math.abs((neighbor.neighborAfter || 0) - (neighbor.neighborBefore || 0)) <=
        2,
    result: pass ? "PASS" : "FAIL",
  });

  await page.screenshot({
    path: out(`step162-${tag}-default-1440.png`),
    fullPage: true,
  });
}

// sticky audit on schedule
await boot(page, "schedule");
const sticky = await page.evaluate(() => {
  const wrap = document.querySelector(".sheetwrap");
  const table = document.querySelector("table.excel-sheet");
  const idTh = table.querySelector(
    'thead tr:not(.sheet-group-row) th[data-column="id"]',
  );
  const nameTh = table.querySelector(
    'thead tr:not(.sheet-group-row) th[data-column="name"]',
  );
  const idTd = table.querySelector('tbody td[data-column="id"]');
  const nameTd = table.querySelector('tbody td[data-column="name"]');
  const before = {
    idL: idTh.getBoundingClientRect().left,
    nameL: nameTh.getBoundingClientRect().left,
  };
  wrap.scrollLeft = wrap.scrollWidth;
  const after = {
    idL: idTh.getBoundingClientRect().left,
    nameL: nameTh.getBoundingClientRect().left,
    idBody: idTd.getBoundingClientRect().left,
    nameBody: nameTd.getBoundingClientRect().left,
    overlap: nameTh.getBoundingClientRect().left < idTh.getBoundingClientRect().right - 1,
  };
  return {
    hold:
      Math.abs(after.idL - before.idL) <= 2 &&
      Math.abs(after.nameL - before.nameL) <= 2 &&
      Math.abs(after.idBody - after.idL) <= 2 &&
      Math.abs(after.nameBody - after.nameL) <= 2 &&
      !after.overlap,
    before,
    after,
  };
});
await page.screenshot({ path: out("step162-jadwal-hscroll-end-1440.png") });

const report = {
  url: URL,
  jsErrors: errors,
  sticky,
  matrix,
  passAll: matrix.every((m) => m.result === "PASS") && sticky.hold,
};
fs.writeFileSync(out("step162-final-report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
