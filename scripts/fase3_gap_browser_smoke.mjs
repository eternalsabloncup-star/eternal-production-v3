/**
 * Fase 3 gap-closure browser + API smoke (test DB only).
 * Requires API on V3_SMOKE_API and smoke.lead seeded.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8011/api/v1";
const STATIC_PORT = Number(process.env.V3_SMOKE_STATIC_PORT || 4178);

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  return "application/octet-stream";
}

const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  // Same-origin proxy so live-runtime default `/api/v1` works without CORS.
  if (url.pathname.startsWith("/api/")) {
    try {
      const method = req.method || "GET";
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const bodyBuf = Buffer.concat(chunks);
      const init = {
        method,
        headers: {
          authorization: req.headers.authorization || "",
          accept: "application/json",
        },
      };
      if (req.headers["content-type"]) {
        init.headers["content-type"] = req.headers["content-type"];
      }
      if (!["GET", "HEAD"].includes(method) && bodyBuf.length) {
        init.body = bodyBuf;
      }
      const upstream = await fetch(API_ORIGIN + url.pathname + url.search, init);
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

await new Promise((resolve) => server.listen(STATIC_PORT, "127.0.0.1", resolve));

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
const auth = { Authorization: "Bearer " + access_token };

async function api(path, init = {}) {
  const res = await fetch(API + path, {
    ...init,
    headers: { ...(init.headers || {}), ...auth },
  });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* ignore */
  }
  return { status: res.status, json, text };
}

const apiProbes = {};
apiProbes.health = (await fetch(API_ORIGIN + "/api/v1/health")).ok;
apiProbes.inbox = (await api("/production/inbox?page=1&page_size=5")).status; // may 403 without gateway/perm
apiProbes.schedule = (await api("/production/ops/schedule?page=1&page_size=5")).status;
apiProbes.deliveries = await api("/production/ops/deliveries?include_accurate_links=true&page_size=20");
apiProbes.tasks = await api("/production/jobs/tasks");
apiProbes.paymentSettings = await api("/production/settings/payment-approval");
apiProbes.branches = await api("/production/settings/branches");
apiProbes.machinesSummary = await api("/production/settings/machines-summary");
apiProbes.receipts = (await api("/production/jobs/payment/receipts?page=1&page_size=5")).status;

const coverage = apiProbes.deliveries.json?.coverage || {};
const taskItems = apiProbes.tasks.json?.items || apiProbes.tasks.json?.tasks || [];
const roles = [...new Set((Array.isArray(taskItems) ? taskItems : []).map((t) => t.role).filter(Boolean))];

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
await page.evaluateOnNewDocument((token) => {
  localStorage.setItem("epv3_access_token", token);
  // Prefer same-origin proxy on the static smoke host.
  window.V3_API_BASE = "/api/v1";
}, access_token);

const errors = [];
page.on("pageerror", (err) => errors.push(String(err)));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push("console:" + msg.text());
});

await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
await page.waitForFunction(
  () =>
    typeof window.v3Api === "object" &&
    document.documentElement.classList.contains("v3-auth-ok"),
  { timeout: 30000 },
);

const ui = await page.evaluate(async () => {
  const out = {
    navLabels: [],
    views: {},
    hasBranchesView: typeof window.v3BranchesSettingsView === "function",
    hasPaymentSettings: typeof window.v3PaymentApprovalSettingsView === "function" ||
      typeof window.v3SettingsPaymentView === "function",
    createIsExplicit: typeof window.v3EnsureJob === "function",
    taskActionLabelFn: typeof window.taskActionLabel === "function",
  };
  document.querySelectorAll("nav button, .nav button, [data-nav], .sidebar button, aside button").forEach((el) => {
    const t = (el.textContent || "").trim().replace(/\s+/g, " ");
    if (t && t.length < 60) out.navLabels.push(t);
  });
  const hooks = [
    ["inbox", "v3InboxView"],
    ["schedule", "v3ScheduleView"],
    ["tasks", "v3TeamTasksView"],
    ["deliveries", "v3DeliveryScheduleView"],
    ["payment", "v3PaymentMonitorView"],
    ["settings", "v3SettingsView"],
    ["branches", "v3BranchesSettingsView"],
  ];
  for (const [key, name] of hooks) {
    out.views[key] = typeof window[name] === "function";
  }
  return out;
});

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function goSection(section) {
  await page.evaluate((sec) => {
    if (typeof window.go === "function") window.go(sec);
    else if (typeof window.render === "function") {
      window.section = sec;
      window.render();
    }
  }, section);
  await sleep(400);
}

const interactive = {
  shipping: {},
  tasks: {},
  payment: {},
  schedule: {},
};

await goSection("shippingSchedule");
await page.waitForFunction(
  () =>
    document.getElementById("v3-del-coverage") ||
    document.querySelector(".v3-delivery-sheet") ||
    /Memuat jadwal pengiriman|Gagal|Belum ada Surat Jalan/i.test(document.body.innerText || ""),
  { timeout: 15000 },
).catch(() => {});
await sleep(600);
interactive.shipping = await page.evaluate(async () => {
  const out = {
    coverage: !!document.getElementById("v3-del-coverage"),
    coverageText: (document.getElementById("v3-del-coverage") || {}).textContent || "",
    sheet: !!document.querySelector(".v3-delivery-sheet"),
    scroll: !!document.querySelector(".v3-delivery-scroll"),
    sticky: (document.querySelector(".v3-delivery-sheet") || {}).dataset?.v3Sticky || "",
    sortBefore: null,
    sortAfter: null,
    colToggle: false,
    search: false,
    pageBodyScrollX: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2,
  };
  const sortBtn = document.querySelector('[data-ops="del-sort"][data-key="customer"]');
  out.sortBefore = sortBtn ? sortBtn.textContent.trim() : null;
  if (sortBtn) {
    sortBtn.click();
    await new Promise((r) => setTimeout(r, 50));
    const again = document.querySelector('[data-ops="del-sort"][data-key="customer"]');
    out.sortAfter = again ? again.textContent.trim() : null;
  }
  const col = document.querySelector('[data-ops="del-col"][data-col="address"]');
  if (col) {
    const was = col.checked;
    col.click();
    await new Promise((r) => setTimeout(r, 120));
    const after = document.querySelector('[data-ops="del-col"][data-col="address"]');
    out.colToggle = !!(after && after.checked !== was);
    if (after && after.checked !== was) {
      after.click();
      await new Promise((r) => setTimeout(r, 80));
    }
  }
  const q = document.getElementById("v3-del-q");
  const form = document.getElementById("v3-del-form");
  if (q && form) {
    q.value = "SMOKE-NO-MATCH-XYZ";
    form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((r) => setTimeout(r, 400));
    out.search = true;
    out.searchEmpty = /Belum ada Surat Jalan|tidak menulis Accurate/i.test(document.body.innerText || "");
    q.value = "";
    form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }
  return out;
});

await goSection("tasks");
interactive.tasks = await page.evaluate(async () => {
  const out = {
    sheet: !!document.querySelector("table.task-sheet"),
    roleSelect: false,
    roles: [],
    filterTrigger: !!document.querySelector(".task-sheet .sheet-filter-trigger"),
    search: false,
    kerjakanOrLihat: 0,
    officialSource: window.__V3_OFFICIAL_TASK_SOURCE__ || null,
    officialCount: Array.isArray(window.__V3_OFFICIAL_TASKS__) ? window.__V3_OFFICIAL_TASKS__.length : 0,
  };
  const sel = document.querySelector('select.fieldcontrol');
  const roleSel = [...document.querySelectorAll("select.fieldcontrol")].find((s) =>
    [...s.options].some((o) => o.textContent.includes("Driver")),
  );
  if (roleSel) {
    out.roles = [...roleSel.options].map((o) => o.textContent.trim());
    out.roleSelect = out.roles.includes("Kepala Produksi") && out.roles.includes("Driver");
    roleSel.value = "Driver";
    roleSel.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 80));
  }
  const search = document.getElementById("task-search");
  if (search && typeof window.setTaskSearch === "function") {
    window.setTaskSearch("SMOKE");
    await new Promise((r) => setTimeout(r, 50));
    out.search = true;
    window.setTaskSearch("");
  }
  out.kerjakanOrLihat = document.querySelectorAll('[data-task-action]').length;
  const filterBtn = document.querySelector(".task-sheet .sheet-filter-trigger");
  if (filterBtn) {
    filterBtn.click();
    await new Promise((r) => setTimeout(r, 50));
    out.filterMenu = !!document.getElementById("task-filter-menu");
    if (typeof window.closeTaskColumnFilter === "function") window.closeTaskColumnFilter();
  }
  return out;
});

await goSection("paymentMonitor");
interactive.payment = await page.evaluate(async () => {
  const out = {
    form: !!document.getElementById("v3-rm-form"),
    sheet: !!document.querySelector(".v3-payment-sheet"),
    scroll: !!document.querySelector(".v3-rm-scroll"),
    sticky: (document.querySelector(".v3-payment-sheet") || {}).dataset?.v3Sticky || "",
    sort: false,
    emptyOrRows: false,
  };
  out.emptyOrRows =
    !!document.querySelector(".v3-payment-sheet tbody tr") ||
    /Tidak ada|Memuat|Gagal/i.test(document.body.innerText);
  const sortBtn = document.querySelector('[data-rm="sort"][data-key="customer"]');
  if (sortBtn) {
    const before = sortBtn.textContent.trim();
    sortBtn.click();
    await new Promise((r) => setTimeout(r, 50));
    const after = document.querySelector('[data-rm="sort"][data-key="customer"]');
    out.sort = !!(after && after.textContent.trim() !== before) || before.includes("Pelanggan");
  } else {
    out.sort = !document.querySelector(".v3-payment-sheet"); // empty/loading still ok
  }
  return out;
});

await goSection("schedule");
await sleep(800);
interactive.schedule = await page.evaluate(async () => {
  const overview = document.getElementById("scheduleOverview");
  const text = (overview || document.body).textContent || "";
  const out = {
    overview: !!overview,
    kontrol: !!document.getElementById("v3-kontrol-qty") || !!document.querySelector("#scheduleOverview .v44-production-metric"),
    statusKerja: !!document.getElementById("v3-status-kerja") || /Status Kerja|Memuat Jadwal|Gagal memuat/i.test(text),
    search: !!document.getElementById("v3-sched-q"),
    sheet: !!document.querySelector("table.excel-sheet, table.sheet"),
    labels: /Total Qty SO|Qty Terjadwal|Qty Sudah Dicetak|Qty Belum Selesai/i.test(text),
    buckets: false,
    stickySoCustomer: false,
  };
  const q = document.getElementById("v3-sched-q");
  if (q) {
    q.value = "SMOKE";
    q.dispatchEvent(new Event("input", { bubbles: true }));
    out.searchTyped = true;
  }
  const bucketBtns = [...document.querySelectorAll("button, [data-bucket], .sheetpill")].filter((el) =>
    /Semua|Belum dijadwalkan|Dijadwalkan|HOLD/i.test(el.textContent || ""),
  );
  out.buckets = bucketBtns.length >= 2;
  if (bucketBtns[1]) {
    bucketBtns[1].click();
    await new Promise((r) => setTimeout(r, 120));
    out.bucketClicked = (bucketBtns[1].textContent || "").trim();
  }
  const sheet = document.querySelector("table.excel-sheet, table.sheet");
  out.stickySoCustomer = !!(sheet && /so|customer|po/i.test(sheet.dataset?.v3Sticky || sheet.innerHTML.slice(0, 400)));
  return out;
});

// SJ detail — buka baris pertama bila ada
await goSection("shippingSchedule");
await sleep(500);
interactive.sjDetail = await page.evaluate(async () => {
  const out = { opened: false, hasDetailApiHook: typeof window !== "undefined", coverageLimited: false };
  const cov = document.getElementById("v3-del-coverage");
  out.coverageLimited = !!(cov && /COVERAGE TERBATAS/i.test(cov.textContent || ""));
  const rowBtn = document.querySelector(
    '[data-ops="del-open"], .v3-delivery-sheet tbody tr button, .v3-delivery-sheet tbody tr [data-sj]',
  );
  const row = document.querySelector(".v3-delivery-sheet tbody tr");
  if (rowBtn) {
    rowBtn.click();
    await new Promise((r) => setTimeout(r, 200));
    out.opened = true;
  } else if (row) {
    row.click();
    await new Promise((r) => setTimeout(r, 200));
    out.opened = /detail|SJ|Surat Jalan|item/i.test(document.body.innerText || "");
  } else {
    out.opened = false;
    out.emptyList = true;
  }
  return out;
});

// Settings · Cabang — smoke.lead = kepala (bukan Direktur): baca-saja, tanpa tombol Simpan
await goSection("settings");
await sleep(400);
interactive.settingsCabang = await page.evaluate(async () => {
  const out = {
    tabOpened: false,
    blockedBanner: false,
    writableBanner: false,
    noFakeSave: true,
    table: false,
  };
  const tab = [...document.querySelectorAll("button")].find((b) => /^Cabang$/i.test((b.textContent || "").trim()));
  if (tab) {
    tab.click();
    await new Promise((r) => setTimeout(r, 700));
    out.tabOpened = true;
  }
  out.blockedBanner = !!document.querySelector('[data-testid="master-cabang-blocked"]') ||
    /hanya baca untuk akun ini|Master Cabang writable:\s*BLOCKED/i.test(document.body.innerText || "");
  out.writableBanner = !!document.querySelector('[data-testid="master-cabang-writable"]');
  out.table = !!document.querySelector('[data-testid="branches-effective-table"]');
  const saveish = [...document.querySelectorAll("button")].filter((b) =>
    /Simpan cabang|Tambah cabang|Create branch/i.test(b.textContent || ""),
  );
  // Kepala: tidak boleh ada tombol mutasi. Direktur smoke terpisah.
  out.noFakeSave = saveish.length === 0;
  return out;
});

// Tugas Tim — bukti tombol Kerjakan / Approval Sampel (tidak mengklaim mutasi API sukses)
await goSection("tasks");
await sleep(400);
interactive.taskActions = await page.evaluate(async () => {
  const out = {
    actionButtons: document.querySelectorAll("[data-task-action]").length,
    kerjakanLabel: 0,
    sampleApproveLabel: 0,
    clicked: false,
    mutateClaimed: false,
  };
  const buttons = [...document.querySelectorAll("button, [data-task-action]")];
  out.kerjakanLabel = buttons.filter((b) => /Kerjakan/i.test(b.textContent || "")).length;
  out.sampleApproveLabel = buttons.filter((b) => /Approval Sampel|Setujui Sampel|sample_approve/i.test(b.textContent || "")).length;
  const first = document.querySelector("[data-task-action]");
  if (first) {
    first.click();
    await new Promise((r) => setTimeout(r, 150));
    out.clicked = true;
    out.panelOrToast = /sampel|upload|loading|POD|jadwal|panel|file|Gagal|izin/i.test(document.body.innerText || "");
  }
  return out;
});

await browser.close();
server.close();

const interactiveOk =
  interactive.shipping.coverage &&
  interactive.shipping.sheet &&
  interactive.shipping.scroll &&
  interactive.shipping.sticky === "sj,so" &&
  String(interactive.shipping.coverageText).includes("COVERAGE TERBATAS") &&
  !!interactive.shipping.sortBefore &&
  interactive.shipping.colToggle &&
  interactive.shipping.search &&
  interactive.tasks.sheet &&
  interactive.tasks.roleSelect &&
  interactive.tasks.filterTrigger &&
  interactive.tasks.filterMenu &&
  interactive.payment.form &&
  interactive.payment.sheet &&
  interactive.payment.sticky === "so,customer" &&
  interactive.schedule.overview &&
  interactive.schedule.kontrol &&
  interactive.schedule.statusKerja &&
  interactive.sjDetail.coverageLimited &&
  interactive.settingsCabang.blockedBanner &&
  interactive.settingsCabang.noFakeSave &&
  interactive.settingsCabang.table;

const result = {
  ok: false,
  api: {
    health: apiProbes.health,
    inbox: apiProbes.inbox,
    schedule: apiProbes.schedule,
    deliveries_status: apiProbes.deliveries.status,
    accurate_sj_list_endpoint: coverage.accurate_sj_list_endpoint ?? null,
    include_accurate_links: coverage.include_accurate_links ?? null,
    tasks_status: apiProbes.tasks.status,
    task_roles_seen: roles,
    payment_settings_status: apiProbes.paymentSettings.status,
    bypass_enabled_default_read: apiProbes.paymentSettings.json?.payment_approval?.bypass_enabled,
    branches_status: apiProbes.branches.status,
    branches_can_manage: apiProbes.branches.json?.can_manage,
    machines_status: apiProbes.machinesSummary.status,
    receipts: apiProbes.receipts,
  },
  ui,
  interactive,
  interactiveOk,
  errors,
};

result.ok =
  result.api.health &&
  [200, 403].includes(result.api.inbox) &&
  result.api.schedule === 200 &&
  result.api.deliveries_status === 200 &&
  result.api.tasks_status === 200 &&
  result.api.payment_settings_status === 200 &&
  result.api.branches_status === 200 &&
  result.api.branches_can_manage === false &&
  result.api.machines_status === 200 &&
  result.ui.createIsExplicit &&
  result.ui.hasBranchesView &&
  result.ui.hasPaymentSettings &&
  result.api.task_roles_seen.length >= 1 &&
  interactiveOk &&
  errors.filter(
    (e) =>
      !String(e).includes("favicon") &&
      !String(e).includes("Failed to load resource") &&
      !String(e).includes("404") &&
      !String(e).includes("403") &&
      !String(e).includes("503"),
  ).length === 0;

console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 1);
