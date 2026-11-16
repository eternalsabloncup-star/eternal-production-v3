"""P0 multi-SJ × SJ-line × SO-line Loading regressions (isolated test DB only)."""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from tests.db_url_guard import (
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)
from tests.production.sj_line_helpers import loading_body, sj_line_item

_async_url, _sync_url = resolve_test_database_urls()
assert is_test_database_url(_async_url)
assert is_test_database_url(_sync_url)
assert database_name(_async_url).endswith("_test")
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
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.OUTPUT_HELPER_VERIFY,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
]
RETURN_REQUEST_PERMS = [
    P.JOB_READ,
    P.DELIVERY_LOADING_RETURN_REQUEST,
]
RETURN_APPROVE_PERMS = [
    P.JOB_READ,
    P.DELIVERY_LOADING_RETURN_APPROVE,
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
                username="msj.lead",
                display_name="MSJ Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="msj.other",
                display_name="Other",
                role="ops",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="return.req",
                display_name="Return Requester",
                role="helper",
                password_hash=hash_password("secret-pass"),
                permissions=RETURN_REQUEST_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="return.appr",
                display_name="Return Approver",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=RETURN_APPROVE_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="return.wrongbr",
                display_name="Wrong Branch Approver",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=RETURN_APPROVE_PERMS,
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        await session.commit()

    # Default SJ catalog — tests may override via monkeypatch.
    catalog: dict[str, list] = {
        "SJ1": [
            sj_line_item(
                accurate_sj_line_id="SL1", so_line_id="L1", quantity=4000, sku="CUP"
            )
        ],
        "SJ2": [
            sj_line_item(
                accurate_sj_line_id="SL2", so_line_id="L1", quantity=6000, sku="CUP"
            )
        ],
        "SJ-MULTI": [
            sj_line_item(
                accurate_sj_line_id="SL-A", so_line_id="L1", quantity=100, sku="CUP-A"
            ),
            sj_line_item(
                accurate_sj_line_id="SL-B", so_line_id="L2", quantity=100, sku="CUP-A"
            ),
        ],
        "SJ-RATIO": [
            sj_line_item(
                accurate_sj_line_id="SL-R",
                so_line_id="L1",
                quantity=10,
                unit_ratio=100,
            )
        ],
        "SJ-BAD": [
            sj_line_item(
                accurate_sj_line_id="SL-BAD",
                so_line_id="L1",
                quantity=50,
                loading_eligible=False,
            )
        ],
        "SJ-CANCELLED": [],
        "SJ-5K": [
            sj_line_item(
                accurate_sj_line_id="SL-5K",
                so_line_id="L1",
                quantity=5000,
                sku="CUP",
            )
        ],
    }

    async def _valid_sj(**kwargs):
        sj = kwargs["accurate_sj_id"]
        if sj == "SJ-CANCELLED":
            from fastapi import HTTPException

            raise HTTPException(409, "Surat Jalan Accurate tidak aktif")
        if sj == "SJ-WRONG-SO":
            from fastapi import HTTPException

            raise HTTPException(
                409, "Surat Jalan Accurate tidak cocok dengan Sales Order job"
            )
        if sj == "SJ-WRONG-BRANCH":
            from fastapi import HTTPException

            raise HTTPException(
                409, "Surat Jalan Accurate tidak cocok dengan cabang job"
            )
        lines = catalog.get(sj)
        if lines is None:
            from fastapi import HTTPException

            raise HTTPException(409, "Surat Jalan Accurate tidak ditemukan — loading ditolak")
        return {
            "verified": True,
            "mode": "gateway",
            "accurate_sj_id": sj,
            "accurate_sj_number": kwargs["accurate_sj_number"],
            "sales_order_number": kwargs.get("expected_so_number") or "SO-MSJ",
            "branch_id": "branch-a",
            "line_items": lines,
            "loading_eligible": bool(lines)
            and all(x.get("loading_eligible") is True for x in lines),
            "live_verified": False,
        }

    monkeypatch.setattr(
        "app.services.accurate_evidence.require_valid_sj", _valid_sj
    )
    # Expose catalog for tests that mutate lines.
    client_box = {"catalog": catalog}

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._msj = client_box  # type: ignore[attr-defined]
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _login(client: AsyncClient, user: str = "msj.lead") -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "secret-pass"},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_packed(
    client: AsyncClient,
    h: dict,
    *,
    so: str = "SO-MSJ",
    lines: list[tuple[str, str]],
    synced: bool = False,
) -> int:
    """Create job through design/payment/schedule/sample/output/packing.

    Lines are always classified print so packing and loading have an official identity.
    """
    del synced
    body = {
        "accurate_so_number": so,
        "branch_id": "branch-a",
        "line_items": [
            {"accurate_line_id": lid, "quantity": qty, "production_process": "print"}
            for lid, qty in lines
        ],
    }
    job = await client.post("/api/v1/production/jobs", headers=h, json=body)
    assert job.status_code == 200, job.text
    jid = job.json()["id"]

    d = await client.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        headers=h,
        json={"file_name": "a.pdf", "storage_key": f"d-{jid}"},
    )
    assert d.status_code == 200, d.text
    dec = await client.post(
        f"/api/v1/production/jobs/design/versions/{d.json()['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    assert dec.status_code == 200, dec.text
    pay = await client.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        headers=h,
        json={"reason": "msj test bypass"},
    )
    assert pay.status_code == 200, pay.text

    for so_line, qty in lines:
        asg = await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": so_line,
                "color_pass": 1,
                "operator_name": "Op",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": qty,
            },
        )
        assert asg.status_code == 200, asg.text
        aid = asg.json()["id"]
        scr = await client.post(
            f"/api/v1/production/jobs/{jid}/prep/screener",
            headers=h,
            json={
                "so_line_id": so_line,
                "qty": "1",
                "po_qty": qty,
                "screen_size": "kecil",
                "evidence_ref": "scr",
                "idempotency_key": f"scr-{jid}-{so_line}",
                "assignment_id": aid,
            },
        )
        assert scr.status_code == 200, scr.text
        helper = await client.post(
            f"/api/v1/production/jobs/{jid}/prep/helper",
            headers=h,
            json={
                "so_line_id": so_line,
                "qty": qty,
                "po_qty": qty,
                "evidence_ref": "help",
                "idempotency_key": f"help-{jid}-{so_line}",
                "assignment_id": aid,
            },
        )
        assert helper.status_code == 200, helper.text
        sample = await client.post(
            f"/api/v1/production/jobs/{jid}/samples",
            headers=h,
            json={
                "file_name": "s.jpg",
                "storage_key": f"s-{jid}-{so_line}",
                "assignment_id": aid,
            },
        )
        assert sample.status_code == 200, sample.text
        sok = await client.post(
            f"/api/v1/production/jobs/samples/{sample.json()['id']}/decision",
            headers=h,
            json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
        )
        assert sok.status_code == 200, sok.text
        out = await client.post(
            f"/api/v1/production/jobs/{jid}/outputs",
            headers=h,
            json={
                "assignment_id": aid,
                "qty_physical": qty,
                "color_pass": 1,
                "idempotency_key": f"out-{jid}-{so_line}",
            },
        )
        assert out.status_code == 200, out.text
        from tests.production.helper_verify_helpers import helper_verify_output

        await helper_verify_output(
            client,
            jid,
            out.json()["id"],
            qty,
            headers=h,
            idem=f"hv-{jid}-{so_line}",
        )
        pack = await client.post(
            f"/api/v1/production/jobs/{jid}/packing",
            headers=h,
            json={
                "so_line_id": so_line,
                "qty_physical": qty,
                "idempotency_key": f"pack-{jid}-{so_line}",
            },
        )
        assert pack.status_code == 200, pack.text
    return jid


@pytest.mark.asyncio
async def test_01_single_sj(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="msj-01-single",
        ),
    )
    assert r.status_code == 200, r.text
    assert r.json()["accurate_sj_line_id"] == "SL1"
    assert r.json()["so_line_id"] == "L1"


@pytest.mark.asyncio
async def test_02_03_two_sj_one_so_line_caps(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10000")])
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="4000",
            idempotency_key="msj-02a-sj1",
        ),
    )
    assert a.status_code == 200, a.text
    b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ2",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="6000",
            idempotency_key="msj-02b-sj2",
        ),
    )
    assert b.status_code == 200, b.text
    # SJ1 cap exceeded
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="1",
            idempotency_key="msj-02c-over",
        ),
    )
    assert over.status_code == 409


@pytest.mark.asyncio
async def test_04_partial_and_05_sj_overload(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "5000")])
    p = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="1000",
            idempotency_key="msj-04-partial",
        ),
    )
    assert p.status_code == 200
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="3001",
            idempotency_key="msj-05-overload",
        ),
    )
    assert over.status_code == 409


@pytest.mark.asyncio
@pytest.mark.strict_loading_cap
async def test_06_loading_capped_by_packing_even_when_sj_allows_more(client: AsyncClient):
    """Owner decision: Loading <= packing-verified qty, even if the SJ line allows more."""
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100"), ("L2", "500")], synced=True)
    client._msj["catalog"]["SJ1"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="SL1", so_line_id="L1", quantity=1000)
    ]
    body = dict(accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1")
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading", headers=h,
        json=loading_body(qty_physical="200", idempotency_key="msj-06-over-cap", **body),
    )
    assert over.status_code == 409 and "packing sah" in over.text
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/loading", headers=h,
        json=loading_body(qty_physical="100", idempotency_key="msj-06-at-cap1", **body),
    )
    assert ok.status_code == 200, ok.text
    auth = await client.get(
        f"/api/v1/production/jobs/{jid}/loading-authority", headers=h,
        params={"accurate_sj_id": "SJ1", "accurate_sj_number": "SJ1", "accurate_sj_line_id": "SL1", "so_line_id": "L1"},
    )
    assert auth.json()["packed_qty"] == "100" and auth.json()["loading_available"] == "0"


@pytest.mark.asyncio
async def test_multi_line_same_sku_distinct_so_lines(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100"), ("L2", "100")])
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-A",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="msj-ml-a",
        ),
    )
    assert a.status_code == 200, a.text
    b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-B",
            so_line_id="L2",
            qty_physical="100",
            idempotency_key="msj-ml-b",
        ),
    )
    assert b.status_code == 200, b.text
    # Wrong mapping SL-A → L2
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-A",
            so_line_id="L2",
            qty_physical="1",
            idempotency_key="msj-ml-bad",
        ),
    )
    assert bad.status_code == 409


@pytest.mark.asyncio
async def test_unit_ratio_base_conversion(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "1000")])
    # quantity 10 * ratio 100 = 1000 base
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-RATIO",
            accurate_sj_line_id="SL-R",
            so_line_id="L1",
            qty_physical="1000",
            idempotency_key="msj-ratio-ok",
        ),
    )
    assert ok.status_code == 200, ok.text
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-RATIO",
            accurate_sj_line_id="SL-R",
            so_line_id="L1",
            qty_physical="1",
            idempotency_key="msj-ratio-over",
        ),
    )
    assert over.status_code == 409


@pytest.mark.asyncio
async def test_null_conflicting_and_ineligible(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "50")])
    missing = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json={
            "accurate_sj_id": "SJ1",
            "accurate_sj_number": "SJ1",
            "qty_physical": "10",
            "idempotency_key": "msj-null-ids",
        },
    )
    assert missing.status_code == 422
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-BAD",
            accurate_sj_line_id="SL-BAD",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-ineligible",
        ),
    )
    assert bad.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_idempotency(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    body = loading_body(
        accurate_sj_id="SJ1",
        accurate_sj_line_id="SL1",
        so_line_id="L1",
        qty_physical="40",
        idempotency_key="msj-dup-key1",
    )
    a = await client.post(f"/api/v1/production/jobs/{jid}/loading", headers=h, json=body)
    b = await client.post(f"/api/v1/production/jobs/{jid}/loading", headers=h, json=body)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]


@pytest.mark.asyncio
async def test_concurrent_over_remaining(client: AsyncClient):
    """Concurrent Loading capped by SJ line (4000), not Packing."""
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])

    async def _one(key: str):
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading",
            headers=h,
            json=loading_body(
                accurate_sj_id="SJ1",
                accurate_sj_line_id="SL1",
                so_line_id="L1",
                qty_physical="2500",
                idempotency_key=key,
            ),
        )

    r1, r2 = await asyncio.gather(_one("msj-conc-one"), _one("msj-conc-two"))
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409], (r1.status_code, r1.text, r2.status_code, r2.text)


@pytest.mark.asyncio
async def test_wrong_branch_document_cancelled(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "50")])
    wrong_so = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-WRONG-SO",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-wrong-so",
        ),
    )
    assert wrong_so.status_code == 409
    cancelled = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-CANCELLED",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-cancelled",
        ),
    )
    assert cancelled.status_code == 409
    other = await _login(client, "msj.other")
    denied = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=other,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-wrong-branch",
        ),
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_legacy_null_line_blocks_new_loading(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="loading",
                qty_physical=Decimal("10"),
                accurate_sj_id="SJ1",
                accurate_sj_number="SJ1",
                accurate_sj_line_id=None,
                so_line_id=None,
                idempotency_key="legacy-null-load",
                actor_user_id=1,
            )
        )
        await session.commit()
    blocked = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-legacy-block",
        ),
    )
    assert blocked.status_code == 409
    assert "legacy" in blocked.text.lower() or "baris" in blocked.text.lower()


@pytest.mark.asyncio
async def test_07_sj1_pod_sj2_pending_and_pod_guards(client: AsyncClient):
    from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle

    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10000")])
    await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="4000",
            idempotency_key="msj-pod-l1",
        ),
    )
    # POD without loading on SJ2
    ids = await upload_pod_bundle(client, jid, "SJ2", headers=h)
    no = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ2", "10", "pod-sj2-early", ids),
    )
    assert no.status_code == 409
    # Partial POD SJ1 + four attachments
    p1 = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ1", "1000", "pod-sj1-part", p1),
    )
    assert ok.status_code == 200, ok.text
    # SJ2 still loadable
    l2 = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ2",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="1000",
            idempotency_key="msj-pod-l2",
        ),
    )
    assert l2.status_code == 200, l2.text


@pytest.mark.asyncio
async def test_cancel_blocks_new_loading(client: AsyncClient):
    """Cancel before Loading succeeds; cancelled SJ cannot load."""
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/sj/cancel",
        headers=h,
        json={
            "accurate_sj_id": "SJ1",
            "reason": "supersede",
            "idempotency_key": "msj-cancel-before-load",
        },
    )
    assert cancel.status_code == 200, cancel.text
    again = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-after-cancel",
        ),
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_cancel_rejected_when_unreversed_loading(client: AsyncClient):
    """SJ cancel stays separate — blocked while net Loading > 0."""
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="40",
            idempotency_key="msj-cancel-load40",
        ),
    )
    assert load.status_code == 200, load.text
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/sj/cancel",
        headers=h,
        json={
            "accurate_sj_id": "SJ1",
            "reason": "attempt SJ cancel while loaded",
            "idempotency_key": "msj-cancel-after-load",
        },
    )
    assert cancel.status_code == 409
    # SJ2 has its own SJ-line authority — Packing is not a cross-SJ hard cap.
    ok_sj2 = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ2",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="msj-sj2-independent-cap",
        ),
    )
    assert ok_sj2.status_code == 200, ok_sj2.text


@pytest.mark.asyncio
async def test_historical_sj_cancelled_blocks_that_sj_only(client: AsyncClient):
    """Document-cancelled SJ blocks that SJ; other SJ uses own line cap."""
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="loading",
                qty_physical=Decimal("40"),
                accurate_sj_id="SJ1",
                accurate_sj_number="SJ1",
                accurate_sj_line_id="SL1",
                so_line_id="L1",
                idempotency_key="hist-cancel-load40",
                actor_user_id=1,
            )
        )
        session.add(
            ProductionEvent(
                job_id=jid,
                event_type="sj_cancelled",
                qty_physical=Decimal("0"),
                accurate_sj_id="SJ1",
                idempotency_key="hist-cancel-sj1",
                actor_user_id=1,
                reason="legacy cancel already recorded",
            )
        )
        await session.commit()
    blocked = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-hist-sj1-blocked",
        ),
    )
    assert blocked.status_code == 409
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ2",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="msj-hist-sj2-ok",
        ),
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_cancel_after_pod_rejected(client: AsyncClient):
    from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle

    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="40",
            idempotency_key="msj-pod-then-cancel-load",
        ),
    )
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ1", "40", "msj-pod-then-cancel", ids),
    )
    assert pod.status_code == 200, pod.text
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/sj/cancel",
        headers=h,
        json={
            "accurate_sj_id": "SJ1",
            "reason": "after pod",
            "idempotency_key": "msj-cancel-after-pod",
        },
    )
    assert cancel.status_code == 409
    # Cancelled? No — still active for history; new POD blocked only when cancelled.
    # Historical POD remains; further POD beyond loaded remaining fails.
    ids2 = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    over_pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ1", "1", "msj-pod-over-remaining", ids2),
    )
    assert over_pod.status_code == 409


@pytest.mark.asyncio
async def test_idempotency_payload_mismatch(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    key = "msj-idem-payload-key"
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="40",
            idempotency_key=key,
        ),
    )
    assert a.status_code == 200, a.text
    same = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="40",
            idempotency_key=key,
        ),
    )
    assert same.status_code == 200
    assert same.json()["id"] == a.json()["id"]
    diff_qty = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="41",
            idempotency_key=key,
        ),
    )
    assert diff_qty.status_code == 409
    diff_line = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ2",
            accurate_sj_line_id="SL2",
            so_line_id="L1",
            qty_physical="40",
            idempotency_key=key,
        ),
    )
    assert diff_line.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_cancel_vs_loading(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])

    async def _load():
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading",
            headers=h,
            json=loading_body(
                accurate_sj_id="SJ1",
                accurate_sj_line_id="SL1",
                so_line_id="L1",
                qty_physical="40",
                idempotency_key="msj-race-load",
            ),
        )

    async def _cancel():
        return await client.post(
            f"/api/v1/production/jobs/{jid}/sj/cancel",
            headers=h,
            json={
                "accurate_sj_id": "SJ1",
                "reason": "race",
                "idempotency_key": "msj-race-cancel",
            },
        )

    r_load, r_cancel = await asyncio.gather(_load(), _cancel())
    codes = {r_load.status_code, r_cancel.status_code}
    # Exactly one succeeds path-consistent: either load then cancel-409,
    # or cancel then load-409. Never both 200.
    assert 200 in codes
    assert 409 in codes
    assert codes == {200, 409}, (r_load.status_code, r_load.text, r_cancel.status_code, r_cancel.text)


@pytest.mark.asyncio
async def test_fractional_and_incompatible_uom(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "100")])
    frac = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10.5",
            idempotency_key="msj-frac-pcs",
        ),
    )
    assert frac.status_code == 409
    # Mutate catalog to BOX uom
    client._msj["catalog"]["SJ1"] = [  # type: ignore[attr-defined]
        sj_line_item(
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            quantity=4000,
            sku="CUP",
        )
    ]
    client._msj["catalog"]["SJ1"][0]["uom"] = "BOX"  # type: ignore[attr-defined]
    box = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-box-uom",
        ),
    )
    assert box.status_code == 409
    # Invalid ratio
    client._msj["catalog"]["SJ1"][0]["uom"] = "PCS"  # type: ignore[attr-defined]
    client._msj["catalog"]["SJ1"][0]["unit_ratio"] = 0  # type: ignore[attr-defined]
    client._msj["catalog"]["SJ1"][0]["loading_eligible"] = True  # type: ignore[attr-defined]
    bad_ratio = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="msj-bad-ratio",
        ),
    )
    assert bad_ratio.status_code == 409


@pytest.mark.asyncio
async def test_multicolor_packing_still_min_pass(client: AsyncClient):
    """Multicolor packing regression: packing still min(pass nets); loading uses packed."""
    h = await _login(client)
    job = await client.post(
        "/api/v1/production/jobs",
        headers=h,
        json={
            "accurate_so_number": "SO-MSJ-MC",
            "branch_id": "branch-a",
            "line_items": [
                {
                    "accurate_line_id": "L1",
                    "quantity": "100",
                    "production_process": "print",
                }
            ],
        },
    )
    jid = job.json()["id"]
    d = await client.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        headers=h,
        json={"file_name": "a.pdf", "storage_key": "mc-design-key"},
    )
    await client.post(
        f"/api/v1/production/jobs/design/versions/{d.json()['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    await client.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        headers=h,
        json={"reason": "mc"},
    )
    a1 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "L1",
                "color_pass": 1,
                "operator_name": "Op",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "100",
            },
        )
    ).json()
    a2 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "L1",
                "color_pass": 2,
                "operator_name": "Op2",
                "machine_name": "M2",
                "work_date": str(date.today()),
                "qty_planned": "100",
            },
        )
    ).json()
    for asg, key in ((a1, "mc-screen-one"), (a2, "mc-screen-two")):
        await client.post(
            f"/api/v1/production/jobs/{jid}/prep/screener",
            headers=h,
            json={
                "so_line_id": "L1",
                "qty": "1",
                "po_qty": "100",
                "screen_size": "kecil",
                "evidence_ref": "s",
                "idempotency_key": key,
                "assignment_id": asg["id"],
            },
        )
    await client.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty": "100",
            "po_qty": "100",
            "evidence_ref": "h",
            "idempotency_key": "mc-helper-key",
            "assignment_id": a1["id"],
        },
    )
    sample = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/samples",
            headers=h,
            json={
                "file_name": "s.jpg",
                "storage_key": "mc-sample-key",
                "assignment_id": a1["id"],
            },
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/samples/{sample['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "test setup bypass"},
    )
    o1 = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": a1["id"],
            "qty_physical": "100",
            "color_pass": 1,
            "idempotency_key": "mc-output-one",
        },
    )
    o2 = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": a2["id"],
            "qty_physical": "80",
            "color_pass": 2,
            "idempotency_key": "mc-output-two",
        },
    )
    from tests.production.helper_verify_helpers import helper_verify_output

    await helper_verify_output(
        client, jid, o1.json()["id"], "100", headers=h, idem="hv-mc-1"
    )
    await helper_verify_output(
        client, jid, o2.json()["id"], "80", headers=h, idem="hv-mc-2"
    )
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "81",
            "idempotency_key": "mc-pack-overflow",
        },
    )
    assert over.status_code == 409
    pack = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "L1",
            "qty_physical": "80",
            "idempotency_key": "mc-pack-ok80",
        },
    )
    assert pack.status_code == 200
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="80",
            idempotency_key="mc-load-ok80",
        ),
    )
    assert load.status_code == 200, load.text


@pytest.mark.asyncio
async def test_owner_sj_authority_partial_and_cancel_loading(client: AsyncClient):
    """SJ 5000 → load 2000+1000; cancel second 1000 → remaining capacity 3000."""
    h = await _login(client)
    # Packing deliberately low — must NOT hard-cap Loading.
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="2000",
            idempotency_key="own-load-2000",
        ),
    )
    assert a.status_code == 200, a.text
    b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="1000",
            idempotency_key="own-load-1000",
        ),
    )
    assert b.status_code == 200, b.text
    eid = b.json()["id"]
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "1000",
            "reason": "wrong confirmation",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-cancel-1000",
        },
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["event_type"] == "loading_cancelled"
    # Remaining SJ capacity = 5000 - 2000 = 3000
    again = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="3000",
            idempotency_key="own-reload-3000",
        ),
    )
    assert again.status_code == 200, again.text
    over = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="1",
            idempotency_key="own-over-sj",
        ),
    )
    assert over.status_code == 409


@pytest.mark.asyncio
async def test_owner_partial_cancel_and_over_cancel(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="1000",
            idempotency_key="own-partial-src",
        ),
    )
    eid = load.json()["id"]
    part = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "500",
            "reason": "partial wrong qty",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-partial-500",
        },
    )
    assert part.status_code == 200, part.text
    too_much = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "600",
            "reason": "over remaining",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-over-cancel",
        },
    )
    assert too_much.status_code == 409
    # Duplicate same cancel key idempotent
    dup = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "500",
            "reason": "partial wrong qty",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-partial-500",
        },
    )
    assert dup.status_code == 200
    assert dup.json()["id"] == part.json()["id"]
    # Different qty same key → 409
    mismatch = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "400",
            "reason": "partial wrong qty",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-partial-500",
        },
    )
    assert mismatch.status_code == 409


@pytest.mark.asyncio
async def test_owner_packing_below_loading_allowed(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "5")])
    r = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="own-pack-below-load",
        ),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_owner_cancel_after_pod_protects_delivered(client: AsyncClient):
    from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle

    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="own-pod-load",
        ),
    )
    eid = load.json()["id"]
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ1", "60", "own-pod-60", ids),
    )
    assert pod.status_code == 200, pod.text
    # Cancelling 50 leaves net 50 < pod 60 → reject
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "50",
            "reason": "too much vs pod",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-cancel-vs-pod",
        },
    )
    assert bad.status_code == 409
    # Cancelling 40 leaves net 60 == pod → ok
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h,
        json={
            "qty_physical": "40",
            "reason": "undelivered remainder",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "own-cancel-ok-vs-pod",
        },
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_physical_return_dual_approval_flow(client: AsyncClient):
    from tests.production.pod_attach_helpers import PNG_1X1

    h_lead = await _login(client)
    jid = await _seed_packed(client, h_lead, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h_lead,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="20",
            idempotency_key="own-ret-src",
        ),
    )
    eid = load.json()["id"]
    # Direct physical_return cancel path removed
    direct = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
        headers=h_lead,
        json={
            "qty_physical": "5",
            "reason": "goods back",
            "cancel_kind": "physical_return",
            "idempotency_key": "own-ret-direct",
        },
    )
    assert direct.status_code == 422

    h_req = await _login(client, "return.req")
    h_appr = await _login(client, "return.appr")
    missing = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
        headers=h_req,
        json={
            "qty_physical": "5",
            "reason": "goods back",
            "idempotency_key": "own-ret-no-photo",
            "evidence_attachment_id": 999999,
        },
    )
    assert missing.status_code == 404
    up = await client.post(
        f"/api/v1/production/jobs/{jid}/attachments",
        headers=h_req,
        data={"accurate_sj_id": "SJ1", "purpose": "loading_return_photo"},
        files={"file": ("ret.png", PNG_1X1, "image/png")},
    )
    assert up.status_code == 200, up.text
    aid = up.json()["id"]
    req = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
        headers=h_req,
        json={
            "qty_physical": "5",
            "reason": "goods back",
            "idempotency_key": "own-ret-req",
            "evidence_attachment_id": aid,
        },
    )
    assert req.status_code == 200, req.text
    assert req.json()["event_type"] == "loading_return_requested"
    rid = req.json()["id"]
    # Request does not release capacity — cannot load beyond remaining SJ until approve
    # Same-user approve forbidden
    same = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
        headers=h_req,
        json={"idempotency_key": "own-ret-same-user"},
    )
    assert same.status_code in (403, 409)
    # Wrong branch approver
    h_wrong = await _login(client, "return.wrongbr")
    wrong = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
        headers=h_wrong,
        json={"idempotency_key": "own-ret-wrongbr"},
    )
    assert wrong.status_code == 403
    ok = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
        headers=h_appr,
        json={"idempotency_key": "own-ret-approve", "reason": "received"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["event_type"] == "loading_cancelled"
    payload = ok.json().get("payload_json") or ""
    assert "physical_return" in payload
    # Duplicate approve rejected
    dup = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
        headers=h_appr,
        json={"idempotency_key": "own-ret-approve-2"},
    )
    assert dup.status_code == 409
    # Idempotent replay same key
    replay = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
        headers=h_appr,
        json={"idempotency_key": "own-ret-approve", "reason": "received"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == ok.json()["id"]


@pytest.mark.asyncio
async def test_owner_concurrent_loading_and_cancel(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-5K",
            accurate_sj_line_id="SL-5K",
            so_line_id="L1",
            qty_physical="4000",
            idempotency_key="own-race-src",
        ),
    )
    eid = load.json()["id"]

    async def _more():
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading",
            headers=h,
            json=loading_body(
                accurate_sj_id="SJ-5K",
                accurate_sj_line_id="SL-5K",
                so_line_id="L1",
                qty_physical="1500",
                idempotency_key="own-race-load",
            ),
        )

    async def _cancel():
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
            headers=h,
            json={
                "qty_physical": "1000",
                "reason": "race cancel",
                "cancel_kind": "confirmation_cancel",
                "idempotency_key": "own-race-cancel",
            },
        )

    r_load, r_cancel = await asyncio.gather(_more(), _cancel())
    # Cancel should succeed; additional load may succeed (after cancel frees 1000)
    # or fail if load ran first against remaining 1000 with qty 1500.
    assert r_cancel.status_code == 200, r_cancel.text
    assert r_load.status_code in (200, 409), r_load.text


@pytest.mark.asyncio
async def test_hardening_double_cancel_distinct_keys(client: AsyncClient):
    """Different idempotency keys cannot cancel the same remaining qty twice."""
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="hard-dbl-src",
        ),
    )
    eid = load.json()["id"]

    async def _cancel(key: str):
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading/{eid}/cancel",
            headers=h,
            json={
                "qty_physical": "100",
                "reason": "full cancel race",
                "cancel_kind": "confirmation_cancel",
                "idempotency_key": key,
            },
        )

    a, b = await asyncio.gather(_cancel("hard-dbl-a"), _cancel("hard-dbl-b"))
    codes = sorted([a.status_code, b.status_code])
    assert codes == [200, 409], (a.status_code, a.text, b.status_code, b.text)


@pytest.mark.asyncio
async def test_hardening_cancel_one_line_does_not_free_other(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10"), ("L2", "10")])
    a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-A",
            so_line_id="L1",
            qty_physical="80",
            idempotency_key="hard-line-a",
        ),
    )
    b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-B",
            so_line_id="L2",
            qty_physical="80",
            idempotency_key="hard-line-b",
        ),
    )
    assert a.status_code == 200 and b.status_code == 200
    cancel_a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{a.json()['id']}/cancel",
        headers=h,
        json={
            "qty_physical": "80",
            "reason": "cancel line A only",
            "cancel_kind": "confirmation_cancel",
            "idempotency_key": "hard-cancel-a",
        },
    )
    assert cancel_a.status_code == 200
    # Line B still at 80/100 — cannot load 30 more on B
    over_b = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-B",
            so_line_id="L2",
            qty_physical="30",
            idempotency_key="hard-over-b",
        ),
    )
    assert over_b.status_code == 409
    # Line A freed — can load again up to 100
    reload_a = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-MULTI",
            accurate_sj_line_id="SL-A",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="hard-reload-a",
        ),
    )
    assert reload_a.status_code == 200, reload_a.text


@pytest.mark.asyncio
async def test_hardening_invalid_return_attachment_rejected(client: AsyncClient):
    from tests.production.pod_attach_helpers import PNG_1X1

    h = await _login(client)
    h_req = await _login(client, "return.req")
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="20",
            idempotency_key="hard-bad-att-src",
        ),
    )
    eid = load.json()["id"]
    pod_up = await client.post(
        f"/api/v1/production/jobs/{jid}/attachments",
        headers=h,
        data={"accurate_sj_id": "SJ1", "purpose": "pod_photo_1"},
        files={"file": ("p.png", PNG_1X1, "image/png")},
    )
    assert pod_up.status_code == 200
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
        headers=h_req,
        json={
            "qty_physical": "5",
            "reason": "goods back",
            "evidence_attachment_id": pod_up.json()["id"],
            "idempotency_key": "hard-bad-pod-purpose",
        },
    )
    assert bad.status_code == 409


@pytest.mark.asyncio
async def test_physical_return_reject_and_concurrent_approve(client: AsyncClient):
    from tests.production.pod_attach_helpers import PNG_1X1

    h = await _login(client)
    h_req = await _login(client, "return.req")
    h_appr = await _login(client, "return.appr")
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="50",
            idempotency_key="ret-rej-src",
        ),
    )
    eid = load.json()["id"]

    async def _upload_and_request(key: str, qty: str):
        up = await client.post(
            f"/api/v1/production/jobs/{jid}/attachments",
            headers=h_req,
            data={"accurate_sj_id": "SJ1", "purpose": "loading_return_photo"},
            files={"file": (f"{key}.png", PNG_1X1, "image/png")},
        )
        assert up.status_code == 200, up.text
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
            headers=h_req,
            json={
                "qty_physical": qty,
                "reason": "return",
                "evidence_attachment_id": up.json()["id"],
                "idempotency_key": key,
            },
        )

    r1 = await _upload_and_request("ret-req-reject", "10")
    assert r1.status_code == 200, r1.text
    rej = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{r1.json()['id']}/reject",
        headers=h_appr,
        json={"idempotency_key": "ret-rej-dec", "reason": "not received"},
    )
    assert rej.status_code == 200, rej.text
    assert rej.json()["event_type"] == "loading_return_rejected"
    # Cannot approve after reject
    after = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{r1.json()['id']}/approve",
        headers=h_appr,
        json={"idempotency_key": "ret-rej-then-appr"},
    )
    assert after.status_code == 409

    # Concurrent approve of two requests that together exceed remaining
    a = await _upload_and_request("ret-conc-a", "40")
    b = await _upload_and_request("ret-conc-b", "40")
    assert a.status_code == 200 and b.status_code == 200

    async def _approve(rid: int, key: str):
        return await client.post(
            f"/api/v1/production/jobs/{jid}/loading/return-requests/{rid}/approve",
            headers=h_appr,
            json={"idempotency_key": key, "reason": "ok"},
        )

    x, y = await asyncio.gather(
        _approve(a.json()["id"], "ret-conc-appr-a"),
        _approve(b.json()["id"], "ret-conc-appr-b"),
    )
    codes = sorted([x.status_code, y.status_code])
    assert codes == [200, 409], (x.status_code, x.text, y.status_code, y.text)


@pytest.mark.asyncio
async def test_physical_return_pod_guard(client: AsyncClient):
    from tests.production.pod_attach_helpers import PNG_1X1, pod_body, upload_pod_bundle

    h = await _login(client)
    h_req = await _login(client, "return.req")
    h_appr = await _login(client, "return.appr")
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="100",
            idempotency_key="ret-pod-src",
        ),
    )
    eid = load.json()["id"]
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json=pod_body("SJ1", "70", "ret-pod-70", ids),
    )
    assert pod.status_code == 200, pod.text
    up = await client.post(
        f"/api/v1/production/jobs/{jid}/attachments",
        headers=h_req,
        data={"accurate_sj_id": "SJ1", "purpose": "loading_return_photo"},
        files={"file": ("r.png", PNG_1X1, "image/png")},
    )
    # Request 40 would leave net 60 < pod 70 → reject at request
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
        headers=h_req,
        json={
            "qty_physical": "40",
            "reason": "too much vs pod",
            "evidence_attachment_id": up.json()["id"],
            "idempotency_key": "ret-pod-bad",
        },
    )
    assert bad.status_code == 409
    up2 = await client.post(
        f"/api/v1/production/jobs/{jid}/attachments",
        headers=h_req,
        data={"accurate_sj_id": "SJ1", "purpose": "loading_return_photo"},
        files={"file": ("r2.png", PNG_1X1, "image/png")},
    )
    ok_req = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/{eid}/return-requests",
        headers=h_req,
        json={
            "qty_physical": "30",
            "reason": "undelivered",
            "evidence_attachment_id": up2.json()["id"],
            "idempotency_key": "ret-pod-ok",
        },
    )
    assert ok_req.status_code == 200, ok_req.text
    appr = await client.post(
        f"/api/v1/production/jobs/{jid}/loading/return-requests/{ok_req.json()['id']}/approve",
        headers=h_appr,
        json={"idempotency_key": "ret-pod-appr"},
    )
    assert appr.status_code == 200, appr.text


def test_alembic_0008_upgrade_downgrade_isolated():
    from alembic import command
    from alembic.config import Config

    sync = os.environ["DATABASE_URL_SYNC"]
    assert is_test_database_url(sync)
    cfg = Config("alembic.ini")
    eng = create_engine(sync)
    with eng.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        # Simulate pre-0008: drop column/index if create_all already added from model.
        conn.execute(
            text("ALTER TABLE production_events DROP COLUMN IF EXISTS accurate_sj_line_id")
        )
        conn.execute(text("DROP INDEX IF EXISTS ix_production_events_loading_alloc"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.stamp(cfg, "20261112_0007")
    command.upgrade(cfg, "20261113_0008")
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='production_events'"
                )
            )
        }
        assert "accurate_sj_line_id" in cols
        idx = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename='production_events'"
                )
            )
        }
        assert "ix_production_events_loading_alloc" in idx
    command.downgrade(cfg, "20261112_0007")
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='production_events'"
                )
            )
        }
        assert "accurate_sj_line_id" not in cols
