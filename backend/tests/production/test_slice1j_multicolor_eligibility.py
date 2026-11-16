"""Slice 1J — packing eligibility requires ALL scheduled color passes."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.production.engine import (
    eligible_finished_qty_from_events,
    packing_qty_from_events,
    physical_cup_qty_from_events,
    qty_for_color_pass_from_events,
    required_color_passes_from_assignments,
)


def _ev(**kwargs):
    return SimpleNamespace(**kwargs)


def test_required_passes_from_schedule_not_assumed_single_color():
    asg = [
        SimpleNamespace(status="active", so_line_id="L1", color_pass=1),
        SimpleNamespace(status="active", so_line_id="L1", color_pass=2),
        SimpleNamespace(status="cancelled_remaining", so_line_id="L1", color_pass=3),
        SimpleNamespace(status="active", so_line_id="L2", color_pass=1),
    ]
    assert required_color_passes_from_assignments(asg, so_line_id="L1") == frozenset(
        {1, 2}
    )
    assert required_color_passes_from_assignments([], so_line_id="L1") == frozenset({1})


def test_incomplete_pass2_blocks_finished_eligibility():
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("5000"),
        ),
    ]
    required = frozenset({1, 2})
    assert eligible_finished_qty_from_events(events, required, so_line_id="L1") == Decimal(
        "0"
    )
    assert physical_cup_qty_from_events(events, so_line_id="L1") == Decimal("5000")


def test_partial_pass2_limits_packable_to_min():
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("5000"),
        ),
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("3000"),
        ),
    ]
    assert eligible_finished_qty_from_events(
        events, frozenset({1, 2}), so_line_id="L1"
    ) == Decimal("3000")


def test_full_two_color_eligible_is_min_not_sum():
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("5000"),
        ),
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("5000"),
        ),
    ]
    assert eligible_finished_qty_from_events(
        events, frozenset({1, 2}), so_line_id="L1"
    ) == Decimal("5000")


def test_reject_on_pass_reduces_that_pass_before_min():
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("5000"),
        ),
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("5000"),
        ),
        _ev(
            event_type="reject_verified",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("200"),
        ),
    ]
    assert qty_for_color_pass_from_events(events, 2, so_line_id="L1") == Decimal("4800")
    assert eligible_finished_qty_from_events(
        events, frozenset({1, 2}), so_line_id="L1"
    ) == Decimal("4800")


def test_derive_blocks_packing_until_all_passes_done():
    from app.services.production.engine import derive_team_tasks_for_job

    job = SimpleNamespace(
        id=1,
        accurate_so_number="SO/1J/MC",
        branch_id="branch-a",
        customer_name="Cust",
        design_status="approved",
        payment_status="approved",
        sample_status="approved",
        processing_status="Terproses",
    )
    lines = [SimpleNamespace(production_process="print", so_line_id="L1")]
    assignments = [
        SimpleNamespace(status="active", so_line_id="L1", color_pass=1),
        SimpleNamespace(status="active", so_line_id="L1", color_pass=2),
    ]
    prep = [
        SimpleNamespace(role="screener", qty=Decimal("1"), so_line_id="L1"),
        SimpleNamespace(role="helper", qty=Decimal("5000"), so_line_id="L1"),
    ]
    samples = [SimpleNamespace(status="approved")]
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("5000"),
        ),
    ]
    tasks = derive_team_tasks_for_job(
        job,
        lines=lines,
        designs=[],
        assignments=assignments,
        prep_states=prep,
        samples=samples,
        events=events,
    )
    states = {t["kind"]: t["state"] for t in tasks}
    assert states.get("print") == "done"
    assert states.get("packing") == "blocked"
    assert packing_qty_from_events(events) == Decimal("0")


# ---- API integration ----
import os
from datetime import date

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


ALL_PERMS_1J = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.OUTPUT_HELPER_VERIFY,
    P.PACKING_RECORD,
]


@pytest.fixture
async def client_1j():
    get_settings.cache_clear()
    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            User(
                username="slice1j.lead",
                display_name="Slice1J",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS_1J,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "slice1j.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200, login.text
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _seed_two_color_job(client: AsyncClient) -> tuple[int, dict, dict]:
    job = (
        await client.post(
            "/api/v1/production/jobs",
            json={
                "accurate_so_number": "SO/1J/ELIG",
                "branch_id": "branch-a",
                "customer_name": "Elig",
                "line_items": [
                    {
                        "accurate_line_id": "L1",
                        "quantity": "5000",
                        "production_process": "print",
                    }
                ],
            },
        )
    ).json()
    jid = job["id"]
    design = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/design/versions",
            json={"file_name": "d.pdf", "storage_key": "d"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{design['id']}/decision",
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    await client.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        json={"reason": "test"},
    )
    asg1 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            json={
                "so_line_id": "L1",
                "color_pass": 1,
                "operator_name": "A",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "5000",
            },
        )
    ).json()
    asg2 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            json={
                "so_line_id": "L1",
                "color_pass": 2,
                "operator_name": "B",
                "machine_name": "M2",
                "work_date": str(date.today()),
                "qty_planned": "5000",
            },
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "5000",
            "screen_size": "kecil",
            "evidence_ref": "scr",
            "idempotency_key": "scr-1j-elig-pass",
            "assignment_id": asg1["id"],
        },
    )
    await client.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        json={
            "so_line_id": "L1",
            "qty": "5000",
            "po_qty": "5000",
            "evidence_ref": "hlp",
            "idempotency_key": "hlp-1j-elig-pass",
        },
    )
    sample = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/samples",
            json={"file_name": "s.jpg", "storage_key": "s", "assignment_id": asg1["id"]},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/samples/{sample['id']}/decision",
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    return jid, asg1, asg2


@pytest.mark.asyncio
async def test_api_pass1_only_cannot_pack(client_1j: AsyncClient) -> None:
    jid, asg1, _asg2 = await _seed_two_color_job(client_1j)
    o1 = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "5000",
            "color_pass": 1,
            "idempotency_key": "out-1j-p1-only",
        },
    )
    assert o1.status_code == 200
    from tests.production.helper_verify_helpers import helper_verify_output

    await helper_verify_output(client_1j, jid, o1.json()["id"], "5000", idem="hv-1j-p1-only")
    blocked = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/packing",
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "pack-1j-blocked",
        },
    )
    assert blocked.status_code == 409, blocked.text


@pytest.mark.asyncio
async def test_api_partial_pass2_caps_packing(client_1j: AsyncClient) -> None:
    jid, asg1, asg2 = await _seed_two_color_job(client_1j)
    o1 = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "5000",
            "color_pass": 1,
            "idempotency_key": "out-1j-p1-full",
        },
    )
    assert o1.status_code == 200
    o2 = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        json={
            "assignment_id": asg2["id"],
            "qty_physical": "3000",
            "color_pass": 2,
            "idempotency_key": "out-1j-p2-partial",
        },
    )
    assert o2.status_code == 200
    from tests.production.helper_verify_helpers import helper_verify_output

    await helper_verify_output(client_1j, jid, o1.json()["id"], "5000", idem="hv-1j-p1")
    await helper_verify_output(client_1j, jid, o2.json()["id"], "3000", idem="hv-1j-p2")
    over = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/packing",
        json={
            "so_line_id": "L1",
            "qty_physical": "3001",
            "idempotency_key": "pack-1j-over-partial",
        },
    )
    assert over.status_code == 409, over.text
    ok = await client_1j.post(
        f"/api/v1/production/jobs/{jid}/packing",
        json={
            "so_line_id": "L1",
            "qty_physical": "3000",
            "idempotency_key": "pack-1j-ok-partial",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["event_type"] == "packing_batch"
