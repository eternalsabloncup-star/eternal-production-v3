"""E3: approval_at, bypass_by, qty_helper_prepared — disposable PostgreSQL only."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from tests.db_url_guard import resolve_test_database_urls

_async_url, _sync_url = resolve_test_database_urls()
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_not_from_v1"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_distinct"
os.environ["V3_WORKFLOW_AUTHORIZATION"] = "legacy"

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.production.payment_settings import DEFAULT_PAYMENT_SETTINGS
from app.models.production.prep import JobLineQty, PrepState
from app.models.user import User
from app.services.production import payment_settings as pay_settings
from app.services.production import permissions as P
from app.services.production.prep import PREP_ROLE_CUP

get_settings.cache_clear()


async def _enable_bypass(session):
    row = await pay_settings.get_or_create_settings(session)
    cfg = dict(DEFAULT_PAYMENT_SETTINGS)
    if isinstance(row.config_json, dict):
        cfg.update({k: v for k, v in row.config_json.items() if isinstance(v, bool)})
    cfg["bypass_enabled"] = True
    row.config_json = cfg
    await session.flush()


@pytest.fixture
async def client():
    await dispose_engine()
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        lead = User(
            username="e3t.lead",
            display_name="E3T Lead",
            role="kepala_produksi",
            password_hash=hash_password("secret-pass"),
            permissions=[P.JOB_READ, P.JOB_CREATE, P.SCHEDULE_MANAGE],
            branch_ids=["branch-a"],
            is_active=True,
        )
        director = User(
            username="e3t.direktur",
            display_name="E3T Direktur",
            role="direktur",
            password_hash=hash_password("secret-pass"),
            permissions=[P.JOB_READ, P.JOB_CREATE, P.SCHEDULE_MANAGE, P.PAYMENT_BYPASS],
            branch_ids=["branch-a"],
            is_active=True,
        )
        session.add_all([lead, director])
        await session.flush()
        await _enable_bypass(session)

        job_ok = ProductionJob(
            accurate_so_number="SO/E3T/OK",
            accurate_id="e3t-ok",
            branch_id="branch-a",
            customer_name="Cust OK",
            design_status="approved",
            payment_status="pending",
        )
        job_byp = ProductionJob(
            accurate_so_number="SO/E3T/BYP",
            accurate_id="e3t-byp",
            branch_id="branch-a",
            customer_name="Cust Byp",
            design_status="approved",
            payment_status="pending",
        )
        job_hlp = ProductionJob(
            accurate_so_number="SO/E3T/HLP",
            accurate_id="e3t-hlp",
            branch_id="branch-a",
            customer_name="Cust Hlp",
            design_status="approved",
            payment_status="approved",
        )
        job_empty = ProductionJob(
            accurate_so_number="SO/E3T/EMPTY",
            accurate_id="e3t-empty",
            branch_id="branch-a",
            customer_name="Cust Empty",
            design_status="approved",
            payment_status="pending",
        )
        session.add_all([job_ok, job_byp, job_hlp, job_empty])
        await session.flush()
        session.add(
            PaymentReceiptRef(
                job_id=job_ok.id,
                accurate_receipt_id="RCP-E3T-1",
                accurate_receipt_number="RCP-E3T-1",
                amount=Decimal("25000"),
                evidence_verified=True,
                status="valid",
                recorded_by=director.id,
                idempotency_key="e3t-rcp-1",
            )
        )
        session.add(
            PaymentBypass(
                job_id=job_byp.id,
                reason="e3t bypass",
                authorized_by=director.id,
                active=True,
                gate_before="pending",
                idempotency_key="e3t-byp-1",
            )
        )
        for job in (job_ok, job_byp, job_hlp, job_empty):
            session.add(
                JobLineQty(
                    job_id=job.id,
                    so_line_id="L1",
                    accurate_item_id="P1",
                    po_qty=Decimal("40"),
                    production_process="print",
                )
            )
        session.add(
            PrepState(
                job_id=job_hlp.id,
                so_line_id="L1",
                role=PREP_ROLE_CUP,
                qty=Decimal("7"),
                updated_by=lead.id,
            )
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _login(ac, username: str) -> dict:
    r = await ac.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret-pass"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_approval_at_from_verified_receipt_not_last_updated(client):
    h = await _login(client, "e3t.lead")
    body = (await client.get("/api/v1/production/jobs/payment/receipts?q=SO/E3T/OK", headers=h)).json()
    item = body["items"][0]
    assert item["payment_status"] == "approved"
    assert item["approval_at"] is not None
    assert item["approval_at"] != item.get("last_updated_at") or item["last_updated_at"] is not None
    # Canonical: earliest verified receipt created_at (ISO); must match receipt recorded_at.
    recorded = [r["recorded_at"] for r in item["receipts"] if r["evidence_verified"]]
    assert item["approval_at"] in recorded
    empty = (
        await client.get("/api/v1/production/jobs/payment/receipts?q=SO/E3T/EMPTY", headers=h)
    ).json()["items"][0]
    assert empty["payment_status"] == "pending"
    assert empty["approval_at"] is None


@pytest.mark.asyncio
async def test_bypass_by_gated_to_bypass_permission(client):
    h_lead = await _login(client, "e3t.lead")
    h_dir = await _login(client, "e3t.direktur")
    lead_item = (
        await client.get("/api/v1/production/jobs/payment/receipts?q=SO/E3T/BYP", headers=h_lead)
    ).json()["items"][0]
    dir_item = (
        await client.get("/api/v1/production/jobs/payment/receipts?q=SO/E3T/BYP", headers=h_dir)
    ).json()["items"][0]
    assert lead_item["payment_status"] == "bypassed"
    assert lead_item["bypass_active"] is True
    assert lead_item["bypass_by"] is None
    assert lead_item["bypasses"][0]["authorized_by"] is None
    assert lead_item["bypasses"][0]["authorized_by_name"] is None
    assert dir_item["bypass_by"] == "E3T Direktur"
    assert dir_item["bypasses"][0]["authorized_by_name"] == "E3T Direktur"
    assert dir_item["approval_at"] is not None


@pytest.mark.asyncio
async def test_qty_helper_prepared_from_prep_state_not_so_qty(client):
    h = await _login(client, "e3t.lead")
    body = (
        await client.get("/api/v1/production/ops/schedule?q=SO/E3T/HLP", headers=h)
    ).json()
    assert body["items"]
    row = body["items"][0]
    assert Decimal(row["qty_print_po"]) == Decimal("40")
    assert Decimal(row["qty_helper_prepared"]) == Decimal("7")
    empty = (
        await client.get("/api/v1/production/ops/schedule?q=SO/E3T/EMPTY", headers=h)
    ).json()["items"][0]
    assert empty["qty_helper_prepared"] is None
