/**
 * Step 160 — schedule header geometry measure + screenshots.
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP160_BASE || "http://127.0.0.1:5173";
const OUT = process.env.STEP160_OUT || "/opt/cursor/artifacts";
const URL = `${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT, { recursive: true });
const out = (n) => path.join(OUT, n);

async function boot(page, section = "schedule") {
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 15000 },
  );
  await page.evaluate((s) => {
    if (typeof go === "function") go(s);
  }, section);
  await new Promise((r) => setTimeout(r, 700));
}

async function measure(page) {
  return page.evaluate(() => {
    const table = document.querySelector("table.excel-sheet");
    if (!table) return { ok: false, reason: "no table" };
    const groupThs = [...table.querySelectorAll("tr.sheet-group-row th")];
    const colThs = [
      ...table.querySelectorAll(
        "thead tr:not(.sheet-group-row) th:not(.v40-col-hidden)",
      ),
    ];
    const groups = groupThs.map((th) => {
      const keys = (th.getAttribute("data-group-keys") || th.getAttribute("data-column") || "")
        .split(",")
        .filter(Boolean);
      const gr = th.getBoundingClientRect();
      const children = keys
        .map((k) =>
          table.querySelector(
            `thead tr:not(.sheet-group-row) th[data-column="${k}"]`,
          ),
        )
        .filter(Boolean)
        .map((el) => {
          const r = el.getBoundingClientRect();
          return { key: el.getAttribute("data-column"), left: r.left, right: r.right, width: r.width };
        });
      const childLeft = children.length ? Math.min(...children.map((c) => c.left)) : gr.left;
      const childRight = children.length ? Math.max(...children.map((c) => c.right)) : gr.right;
      return {
        label: (th.textContent || "").trim(),
        colspan: Number(th.getAttribute("colspan") || 1),
        keys,
        groupLeft: gr.left,
        groupRight: gr.right,
        childLeft,
        childRight,
        dxL: Math.abs(gr.left - childLeft),
        dxR: Math.abs(gr.right - childRight),
        alignOk:
          Math.abs(gr.left - childLeft) <= 2 &&
          Math.abs(gr.right - childRight) <= 2,
      };
    });
    const bodySample = colThs.slice(0, 6).map((th) => {
      const key = th.getAttribute("data-column");
      const hr = th.getBoundingClientRect();
      const td = table.querySelector(`tbody td[data-column="${key}"]`);
      const br = td ? td.getBoundingClientRect() : null;
      const cs = getComputedStyle(th);
      return {
        key,
        headerW: hr.width,
        bodyW: br ? br.width : null,
        match: br ? Math.abs(hr.width - br.width) <= 2 : null,
        headerTop: cs.top,
        position: cs.position,
        topY: hr.top,
      };
    });
    const tops = colThs.map((th) => th.getBoundingClientRect().top);
    const topBase = tops[0] || 0;
    const columnTopsAligned = tops.every((t) => Math.abs(t - topBase) <= 1);
    const positionsSticky = colThs.every(
      (th) => getComputedStyle(th).position === "sticky",
    );
    const kpi = document.querySelector(".v160-kpi-row .v44-production-strip-items");
    return {
      ok: true,
      groupCount: groups.length,
      groups,
      allGroupsAlign: groups.every((g) => g.alignOk || g.colspan === 1 && !g.keys.length),
      bodySample,
      headerBodyMatch: bodySample.every((x) => x.match !== false),
      columnTopsAligned,
      positionsSticky,
      kpiCols: kpi ? getComputedStyle(kpi).gridTemplateColumns : null,
      claimsLiveGateway: /Gateway Accurate/i.test(
        document.getElementById("v50-source-status")?.textContent || "",
      ),
      previewLabel: /SIMULASI|FIXTURE/i.test(document.body.innerText),
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

const viewports = [
  { w: 1366, h: 768, tag: "1366" },
  { w: 1440, h: 900, tag: "1440" },
  { w: 1920, h: 1080, tag: "1920" },
];

const reports = {};
for (const vp of viewports) {
  await page.setViewport({ width: vp.w, height: vp.h });
  await boot(page, "schedule");
  reports[vp.tag] = await measure(page);
  if (vp.tag === "1440") {
    await page.screenshot({ path: out("step160-jadwal-full-1440.png"), fullPage: true });
    const head = await page.$("table.excel-sheet thead");
    if (head) await head.screenshot({ path: out("step160-header-closeup-1440.png") });
    const kpi = await page.$(".v160-kpi-row, .v44-production-strip");
    if (kpi) await kpi.screenshot({ path: out("step160-kpi-row-1440.png") });

    // resize
    await page.evaluate(() => {
      const CR = window.V3ColumnResize;
      if (!CR) return;
      CR.saveColumnWidths("epv3:colw:schedule", { id: 200, name: 220, item: 260 });
      if (typeof render === "function") render();
    });
    await new Promise((r) => setTimeout(r, 500));
    reports[vp.tag + "_afterResize"] = await measure(page);
    await page.screenshot({ path: out("step160-after-resize-1440.png"), fullPage: false });

    // hide/show a non-sticky column
    await page.evaluate(() => {
      if (typeof setSheetColumnVisible === "function") {
        setSheetColumnVisible("branch", false);
      }
    });
    await new Promise((r) => setTimeout(r, 300));
    reports[vp.tag + "_afterHide"] = await measure(page);
    await page.screenshot({ path: out("step160-after-hide-1440.png"), fullPage: false });
    await page.evaluate(() => {
      if (typeof setSheetColumnVisible === "function") setSheetColumnVisible("branch", true);
    });

    // horizontal scroll
    await page.evaluate(() => {
      const wrap = document.querySelector(".sheetwrap");
      if (wrap) wrap.scrollLeft = 520;
    });
    await new Promise((r) => setTimeout(r, 200));
    await page.screenshot({ path: out("step160-hscroll-1440.png"), fullPage: false });
  }
}

await page.setViewport({ width: 1440, height: 900 });
await boot(page, "inbox");
await page.screenshot({ path: out("step160-inbox-regression-1440.png"), fullPage: true });

const summary = {
  url: URL,
  reports,
  jsErrors: errors.filter((e) => !/history/i.test(e)).slice(0, 20),
  files: fs.readdirSync(OUT).filter((f) => f.startsWith("step160-")),
};
fs.writeFileSync(out("step160-geometry-report.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
await browser.close();

const base = reports["1440"];
if (!base?.ok || !base.headerBodyMatch) process.exitCode = 3;
if (base && base.groups?.some((g) => g.colspan > 1 && !g.alignOk)) process.exitCode = 4;
