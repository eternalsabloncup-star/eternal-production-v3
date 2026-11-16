"""Function First Iterasi 2 — Delivery Integrity focused gates (disposable DB)."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from tests.db_url_guard import (
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)
from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body, sj_line_item

_async_url, _sync_url = resolve_test_database_urls()
assert is_test_database_url(_async_url)
assert database_name(_async_url).endswith("_test")
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_delivery_iter2"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_delivery_iter2"

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.production.event import ProductionEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.production import permissions as P  # noqa: E402

get_settings.cache_clear()

ALL_PERMS = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.JOB_CANCEL,
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
    P.DELIVERY_MANAGE,
    P.PREP_HELPER,
    P.PREP_SCREENER,
]


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
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
                username="di.lead",
                display_name="DI Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="di.noperm",
                display_name="No Perm",
                role="ops",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="di.wrongbr",
                display_name="Wrong Branch",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        await session.commit()

    catalog: dict[str, list] = {
        "SJ-DI": [
            sj_line_item(
                accurate_sj_line_id="SL1", so_line_id="L1", quantity=100, sku="CUP"
            )
        ],
        "SJ-DI-B": [
            sj_line_item(
                accurate_sj_line_id="SL2", so_line_id="L1", quantity=40, sku="CUP"
            )
        ],
    }

    async def _valid_sj(**kwargs):
        sj = kwargs["accurate_sj_id"]
        lines = catalog.get(sj)
        if lines is None:
            from fastapi import HTTPException

            raise HTTPException(409, "Surat Jalan Accurate tidak ditemukan")
        return {
            "verified": True,
            "mode": "gateway",
            "accurate_sj_id": sj,
            "accurate_sj_number": kwargs["accurate_sj_number"],
            "sales_order_number": kwargs.get("expected_so_number") or "SO-DI",
            "branch_id": "branch-a",
            "line_items": lines,
            "loading_eligible": True,
            "live_verified": False,
        }

    monkeypatch.setattr("app.services.accurate_evidence.require_valid_sj", _valid_sj)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._di_catalog = catalog  # type: ignore[attr-defined]
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _login(client: AsyncClient, user: str = "di.lead") -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "secret-pass"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_job(
    client: AsyncClient,
    h: dict,
    so: str,
    *,
    process: str = "print",
    qty: str = "100",
) -> int:
    body = {
        "accurate_so_number": so,
        "branch_id": "branch-a",
        "line_items": [
            {
                "accurate_line_id": "L1",
                "quantity": qty,
                "production_process": process,
            }
        ],
    }
    job = await client.post("/api/v1/production/jobs", headers=h, json=body)
    assert job.status_code == 200, job.text
    return int(job.json()["id"])


async def _seed_helper_verified(jid: int, qty: str = "80") -> None:
    async with get_session_factory()() as s:
        s.add(
            ProductionEvent(
                job_id=jid,
                event_type="output_helper_verified",
                so_line_id="L1",
                qty_physical=Decimal(qty),
                color_pass=1,
                idempotency_key=f"di-hv-{jid}-{qty}",
                actor_user_id=1,
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_unknown_process_packing_always_rejected(client: AsyncClient):
    """Fail-closed even when conftest disables REQUIRE_SYNCED_LINE_QTY."""
    h = await _login(client)
    jid = await _create_job(client, h, "SO-DI-UNK", process="unknown")
    await _seed_helper_verified(jid, "50")
    packed = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "10",
            "idempotency_key": "di-unk-pack-01",
        },
    )
    assert packed.status_code == 409
    assert "belum resmi" in packed.text


@pytest.mark.asyncio
async def test_cancelled_job_blocks_packing_loading_pod(client: AsyncClient):
    h = await _login(client)
    jid = await _create_job(client, h, "SO-DI-CANCEL")
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/cancel",
        headers=h,
        json={
            "reason": "batal sebelum packing",
            "idempotency_key": "di-cancel-job-01",
        },
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["lifecycle_status"] == "cancelled"

    packed = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "di-cancel-pack-01",
        },
    )
    assert packed.status_code == 409
    assert "cancelled" in packed.text.lower()

    loaded = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-DI",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="1",
            idempotency_key="di-cancel-load-01",
        ),
    )
    assert loaded.status_code == 409
    assert "cancelled" in loaded.text.lower()

    ids = await upload_pod_bundle(client, jid, "SJ-DI", headers=h)
    pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "1", "di-cancel-pod-01", ids),
    )
    assert pod.status_code == 409
    assert "cancelled" in pod.text.lower()


@pytest.mark.asyncio
async def test_packing_identical_replay_and_ceiling(client: AsyncClient):
    h = await _login(client)
    jid = await _create_job(client, h, "SO-DI-PACK", qty="100")
    await _seed_helper_verified(jid, "40")

    over = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "41",
            "idempotency_key": "di-pack-over",
        },
    )
    assert over.status_code == 409

    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "25",
            "idempotency_key": "di-pack-ok-25",
        },
    )
    assert ok.status_code == 200, ok.text
    eid = ok.json()["id"]

    replay = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "25",
            "idempotency_key": "di-pack-ok-25",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == eid

    mismatch = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "di-pack-ok-25",
        },
    )
    assert mismatch.status_code == 409

    async with get_session_factory()() as s:
        packed_sum = await s.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "packing_batch",
                ProductionEvent.so_line_id == "L1",
            )
        )
    assert Decimal(packed_sum or 0) == Decimal("25")


@pytest.mark.strict_loading_cap
@pytest.mark.asyncio
async def test_loading_pod_qty_chain_partial_multi_sj(client: AsyncClient):
    h = await _login(client)
    jid = await _create_job(client, h, "SO-DI", qty="100")
    await _seed_helper_verified(jid, "80")
    pack = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "70",
            "idempotency_key": "di-chain-pack-70",
        },
    )
    assert pack.status_code == 200, pack.text

    # POD before loading rejected
    early_ids = await upload_pod_bundle(client, jid, "SJ-DI", headers=h)
    early = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "1", "di-pod-early", early_ids),
    )
    assert early.status_code == 409

    # Over packing-cap loading rejected
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-DI",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="71",
            idempotency_key="di-load-over",
        ),
    )
    assert over.status_code == 409

    load_a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-DI",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="50",
            idempotency_key="di-load-a-50",
        ),
    )
    assert load_a.status_code == 200, load_a.text
    load_a_id = load_a.json()["id"]

    # Identical loading replay
    load_replay = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-DI",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="50",
            idempotency_key="di-load-a-50",
        ),
    )
    assert load_replay.status_code == 200
    assert load_replay.json()["id"] == load_a_id

    # Multi-SJ partial on second SJ
    load_b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-DI-B",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="20",
            idempotency_key="di-load-b-20",
        ),
    )
    assert load_b.status_code == 200, load_b.text

    # Partial POD SJ-DI
    ids = await upload_pod_bundle(client, jid, "SJ-DI", headers=h)
    pod1 = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "30", "di-pod-part-30", ids),
    )
    assert pod1.status_code == 200, pod1.text
    pod1_id = pod1.json()["id"]

    # Identical POD replay
    pod_replay = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "30", "di-pod-part-30", ids),
    )
    assert pod_replay.status_code == 200
    assert pod_replay.json()["id"] == pod1_id

    # Over remaining POD
    ids2 = await upload_pod_bundle(client, jid, "SJ-DI", headers=h)
    pod_over = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "21", "di-pod-over", ids2),
    )
    assert pod_over.status_code == 409

    # Rest of SJ-DI
    ids3 = await upload_pod_bundle(client, jid, "SJ-DI", headers=h)
    pod_rest = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ-DI", "20", "di-pod-rest-20", ids3),
    )
    assert pod_rest.status_code == 200, pod_rest.text

    async with get_session_factory()() as s:
        verified = await s.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "output_helper_verified",
            )
        )
        packed = await s.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "packing_batch",
            )
        )
        loaded = await s.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "loading",
            )
        )
        delivered = await s.scalar(
            select(func.coalesce(func.sum(ProductionEvent.qty_physical), 0)).where(
                ProductionEvent.job_id == jid,
                ProductionEvent.event_type == "pod",
            )
        )
    assert Decimal(delivered or 0) <= Decimal(loaded or 0) <= Decimal(packed or 0) <= Decimal(
        verified or 0
    )
    assert Decimal(delivered or 0) == Decimal("50")
    assert Decimal(loaded or 0) == Decimal("70")
    assert Decimal(packed or 0) == Decimal("70")


@pytest.mark.asyncio
async def test_permission_negative_packing_and_loading(client: AsyncClient):
    h_lead = await _login(client)
    jid = await _create_job(client, h_lead, "SO-DI-PERM")
    await _seed_helper_verified(jid, "10")

    h_no = await _login(client, "di.noperm")
    packed = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h_no,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "di-noperm-pack",
        },
    )
    assert packed.status_code == 403

    h_br = await _login(client, "di.wrongbr")
    packed_br = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h_br,
        json={
            "so_line_id": "L1",
            "qty_physical": "1",
            "idempotency_key": "di-wrongbr-pack",
        },
    )
    assert packed_br.status_code == 403

    loaded = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h_no,
        json=loading_body(
            accurate_sj_id="SJ-DI",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="1",
            idempotency_key="di-noperm-load",
        ),
    )
    assert loaded.status_code == 403
