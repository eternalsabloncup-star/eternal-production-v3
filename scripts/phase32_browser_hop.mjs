/**
 * Browser → V3 capability endpoint (gateway already proven via API path).
 */
import fs from "fs";
import http from "http";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const API_PORT = process.env.API_PORT || "8012";
const puppeteer = require(
  "/tmp/epv3-puppeteer/node_modules/puppeteer-core"
);

const html = `<!doctype html><meta charset=utf-8><title>P32</title>
<pre id=out>loading</pre>
<script>
(async () => {
  const login = await fetch("http://127.0.0.1:${API_PORT}/api/v1/auth/login", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({username:"smoke32.lead", password:"secret-pass"})
  });
  const tok = (await login.json()).access_token;
  const cap = await fetch(
    "http://127.0.0.1:${API_PORT}/api/v1/production/jobs/evidence/capability",
    { headers: { Authorization: "Bearer " + tok } }
  );
  document.getElementById("out").textContent = await cap.text();
})().catch((e) => {
  document.getElementById("out").textContent = String(e);
});
</script>`;

await new Promise((resolve, reject) => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(html);
  });
  server.listen(8765, "127.0.0.1", async () => {
    try {
      const exe =
        process.env.CHROME_PATH ||
        (fs.existsSync("/usr/bin/google-chrome")
          ? "/usr/bin/google-chrome"
          : "/usr/bin/chromium-browser");
      const browser = await puppeteer.launch({
        executablePath: exe,
        headless: "new",
        args: ["--no-sandbox", "--disable-gpu"],
      });
      const page = await browser.newPage();
      await page.goto("http://127.0.0.1:8765/", {
        waitUntil: "networkidle0",
        timeout: 20000,
      });
      await new Promise((r) => setTimeout(r, 2000));
      const out = await page.$eval("#out", (el) => el.textContent);
      fs.writeFileSync("/tmp/epv3-browser32-capability.json", out || "");
      console.log("browser_capability", (out || "").slice(0, 240));
      await browser.close();
      server.close();
      resolve();
    } catch (err) {
      server.close();
      reject(err);
    }
  });
});
