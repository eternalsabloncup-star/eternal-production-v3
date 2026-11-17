"""Disposable APP_ENV=test API with V3_WORKFLOW_AUTHORIZATION=enforced.

Seeds ONLY disposable test users + manual ScopedGrant packs.
Never touches Live / Production. Never auto-grants existing users.
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
name = "epv3_e2e_enf_" + uuid.uuid4().hex[:10] + "_test"
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
        "V3_SETTINGS_ENABLED": "true",
        "V3_WORKFLOW_AUTHORIZATION": "enforced",
        "V3_JWT_SECRET": "v3_e2e_browser_enf_jwt",
        "V3_PASSWORD_PEPPER": "v3_e2e_browser_enf_pepper",
    }
)
open("/tmp/epv3-e2e-browser-enf-db.name", "w").write(name)
print("DB", name, flush=True)
print("AUTH_MODE enforced", flush=True)

import app.services.accurate_evidence as ae


async def _valid_sj(**kwargs):
    return {
        "verified": True,
        "mode": "fixture",
        "accurate_sj_id": kwargs.get("accurate_sj_id") or "sj-browser",
        "accurate_sj_number": kwargs.get("accurate_sj_number") or "SJ/BROWSER/001",
        "sales_order_number": "SO/E2E/BROWSER-ENF",
        "branch_id": "branch-a",
        "line_items": [
            {
                "sku": "CUP",
                "qty": 100,
                "uom": "PCS",
                "accurate_sj_line_id": "SL-1",
                "so_line_id": "line-print",
                "accurate_so_id": "9400",
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

from app.authorization.accounts import AccountCredential
from app.authorization.bootstrap import bootstrap_director
from app.authorization.models import (
    AccessGroup,
    AccessState,
    Membership,
    ScopedGrant,
)
from app.authorization.role_packs import ROLE_PACKS
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.models.auth_audit import AuthAuditEvent
from app.models.production.job import ProductionJob
from app.models.production.operations import ProductionMachine
from app.models.production.prep import JobLineQty
from app.models.user import User
from app.services.production import payment_settings as pay

# Register ORM tables
import app.authorization.models  # noqa: F401
import app.authorization.accounts  # noqa: F401
import app.authorization.ownership  # noqa: F401

get_settings.cache_clear()

PASS = "secret-pass"
BRANCH_A = "branch-a"
BRANCH_B = "branch-b"

# Manual extras beyond ROLE_PACKS required for Panel V3 / loading authority lookup
EXTRA_CAPS = {
    "kepala_produksi": (),
    "designer": ("job.board.read",),
    "screener": ("job.board.read",),
    "helper": ("job.board.read",),
    "operator": ("job.board.read",),
    "driver": ("job.board.read", "loading.authority.read"),
}

# UI mirrors: catalog capability codes on User.permissions for button affordance only.
# Server authorize_request never ORs these into ScopedGrant decisions.
UI_MIRROR = {
    "designer": ["design.version.create", "design.decision.record", "job.read", "task.read"],
    "screener": ["prep.screener.record", "job.read", "task.read", "job.board.read"],
    "helper": [
        "prep.helper.record",
        "output.helper.verify",
        "packing.record",
        "job.read",
        "task.read",
        "job.board.read",
    ],
    "operator": [
        "sample.version.create",
        "output.record",
        "reject.record",
        "job.read",
        "task.read",
        "job.board.read",
    ],
    "driver": [
        "loading.record",
        "delivery.pod.record",
        "attachment.delivery.create",
        "loading.authority.read",
        "job.read",
        "task.read",
        "job.board.read",
    ],
    "kepala": [
        "schedule.assignment.create",
        "sample.decision.record",
        "job.board.read",
        "tracking.read",
        "job.read",
        "task.read",
        "assignee.read",
        "machine.read",
    ],
}


async def seed():
    await dispose_engine()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure auth audit + credentials tables exist
        await conn.run_sync(lambda c: AuthAuditEvent.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: AccountCredential.__table__.create(c, checkfirst=True))

    async with get_session_factory()() as s:
        users = {}
        # Director first
        d = User(
            username="e2e.direktur",
            display_name="Direktur E2E Enforced",
            role="Direktur",
            password_hash=hash_password(PASS),
            permissions=[],  # Full Access via director membership, not legacy OR
            branch_ids=[BRANCH_A, BRANCH_B],
            is_active=True,
        )
        s.add(d)
        await s.flush()
        users["direktur"] = d
        s.add(AccountCredential(user_id=d.id, generation=1, must_change_password=False))

        role_users = {
            "kepala": ("kepala_produksi", "Kepala Produksi"),
            "designer": ("designer", "Designer"),
            "screener": ("screener", "Screener"),
            "helper": ("helper", "Helper"),
            "operator": ("operator", "Op Browser Enf"),
            "driver": ("driver", "Driver"),
        }
        for key, (pack_key, label) in role_users.items():
            u = User(
                username=f"e2e.{key}",
                display_name=label,
                role=pack_key,
                password_hash=hash_password(PASS),
                permissions=list(UI_MIRROR.get(key, [])),
                branch_ids=[BRANCH_A],
                is_active=True,
            )
            s.add(u)
            await s.flush()
            users[key] = u
            s.add(AccountCredential(user_id=u.id, generation=1, must_change_password=False))

        # Wrong-branch + no-grant negative users (test-only)
        wb = User(
            username="e2e.wrongbranch",
            display_name="Wrong Branch",
            role="operator",
            password_hash=hash_password(PASS),
            permissions=list(UI_MIRROR["operator"]),
            branch_ids=[BRANCH_B],
            is_active=True,
        )
        s.add(wb)
        await s.flush()
        users["wrongbranch"] = wb
        s.add(AccountCredential(user_id=wb.id, generation=1, must_change_password=False))

        ng = User(
            username="e2e.nogrant",
            display_name="No Grant",
            role="operator",
            password_hash=hash_password(PASS),
            permissions=[],
            branch_ids=[BRANCH_A],
            is_active=True,
        )
        s.add(ng)
        await s.flush()
        users["nogrant"] = ng
        s.add(AccountCredential(user_id=ng.id, generation=1, must_change_password=False))

        s.add(AccessState(id=1, revision=0, bootstrapped=False))
        await s.flush()
        await bootstrap_director(
            s,
            owner_user_id=d.id,
            expected_username="e2e.direktur",
            approval_reference="Sandbox browser enforced E2E — disposable only",
        )

        # Manual ScopedGrant packs for six roles on branch-a only
        pack_key_map = {
            "kepala": "kepala_produksi",
            "designer": "designer",
            "screener": "screener",
            "helper": "helper",
            "operator": "operator",
            "driver": "driver",
        }
        for key, pack_key in pack_key_map.items():
            pack = ROLE_PACKS[pack_key]
            g = AccessGroup(name=f"E2E pack {pack_key}", system_key=None, active=True)
            s.add(g)
            await s.flush()
            s.add(Membership(user_id=users[key].id, group_id=g.id, active=True))
            caps = list(pack["capabilities"]) + list(EXTRA_CAPS.get(pack_key, ()))
            for cap in caps:
                s.add(
                    ScopedGrant(
                        group_id=g.id,
                        capability=cap,
                        branches=[BRANCH_A],
                        ownership=pack["ownership_default"],
                        assignments=[],
                        active=True,
                    )
                )

        # Wrong-branch: same operator pack but ONLY branch-b
        g_wb = AccessGroup(name="E2E wrongbranch operator", system_key=None, active=True)
        s.add(g_wb)
        await s.flush()
        s.add(Membership(user_id=users["wrongbranch"].id, group_id=g_wb.id, active=True))
        for cap in list(ROLE_PACKS["operator"]["capabilities"]) + ["job.board.read"]:
            s.add(
                ScopedGrant(
                    group_id=g_wb.id,
                    capability=cap,
                    branches=[BRANCH_B],
                    ownership="all",
                    assignments=[],
                    active=True,
                )
            )

        s.add(
            ProductionMachine(
                branch_id=BRANCH_A,
                name="Semi Auto Enforced",
                kind="semi_auto",
                capacity_per_shift=Decimal("5000"),
                shifts_per_day=1,
                active=True,
                created_by=users["kepala"].id,
            )
        )
        job = ProductionJob(
            accurate_so_number="SO/E2E/BROWSER-ENF",
            accurate_id="9400",
            branch_id=BRANCH_A,
            customer_name="Browser Enforced Co",
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
        # Job on branch-b for cross-branch deny proofs
        job_b = ProductionJob(
            accurate_so_number="SO/E2E/BROWSER-ENF-B",
            accurate_id="9401",
            branch_id=BRANCH_B,
            customer_name="Other Branch Co",
            design_status="pending",
            payment_status="pending",
        )
        s.add(job_b)

        body = await pay.read_payment_approval(s, users["direktur"])
        cfg = dict(body["payment_approval"])
        cfg["bypass_enabled"] = True
        await pay.update_payment_approval(
            s,
            users["direktur"],
            version=body["version"],
            payment_approval=cfg,
            reason="Enable bypass for enforced browser disposable",
        )
        await s.commit()
        print(
            "JOB",
            job.id,
            "OPERATOR",
            users["operator"].id,
            "DIREKTUR",
            users["direktur"].id,
            flush=True,
        )
        print(
            "GRANTS",
            {k: pack_key_map[k] for k in pack_key_map},
            flush=True,
        )
    await dispose_engine()


asyncio.run(seed())

# Prove mode before serving
assert get_settings().v3_workflow_authorization == "enforced"
assert get_settings().v3_settings_enabled is True

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8014, log_level="warning")
