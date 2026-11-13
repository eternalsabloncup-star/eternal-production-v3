#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
export APP_ENV=test
export V3_JWT_SECRET=v3_test_jwt_secret_not_from_v1
export V3_PASSWORD_PEPPER=v3_test_password_pepper_distinct
export DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test}"
export DATABASE_URL_SYNC="${TEST_DATABASE_URL_SYNC:-postgresql+psycopg2://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test}"
export V3_ACCURATE_READ_GATEWAY_URL="${V3_ACCURATE_READ_GATEWAY_URL:-}"
export V3_ACCURATE_READ_GATEWAY_TOKEN="${V3_ACCURATE_READ_GATEWAY_TOKEN:-}"

python - <<'PY'
import asyncio, os
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.models.user import User
from app.services.production import permissions as P
get_settings.cache_clear()
ALL=[P.JOB_CREATE,P.JOB_READ,P.DESIGN_UPLOAD,P.DESIGN_APPROVE,P.DESIGN_BYPASS,P.PAYMENT_RECORD,P.PAYMENT_BYPASS,P.PAYMENT_REVOKE,P.SCHEDULE_MANAGE,P.PREP_SCREENER,P.PREP_HELPER,P.SAMPLE_UPLOAD,P.SAMPLE_DECIDE,P.OUTPUT_CONFIRM,P.REJECT_RECORD,P.REJECT_VERIFY,P.PACKING_RECORD,P.DELIVERY_MANAGE,P.TRACKING_READ,P.PAYROLL_MANAGE,P.PAYROLL_READ]
async def main():
    await dispose_engine(); get_settings.cache_clear()
    engine=get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory=get_session_factory()
    async with factory() as session:
        from sqlalchemy import select
        existing=await session.scalar(select(User).where(User.username=="smoke.lead"))
        if existing is None:
            session.add(User(username="smoke.lead",display_name="Smoke",role="kepala_produksi",password_hash=hash_password("secret-pass"),permissions=ALL,branch_ids=["branch-a"],is_active=True))
            await session.commit()
            print("seeded smoke.lead")
        else:
            print("smoke.lead exists")
    await dispose_engine()
asyncio.run(main())
PY

# Kill any prior smoke API
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8011" 2>/dev/null || true
sleep 0.5
export CORS_ORIGINS="http://127.0.0.1:4177,http://localhost:4177"
uvicorn app.main:app --host 127.0.0.1 --port 8011 >/tmp/epv3-smoke-api.log 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
for i in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8011/api/v1/health >/dev/null; then break; fi
  sleep 0.3
done
curl -sf http://127.0.0.1:8011/api/v1/health >/dev/null

cd "$ROOT"
export V3_SMOKE_API=http://127.0.0.1:8011/api/v1
export PUPPETEER_CORE_PATH="${PUPPETEER_CORE_PATH:-/tmp/epv3-puppeteer/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js}"
node scripts/phase31_browser_smoke.mjs
