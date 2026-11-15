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
  };
  document.querySelectorAll("nav button, .nav button, [data-nav], .sidebar button, aside button").forEach((el) => {
    const t = (el.textContent || "").trim().replace(/\s+/g, " ");
    if (t && t.length < 60) out.navLabels.push(t);
  });
  // Try known live view hooks if present
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

await browser.close();
server.close();

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
  errors.filter(
    (e) =>
      !String(e).includes("favicon") &&
      !String(e).includes("Failed to load resource") &&
      !String(e).includes("404"),
  ).length === 0;

console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 1);
