"""End-to-end Phase 2 workflow slice: design → payment → schedule → sample → output → pack → load → POD."""

from __future__ import annotations

import os
from datetime import date
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

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_RECORD,
    P.PAYMENT_BYPASS,
    P.PAYMENT_REVOKE,
    P.SCHEDULE_MANAGE,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
]


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
        session.add(
            User(
                username="prod.lead",
                display_name="Prod Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _token(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "prod.lead", "password": "secret-pass"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_full_happy_path_and_guards(client: AsyncClient) -> None:
    token = await _token(client)
    h = {"Authorization": f"Bearer {token}"}

    job = await client.post(
        "/api/v1/production/jobs",
        headers=h,
        json={
            "accurate_so_number": "SO/PHASE2/001",
            "branch_id": "branch-a",
            "customer_name": "Customer A",
        },
    )
    assert job.status_code == 200
    job_id = job.json()["id"]

    blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        headers=h,
        json={
            "so_line_id": "line-1",
            "color_pass": 1,
            "operator_name": "Rizki",
            "machine_name": "Semi Auto 01",
            "work_date": str(date.today()),
            "qty_planned": "100",
        },
    )
    assert blocked.status_code == 409

    design = await client.post(
        f"/api/v1/production/jobs/{job_id}/design/versions",
        headers=h,
        json={"file_name": "art-v1.pdf", "storage_key": "designs/art-v1.pdf"},
    )
    assert design.status_code == 200
    decided = await client.post(
        f"/api/v1/production/jobs/design/versions/{design.json()['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )
    assert decided.status_code == 200

    # New design upload revokes prior approval gate
    design2 = await client.post(
        f"/api/v1/production/jobs/{job_id}/design/versions",
        headers=h,
        json={"file_name": "art-v2.pdf", "storage_key": "designs/art-v2.pdf"},
    )
    assert design2.status_code == 200
    job_pending = await client.get(f"/api/v1/production/jobs/{job_id}", headers=h)
    assert job_pending.json()["design_status"] == "pending"
    await client.post(
        f"/api/v1/production/jobs/design/versions/{design2.json()['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )

    pay = await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/receipts",
        headers=h,
        json={"accurate_receipt_id": "RCV-1", "amount": "1500000"},
    )
    assert pay.status_code == 200

    asg = await client.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        headers=h,
        json={
            "so_line_id": "line-1",
            "color_pass": 1,
            "operator_name": "Rizki",
            "machine_name": "Semi Auto 01",
            "work_date": str(date.today()),
            "qty_planned": "100",
        },
    )
    assert asg.status_code == 200
    assignment_id = asg.json()["id"]

    sample = await client.post(
        f"/api/v1/production/jobs/{job_id}/samples",
        headers=h,
        json={
            "file_name": "sample.jpg",
            "storage_key": "samples/1.jpg",
            "assignment_id": assignment_id,
        },
    )
    assert sample.status_code == 200
    out_blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": assignment_id,
            "qty_physical": "10",
            "idempotency_key": "out-blocked-1",
        },
    )
    assert out_blocked.status_code == 409
    await client.post(
        f"/api/v1/production/jobs/samples/{sample.json()['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )

    out = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": assignment_id,
            "qty_physical": "40",
            "qty_pass_ops": "40",
            "color_pass": 1,
            "idempotency_key": "out-pass-1",
            "lot_code": "L1",
        },
    )
    assert out.status_code == 200
    dup = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": assignment_id,
            "qty_physical": "40",
            "idempotency_key": "out-pass-1",
        },
    )
    assert dup.status_code == 409

    rej = await client.post(
        f"/api/v1/production/jobs/{job_id}/rejects",
        headers=h,
        json={
            "assignment_id": assignment_id,
            "qty_physical": "5",
            "reason": "misprint",
            "idempotency_key": "rej-pass-1",
            "lot_code": "L1",
        },
    )
    assert rej.status_code == 200
    verified = await client.post(
        f"/api/v1/production/jobs/rejects/{rej.json()['id']}/verify",
        headers=h,
        json={"approved_qty": "5"},
    )
    assert verified.status_code == 200

    pack = await client.post(
        f"/api/v1/production/jobs/{job_id}/packing",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty_physical": "35",
            "idempotency_key": "pack-pass-1",
            "lot_code": "L1",
        },
    )
    assert pack.status_code == 200
    over = await client.post(
        f"/api/v1/production/jobs/{job_id}/packing",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty_physical": "1",
            "idempotency_key": "pack-over-1",
        },
    )
    assert over.status_code == 409

    pod_blocked = await client.post(
        f"/api/v1/production/jobs/{job_id}/pod",
        headers=h,
        json={
            "accurate_sj_id": "sj-1",
            "qty_physical": "10",
            "idempotency_key": "pod-early-1",
            "evidence_ref": "photo-1",
            "receiver_name": "Budi",
        },
    )
    assert pod_blocked.status_code == 409

    load = await client.post(
        f"/api/v1/production/jobs/{job_id}/loading",
        headers=h,
        json={
            "accurate_sj_id": "sj-1",
            "accurate_sj_number": "SJ/001",
            "qty_physical": "20",
            "idempotency_key": "load-pass-1",
        },
    )
    assert load.status_code == 200
    pod = await client.post(
        f"/api/v1/production/jobs/{job_id}/pod",
        headers=h,
        json={
            "accurate_sj_id": "sj-1",
            "qty_physical": "20",
            "idempotency_key": "pod-pass-1",
            "evidence_ref": "photo-1",
            "receiver_name": "Budi",
        },
    )
    assert pod.status_code == 200

    tracking = await client.get(
        f"/api/v1/production/jobs/{job_id}/tracking", headers=h
    )
    assert tracking.status_code == 200
    types = [e["event_type"] for e in tracking.json()["events"]]
    assert "output_confirmed" in types
    assert "reject_verified" in types
    assert "packing_batch" in types
    assert "loading" in types
    assert "pod" in types


@pytest.mark.asyncio
async def test_cancel_remaining_preserves_confirmed(client: AsyncClient) -> None:
    token = await _token(client)
    h = {"Authorization": f"Bearer {token}"}
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO/PHASE2/002", "branch_id": "branch-a"},
        )
    ).json()
    job_id = job["id"]
    design = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{design['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "owner"},
    )
    await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/bypass",
        headers=h,
        json={"reason": "authorized bypass"},
    )
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Bima",
                "machine_name": "Semi Auto 02",
                "work_date": str(date.today()),
                "qty_planned": "50",
            },
        )
    ).json()
    out2 = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=h,
        json={
            "assignment_id": asg["id"],
            "qty_physical": "20",
            "idempotency_key": "out-pass-2",
        },
    )
    assert out2.status_code == 200
    cancel = await client.post(
        f"/api/v1/production/jobs/schedule/assignments/{asg['id']}/cancel-remaining",
        headers=h,
        json={"reason": "customer reduce"},
    )
    assert cancel.status_code == 200
    assert Decimal(cancel.json()["qty_cancelled_remaining"]) == Decimal("30")

    # Payment invalidate closes gate when no other evidence
    receipt = await client.post(
        f"/api/v1/production/jobs/{job_id}/payment/receipts",
        headers=h,
        json={"accurate_receipt_id": "RCV-late"},
    )
    # First revoke bypass so invalidate can close gate
    # (bypass still active from earlier — invalidate alone keeps bypass)
    # Create a fresh job for invalidate-only path
    job3 = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO/PHASE2/003", "branch_id": "branch-a"},
        )
    ).json()
    d3 = (
        await client.post(
            f"/api/v1/production/jobs/{job3['id']}/design/versions",
            headers=h,
            json={"file_name": "b.pdf", "storage_key": "b"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{d3['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )
    r3 = (
        await client.post(
            f"/api/v1/production/jobs/{job3['id']}/payment/receipts",
            headers=h,
            json={"accurate_receipt_id": "RCV-only"},
        )
    ).json()
    inv = await client.post(
        f"/api/v1/production/jobs/payment/receipts/{r3['id']}/invalidate",
        headers=h,
        json={"reason": "reversed in Accurate"},
    )
    assert inv.status_code == 200
    job3_state = await client.get(
        f"/api/v1/production/jobs/{job3['id']}", headers=h
    )
    assert job3_state.json()["payment_status"] == "pending"
    assert receipt.status_code == 200
