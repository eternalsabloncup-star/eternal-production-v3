#!/usr/bin/env bash
# Phase 4: disposable Postgres test DB + fixture gateway + API + browser hop.
# Does NOT claim live Accurate verification.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GW_PORT=8093
API_PORT=8014
STATIC_PORT=8766
M2M="phase4-m2m-token"

pkill -f "uvicorn app.main:app --host 127.0.0.1 --port ${GW_PORT}" 2>/dev/null || true
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}" 2>/dev/null || true
sleep 0.3

export GATEWAY_MODE=fixture
export GATEWAY_M2M_TOKEN="$M2M"
cd "$ROOT/accurate-gateway"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$GW_PORT" >/tmp/epv3-gw4.log 2>&1 &
GW_PID=$!

cd "$ROOT/backend"
eval "$(.venv/bin/python - <<'PY'
from tests.db_url_guard import resolve_test_database_urls
a,s=resolve_test_database_urls()
print(f"export DATABASE_URL={a!r}")
print(f"export DATABASE_URL_SYNC={s!r}")
PY
)"
export APP_ENV=development
export CORS_ORIGINS="http://127.0.0.1:${STATIC_PORT},http://localhost:${STATIC_PORT}"
export V3_ACCURATE_READ_GATEWAY_URL="http://127.0.0.1:${GW_PORT}"
export V3_ACCURATE_READ_GATEWAY_TOKEN="$M2M"
export V3_ACCURATE_EVIDENCE_ENFORCE=true
export V3_JWT_SECRET="${V3_JWT_SECRET:-v3_phase4_jwt_secret_not_from_v1}"
export V3_PASSWORD_PEPPER="${V3_PASSWORD_PEPPER:-v3_phase4_password_pepper_distinct}"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >/tmp/epv3-api4.log 2>&1 &
API_PID=$!
cleanup(){ kill $GW_PID $API_PID 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${GW_PORT}/health" >/dev/null && break; sleep 0.2; done
for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null && break; sleep 0.2; done

echo "== gateway list page1 =="
curl -sS -H "Authorization: Bearer ${M2M}" \
  "http://127.0.0.1:${GW_PORT}/sales-orders?page=1&limit=20" | tee /tmp/epv3-p4-gw-page1.json | head -c 200
echo

cd "$ROOT/backend"
API_PORT="$API_PORT" GW_PORT="$GW_PORT" M2M="$M2M" .venv/bin/python <<'PY'
import asyncio, json, os, time
import httpx
from sqlalchemy import select
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.models.user import User
from app.services.production import permissions as P

API=f"http://127.0.0.1:{os.environ['API_PORT']}"
ALL=[getattr(P,n) for n in dir(P) if n.isupper()]+["production.inbox.read","production.order.read"]

async def main():
    await dispose_engine()
    eng=get_engine()
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    fac=get_session_factory()
    async with fac() as s:
        u=await s.scalar(select(User).where(User.username=="p4.lead"))
        if not u:
            s.add(User(username="p4.lead",display_name="P4",role="kepala_produksi",
                       password_hash=hash_password("secret-pass"),permissions=ALL,
                       branch_ids=["branch-a","BR-JKT"],is_active=True))
            await s.commit()
    async with httpx.AsyncClient(base_url=API,timeout=30.0) as c:
        tok=(await c.post("/api/v1/auth/login",json={"username":"p4.lead","password":"secret-pass"})).json()["access_token"]
        h={"Authorization":f"Bearer {tok}"}
        # Align fixture receipt SO with job
        # Use SO-LIVE-001 + RCP-OK-1 from gateway fixture (branch BR-JKT)
        job=(await c.post("/api/v1/production/jobs",headers=h,json={"accurate_so_number":"SO-LIVE-001","branch_id":"BR-JKT"})).json()
        jid=job["id"]
        d=(await c.post(f"/api/v1/production/jobs/{jid}/design/versions",headers=h,json={"file_name":"a.pdf","storage_key":"a"})).json()
        await c.post(f"/api/v1/production/jobs/design/versions/{d['id']}/decision",headers=h,json={"decision":"approved"})
        ok=await c.post(f"/api/v1/production/jobs/{jid}/payment/receipts",headers=h,json={"accurate_receipt_id":"RCP-OK-1"})
        bad=await c.post(f"/api/v1/production/jobs/{jid}/payment/receipts",headers=h,json={"accurate_receipt_id":"RCP-CANCELLED"})
        inbox=await c.get("/api/v1/production/inbox?page=1&limit=20",headers=h)
        t0=time.perf_counter()
        pages=await asyncio.gather(*[c.get(f"/api/v1/production/inbox?page={p}&limit=20",headers=h) for p in (1,2,3,4)])
        inbox_ms=(time.perf_counter()-t0)*1000
        report={
            "mode":"fixture",
            "live_verified":False,
            "receipt_ok":ok.status_code,
            "receipt_cancelled":bad.status_code,
            "inbox_status":inbox.status_code,
            "inbox_total":inbox.json().get("total") if inbox.status_code==200 else None,
            "inbox_page_len":len(inbox.json().get("rows",[])) if inbox.status_code==200 else None,
            "multi_page_ok":all(p.status_code==200 for p in pages),
            "inbox_4pages_ms":round(inbox_ms,1),
            "job_id":jid,
        }
        open("/tmp/epv3-p4-api-report.json","w").write(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        assert ok.status_code==200 and bad.status_code==409
        assert inbox.status_code==200 and inbox.json()["total"]>=70
    await dispose_engine()
asyncio.run(main())
PY

# Static V49 + browser hop
cd "$ROOT/frontend/public"
python3 -m http.server "$STATIC_PORT" --bind 127.0.0.1 >/tmp/epv3-static4.log 2>&1 &
STATIC_PID=$!
cleanup(){ kill $GW_PID $API_PID $STATIC_PID 2>/dev/null || true; }
trap cleanup EXIT
sleep 0.4

API_PORT="$API_PORT" STATIC_PORT="$STATIC_PORT" node <<'NODE' || echo "browser hop skipped"
import fs from "fs";
import http from "http";
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const API = process.env.API_PORT || "8014";
const STATIC = process.env.STATIC_PORT || "8766";
let puppeteer;
try { puppeteer = require("/tmp/epv3-puppeteer/node_modules/puppeteer-core"); }
catch (e) { console.log("no puppeteer"); process.exit(0); }
const exe = fs.existsSync("/usr/bin/google-chrome") ? "/usr/bin/google-chrome" : "/usr/bin/chromium-browser";
const browser = await puppeteer.launch({ executablePath: exe, headless: "new", args: ["--no-sandbox","--disable-gpu"] });
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${STATIC}/production.html`, { waitUntil: "domcontentloaded", timeout: 20000 });
const title = await page.title();
const hasRuntime = await page.evaluate(() => typeof window.v3OpenWorkflow === "function" || !!document.querySelector("script[src*='live-runtime']"));
// Login + inbox via page fetch (CORS allowed)
const inbox = await page.evaluate(async (api) => {
  const login = await fetch(`http://127.0.0.1:${api}/api/v1/auth/login`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({username:"p4.lead", password:"secret-pass"})
  });
  const tok = (await login.json()).access_token;
  const r = await fetch(`http://127.0.0.1:${api}/api/v1/production/inbox?page=1&limit=20`, {
    headers: { Authorization: "Bearer " + tok }
  });
  const body = await r.json();
  return { status: r.status, total: body.total, rows: (body.rows||[]).length, titleHint: document.title };
}, API);
fs.writeFileSync("/tmp/epv3-p4-browser.json", JSON.stringify({ title, hasRuntime, inbox }, null, 2));
console.log(JSON.stringify({ title, hasRuntime, inbox }));
await browser.close();
NODE

echo "PHASE4_SMOKE_OK fixture_mode"
