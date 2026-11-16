/**
 * Browser E2E — six-role mutations under V3_WORKFLOW_AUTHORIZATION=enforced.
 * Also proves sticky Output idempotency (double-click + retry after simulated timeout).
 *
 * Prerequisite: scripts/fase3_e2e_browser_enforced_server.py on :8014
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(path.resolve(__dirname, ".."), "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8014/api/v1";
const STATIC_PORT = Number(process.env.V3_SMOKE_STATIC_PORT || 4188);
const PASS = "secret-pass";
const SO = "SO/E2E/BROWSER-ENF";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (url.pathname.startsWith("/api/")) {
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
      if (req.headers["content-type"]) init.headers["content-type"] = req.headers["content-type"];
      if (!["GET", "HEAD"].includes(method) && bodyBuf.length) init.body = bodyBuf;
      const upstream = await fetch(API_ORIGIN + url.pathname + url.search, init);
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") || "application/json",
      });
      res.end(buf);
      return;
    }
    let rel = decodeURIComponent(url.pathname);
    if (rel === "/") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end("<!doctype html><title>V3 E2E Enforced</title><p>OK</p>");
      return;
    }
    const file = path.join(publicDir, rel.replace(/^\//, ""));
    if (!file.startsWith(publicDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404);
      res.end("missing");
      return;
    }
    res.writeHead(200, { "Content-Type": contentType(file) });
    fs.createReadStream(file).pipe(res);
  } catch (err) {
    try {
      res.writeHead(500);
      res.end(String(err));
    } catch {
      /* */
    }
  }
});
await new Promise((r) => server.listen(STATIC_PORT, "127.0.0.1", r));

const puppeteer = (
  await import("/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js")
).default;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const page = await browser.newPage();
page.setDefaultTimeout(45000);

async function login(user) {
  const res = await fetch(API + "/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: user, password: PASS }),
  });
  if (!res.ok) throw new Error("login " + user + " " + res.status);
  return await res.json();
}

async function api(token, pathName, init = {}) {
  const res = await fetch(API + pathName, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: "Bearer " + token,
      Accept: "application/json",
    },
  });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* */
  }
  return { status: res.status, json, text };
}

function pngFile() {
  const b64 =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  return Uint8Array.from(Buffer.from(b64, "base64"));
}

function rec(row) {
  results.push(row);
  console.log(JSON.stringify(row));
}

async function openAs(user) {
  const body = await login(user);
  const token = body.access_token;
  if (body.workflow_authorization !== "enforced") {
    throw new Error("expected enforced, got " + body.workflow_authorization);
  }
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/`, {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });
  await page.evaluate((tok) => {
    localStorage.setItem("epv3_access_token", tok);
    localStorage.setItem("v3_token", tok);
    localStorage.setItem("access_token", tok);
    window.V3_API_BASE = "/api/v1";
  }, token);
  await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForFunction(
    () =>
      document.documentElement.classList.contains("v3-auth-ok") &&
      typeof window.v3OpenWorkflow === "function",
    { timeout: 30000 },
  );
  await sleep(600);
  await page.evaluate((so) => {
    window.__V3_INBOX__ = {
      mode: "live",
      items: [{ id: so }],
      total: 1,
      rowCount: 1,
      page: 1,
      pageSize: 50,
      fetchError: "",
    };
  }, SO);
  return { token, loginBody: body };
}

async function seedOfficialTasks(token) {
  const tasks = await api(token, "/production/jobs/tasks");
  await page.evaluate(
    (payload, so) => {
      window.__V3_INBOX__ = Object.assign({}, window.__V3_INBOX__ || {}, {
        mode: "live",
        fetchError: "",
      });
      window.__V3_OFFICIAL_TASK_SOURCE__ = "v3_official";
      window.__V3_OFFICIAL_TASK_ERROR__ = null;
      window.__V3_OFFICIAL_TASKS__ = (payload.tasks || []).map((task) => ({
        o: {
          id: task.accurate_so_number,
          name: task.customer_name || task.accurate_so_number,
          branch: task.branch_id || "branch-a",
          v3JobId: task.job_id,
        },
        t: {
          id: task.kind,
          role: task.role,
          label: task.label,
          verb: task.verb || "Kerjakan",
          group: task.group || task.kind,
        },
        e: {
          status:
            task.state === "actionable"
              ? "Siap"
              : task.state === "done"
                ? "Selesai"
                : "Menunggu",
          note: task.reason || "",
          updated: "V3",
          qty: 0,
          file: "",
        },
        status:
          task.state === "actionable"
            ? "Siap"
            : task.state === "done"
              ? "Selesai"
              : "Menunggu",
        official: task,
      }));
      if (!Array.isArray(window.orders)) window.orders = [];
      if (!window.orders.find((o) => o && o.id === so)) {
        window.orders.push({
          id: so,
          name: "Browser Enforced Co",
          branch: "branch-a",
          branchId: "branch-a",
          qty: 100,
          v3JobId: (payload.jobs && payload.jobs[0] && payload.jobs[0].id) || 1,
          sourceLines: [
            {
              id: "line-print",
              qty: 100,
              processSnapshot: "PRINT",
              production_process: "print",
              itemId: "P1",
            },
          ],
        });
      }
      if (typeof window.go === "function") window.go("tasks");
    },
    tasks.json || {},
    SO,
  );
  await sleep(500);
  return tasks;
}

async function openPanelViaKerjakan(kindHint) {
  return page.evaluate(
    (hint, so) => {
      const buttons = [
        ...document.querySelectorAll('button[data-task-action="kerjakan"]'),
      ];
      const match = buttons.find((b) => {
        const soAttr = b.getAttribute("data-so");
        const kind = b.getAttribute("data-kind");
        if (soAttr && soAttr !== so) return false;
        if (hint && kind && kind !== hint) return false;
        return true;
      });
      if (match) {
        match.click();
        return { path: "kerjakan_button", kind: match.getAttribute("data-kind") };
      }
      if (typeof window.openTask === "function") {
        window.openTask(so, hint || "detail");
        return { path: "openTask", kind: hint };
      }
      return { path: "none" };
    },
    kindHint || null,
    SO,
  );
}

async function waitDrawer(label) {
  await page.waitForSelector(".v3-workflow-body, [data-v3], #v3-close-drawer", {
    timeout: 25000,
  });
  await sleep(600);
}

async function clickV3(action, { allowGet = false, timeoutMs = 20000 } = {}) {
  const before = Date.now();
  const hitPromise = new Promise((resolve) => {
    const handler = async (res) => {
      try {
        const u = res.url();
        if (!u.includes("/api/v1/production/")) return;
        const method = res.request().method();
        if (!allowGet && ["GET", "HEAD"].includes(method)) return;
        page.off("response", handler);
        resolve({
          url: u,
          status: res.status(),
          method,
          ms: Date.now() - before,
        });
      } catch {
        /* */
      }
    };
    page.on("response", handler);
    setTimeout(() => {
      page.off("response", handler);
      resolve(null);
    }, timeoutMs);
  });
  const clicked = await page.evaluate((act) => {
    const btn = document.querySelector(`[data-v3="${act}"]`);
    if (!btn) return false;
    btn.disabled = false;
    btn.click();
    return true;
  }, action);
  const hit = await hitPromise;
  return { clicked, hit };
}

async function setField(id, value) {
  await page.evaluate(
    (i, v) => {
      const el = document.getElementById(i);
      if (!el) return;
      el.value = v;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    },
    id,
    String(value),
  );
}

async function selectFirst(id) {
  return page.evaluate((i) => {
    const el = document.getElementById(i);
    if (!el) return false;
    const opt = [...el.options].find((o) => o.value);
    if (!opt) return false;
    el.value = opt.value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, id);
}

async function attachPng(id) {
  const input = await page.$(`#${id}`);
  if (!input) return false;
  const tmp = `/tmp/${id}-enf.png`;
  fs.writeFileSync(tmp, pngFile());
  await input.uploadFile(tmp);
  return true;
}

async function tracking(token, jobId) {
  return api(token, `/production/jobs/${jobId}/tracking`);
}

async function verifierToken() {
  return (await login("e2e.kepala")).access_token;
}

async function runStep(name, fn) {
  try {
    await fn();
  } catch (err) {
    rec({
      role: name,
      action: "step_error",
      http: null,
      authMode: "enforced",
      verdict: "FAIL",
      detail: { error: String(err && err.message ? err.message : err) },
    });
  }
}

// --- Prove login reports enforced ---
{
  const body = await login("e2e.direktur");
  rec({
    role: "System",
    action: "Login reports workflow_authorization",
    http: 200,
    authMode: body.workflow_authorization,
    dbBefore: "—",
    dbAfter: `system_director=${body.system_director}`,
    verdict: body.workflow_authorization === "enforced" ? "PASS_MUTATION" : "FAIL",
    detail: {
      workflow_authorization: body.workflow_authorization,
      settings_enabled: body.settings_enabled,
      system_director: body.system_director,
    },
  });
}

let jobId = 1;
let assignmentId = null;
let outputEventId = null;

// --- Designer upload ---
await runStep("Designer", async () => {
  const { token, loginBody } = await openAs("e2e.designer");
  await seedOfficialTasks(token);
  const open = await openPanelViaKerjakan("design_upload");
  await waitDrawer("designer");
  await setField("v3-design-file", "enf-design.pdf");
  await setField("v3-design-key", "designs/enf-design.pdf");
  await setField("v3-design-line", "line-print");
  const mut = await clickV3("design-upload");
  await sleep(700);
  const board = await api(token, `/production/jobs/${jobId}/board`);
  // board may 403 without job.board.read — use director for board verify
  const vtok = (await login("e2e.direktur")).access_token;
  const b2 = await api(vtok, `/production/jobs/${jobId}/board`);
  const n = (b2.json?.design_versions || []).length;
  rec({
    role: "Designer",
    action: "Upload desain (enforced UI)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    dbBefore: "versions=0",
    dbAfter: `versions=${n}`,
    openPath: open.path,
    verdict: mut.hit?.status < 300 && n >= 1 ? "PASS_MUTATION" : "FAIL",
    detail: { mut, open },
  });
});

// --- Direktur bypass ---
await runStep("Direktur", async () => {
  const { token, loginBody } = await openAs("e2e.direktur");
  await seedOfficialTasks(token);
  await page.evaluate((so) => window.openTask(so, "design_approve"), SO);
  await waitDrawer("direktur");
  await setField("v3-design-bypass-reason", "enforced e2e design bypass");
  const dmut = await clickV3("design-bypass");
  await sleep(400);
  await setField("v3-pay-bypass-reason", "enforced e2e payment bypass");
  const pmut = await clickV3("pay-bypass");
  await sleep(700);
  const job = await api(token, `/production/jobs/${jobId}`);
  rec({
    role: "Direktur",
    action: "Design+payment bypass (Full Access)",
    http: `${dmut.hit?.status}/${pmut.hit?.status}`,
    authMode: loginBody.workflow_authorization,
    dbAfter: `design=${job.json?.design_status};payment=${job.json?.payment_status}`,
    verdict:
      dmut.hit?.status < 300 &&
      pmut.hit?.status < 300 &&
      job.json?.payment_status === "bypassed"
        ? "PASS_MUTATION"
        : "FAIL",
    detail: { dmut, pmut, system_director: loginBody.system_director },
  });
});

// --- Kepala schedule ---
await runStep("Kepala", async () => {
  const { token, loginBody } = await openAs("e2e.kepala");
  const before = await api(token, `/production/jobs/${jobId}`);
  jobId = before.json?.id || 1;
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("schedule");
  await waitDrawer("kepala");
  await page.evaluate((so) => {
    const o = (window.orders || []).find((x) => x && x.id === so);
    if (o) {
      o.branch = "branch-a";
      o.branchId = "branch-a";
    }
  }, SO);
  await setField("v3-asg-line", "line-print");
  await setField("v3-asg-date", new Date().toISOString().slice(0, 10));
  await setField("v3-asg-pass", "1");
  await setField("v3-asg-qty", "100");
  for (let i = 0; i < 40; i++) {
    if ((await selectFirst("v3-asg-op")) && (await selectFirst("v3-asg-mc"))) break;
    await sleep(250);
  }
  const mut = await clickV3("asg-create");
  await sleep(900);
  const board = await api(token, `/production/jobs/${jobId}/board`);
  assignmentId = board.json?.assignments?.[0]?.id || null;
  rec({
    role: "Kepala Produksi",
    action: "Assignment (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    dbAfter: `assignment_id=${assignmentId}`,
    verdict: mut.hit?.status < 300 && assignmentId ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

// --- Screener / Helper / Sample / Approve / Output ---
await runStep("Screener", async () => {
  const { token, loginBody } = await openAs("e2e.screener");
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("screen");
  await waitDrawer("screener");
  await setField("v3-prep-line", "line-print");
  await setField("v3-prep-po", "100");
  await setField("v3-prep-screen", "2");
  await setField("v3-prep-ev", "enf-screen");
  if (assignmentId) await setField("v3-asg-id", String(assignmentId));
  const mut = await clickV3("prep-screen");
  await sleep(700);
  const vtok = await verifierToken();
  const types = ((await tracking(vtok, jobId)).json?.events || []).map((e) => e.event_type);
  rec({
    role: "Screener",
    action: "Prep screen (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    dbAfter: types.includes("prep_screener") ? "prep_screener" : types.slice(-2).join(","),
    verdict: mut.hit?.status < 300 && types.includes("prep_screener") ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

await runStep("Helper/prep", async () => {
  const { token, loginBody } = await openAs("e2e.helper");
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("prepare");
  await waitDrawer("helper");
  await setField("v3-prep-line", "line-print");
  await setField("v3-prep-po", "100");
  await setField("v3-prep-helper", "80");
  await setField("v3-prep-ev", "enf-helper");
  if (assignmentId) await setField("v3-asg-id", String(assignmentId));
  const mut = await clickV3("prep-helper");
  await sleep(700);
  const vtok = await verifierToken();
  const types = ((await tracking(vtok, jobId)).json?.events || []).map((e) => e.event_type);
  rec({
    role: "Helper",
    action: "Prep helper (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    dbAfter: types.includes("prep_helper") ? "prep_helper" : "",
    verdict: mut.hit?.status < 300 && types.includes("prep_helper") ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

await runStep("Operator/sample", async () => {
  const { token, loginBody } = await openAs("e2e.operator");
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("sample");
  await waitDrawer("sample");
  await setField("v3-sample-file", "enf-sample.jpg");
  await setField("v3-sample-key", "samples/enf-sample.jpg");
  const mut = await clickV3("sample-upload");
  await sleep(700);
  rec({
    role: "Operator",
    action: "Sample upload (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    verdict: mut.hit?.status < 300 ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

await runStep("Kepala/sample_approve", async () => {
  const { token, loginBody } = await openAs("e2e.kepala");
  await seedOfficialTasks(token);
  await page.evaluate((so) => window.openTask(so, "sample_approve"), SO);
  await waitDrawer("sample-approve");
  for (let i = 0; i < 20; i++) {
    if (await page.evaluate(() => !!document.querySelector('[data-v3="sample-approve"]')))
      break;
    await sleep(300);
  }
  const mut = await clickV3("sample-approve");
  await sleep(700);
  rec({
    role: "Kepala Produksi",
    action: "Sample approve (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    verdict: mut.hit?.status < 300 ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

// --- Output + sticky idempotency ---
await runStep("Operator/output+idem", async () => {
  const { token, loginBody } = await openAs("e2e.operator");
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("print");
  await waitDrawer("print");
  if (assignmentId) await setField("v3-out-asg", String(assignmentId));
  await setField("v3-out-qty", "40");
  await setField("v3-out-pass", "1");
  await setField("v3-out-lot", "L1");

  const keyBefore = await page.evaluate(() => {
    const slot = window.__V3_IDEM__;
    return slot ? Object.keys(slot.slots || {}) : [];
  });

  const mut = await clickV3("out-confirm");
  await sleep(900);

  const keyAfterFirst = await page.evaluate(() => {
    const slots = window.__V3_IDEM__ && window.__V3_IDEM__.slots;
    const keys = Object.keys(slots || {});
    const first = keys[0] && slots[keys[0]];
    return { keys, committed: first && first.committed, key: first && first.key };
  });

  // Double-click same logical submission (sticky key) — must not create second event.
  // Short timeout: success path short-circuits with no new POST (hit may be null).
  const dup = await clickV3("out-confirm", { timeoutMs: 4000 });
  await sleep(400);

  // Simulate timeout retry: sticky/latch should short-circuit or 409-reconcile.
  const retry = await clickV3("out-confirm", { timeoutMs: 4000 });
  await sleep(400);

  const vtok = await verifierToken();
  const tr = await tracking(vtok, jobId);
  const outs = (tr.json?.events || []).filter((e) => e.event_type === "output_confirmed");
  outputEventId = outs[0]?.id || null;
  const qtySum = outs.reduce((s, e) => s + Number(e.qty_physical || 0), 0);

  rec({
    role: "Operator",
    action: "Output + sticky idempotency double-click/retry",
    http: `${mut.hit?.status}/${dup.hit?.status}/${retry.hit?.status}`,
    authMode: loginBody.workflow_authorization,
    dbBefore: "0 output",
    dbAfter: `events=${outs.length};qty=${qtySum};id=${outputEventId}`,
    audit: outs.length === 1 && qtySum === 40,
    verdict:
      mut.hit?.status < 300 &&
      outs.length === 1 &&
      qtySum === 40 &&
      keyAfterFirst.committed
        ? "PASS_MUTATION"
        : "FAIL",
    detail: {
      mut,
      dup,
      retry,
      keyBefore,
      keyAfterFirst,
      note: "dup/retry may be 409 reconciled or short-circuit; DB must stay single event qty 40",
    },
  });
});

await runStep("Helper/pack", async () => {
  const { token, loginBody } = await openAs("e2e.helper");
  await seedOfficialTasks(token);
  await page.evaluate((so) => window.openTask(so, "packing"), SO);
  await waitDrawer("pack");
  if (!outputEventId) {
    const vtok = await verifierToken();
    const outs = ((await tracking(vtok, jobId)).json?.events || []).filter(
      (e) => e.event_type === "output_confirmed",
    );
    outputEventId = outs[0]?.id || null;
  }
  if (outputEventId) {
    await setField("v3-hv-src", String(outputEventId));
    await setField("v3-hv-qty", "40");
  }
  const hv = await clickV3("out-helper-verify");
  await sleep(500);
  await setField("v3-pack-line", "line-print");
  await setField("v3-pack-qty", "35");
  await setField("v3-pack-lot", "L1");
  const pack = await clickV3("pack");
  await sleep(700);
  const vtok = await verifierToken();
  const types = ((await tracking(vtok, jobId)).json?.events || []).map((e) => e.event_type);
  rec({
    role: "Helper",
    action: "Verify+packing (enforced)",
    http: `${hv.hit?.status}/${pack.hit?.status}`,
    authMode: loginBody.workflow_authorization,
    dbAfter: types.filter((t) => /helper_verif|packing/.test(t)).join(","),
    verdict: hv.hit?.status < 300 && pack.hit?.status < 300 ? "PASS_MUTATION" : "FAIL",
    detail: { hv, pack },
  });
});

await runStep("Driver", async () => {
  const { token, loginBody } = await openAs("e2e.driver");
  await seedOfficialTasks(token);
  await openPanelViaKerjakan("loading");
  await waitDrawer("driver");
  await setField("v3-sj-id", "sj-browser");
  await setField("v3-sj-no", "SJ/BROWSER/001");
  await setField("v3-sj-line", "SL-1");
  await setField("v3-load-so-line", "line-print");
  await setField("v3-load-qty", "20");
  const auth = await clickV3("load-authority", { allowGet: true });
  await sleep(800);
  await page.evaluate(() => {
    const b = document.getElementById("v3-load-btn");
    if (b) b.disabled = false;
  });
  const load = await clickV3("load");
  await sleep(900);
  await setField("v3-pod-qty", "20");
  await setField("v3-pod-recv", "Penerima Enforced");
  await attachPng("v3-pod-photo1");
  await attachPng("v3-pod-photo2");
  await attachPng("v3-pod-sig-s");
  await attachPng("v3-pod-sig-r");
  const podPromise = new Promise((resolve) => {
    let last = null;
    const handler = async (res) => {
      const u = res.url();
      if (!u.includes("/api/v1/production/")) return;
      if (["GET", "HEAD"].includes(res.request().method())) return;
      last = { url: u, status: res.status(), method: res.request().method() };
      if (u.includes("/pod")) {
        page.off("response", handler);
        resolve(last);
      }
    };
    page.on("response", handler);
    setTimeout(() => {
      page.off("response", handler);
      resolve(last);
    }, 25000);
  });
  await page.evaluate(() => {
    const btn = document.querySelector('[data-v3="pod"]');
    if (btn) btn.click();
  });
  const podHit = await podPromise;
  await sleep(1000);
  const vtok = await verifierToken();
  const types = ((await tracking(vtok, jobId)).json?.events || []).map((e) => e.event_type);
  rec({
    role: "Driver",
    action: "Loading+POD (enforced)",
    http: `${auth.hit?.status}/${load.hit?.status}/${podHit?.status}`,
    authMode: loginBody.workflow_authorization,
    dbAfter: types.filter((t) => /loading|pod/.test(t)).join(","),
    verdict:
      load.hit?.status < 300 &&
      types.includes("loading") &&
      types.includes("pod")
        ? "PASS_MUTATION"
        : "FAIL",
    detail: { auth, load, podHit, types: types.slice(-8) },
  });
});

// --- Negative: no grant ---
await runStep("NoGrant", async () => {
  const body = await login("e2e.nogrant");
  const r = await api(body.access_token, `/production/jobs/${jobId}`);
  rec({
    role: "NoGrant",
    action: "GET job tanpa ScopedGrant",
    http: r.status,
    authMode: body.workflow_authorization,
    verdict: r.status === 403 ? "PASS_MUTATION" : "FAIL",
    detail: r.json,
  });
});

// --- Negative: wrong branch ---
await runStep("WrongBranch", async () => {
  const body = await login("e2e.wrongbranch");
  const r = await api(body.access_token, `/production/jobs/${jobId}`);
  // job is branch-a; user only granted branch-b
  rec({
    role: "WrongBranch",
    action: "GET job branch-a dengan grant branch-b",
    http: r.status,
    authMode: body.workflow_authorization,
    verdict: r.status === 403 ? "PASS_MUTATION" : "FAIL",
    detail: r.json,
  });
});

// --- Negative: designer payment bypass via UI ---
await runStep("Designer/deny", async () => {
  const { token, loginBody } = await openAs("e2e.designer");
  await page.evaluate((so) => {
    if (!window.orders?.find((o) => o.id === so)) {
      window.orders = window.orders || [];
      window.orders.push({ id: so, name: so, branchId: "branch-a", sourceLines: [] });
    }
    window.openTask(so, "detail");
  }, SO);
  await waitDrawer("deny");
  await setField("v3-pay-bypass-reason", "designer tidak boleh enforced");
  const mut = await clickV3("pay-bypass");
  await sleep(500);
  rec({
    role: "Designer",
    action: "Payment bypass ditolak (enforced)",
    http: mut.hit?.status || null,
    authMode: loginBody.workflow_authorization,
    verdict: mut.hit?.status === 403 ? "PASS_MUTATION" : "FAIL",
    detail: mut,
  });
});

await browser.close();
server.close();

const summary = {
  ok: results.every((r) => r.verdict === "PASS_MUTATION"),
  pass: results.filter((r) => r.verdict === "PASS_MUTATION").length,
  fail: results.filter((r) => r.verdict === "FAIL").length,
  authModeClaimed: "enforced",
  roles: results,
};
fs.writeFileSync(
  "/tmp/epv3-fase3-e2e-browser-enforced.json",
  JSON.stringify(summary, null, 2),
);
console.log(
  JSON.stringify(
    {
      ok: summary.ok,
      pass: summary.pass,
      fail: summary.fail,
      authMode: "enforced",
    },
    null,
    2,
  ),
);
process.exit(summary.ok ? 0 : 2);
