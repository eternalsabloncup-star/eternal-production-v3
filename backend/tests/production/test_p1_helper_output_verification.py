"""P1-02 — helper output verification + packing from verified pool."""

from __future__ import annotations

import os
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "test-secret-helper-verify-xx"
os.environ["V3_PASSWORD_PEPPER"] = "test-pepper-helper-verify"

from tests.db_url_guard import (  # noqa: E402
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)

_async_url, _sync_url = resolve_test_database_urls()
assert is_test_database_url(_async_url)
assert database_name(_async_url).endswith("_test")
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.production import permissions as P  # noqa: E402
from app.services.production.engine import (  # noqa: E402
    eligible_verified_qty_from_events,
    qty_helper_verified_for_pass_from_events,
)

ALL = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.OUTPUT_HELPER_VERIFY,
    P.PACKING_RECORD,
    P.PREP_HELPER,
    P.PREP_SCREENER,
]


def _ev(**kwargs):
    return SimpleNamespace(**kwargs)


def test_verified_min_across_passes_not_sum():
    events = [
        _ev(
            event_type="output_helper_verified",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("100"),
        ),
        _ev(
            event_type="output_helper_verified",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("60"),
        ),
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("999"),
        ),
    ]
    assert qty_helper_verified_for_pass_from_events(events, 1, so_line_id="L1") == Decimal(
        "100"
    )
    assert eligible_verified_qty_from_events(
        events, frozenset({1, 2}), so_line_id="L1"
    ) == Decimal("60")


@pytest_asyncio.fixture
async def client():
    await dispose_engine()
    get_settings.cache_clear()
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        ops = User(
            username="hv.ops",
            display_name="HV Ops",
            role="kepala_produksi",
            password_hash=hash_password("x"),
            permissions=ALL,
            branch_ids=["BR-JKT"],
            is_active=True,
        )
        helper = User(
            username="hv.helper",
            display_name="HV Helper",
            role="helper",
            password_hash=hash_password("x"),
            permissions=[
                P.JOB_READ,
                P.OUTPUT_HELPER_VERIFY,
                P.PACKING_RECORD,
            ],
            branch_ids=["BR-JKT"],
            is_active=True,
        )
        session.add_all([ops, helper])
        await session.commit()
        await session.refresh(ops)
        await session.refresh(helper)
        ops_tok = create_access_token(ops)
        help_tok = create_access_token(helper)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, ops_tok, help_tok
    await dispose_engine()


async def _ready_job(ac: AsyncClient, h: dict, so: str, passes: int = 1):
    job = await ac.post(
        "/api/v1/production/jobs",
        headers=h,
        json={
            "accurate_so_number": so,
            "branch_id": "BR-JKT",
            "customer_name": "HV Cust",
            "line_items": [
                {"id": "L1", "quantity": 100, "production_process": "print"}
            ],
        },
    )
    assert job.status_code == 200, job.text
    jid = job.json()["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        headers=h,
        json={"file_name": "d.pdf", "storage_key": "d.pdf"},
    )
    await ac.post(
        f"/api/v1/production/jobs/design/versions/{up.json()['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "test bypass"},
    )
    await ac.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        headers=h,
        json={"reason": "pay"},
    )
    asg_ids = []
    for p in range(1, passes + 1):
        a = await ac.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "L1",
                "color_pass": p,
                "operator_name": f"Op{p}",
                "machine_name": "M1",
                "work_date": "2026-11-13",
                "qty_planned": "100",
            },
        )
        assert a.status_code == 200, a.text
        asg_ids.append(a.json()["id"])
    # helper prep so output allowed
    prep = await ac.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty": "100",
            "evidence_ref": f"prep-{so}",
            "idempotency_key": f"prep-{so}-key",
            "po_qty": "100",
        },
    )
    assert prep.status_code == 200, prep.text
    return jid, asg_ids


@pytest.mark.asyncio
async def test_packing_requires_helper_verify_partial_and_duplicate(client):
    ac, ops_tok, help_tok = client
    h = {"Authorization": f"Bearer {ops_tok}"}
    hh = {"Authorization": f"Bearer {help_tok}"}
    jid, asg_ids = await _ready_job(ac, h, "SO-HV-001", passes=1)

    out = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg_ids[0],
            "qty_physical": "40",
            "color_pass": 1,
            "idempotency_key": "out-hv-0001",
        },
    )
    assert out.status_code == 200, out.text
    oid = out.json()["id"]

    # Packing before verify rejected
    pack0 = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "10",
            "idempotency_key": "pack-before-01",
        },
    )
    assert pack0.status_code == 409

    # Partial verify
    v1 = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{oid}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": oid,
            "qty_physical": "25",
            "idempotency_key": "hv-partial-001",
        },
    )
    assert v1.status_code == 200, v1.text
    assert v1.json()["event_type"] == "output_helper_verified"

    pack_ok = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "25",
            "idempotency_key": "pack-ok-001",
        },
    )
    assert pack_ok.status_code == 200, pack_ok.text

    # Over verified rejected
    pack_over = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "pack-over-001",
        },
    )
    assert pack_over.status_code == 409

    # Duplicate verify beyond remaining
    v_over = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{oid}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": oid,
            "qty_physical": "20",
            "idempotency_key": "hv-over-001",
        },
    )
    assert v_over.status_code == 409

    # Remaining 15 ok
    v2 = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{oid}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": oid,
            "qty_physical": "15",
            "idempotency_key": "hv-rest-001",
        },
    )
    assert v2.status_code == 200
    v2_id = v2.json()["id"]

    # Identical replay → return prior (no double count)
    v_same = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{oid}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": oid,
            "qty_physical": "15",
            "idempotency_key": "hv-rest-001",
        },
    )
    assert v_same.status_code == 200, v_same.text
    assert v_same.json()["id"] == v2_id

    # Mismatched payload with same key → 409
    v_dup = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{oid}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": oid,
            "qty_physical": "1",
            "idempotency_key": "hv-rest-001",
        },
    )
    assert v_dup.status_code == 409


@pytest.mark.asyncio
async def test_multicolor_packing_uses_min_verified(client):
    ac, ops_tok, help_tok = client
    h = {"Authorization": f"Bearer {ops_tok}"}
    hh = {"Authorization": f"Bearer {help_tok}"}
    jid, asg_ids = await _ready_job(ac, h, "SO-HV-MC", passes=2)

    o1 = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg_ids[0],
            "qty_physical": "50",
            "color_pass": 1,
            "idempotency_key": "mc-out-pass1",
        },
    )
    o2 = await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg_ids[1],
            "qty_physical": "50",
            "color_pass": 2,
            "idempotency_key": "mc-out-pass2",
        },
    )
    assert o1.status_code == 200 and o2.status_code == 200, (o1.text, o2.text)
    await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{o1.json()['id']}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": o1.json()["id"],
            "qty_physical": "50",
            "idempotency_key": "mc-hv-pass1",
        },
    )
    # Only pass1 verified — packing blocked
    blocked = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "10",
            "idempotency_key": "mc-pack-block1",
        },
    )
    assert blocked.status_code == 409
    await ac.post(
        f"/api/v1/production/jobs/{jid}/outputs/{o2.json()['id']}/helper-verifications",
        headers=hh,
        json={
            "source_output_event_id": o2.json()["id"],
            "qty_physical": "30",
            "idempotency_key": "mc-hv-pass2",
        },
    )
    # min(50,30)=30
    ok = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "30",
            "idempotency_key": "mc-pack-ok-01",
        },
    )
    assert ok.status_code == 200, ok.text
    over = await ac.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=hh,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "mc-pack-over1",
        },
    )
    assert over.status_code == 409
