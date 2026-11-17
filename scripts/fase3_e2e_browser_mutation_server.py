"""Disposable API server with Accurate SJ/receipt stubs for browser mutation E2E.

APP_ENV=test only. Does not touch Live Accurate or Production DB.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql

base = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not base:
    base = "postgresql+asyncpg://epv3_test:epv3_ci_test_only@127.0.0.1:5432/eternal_production_v3_test"
parsed = urlsplit(base.replace("+asyncpg", "").replace("+psycopg2", ""))
name = "epv3_e2e_bm_" + uuid.uuid4().hex[:10] + "_test"
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
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": async_u,
        "DATABASE_URL_SYNC": sync,
        "V3_WORKFLOW_AUTHORIZATION": os.environ.get("V3_WORKFLOW_AUTHORIZATION", "legacy"),
        "V3_JWT_SECRET": "v3_e2e_browser_mut_jwt",
        "V3_PASSWORD_PEPPER": "v3_e2e_browser_mut_pepper",
    }
)
open("/tmp/epv3-e2e-browser-mut-db.name", "w").write(name)
print("DB", name, flush=True)

# Monkeypatch Accurate evidence before app import consumers resolve it at call time.
import app.services.accurate_evidence as ae


async def _valid_sj(**kwargs):
    return {
        "verified": True,
        "mode": "fixture",
        "accurate_sj_id": kwargs.get("accurate_sj_id") or "sj-browser",
        "accurate_sj_number": kwargs.get("accurate_sj_number") or "SJ/BROWSER/001",
        "sales_order_number": "SO/E2E/BROWSER-MUT",
        "branch_id": "branch-a",
        "line_items": [
            {
                "sku": "CUP",
                "qty": 100,
                "uom": "PCS",
                "accurate_sj_line_id": "SL-1",
                "so_line_id": "line-print",
                "accurate_so_id": "9300",
                "accurate_item_id": "P1",
                "quantity": 100,
                "qty_verified": True,
                "unit_ratio": 1.0,
                "unit_ratio_verified": True,
                "line_identity_complete": True,
                "loading_eligible": True,
                "identity_conflicts": [],
                "so_line_id_source": "fixture",
                "so_line_field_semantics_verified": True,
                "so_line_cross_verified": False,
            }
        ],
        "loading_eligible": True,
        "live_verified": False,
    }


ae.require_valid_sj = _valid_sj  # type: ignore[assignment]

import asyncio

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.models.production.job import ProductionJob
from app.models.production.operations import ProductionMachine
from app.models.production.prep import JobLineQty
from app.models.user import User
from app.services.production import payment_settings as pay
from app.services.production import permissions as P

# Register authorization ORM tables for create_all (enforced sandbox + load_access).
import app.authorization.models  # noqa: F401
import app.authorization.accounts  # noqa: F401
import app.authorization.ownership  # noqa: F401

get_settings.cache_clear()


async def seed():
    await dispose_engine()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    roles = {
        "direktur": (
            "Direktur",
            [
                P.JOB_CREATE,
                P.JOB_READ,
                P.DESIGN_UPLOAD,
                P.DESIGN_APPROVE,
                P.DESIGN_BYPASS,
                P.PAYMENT_BYPASS,
                P.PAYMENT_RECORD,
                P.SAMPLE_DECIDE,
                P.SCHEDULE_MANAGE,
                P.TRACKING_READ,
                P.DELIVERY_MANAGE,
            ],
        ),
        "kepala": (
            "kepala_produksi",
            [
                P.JOB_CREATE,
                P.JOB_READ,
                P.SCHEDULE_MANAGE,
                P.SAMPLE_DECIDE,
                P.DELIVERY_MANAGE,
                P.TRACKING_READ,
            ],
        ),
        "designer": ("designer", [P.JOB_READ, P.DESIGN_UPLOAD, P.DESIGN_APPROVE]),
        "screener": ("screener", [P.JOB_READ, P.PREP_SCREENER]),
        "helper": (
            "helper",
            [P.JOB_READ, P.PREP_HELPER, P.OUTPUT_HELPER_VERIFY, P.PACKING_RECORD],
        ),
        "operator": (
            "operator",
            [P.JOB_READ, P.SAMPLE_UPLOAD, P.OUTPUT_CONFIRM, P.REJECT_RECORD],
        ),
        "driver": ("driver", [P.JOB_READ, P.DELIVERY_MANAGE, P.TRACKING_READ]),
    }
    async with get_session_factory()() as s:
        users = {}
        for key, (role, perms) in roles.items():
            u = User(
                username=f"e2e.{key}",
                display_name=key if key != "operator" else "Op Browser",
                role=role,
                password_hash=hash_password("secret-pass"),
                permissions=list(perms),
                branch_ids=["branch-a"],
                is_active=True,
            )
            s.add(u)
            users[key] = u
        await s.flush()
        s.add(
            ProductionMachine(
                branch_id="branch-a",
                name="Semi Auto Browser",
                kind="semi_auto",
                capacity_per_shift=Decimal("5000"),
                shifts_per_day=1,
                active=True,
                created_by=users["kepala"].id,
            )
        )
        job = ProductionJob(
            accurate_so_number="SO/E2E/BROWSER-MUT",
            accurate_id="9300",
            branch_id="branch-a",
            customer_name="Browser Mutation Co",
            design_status="pending",
            payment_status="pending",
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
        # Enable payment bypass toggle for Direktur UI
        body = await pay.read_payment_approval(s, users["direktur"])
        cfg = dict(body["payment_approval"])
        cfg["bypass_enabled"] = True
        await pay.update_payment_approval(
            s,
            users["direktur"],
            version=body["version"],
            payment_approval=cfg,
            reason="Enable bypass for browser mutation disposable",
        )
        await s.commit()
        print("JOB", job.id, "OPERATOR", users["operator"].id, flush=True)
    await dispose_engine()


asyncio.run(seed())

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8013, log_level="warning")
