/**
 * P0 — Output lost-response / network recovery (browser + API).
 * Prerequisite: scripts/fase3_e2e_browser_enforced_server.py on :8014
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(path.resolve(__dirname, ".."), "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8014/api/v1";
const STATIC_PORT = Number(process.env.V3_SMOKE_STATIC_PORT || 4190);
const PASS = "secret-pass";
const SO = "SO/E2E/BROWSER-ENF";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

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
      res.end("<!doctype html><title>V3 Net Recovery</title><p>OK</p>");
      return;
    }
    const file = path.join(publicDir, rel.replace(/^\//, ""));
    if (!file.startsWith(publicDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404);
      res.end("missing");
      return;
    }
    const ct = file.endsWith(".html")
      ? "text/html; charset=utf-8"
      : file.endsWith(".js")
        ? "text/javascript; charset=utf-8"
        : "application/octet-stream";
    res.writeHead(200, { "Content-Type": ct });
    fs.createReadStream(file).pipe(res);
  } catch (err) {
    res.writeHead(500);
    res.end(String(err));
  }
});
await new Promise((r) => server.listen(STATIC_PORT, "127.0.0.1", r));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function rec(row) {
  results.push(row);
  console.log(JSON.stringify(row));
}

async function login(user) {
  const res = await fetch(API + "/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: user, password: PASS }),
  });
  if (!res.ok) throw new Error("login " + user + " " + res.status);
  return res.json();
}

async function api(token, pathName, init = {}) {
  const headers = {
    Authorization: "Bearer " + token,
    Accept: "application/json",
    ...(init.headers || {}),
  };
  let body = init.body;
  if (body && typeof body === "object" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const res = await fetch(API + pathName, {
    method: init.method || (body ? "POST" : "GET"),
    headers,
    body,
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

async function ensureReadyForOutput(dir, op, kepala, jobId) {
  const tr = await api(kepala.access_token, `/production/jobs/${jobId}/tracking`);
  const types = (tr.json?.events || []).map((e) => e.event_type);
  if (types.includes("output_confirmed")) return { already: true };

  const job = await api(dir.access_token, `/production/jobs/${jobId}`);
  if (job.json?.design_status !== "bypassed" && job.json?.design_status !== "approved") {
    await api(dir.access_token, `/production/jobs/${jobId}/design/versions`, {
      method: "POST",
      body: { file_name: "d.pdf", storage_key: "designs/net.pdf", so_line_id: "line-print" },
    });
    const board2 = await api(dir.access_token, `/production/jobs/${jobId}/board`);
    const ver = (board2.json?.design_versions || []).find((d) => d.status === "pending");
    if (ver) {
      const dec = await api(dir.access_token, `/production/jobs/design/versions/${ver.id}/decision`, {
        method: "POST",
        body: { decision: "approved", bypass: true, reason: "net-recovery-test design bypass" },
      });
      if (dec.status >= 300) throw new Error("design " + dec.status + " " + dec.text);
    }
  }
  if (job.json?.payment_status !== "bypassed") {
    const pay = await api(dir.access_token, `/production/jobs/${jobId}/payment/bypass`, {
      method: "POST",
      body: { reason: "net-recovery-test-bypass-payment", idempotency_key: "net-pay-bypass-001" },
    });
    if (pay.status >= 300 && pay.status !== 409) throw new Error("pay " + pay.status + " " + pay.text);
  }

  let board3 = await api(kepala.access_token, `/production/jobs/${jobId}/board`);
  let asg = (board3.json?.assignments || [])[0];
  if (!asg) {
    const created = await api(kepala.access_token, `/production/jobs/${jobId}/schedule/assignments`, {
      method: "POST",
      body: {
        so_line_id: "line-print",
        operator_user_id: op.user_id,
        operator_name: "Operator E2E",
        machine_name: "Semi Auto Enforced",
        work_date: new Date().toISOString().slice(0, 10),
        qty_planned: "100",
        color_pass: 1,
      },
    });
    if (created.status >= 300) throw new Error("assignment " + created.status + " " + created.text);
    asg = { id: created.json.id };
  }

  const types2 = (
    (await api(kepala.access_token, `/production/jobs/${jobId}/tracking`)).json?.events || []
  ).map((e) => e.event_type);
  if (!types2.includes("prep_screener")) {
    const sc = await api((await login("e2e.screener")).access_token, `/production/jobs/${jobId}/prep/screener`, {
      method: "POST",
      body: {
        so_line_id: "line-print",
        qty: "1",
        screen_size: "kecil",
        evidence_ref: "ev",
        idempotency_key: "net-prep-screen-1",
      },
    });
    if (sc.status >= 300) throw new Error("prep screen " + sc.status + " " + sc.text);
  }
  if (!types2.includes("prep_helper")) {
    const hp = await api((await login("e2e.helper")).access_token, `/production/jobs/${jobId}/prep/helper`, {
      method: "POST",
      body: {
        so_line_id: "line-print",
        qty: "50",
        evidence_ref: "ev",
        idempotency_key: "net-prep-helper-1",
      },
    });
    if (hp.status >= 300) throw new Error("prep helper " + hp.status + " " + hp.text);
  }

  const job2 = await api(kepala.access_token, `/production/jobs/${jobId}`);
  if (job2.json?.sample_status !== "approved") {
    board3 = await api(kepala.access_token, `/production/jobs/${jobId}/board`);
    let sampleId = (board3.json?.samples || []).find((s) => s.status === "pending")?.id;
    if (!sampleId) {
      const up = await api(op.access_token, `/production/jobs/${jobId}/samples`, {
        method: "POST",
        body: { file_name: "s.jpg", storage_key: "samples/net.jpg", assignment_id: asg.id },
      });
      if (up.status >= 300) throw new Error("sample upload " + up.status + " " + up.text);
      sampleId = up.json.id;
    }
    const dec = await api(kepala.access_token, `/production/jobs/samples/${sampleId}/decision`, {
      method: "POST",
      body: { decision: "approved" },
    });
    if (dec.status >= 300) throw new Error("sample decide " + dec.status + " " + dec.text);
  }
  return { already: false, assignmentId: asg.id };
}

const puppeteer = (
  await import("/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js")
).default;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
page.setDefaultTimeout(45000);

const dir = await login("e2e.direktur");
const op = await login("e2e.operator");
const kepala = await login("e2e.kepala");
const jobId = 1;

const ready = await ensureReadyForOutput(dir, op, kepala, jobId);
if (ready.already) {
  rec({ action: "DB already has output — restart enforced server", verdict: "BLOCKED" });
  await browser.close();
  server.close();
  process.exit(2);
}
const assignmentId = ready.assignmentId;

// --- API: B same-key replay + E payload mismatch + concurrent ---
const keyB = "net-api-same-key-" + Date.now();
const first = await api(op.access_token, `/production/jobs/${jobId}/outputs`, {
  method: "POST",
  body: {
    assignment_id: assignmentId,
    qty_physical: "10",
    color_pass: 1,
    lot_code: "L-API",
    idempotency_key: keyB,
  },
});
const replay = await api(op.access_token, `/production/jobs/${jobId}/outputs`, {
  method: "POST",
  body: {
    assignment_id: assignmentId,
    qty_physical: "10",
    color_pass: 1,
    lot_code: "L-API",
    idempotency_key: keyB,
  },
});
let outs = (
  (await api(kepala.access_token, `/production/jobs/${jobId}/tracking`)).json?.events || []
).filter((e) => e.event_type === "output_confirmed" && e.idempotency_key === keyB);
rec({
  role: "API",
  action: "B same-key replay",
  http: `${first.status}/${replay.status}`,
  dbAfter: `events=${outs.length};id=${outs[0]?.id}`,
  verdict:
    first.status === 200 &&
    replay.status === 200 &&
    outs.length === 1 &&
    String(replay.json?.id) === String(first.json?.id)
      ? "PASS_MUTATION"
      : "FAIL",
  detail: { first: first.json, replay: replay.json },
});

const mismatch = await api(op.access_token, `/production/jobs/${jobId}/outputs`, {
  method: "POST",
  body: {
    assignment_id: assignmentId,
    qty_physical: "11",
    color_pass: 1,
    lot_code: "OTHER",
    idempotency_key: keyB,
  },
});
outs = (
  (await api(kepala.access_token, `/production/jobs/${jobId}/tracking`)).json?.events || []
).filter((e) => e.event_type === "output_confirmed");
rec({
  role: "API",
  action: "E same-key different payload",
  http: mismatch.status,
  dbAfter: `total_outputs=${outs.length}`,
  verdict:
    mismatch.status === 409 &&
    /payload tidak cocok/i.test(mismatch.text || "") &&
    outs.filter((e) => e.idempotency_key === keyB).length === 1
      ? "PASS_MUTATION"
      : "FAIL",
  detail: { text: mismatch.text?.slice(0, 180) },
});

const ck = "net-concurrent-same-" + Date.now();
const [c1, c2] = await Promise.all([
  api(op.access_token, `/production/jobs/${jobId}/outputs`, {
    method: "POST",
    body: {
      assignment_id: assignmentId,
      qty_physical: "1",
      color_pass: 1,
      lot_code: "C1",
      idempotency_key: ck,
    },
  }),
  api(op.access_token, `/production/jobs/${jobId}/outputs`, {
    method: "POST",
    body: {
      assignment_id: assignmentId,
      qty_physical: "1",
      color_pass: 1,
      lot_code: "C1",
      idempotency_key: ck,
    },
  }),
]);
const outsConc = (
  (await api(kepala.access_token, `/production/jobs/${jobId}/tracking`)).json?.events || []
).filter((e) => e.event_type === "output_confirmed" && e.idempotency_key === ck);
rec({
  role: "API",
  action: "Concurrent same-key submits",
  http: `${c1.status}/${c2.status}`,
  dbAfter: `events_with_key=${outsConc.length}`,
  verdict: outsConc.length === 1 && c1.status === 200 && c2.status === 200 ? "PASS_MUTATION" : "FAIL",
  detail: { c1: c1.json, c2: c2.json },
});

// --- Browser C: drop success response then reconcile ---
await page.goto(`http://127.0.0.1:${STATIC_PORT}/`, { waitUntil: "domcontentloaded" });
await page.evaluate((tok) => {
  localStorage.setItem("epv3_access_token", tok);
  localStorage.setItem("v3_token", tok);
  localStorage.setItem("access_token", tok);
  window.V3_API_BASE = "/api/v1";
}, op.access_token);
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
const tasks = await api(op.access_token, "/production/jobs/tasks");
await page.evaluate(
  (payload, so) => {
    window.__V3_INBOX__ = { mode: "live", items: [{ id: so }], fetchError: "" };
    window.__V3_OFFICIAL_TASK_SOURCE__ = "v3_official";
    window.__V3_OFFICIAL_TASKS__ = (payload.tasks || []).map((task) => ({
      ...task,
      so_number: task.so_number || so,
    }));
  },
  tasks.json || { tasks: [] },
  SO,
);
await page.evaluate(
  async (so, asg) => {
    await window.v3OpenWorkflow(so, { taskKind: "print" });
    const set = (id, v) => {
      const el = document.getElementById(id);
      if (el) {
        el.value = String(v);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    };
    set("v3-out-asg", asg);
    set("v3-out-qty", "7");
    set("v3-out-pass", "1");
    set("v3-out-lot", "L-NET");
  },
  SO,
  assignmentId,
);
await sleep(800);

await page.evaluate(() => {
  const orig = window.fetch.bind(window);
  let dropped = false;
  window.fetch = async function (input, init) {
    const url = String(typeof input === "string" ? input : input && input.url);
    const method = ((init && init.method) || "GET").toUpperCase();
    const res = await orig(input, init);
    if (
      !dropped &&
      method === "POST" &&
      /\/production\/jobs\/\d+\/outputs\/?$/.test(url.replace(/\?.*$/, ""))
    ) {
      dropped = true;
      window.__V3_DROP_ONCE__ = true;
      try {
        await res.clone().json();
      } catch {
        /* */
      }
      throw new TypeError("Failed to fetch");
    }
    return res;
  };
});

const beforeOuts = (
  (await api(kepala.access_token, `/production/jobs/${jobId}/tracking`)).json?.events || []
).filter((e) => e.event_type === "output_confirmed").length;

const ui1 = await page.evaluate(async () => {
  const btn = document.querySelector('[data-v3="out-confirm"]');
  if (!btn) return { clicked: false, reason: "no-button" };
  btn.disabled = false;
  btn.click();
  await new Promise((r) => setTimeout(r, 3500));
  const slots = (window.__V3_IDEM__ && window.__V3_IDEM__.slots) || {};
  const keys = Object.keys(slots);
  const first = keys[0] && slots[keys[0]];
  return {
    clicked: true,
    dropped: !!window.__V3_DROP_ONCE__,
    slot: first
      ? {
          key: first.key,
          committed: !!first.committed,
          uncertain: !!first.uncertain,
          fingerprint: first.fingerprint,
        }
      : null,
  };
});

const afterTrack = await api(kepala.access_token, `/production/jobs/${jobId}/tracking`);
const allOuts = (afterTrack.json?.events || []).filter((e) => e.event_type === "output_confirmed");
const netOuts = allOuts.filter((e) => String(e.lot_code || "") === "L-NET");
const afterCount = allOuts.length;

// If uncertain, click again to reconcile without new key
let ui2 = null;
if (ui1.slot && ui1.slot.uncertain && !ui1.slot.committed) {
  ui2 = await page.evaluate(async () => {
    const btn = document.querySelector('[data-v3="out-confirm"]');
    if (!btn) return { clicked: false };
    btn.click();
    await new Promise((r) => setTimeout(r, 2500));
    const slots = (window.__V3_IDEM__ && window.__V3_IDEM__.slots) || {};
    const keys = Object.keys(slots);
    const first = keys[0] && slots[keys[0]];
    return {
      clicked: true,
      slot: first
        ? { key: first.key, committed: !!first.committed, uncertain: !!first.uncertain }
        : null,
    };
  });
}

rec({
  role: "Operator",
  action: "C lost-response drop HTTP after commit → reconcile",
  http: "fetch-throw-after-2xx",
  dbBefore: String(beforeOuts),
  dbAfter: `total=${afterCount};L-NET=${netOuts.length};qty=${netOuts[0]?.qty_physical};key=${netOuts[0]?.idempotency_key}`,
  verdict:
    ui1.clicked &&
    ui1.dropped &&
    netOuts.length === 1 &&
    Number(netOuts[0]?.qty_physical) === 7 &&
    afterCount === beforeOuts + 1 &&
    (ui1.slot?.committed || ui2?.slot?.committed)
      ? "PASS_MUTATION"
      : "FAIL",
  detail: { ui1, ui2, netOut: netOuts[0] || null },
});

const pass = results.filter((r) => r.verdict === "PASS_MUTATION").length;
const fail = results.filter((r) => r.verdict !== "PASS_MUTATION").length;
console.log(JSON.stringify({ ok: fail === 0, pass, fail }, null, 2));

await browser.close();
server.close();
process.exit(fail === 0 ? 0 : 2);
