/** Step 165 — living UI acceptance + before/after screenshots. */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.STEP165_BASE || "http://127.0.0.1:5173";
const OUT = process.env.STEP165_OUT || "/opt/cursor/artifacts/step165";
const URL = `${BASE}/production.html?epv3_preview=fixture`;
fs.mkdirSync(OUT, { recursive: true });
const out = (n) => path.join(OUT, n);

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

async function boot(section) {
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction(
    () => document.documentElement.classList.contains("v3-auth-ok"),
    { timeout: 20000 },
  );
  await page.evaluate((s) => {
    if (typeof go === "function") go(s);
  }, section);
  await new Promise((r) => setTimeout(r, 700));
}

async function shot(name) {
  await page.screenshot({ path: out(name), fullPage: false });
}

const matrix = [];
const viewports = [
  [1366, 768],
  [1440, 900],
  [1920, 1080],
];

for (const [w, h] of viewports) {
  await page.setViewport({ width: w, height: h });
  await boot("inbox");
  const kpi = await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".v36-kpis.v159-kpi-row > div")];
    return cards.map((el) => {
      const cs = getComputedStyle(el);
      return {
        cls: el.className,
        bg: cs.backgroundColor,
        strong: getComputedStyle(el.querySelector("strong") || el).color,
      };
    });
  });
  const solidGreenAll =
    kpi.length > 0 &&
    kpi.every((c) => /rgb\(0,\s*8|rgb\(5,\s*9|rgb\(8,\s*123/.test(c.bg));
  matrix.push({
    vp: `${w}x${h}`,
    section: "inbox",
    kpiCount: kpi.length,
    hasPrimary: kpi.some((c) => c.cls.includes("kpi-primary")),
    hasSecondary: kpi.some((c) => c.cls.includes("kpi-secondary")),
    solidGreenAll,
    livingCss: await page.evaluate(
      () => !!document.getElementById("v165-living-ui"),
    ),
  });
  await shot(`after-inbox-${w}.png`);

  // hover + selected row
  await page.evaluate(() => {
    const tr = document.querySelector(".v36-inbox-sheet tbody tr");
    if (tr) {
      tr.classList.add("focused");
      tr.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    }
  });
  await shot(`after-inbox-selected-${w}.png`);

  // filter empty
  await page.evaluate(() => {
    const input = document.querySelector("#v36-inbox-search");
    if (input) {
      input.value = "ZZZ_NO_MATCH_XYZ";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  await new Promise((r) => setTimeout(r, 400));
  const emptyState = await page.evaluate(() => {
    const el = document.querySelector(".v165-state--filter-empty, .sheetempty");
    return {
      text: (el?.textContent || "").trim().slice(0, 120),
      cls: el?.className || null,
    };
  });
  matrix.push({ vp: `${w}x${h}`, emptyState });
  if (w === 1440) await shot("after-empty-state-1440.png");

  await boot("schedule");
  await shot(`after-jadwal-${w}.png`);
  // sticky/resize smoke
  const resizeOk = await page.evaluate(() => {
    const t = document.querySelector("table[data-v3-colw]");
    return {
      storage: t?.dataset.v3Colw || null,
      handles: t ? t.querySelectorAll("[data-col-resize]").length : 0,
      reset: !!document.querySelector(".v162-reset-lebar"),
    };
  });
  matrix.push({ vp: `${w}x${h}`, scheduleResize: resizeOk });

  await boot("tasks");
  await shot(`after-tugas-${w}.png`);

  if (w === 1440) {
    await boot("inbox");
    await shot("after-sidebar-toolbar-1440.png");
    await page.evaluate(() => {
      const o = (window.orders || []).find((x) => !x.deleted);
      if (o && typeof window.v49PODetail === "function") window.v49PODetail(o.id);
      else {
        const btn = [...document.querySelectorAll("button")].find((b) =>
          /Detail PO|Ringkasan/i.test(b.getAttribute("aria-label") || b.textContent || ""),
        );
        btn?.click();
      }
    });
    await new Promise((r) => setTimeout(r, 500));
    const drawer = await page.evaluate(() => {
      const back = document.querySelector(".drawerback");
      const panel = document.querySelector(
        ".drawerback .detaildrawer, .drawerback .drawer",
      );
      return {
        open: !!back,
        animName: panel ? getComputedStyle(panel).animationName : null,
      };
    });
    matrix.push({ drawer });
    await shot("after-detail-po-1440.png");

    // toast feedback
    await page.evaluate(() => {
      if (typeof toast === "function") toast("Job V3 dibuat untuk SO/TEST");
    });
    await new Promise((r) => setTimeout(r, 200));
    const toastState = await page.evaluate(() => {
      const t = document.getElementById("toast");
      return { cls: t?.className, text: t?.textContent };
    });
    matrix.push({ toastState });
    await shot("after-toast-success-1440.png");

    await page.evaluate(() => {
      if (typeof toast === "function") toast("Transaksi gagal");
    });
    await new Promise((r) => setTimeout(r, 200));
    const toastErr = await page.evaluate(() => {
      const t = document.getElementById("toast");
      return { cls: t?.className, text: t?.textContent };
    });
    matrix.push({ toastErr });

    // Escape closes drawer
    await page.keyboard.press("Escape");
    await new Promise((r) => setTimeout(r, 220));
    const closed = await page.evaluate(
      () => !document.querySelector(".drawerback"),
    );
    matrix.push({ escapeClosed: closed });
  }
}

await browser.close();
const report = { matrix, errors, pass: true };
const fails = [];
for (const row of matrix) {
  if (row.solidGreenAll) fails.push("inbox KPI still solid green");
  if (row.hasPrimary === false) fails.push("missing kpi-primary");
  if (row.hasSecondary === false) fails.push("missing kpi-secondary");
  if (row.livingCss === false) fails.push("missing v165 style");
  if (row.scheduleResize && row.scheduleResize.handles < 1)
    fails.push("resize handles missing");
  if (row.toastState && !/success/.test(row.toastState.cls || ""))
    fails.push("success toast class missing");
  if (row.toastErr && !/error/.test(row.toastErr.cls || ""))
    fails.push("error toast class missing");
  if (row.escapeClosed === false) fails.push("escape did not close drawer");
}
report.fails = [...new Set(fails)];
report.pass = report.fails.length === 0 && errors.length === 0;
fs.writeFileSync(out("step165-report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (!report.pass) process.exit(1);
