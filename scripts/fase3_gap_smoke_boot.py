"""Boot disposable test DB + uvicorn for gap smoke (empty|populated).

Usage (from backend/):
  python ../scripts/fase3_gap_smoke_boot.py populated 8021
  python ../scripts/fase3_gap_smoke_boot.py empty 8022
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql

MODE = (sys.argv[1] if len(sys.argv) > 1 else "populated").strip().lower()
PORT = int(sys.argv[2] if len(sys.argv) > 2 else "8021")
assert MODE in {"empty", "populated"}

base = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not base:
    raise SystemExit(
        "Set TEST_DATABASE_URL or DATABASE_URL to a local *test* Postgres URL "
        "(no hardcoded credentials in this script)."
    )
if "test" not in base.lower():
    raise SystemExit("refusing non-test DATABASE_URL")
parsed = urlsplit(base.replace("+asyncpg", "").replace("+psycopg2", ""))
name = f"epv3_gap_{MODE[:3]}_{uuid.uuid4().hex[:8]}_test"
assert name.endswith("_test")

admin = psycopg2.connect(
    host=parsed.hostname,
    port=parsed.port or 5432,
    user=parsed.username,
    password=parsed.password,
    dbname="postgres",
)
admin.autocommit = True
with admin.cursor() as cur:
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
admin.close()

sync = (
    f"postgresql+psycopg2://{parsed.username}:{parsed.password}"
    f"@{parsed.hostname}:{parsed.port or 5432}/{name}"
)
async_u = sync.replace("+psycopg2", "+asyncpg")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = async_u
os.environ["DATABASE_URL_SYNC"] = sync
os.environ["V3_WORKFLOW_AUTHORIZATION"] = "legacy"
os.environ.setdefault("V3_JWT_SECRET", "v3_gap_smoke_jwt_secret")
os.environ.setdefault("V3_PASSWORD_PEPPER", "v3_gap_smoke_password_pepper")
os.environ["SMOKE_SEED_MODE"] = MODE

print("DB", name, "MODE", MODE, "PORT", PORT, flush=True)
open(f"/tmp/epv3-gap-smoke-{MODE}.db.name", "w").write(name)

from app.authorization import models as access_models  # noqa: F401
from app.authorization.accounts import AccountCredential  # noqa: F401
from app.authorization.ownership import TaskOwnership  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine
from app.models import auth_audit as auth_audit_models  # noqa: F401
from app.models import work_order as work_order_models  # noqa: F401
from app.models.production import attachment as attachment_models  # noqa: F401
from app.models.production import branch as branch_models  # noqa: F401
from app.models.production import design as design_models  # noqa: F401
from app.models.production import event as event_models  # noqa: F401
from app.models.production import job as job_models  # noqa: F401
from app.models.production import operations as operations_models  # noqa: F401
from app.models.production import payment as payment_models  # noqa: F401
from app.models.production import payment_settings as payment_settings_models  # noqa: F401
from app.models.production import payroll as payroll_models  # noqa: F401
from app.models.production import prep as prep_models  # noqa: F401
from app.models.production import sample as sample_models  # noqa: F401
from app.models.production import schedule as schedule_models  # noqa: F401
from app.models.user import User  # noqa: F401

get_settings.cache_clear()


async def create_schema() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(create_schema())

scripts_dir = os.path.dirname(os.path.abspath(__file__))
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
import fase3_gap_smoke_seed_job as seed  # noqa: E402

asyncio.run(seed.main())

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
