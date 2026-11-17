/**
 * Sticky geometry parity across 5 sheets (desktop viewport).
 * Requires smoke.lead + API on V3_SMOKE_API. Does not invent task rows.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_STICKY_STATIC_PORT || 4179);
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

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
      const upstream = await fetch(API_ORIGIN + url.pathname + url.search, {
        method: req.method || "GET",
        headers: { authorization: req.headers.authorization || "", accept: "application/json" },
      });
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") || "application/json",
      });
      res.end(buf);
    } catch (err) {
      res.writeHead(502);
      res.end(String(err));
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

const puppeteerMod = process.env.PUPPETEER_CORE_PATH
  ? await import(process.env.PUPPETEER_CORE_PATH)
  : await import(
      "/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js"
    );
const puppeteer = puppeteerMod.default || puppeteerMod;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await page.evaluateOnNewDocument((token) => {
  localStorage.setItem("epv3_access_token", token);
  window.V3_API_BASE = "/api/v1";
}, access_token);

await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
await page.waitForFunction(
  () => typeof window.v3Api === "object" && document.documentElement.classList.contains("v3-auth-ok"),
  { timeout: 30000 },
);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function go(section) {
  await page.evaluate((sec) => {
    if (typeof window.go === "function") window.go(sec);
  }, section);
  await sleep(700);
}

async function probeSheet(section, selector, expectedSticky) {
  await go(section);
  return page.evaluate(
    async ({ selector, expectedSticky }) => {
      const table = document.querySelector(selector);
      const wrap =
        table?.closest(".sheetwrap, .v36-inbox-sheetwrap, .v3-delivery-scroll, .v3-rm-scroll") ||
        table?.parentElement;
      const out = {
        section: null,
        found: !!table,
        stickyAttr: table?.dataset?.v3Sticky || "",
        expectedSticky,
        stickyAttrOk: false,
        scroll: null,
        columns: [],
        overlap: false,
        headerBodyAlign: true,
        resizeOk: null,
        visibilityOk: null,
        verticalStickyHeader: false,
      };
      out.section = document.body.dataset?.section || expectedSticky;
      if (!table || !wrap) return out;
      out.stickyAttrOk = out.stickyAttr === expectedSticky;
      const keys = expectedSticky.split(",").filter(Boolean);
      const measure = () =>
        keys.map((key, idx) => {
          const th = table.querySelector(`thead tr:not(.sheet-group-row) th[data-column="${key}"]`) ||
            table.querySelector(`thead th[data-column="${key}"]`);
          const td = table.querySelector(`tbody td[data-column="${key}"]`);
          const thR = th ? th.getBoundingClientRect() : null;
          const tdR = td ? td.getBoundingClientRect() : null;
          const thCs = th ? getComputedStyle(th) : null;
          const tdCs = td ? getComputedStyle(td) : null;
          return {
            key,
            idx,
            thSticky: !!(thCs && thCs.position.includes("sticky")),
            tdSticky: !!(tdCs && tdCs.position.includes("sticky")),
            thLeft: thCs?.left || null,
            tdLeft: tdCs?.left || null,
            thZ: thCs ? Number(thCs.zIndex) || 0 : 0,
            tdZ: tdCs ? Number(tdCs.zIndex) || 0 : 0,
            thWidth: thR ? thR.width : 0,
            tdWidth: tdR ? tdR.width : 0,
            thX: thR ? thR.x : null,
            tdX: tdR ? tdR.x : null,
          };
        });

      const beforeScroll = measure();
      const left0 = wrap.scrollLeft;
      wrap.scrollLeft = Math.min(wrap.scrollWidth, left0 + 220);
      await new Promise((r) => setTimeout(r, 50));
      const afterScroll = measure();
      wrap.scrollTop = Math.min(wrap.scrollHeight, wrap.scrollTop + 80);
      await new Promise((r) => setTimeout(r, 40));
      const head = table.querySelector("thead th");
      const headCs = head ? getComputedStyle(head) : null;
      out.verticalStickyHeader = !!(headCs && headCs.position.includes("sticky"));
      wrap.scrollLeft = left0;
      wrap.scrollTop = 0;

      out.scroll = {
        canScrollX: wrap.scrollWidth > wrap.clientWidth + 2,
        canScrollY: wrap.scrollHeight > wrap.clientHeight + 2,
        stickyHolds:
          afterScroll.length > 0 &&
          afterScroll.every((m, i) => {
            const b = beforeScroll[i];
            if (!m.thSticky) return false;
            if (m.thX == null || b.thX == null) return false;
            // Sticky columns should stay near the same viewport X after scroll.
            return Math.abs(m.thX - b.thX) < 3;
          }),
      };
      out.columns = afterScroll;
      // Overlap: later sticky left edge must not sit left of earlier sticky right edge.
      for (let i = 1; i < afterScroll.length; i++) {
        const prev = afterScroll[i - 1];
        const cur = afterScroll[i];
        if (prev.thX != null && cur.thX != null && cur.thX + 0.5 < prev.thX + prev.thWidth - 1) {
          out.overlap = true;
        }
      }
      const emptyOnly = !!table.querySelector(
        "tbody tr td[colspan].sheetempty, tbody tr td[colspan].v165-state, tbody tr td[colspan]",
      );
      const dataRows = [...table.querySelectorAll("tbody tr")].filter(
        (tr) => !tr.querySelector("td[colspan]"),
      );
      out.emptyBodyOnly = emptyOnly && dataRows.length === 0;
      // Empty colspan placeholder is not a real sticky body cell — require header sticky only.
      out.headerBodyAlign = out.emptyBodyOnly
        ? afterScroll.every((m) => m.thSticky)
        : afterScroll.every((m) => {
            if (!m.tdWidth) return m.thSticky;
            return (
              m.thSticky &&
              m.tdSticky &&
              Math.abs(m.thWidth - m.tdWidth) < 2.5 &&
              Math.abs((m.thX || 0) - (m.tdX || 0)) < 2.5
            );
          });

      // Column visibility toggle if present
      const colToggle =
        document.querySelector(`[data-ops="del-col"]`) ||
        document.querySelector(`[data-rm][data-col]`) ||
        document.querySelector('input[data-column-visibility]');
      if (colToggle && !colToggle.disabled) {
        const was = colToggle.checked;
        colToggle.click();
        await new Promise((r) => setTimeout(r, 80));
        out.visibilityOk = colToggle.checked !== was;
        if (colToggle.checked !== was) {
          colToggle.click();
          await new Promise((r) => setTimeout(r, 40));
        }
      } else {
        out.visibilityOk = null;
      }

      // Resize handle presence (Jadwal / Inbox often expose resize)
      out.resizeOk = !!table.querySelector(
        ".col-resizer, .sheet-col-resizer, [data-resize], th .resize",
      );
      return out;
    },
    { selector, expectedSticky },
  );
}

const sheets = [
  { name: "schedule", section: "schedule", selector: "table.excel-sheet, table.v3-schedule-sheet, table.sheet", sticky: "id,name" },
  { name: "tasks", section: "tasks", selector: "table.task-sheet", sticky: "so,customer" },
  { name: "inbox", section: "inbox", selector: "table.v36-inbox-sheet", sticky: "id,name" },
  { name: "shipping", section: "shippingSchedule", selector: "table.v3-delivery-sheet", sticky: "sj,so" },
  { name: "payment", section: "paymentMonitor", selector: "table.v3-payment-sheet", sticky: "so,customer" },
];

const results = {};
for (const s of sheets) {
  results[s.name] = await probeSheet(s.section, s.selector, s.sticky);
  results[s.name].name = s.name;
}

await browser.close();
server.close();

const perSheetOk = Object.fromEntries(
  Object.entries(results).map(([k, v]) => {
    const ok =
      v.found &&
      v.stickyAttrOk &&
      v.scroll?.stickyHolds !== false &&
      v.overlap === false &&
      v.headerBodyAlign === true &&
      v.verticalStickyHeader === true;
    return [k, ok];
  }),
);

const report = {
  ok: Object.values(perSheetOk).every(Boolean),
  viewport: { width: 1440, height: 900 },
  perSheetOk,
  results,
};

console.log(JSON.stringify(report, null, 2));
process.exit(report.ok ? 0 : 1);
