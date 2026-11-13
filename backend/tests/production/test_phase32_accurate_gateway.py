"""Phase 3.2 — gateway evidence: security, mismatch, reversal, concurrency."""

from __future__ import annotations

import asyncio
import os

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
from app.services import accurate_evidence as evidence_mod
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
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
]


class _FakeGateway:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(self, path: str, *, params=None) -> dict:
        self.calls.append(path)
        if path not in self.payloads:
            from fastapi import HTTPException

            raise HTTPException(
                404, detail={"code": "document_not_found", "message": "missing"}
            )
        return self.payloads[path]


@pytest.fixture
def enforce(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V3_ACCURATE_EVIDENCE_ENFORCE", "true")
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_URL", "http://127.0.0.1:8091")
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_TOKEN", "test-m2m")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("V3_ACCURATE_EVIDENCE_ENFORCE", raising=False)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_receipt_cancelled_reversed_unverifiable(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/receipts/RCP-C": {
                "id": "RCP-C",
                "status": "CANCELLED",
                "cancelled": True,
                "reversed": False,
                "verifiable": False,
                "sales_order_number": "SO-1",
            },
            "/receipts/RCP-R": {
                "id": "RCP-R",
                "status": "REVERSED",
                "cancelled": False,
                "reversed": True,
                "verifiable": False,
                "sales_order_number": "SO-1",
            },
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)

    with pytest.raises(Exception) as c:
        await evidence_mod.require_valid_receipt("RCP-C", expected_so_number="SO-1")
    assert c.value.status_code == 409

    with pytest.raises(Exception) as r:
        await evidence_mod.require_valid_receipt("RCP-R", expected_so_number="SO-1")
    assert r.value.status_code == 409


@pytest.mark.asyncio
async def test_receipt_so_and_branch_mismatch(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/receipts/RCP-M": {
                "id": "RCP-M",
                "status": "POSTED",
                "cancelled": False,
                "reversed": False,
                "verifiable": True,
                "source": "fixture",
                "amount": 1000,
                "sales_order_number": "SO-OTHER",
                "branch": {"id": "BR-SBY", "name": "Surabaya"},
                "customer": {"id": "C-1", "name": "A"},
            }
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)
    with pytest.raises(Exception) as exc:
        await evidence_mod.require_valid_receipt(
            "RCP-M",
            expected_so_number="SO-LIVE-001",
            expected_branch_id="BR-JKT",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sj_cancelled_and_mismatch(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/delivery-notes/SJ-C": {
                "id": "SJ-C",
                "number": "SJ-C",
                "status": "CANCELLED",
                "cancelled": True,
                "verifiable": False,
                "sales_order_number": "SO-1",
            },
            "/delivery-notes/SJ-M": {
                "id": "SJ-M",
                "number": "SJ-M",
                "status": "DELIVERED",
                "cancelled": False,
                "verifiable": True,
                "sales_order_number": "SO-OTHER",
                "branch": {"id": "BR-SBY", "name": "SBY"},
            },
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)
    with pytest.raises(Exception) as c:
        await evidence_mod.require_valid_sj(
            accurate_sj_id="SJ-C", accurate_sj_number="SJ-C"
        )
    assert c.value.status_code == 409
    with pytest.raises(Exception) as m:
        await evidence_mod.require_valid_sj(
            accurate_sj_id="SJ-M",
            accurate_sj_number="SJ-M",
            expected_so_number="SO-1",
            expected_branch_id="BR-JKT",
        )
    assert m.value.status_code == 409


@pytest.mark.asyncio
async def test_receipt_missing_so_link_fails_closed(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/receipts/RCP-NOLINK": {
                "id": "RCP-NOLINK",
                "status": "POSTED",
                "cancelled": False,
                "reversed": False,
                "verifiable": True,
                "source": "fixture",
                "amount": 1000,
                "sales_order_number": "",
                "branch": {"id": "BR-JKT", "name": "Jakarta"},
            }
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)
    with pytest.raises(Exception) as exc:
        await evidence_mod.require_valid_receipt(
            "RCP-NOLINK", expected_so_number="SO-1"
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_receipt_ok_passes(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/receipts/RCP-OK": {
                "id": "RCP-OK",
                "status": "POSTED",
                "cancelled": False,
                "reversed": False,
                "verifiable": True,
                "source": "fixture",
                "amount": 1000,
                "sales_order_number": "SO-1",
                "branch": {"id": "BR-JKT", "name": "Jakarta"},
                "live_verified": False,
            }
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)
    out = await evidence_mod.require_valid_receipt(
        "RCP-OK", expected_so_number="SO-1", expected_branch_id="BR-JKT"
    )
    assert out["verified"] is True
    assert out["mode"] == "gateway"


@pytest.mark.asyncio
async def test_concurrent_evidence_reads(enforce, monkeypatch):
    gw = _FakeGateway(
        {
            "/receipts/RCP-OK": {
                "id": "RCP-OK",
                "status": "POSTED",
                "cancelled": False,
                "reversed": False,
                "verifiable": True,
                "source": "fixture",
                "amount": 1000,
                "sales_order_number": "SO-1",
                "branch": {"id": "BR-JKT"},
            }
        }
    )
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)

    async def one():
        return await evidence_mod.require_valid_receipt(
            "RCP-OK", expected_so_number="SO-1", expected_branch_id="BR-JKT"
        )

    results = await asyncio.gather(*[one() for _ in range(15)])
    assert all(r["verified"] for r in results)
    assert len(gw.calls) == 15


@pytest.fixture
async def seeded_client():
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


@pytest.mark.asyncio
async def test_bypass_audits_actor_reason_permission(seeded_client: AsyncClient):
    login = await seeded_client.post(
        "/api/v1/auth/login",
        json={"username": "prod.lead", "password": "secret-pass"},
    )
    assert login.status_code == 200
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    job = (
        await seeded_client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO/P32/BYP", "branch_id": "branch-a"},
        )
    ).json()
    d = (
        await seeded_client.post(
            f"/api/v1/production/jobs/{job['id']}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
    ).json()
    await seeded_client.post(
        f"/api/v1/production/jobs/design/versions/{d['id']}/decision",
        headers=h,
        json={"decision": "approved", "bypass": True, "reason": "owner"},
    )
    bypass = await seeded_client.post(
        f"/api/v1/production/jobs/{job['id']}/payment/bypass",
        headers=h,
        json={"reason": "owner authorized staging bypass"},
    )
    assert bypass.status_code == 200
    board = await seeded_client.get(
        f"/api/v1/production/jobs/{job['id']}/board", headers=h
    )
    types = [e["event_type"] for e in board.json()["events"]]
    assert "payment_bypass_authorized" in types
    evt = next(
        e
        for e in board.json()["events"]
        if e["event_type"] == "payment_bypass_authorized"
    )
    assert "owner authorized staging bypass" in (evt.get("reason") or "")
