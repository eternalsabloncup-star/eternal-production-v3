"""Seed disposable PG + start uvicorn :8012 for browser E2E (test only)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql

# Resolve base test URL then create exclusive DB
base = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not base:
    base = "postgresql+asyncpg://epv3_test:epv3_ci_test_only@127.0.0.1:5432/eternal_production_v3_test"
parsed = urlsplit(base.replace("+asyncpg", "").replace("+psycopg2", ""))
name = "epv3_e2e_br_" + uuid.uuid4().hex[:10] + "_test"
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

sync = (
    f"postgresql+psycopg2://{parsed.username}:{parsed.password}"
    f"@{parsed.hostname}:{parsed.port or 5432}/{name}"
)
async_u = sync.replace("+psycopg2", "+asyncpg")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = async_u
os.environ["DATABASE_URL_SYNC"] = sync
os.environ["V3_WORKFLOW_AUTHORIZATION"] = "legacy"
os.environ["V3_JWT_SECRET"] = "v3_e2e_browser_jwt_secret"
os.environ["V3_PASSWORD_PEPPER"] = "v3_e2e_browser_password_pepper"

print("DB", name, flush=True)
open("/tmp/epv3-e2e-browser-db.name", "w").write(name)

import asyncio

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.production.job import ProductionJob
from app.models.production.prep import JobLineQty
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()


async def seed():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    roles = {
        "direktur": (
            "Direktur",
            [P.JOB_CREATE, P.JOB_READ, P.DESIGN_BYPASS, P.PAYMENT_BYPASS, P.PAYMENT_RECORD, P.SAMPLE_DECIDE, P.SCHEDULE_MANAGE, P.TRACKING_READ],
        ),
        "kepala": (
            "kepala_produksi",
            [P.JOB_CREATE, P.JOB_READ, P.SCHEDULE_MANAGE, P.SAMPLE_DECIDE, P.DELIVERY_MANAGE, P.TRACKING_READ],
        ),
        "designer": ("designer", [P.JOB_READ, P.DESIGN_UPLOAD, P.DESIGN_APPROVE]),
        "screener": ("screener", [P.JOB_READ, P.PREP_SCREENER]),
        "helper": ("helper", [P.JOB_READ, P.PREP_HELPER, P.OUTPUT_HELPER_VERIFY, P.PACKING_RECORD]),
        "operator": ("operator", [P.JOB_READ, P.SAMPLE_UPLOAD, P.OUTPUT_CONFIRM, P.REJECT_RECORD]),
        "driver": ("driver", [P.JOB_READ, P.DELIVERY_MANAGE, P.TRACKING_READ]),
    }
    async with get_session_factory()() as s:
        users = {}
        for key, (role, perms) in roles.items():
            u = User(
                username=f"e2e.{key}",
                display_name=key,
                role=role,
                password_hash=hash_password("secret-pass"),
                permissions=list(perms),
                branch_ids=["branch-a"],
                is_active=True,
            )
            s.add(u)
            users[key] = u
        await s.flush()
        job = ProductionJob(
            accurate_so_number="SO/E2E/BROWSER",
            accurate_id="9200",
            branch_id="branch-a",
            customer_name="Browser E2E",
            design_status="bypassed",
            payment_status="bypassed",
        )
        s.add(job)
        await s.flush()
        s.add(
            JobLineQty(
                job_id=job.id,
                so_line_id="line-print",
                accurate_item_id="P1",
                po_qty=Decimal("100"),
                production_process="print",
            )
        )
        s.add(
            ScheduleAssignment(
                job_id=job.id,
                branch_id="branch-a",
                so_line_id="line-print",
                operator_name="Op Browser",
                machine_name="M1",
                work_date=date.today(),
                qty_planned=Decimal("100"),
                created_by=users["kepala"].id,
                status="active",
                color_pass=1,
            )
        )
        await s.commit()
        print("JOB", job.id, flush=True)


asyncio.run(seed())

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8012, log_level="warning")
