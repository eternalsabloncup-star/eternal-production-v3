#!/usr/bin/env bash
# Phase 3.2: API (+ optional browser) → V3 backend → accurate-gateway (fixture).
# Does NOT claim live Accurate verification.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GW_PORT=8091
API_PORT=8012
M2M="phase32-m2m-token"
export GATEWAY_MODE=fixture
export GATEWAY_M2M_TOKEN="$M2M"

pkill -f "uvicorn app.main:app --host 127.0.0.1 --port ${GW_PORT}" 2>/dev/null || true
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}" 2>/dev/null || true
sleep 0.4

cd "$ROOT/accurate-gateway"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$GW_PORT" >/tmp/epv3-gw32.log 2>&1 &
GW_PID=$!

cd "$ROOT/backend"
export APP_ENV=development
export CORS_ORIGINS="http://127.0.0.1:8765,http://localhost:8765,http://127.0.0.1:5173"
export V3_ACCURATE_READ_GATEWAY_URL="http://127.0.0.1:${GW_PORT}"
export V3_ACCURATE_READ_GATEWAY_TOKEN="$M2M"
export V3_ACCURATE_EVIDENCE_ENFORCE=true
export V3_JWT_SECRET="${V3_JWT_SECRET:-v3_smoke_jwt_secret_not_from_v1}"
export V3_PASSWORD_PEPPER="${V3_PASSWORD_PEPPER:-v3_smoke_password_pepper_distinct}"
if [ -z "${DATABASE_URL:-}" ]; then
  eval "$(.venv/bin/python - <<'PY'
from tests.db_url_guard import resolve_test_database_urls
a, s = resolve_test_database_urls()
print(f"export DATABASE_URL={a!r}")
print(f"export DATABASE_URL_SYNC={s!r}")
PY
)"
fi
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >/tmp/epv3-api32.log 2>&1 &
API_PID=$!
cleanup() { kill "$GW_PID" "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:${GW_PORT}/health" >/dev/null && break
  sleep 0.2
done
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null && break
  sleep 0.2
done

echo "== gateway health =="
curl -sS "http://127.0.0.1:${GW_PORT}/health" | tee /tmp/epv3-gw32-health.json
echo
echo "== gateway receipt OK =="
curl -sS -H "Authorization: Bearer ${M2M}" \
  "http://127.0.0.1:${GW_PORT}/receipts/RCP-OK-1" | tee /tmp/epv3-gw32-receipt.json
echo
echo "== gateway receipt CANCELLED =="
curl -sS -H "Authorization: Bearer ${M2M}" \
  "http://127.0.0.1:${GW_PORT}/receipts/RCP-CANCELLED" | tee /tmp/epv3-gw32-receipt-cancelled.json
echo

cd "$ROOT/backend"
API_PORT="$API_PORT" .venv/bin/python <<'PY'
import asyncio, json, os
import httpx
from sqlalchemy import select
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.models.user import User
from app.services.production import permissions as P

API = f"http://127.0.0.1:{os.environ['API_PORT']}"
ALL = [getattr(P, n) for n in dir(P) if n.isupper()]

async def main():
    await dispose_engine()
    eng = get_engine()
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    fac = get_session_factory()
    async with fac() as s:
        u = await s.scalar(select(User).where(User.username == "smoke32.lead"))
        if not u:
            s.add(
                User(
                    username="smoke32.lead",
                    display_name="Smoke32",
                    role="kepala_produksi",
                    password_hash=hash_password("secret-pass"),
                    permissions=ALL,
                    branch_ids=["branch-a", "BR-JKT"],
                    is_active=True,
                )
            )
            await s.commit()
    async with httpx.AsyncClient(base_url=API, timeout=20.0) as c:
        login = await c.post(
            "/api/v1/auth/login",
            json={"username": "smoke32.lead", "password": "secret-pass"},
        )
        login.raise_for_status()
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        cap = await c.get("/api/v1/production/jobs/evidence/capability", headers=h)
        print("capability", cap.status_code, cap.text)
        open("/tmp/epv3-api32-capability.json", "w").write(cap.text)
        job = await c.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO-LIVE-001", "branch_id": "BR-JKT"},
        )
        print("job", job.status_code)
        job.raise_for_status()
        jid = job.json()["id"]
        d = await c.post(
            f"/api/v1/production/jobs/{jid}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
        d.raise_for_status()
        await c.post(
            f"/api/v1/production/jobs/design/versions/{d.json()['id']}/decision",
            headers=h,
            json={"decision": "approved", "bypass": True, "reason": "smoke32"},
        )
        ok = await c.post(
            f"/api/v1/production/jobs/{jid}/payment/receipts",
            headers=h,
            json={"accurate_receipt_id": "RCP-OK-1"},
        )
        print("receipt_ok", ok.status_code, ok.text)
        open("/tmp/epv3-api32-receipt-ok.json", "w").write(ok.text)
        bad = await c.post(
            f"/api/v1/production/jobs/{jid}/payment/receipts",
            headers=h,
            json={"accurate_receipt_id": "RCP-CANCELLED"},
        )
        print("receipt_cancelled", bad.status_code, bad.text)
        open("/tmp/epv3-api32-receipt-cancelled.json", "w").write(
            json.dumps({"status": bad.status_code, "body": bad.text})
        )
        assert ok.status_code == 200, ok.text
        assert bad.status_code == 409, bad.text
    await dispose_engine()

asyncio.run(main())
PY

# Optional browser → backend capability hop
if [ -x /usr/bin/google-chrome ] || [ -x /usr/bin/chromium-browser ]; then
  if [ -f /tmp/epv3-puppeteer/node_modules/puppeteer-core/package.json ]; then
    API_PORT="$API_PORT" node "$ROOT/scripts/phase32_browser_hop.mjs" || echo "browser hop skipped"
  else
    echo "puppeteer-core missing — API path evidence only"
  fi
else
  echo "chrome not found — API path evidence only"
fi

echo "PHASE32_SMOKE_OK fixture_mode live_verified=false"
