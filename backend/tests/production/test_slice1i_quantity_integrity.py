"""Slice 1I — packing event contract + multi-color physical qty integrity."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.production.engine import (
    CANONICAL_PACKING_EVENT,
    packing_qty_from_events,
    physical_cup_qty_from_events,
)


def _ev(**kwargs):
    return SimpleNamespace(**kwargs)


def test_physical_cups_ignore_higher_color_passes():
    events = [
        _ev(event_type="output_confirmed", so_line_id="L1", color_pass=1, qty_physical=Decimal("5000")),
        _ev(event_type="output_confirmed", so_line_id="L1", color_pass=2, qty_physical=Decimal("5000")),
        _ev(event_type="output_confirmed", so_line_id="L1", color_pass=2, qty_physical=Decimal("100")),
    ]
    assert physical_cup_qty_from_events(events, so_line_id="L1") == Decimal("5000")
    assert physical_cup_qty_from_events(events) == Decimal("5000")


def test_physical_cups_apply_corrections_on_pass1_only():
    events = [
        _ev(event_type="output_confirmed", so_line_id="L1", color_pass=1, qty_physical=Decimal("100")),
        _ev(event_type="output_correction", so_line_id="L1", color_pass=1, qty_physical=Decimal("-10")),
        _ev(event_type="output_correction", so_line_id="L1", color_pass=2, qty_physical=Decimal("-50")),
    ]
    assert physical_cup_qty_from_events(events, so_line_id="L1") == Decimal("90")


def test_packing_consumers_accept_canonical_and_alias():
    events = [
        _ev(event_type=CANONICAL_PACKING_EVENT, so_line_id="L1", qty_physical=Decimal("40")),
        _ev(event_type="packing_recorded", so_line_id="L1", qty_physical=Decimal("10")),
        _ev(event_type="packing_batch", so_line_id="L2", qty_physical=Decimal("5")),
    ]
    assert packing_qty_from_events(events, so_line_id="L1") == Decimal("50")
    assert packing_qty_from_events(events) == Decimal("55")


def test_derive_pack_done_uses_packing_batch_not_orphan_alias_only():
    """Regression: historical writers use packing_batch; derive must see them."""
    from app.services.production.engine import derive_team_tasks_for_job

    job = SimpleNamespace(
        id=1,
        accurate_so_number="SO/1I/PACK",
        branch_id="branch-a",
        customer_name="Cust",
        design_status="approved",
        payment_status="approved",
        sample_status="approved",
        processing_status="Terproses",
    )
    lines = [SimpleNamespace(production_process="print", so_line_id="L1")]
    assignments = [SimpleNamespace(status="active", so_line_id="L1")]
    prep = [
        SimpleNamespace(role="screener", qty=Decimal("1")),
        SimpleNamespace(role="helper", qty=Decimal("100")),
    ]
    samples = [SimpleNamespace(status="approved")]
    events = [
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=1,
            qty_physical=Decimal("50"),
        ),
        _ev(
            event_type="output_confirmed",
            so_line_id="L1",
            color_pass=2,
            qty_physical=Decimal("50"),
        ),
        _ev(event_type="packing_batch", so_line_id="L1", qty_physical=Decimal("50")),
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
    assert states.get("packing") == "done"


# ---- API: packing cannot inflate from multi-color passes ----
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

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.PACKING_RECORD,
]


@pytest.fixture
async def client_1i():
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
                username="slice1i.lead",
                display_name="Slice1I",
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
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "slice1i.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_packing_rejects_sum_of_two_color_passes(client_1i: AsyncClient) -> None:
    """5k pass1 + 5k pass2 must not allow packing 10k physical cups."""
    job = (
        await client_1i.post(
            "/api/v1/production/jobs",
            json={
                "accurate_so_number": "SO/1I/MC",
                "branch_id": "branch-a",
                "customer_name": "Multi",
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
        await client_1i.post(
            f"/api/v1/production/jobs/{jid}/design/versions",
            json={"file_name": "d.pdf", "storage_key": "d"},
        )
    ).json()
    await client_1i.post(
        f"/api/v1/production/jobs/design/versions/{design['id']}/decision",
        json={"decision": "approved"},
    )
    await client_1i.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        json={"reason": "test"},
    )
    asg1 = (
        await client_1i.post(
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
        await client_1i.post(
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
    await client_1i.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "5000",
            "screen_size": "kecil",
            "evidence_ref": "scr",
            "idempotency_key": "scr-1i-multi-color",
            "assignment_id": asg1["id"],
        },
    )
    await client_1i.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        json={
            "so_line_id": "L1",
            "qty": "5000",
            "po_qty": "5000",
            "evidence_ref": "hlp",
            "idempotency_key": "hlp-1i-multi-color",
        },
    )
    sample = (
        await client_1i.post(
            f"/api/v1/production/jobs/{jid}/samples",
            json={"file_name": "s.jpg", "storage_key": "s", "assignment_id": asg1["id"]},
        )
    ).json()
    await client_1i.post(
        f"/api/v1/production/jobs/samples/{sample['id']}/decision",
        json={"decision": "approved"},
    )
    assert (
        await client_1i.post(
            f"/api/v1/production/jobs/{jid}/outputs",
            json={
                "assignment_id": asg1["id"],
                "qty_physical": "5000",
                "color_pass": 1,
                "idempotency_key": "out-pass1-5000",
            },
        )
    ).status_code == 200
    assert (
        await client_1i.post(
            f"/api/v1/production/jobs/{jid}/outputs",
            json={
                "assignment_id": asg2["id"],
                "qty_physical": "5000",
                "color_pass": 2,
                "idempotency_key": "out-pass2-5000",
            },
        )
    ).status_code == 200
    over = await client_1i.post(
        f"/api/v1/production/jobs/{jid}/packing",
        json={
            "so_line_id": "L1",
            "qty_physical": "10000",
            "idempotency_key": "pack-over-10000",
        },
    )
    assert over.status_code == 409, over.text
    ok = await client_1i.post(
        f"/api/v1/production/jobs/{jid}/packing",
        json={
            "so_line_id": "L1",
            "qty_physical": "5000",
            "idempotency_key": "pack-ok-5000",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["event_type"] == "packing_batch"
