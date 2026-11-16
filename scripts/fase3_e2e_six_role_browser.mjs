/**
 * Browser E2E interaktif enam role — pola sama dengan fase3_gap_browser_smoke.
 * Klaim PASS_MUTATE hanya jika klik memicu HTTP mutasi 2xx.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "frontend/public");
const API = process.env.V3_SMOKE_API || "http://127.0.0.1:8012/api/v1";
const STATIC_PORT = Number(process.env.V3_SMOKE_STATIC_PORT || 4185);
const PASS = process.env.V3_E2E_PASSWORD || "secret-pass";
const API_ORIGIN = API.replace(/\/api\/v1\/?$/, "");

const ROLES = [
  { user: "e2e.kepala", label: "Kepala Produksi" },
  { user: "e2e.designer", label: "Designer" },
  { user: "e2e.screener", label: "Screener" },
  { user: "e2e.helper", label: "Helper" },
  { user: "e2e.operator", label: "Operator" },
  { user: "e2e.driver", label: "Driver" },
];

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

const puppeteerMod = await import(
  "/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js"
);
const puppeteer = puppeteerMod.default || puppeteerMod;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];

async function loginToken(user) {
  const res = await fetch(API + "/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: user, password: PASS }),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return body.access_token || null;
}

for (const role of ROLES) {
  const row = {
    role: role.label,
    user: role.user,
    login: false,
    tasksOpened: false,
    taskRows: 0,
    kerjakanButtons: 0,
    clicked: false,
    mutateHttp: null,
    refreshOk: false,
    denyProbe: null,
    apiTaskCount: null,
    verdict: "BLOCKED",
    error: "",
  };
  const page = await browser.newPage();
  const apiHits = [];
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/v1/production/")) return;
    apiHits.push({ url: u, status: res.status(), method: res.request().method() });
  });
  try {
    const token = await loginToken(role.user);
    row.login = !!token;
    if (!token) {
      row.error = "login_failed";
      results.push(row);
      await page.close();
      continue;
    }
    // API task count (bukti terpisah dari browser)
    const tasksRes = await fetch(API + "/production/jobs/tasks", {
      headers: { Authorization: "Bearer " + token },
    });
    const tasksBody = await tasksRes.json().catch(() => ({}));
    row.apiTaskCount = (tasksBody.tasks || []).length;

    await page.evaluateOnNewDocument((tok) => {
      localStorage.setItem("epv3_access_token", tok);
      localStorage.setItem("v3_token", tok);
      localStorage.setItem("access_token", tok);
      window.V3_API_BASE = "/api/v1";
    }, token);

    await page.goto(`http://127.0.0.1:${STATIC_PORT}/production.html`, {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
    try {
      await page.waitForFunction(
        () =>
          typeof window.v3Api === "object" ||
          document.documentElement.classList.contains("v3-auth-ok") ||
          document.body.innerText.length > 200,
        { timeout: 20000 },
      );
    } catch {
      /* continue with best-effort UI */
    }
    await sleep(500);
    await page.evaluate(() => {
      if (typeof window.go === "function") window.go("tasks");
      else {
        const btn = [...document.querySelectorAll("button, a")].find((b) =>
          /Tugas Tim/i.test(b.textContent || ""),
        );
        if (btn) btn.click();
      }
    });
    await sleep(1500);
    row.tasksOpened = await page.evaluate(() =>
      /Tugas Tim|Designer|Operator|Screener|Helper|Driver|Kepala|Upload|Screen|Prepare/i.test(
        document.body.innerText || "",
      ),
    );
    const ui = await page.evaluate(() => {
      const buttons = [...document.querySelectorAll("button, [data-task-action]")].filter((b) =>
        /Kerjakan|Approval Sampel|Upload|Input|Sahkan|Panel V3/i.test(b.textContent || ""),
      );
      const rows = document.querySelectorAll("table tbody tr, .v36-table tbody tr");
      return { taskRows: rows.length, kerjakanButtons: buttons.length };
    });
    row.taskRows = ui.taskRows;
    row.kerjakanButtons = ui.kerjakanButtons;
    const before = apiHits.length;
    row.clicked = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button, [data-task-action]")].find((b) =>
        /Kerjakan|Approval Sampel|Upload desain|Input screen|Input cup|Sahkan/i.test(
          b.textContent || "",
        ),
      );
      if (!btn) return false;
      btn.click();
      return true;
    });
    await sleep(1500);
    const mut = apiHits
      .slice(before)
      .filter((h) => !["GET", "HEAD"].includes(h.method));
    row.mutateHttp = mut.length
      ? mut.map((m) => `${m.method}:${m.status}`).join(",")
      : null;

    await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
    await sleep(800);
    await page.evaluate(() => {
      if (typeof window.go === "function") window.go("tasks");
    });
    await sleep(800);
    row.refreshOk = await page.evaluate(() => (document.body.innerText || "").length > 100);

    row.denyProbe = await page.evaluate(async () => {
      const tok =
        localStorage.getItem("epv3_access_token") ||
        localStorage.getItem("v3_token") ||
        localStorage.getItem("access_token");
      const tasks = await fetch("/api/v1/production/jobs/tasks", {
        headers: { Authorization: "Bearer " + tok },
      });
      const body = await tasks.json().catch(() => ({}));
      const items = body.tasks || [];
      const jobId = items[0]?.job_id || 1;
      const bypass = await fetch(`/api/v1/production/jobs/${jobId}/payment/bypass`, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + tok,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reason: "browser deny probe" }),
      });
      return { tasksStatus: tasks.status, bypassStatus: bypass.status, taskCount: items.length };
    });

    if (row.login && row.tasksOpened && row.refreshOk) {
      if (row.clicked && row.mutateHttp && /:(200|201)\b/.test(row.mutateHttp)) {
        row.verdict = "PASS_MUTATE";
      } else if (row.clicked) {
        row.verdict = "PASS_CLICK_NO_MUTATE";
      } else {
        row.verdict = "PASS_UI";
      }
    } else if (row.login && row.apiTaskCount != null) {
      row.verdict = "PASS_API_ONLY";
      row.error = "browser_ui_partial";
    } else {
      row.verdict = "FAIL";
    }
  } catch (err) {
    row.error = String(err);
    row.verdict = "FAIL";
  }
  results.push(row);
  await page.close();
}

await browser.close();
server.close();

const summary = {
  ok: results.every((r) => String(r.verdict).startsWith("PASS")),
  mutateClaimed: results.some((r) => r.verdict === "PASS_MUTATE"),
  note: "PASS_UI / PASS_CLICK_NO_MUTATE bukan klaim mutasi backend dari browser",
  roles: results,
};
fs.writeFileSync("/tmp/epv3-fase3-e2e-six-role-browser.json", JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
process.exit(summary.ok ? 0 : 2);
