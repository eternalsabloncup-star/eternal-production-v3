"""SJ-line Loading authority for board/UI — never invents PCS."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from tests.db_url_guard import (
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)
from tests.production.sj_line_helpers import loading_body, sj_line_item

_async_url, _sync_url = resolve_test_database_urls()
assert is_test_database_url(_async_url)
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
    P.DELIVERY_MANAGE,
    P.DELIVERY_LOADING_RETURN_REQUEST,
    P.DELIVERY_LOADING_RETURN_APPROVE,
    P.PACKING_RECORD,
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
                username="auth.lead",
                display_name="Auth Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="auth.helper",
                display_name="Helper Eff",
                role="helper",
                password_hash=hash_password("secret-pass"),
                permissions=[
                    P.JOB_READ,
                    P.DELIVERY_LOADING_RETURN_REQUEST,
                ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="auth.driver",
                display_name="Driver Eff",
                role="driver",
                password_hash=hash_password("secret-pass"),
                permissions=[
                    P.JOB_READ,
                    P.DELIVERY_MANAGE,
                    P.DELIVERY_LOADING_RETURN_REQUEST,
                ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="auth.kepala",
                display_name="Kepala Eff",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=[
                    P.JOB_READ,
                    P.DELIVERY_LOADING_RETURN_APPROVE,
                ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="auth.noperm",
                display_name="No Perm",
                role="ops",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()

    catalog = {
        "SJ-AUTH": [
            sj_line_item(
                accurate_sj_line_id="SL-A",
                so_line_id="SO-A",
                quantity=100,
                sku="CUP",
            )
        ]
    }

    async def _valid_sj(**kwargs):
        sj = kwargs["accurate_sj_id"]
        lines = catalog.get(sj)
        if lines is None:
            from fastapi import HTTPException

            raise HTTPException(409, "Surat Jalan Accurate tidak ditemukan — loading ditolak")
        return {
            "verified": True,
            "mode": "gateway",
            "accurate_sj_id": sj,
            "accurate_sj_number": kwargs["accurate_sj_number"],
            "sales_order_number": kwargs.get("expected_so_number") or "SO-AUTH",
            "branch_id": "branch-a",
            "line_items": lines,
            "loading_eligible": True,
            "live_verified": False,
        }

    monkeypatch.setattr(
        "app.services.accurate_evidence.require_valid_sj", _valid_sj
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _login(client: AsyncClient, user: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "secret-pass"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _job(client: AsyncClient, token: str) -> int:
    r = await client.post(
        "/api/v1/production/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "accurate_so_number": "SO-AUTH",
            "accurate_id": "acc-auth",
            "branch_id": "branch-a",
            "customer_name": "Auth Cust",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_loading_authority_verified_and_unknown(client: AsyncClient):
    token = await _login(client, "auth.lead")
    jid = await _job(client, token)
    h = {"Authorization": f"Bearer {token}"}

    ok = await client.get(
        f"/api/v1/production/jobs/{jid}/loading-authority",
        headers=h,
        params={
            "accurate_sj_id": "SJ-AUTH",
            "accurate_sj_number": "SJ-AUTH",
            "accurate_sj_line_id": "SL-A",
            "so_line_id": "SO-A",
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["verification"] == "VERIFIED"
    assert body["qty_sj_pcs"] == "100"
    assert body["remaining_loading"] == "100"
    assert body["actions_enabled"] is True
    assert body["packing_monitoring_only"] is True

    bad = await client.get(
        f"/api/v1/production/jobs/{jid}/loading-authority",
        headers=h,
        params={
            "accurate_sj_id": "SJ-MISSING",
            "accurate_sj_number": "SJ-MISSING",
            "accurate_sj_line_id": "SL-A",
            "so_line_id": "SO-A",
        },
    )
    assert bad.status_code == 200, bad.text
    unk = bad.json()
    assert unk["verification"] == "UNKNOWN"
    assert unk["qty_sj_pcs"] is None
    assert unk["remaining_loading"] is None
    assert unk["actions_enabled"] is False


@pytest.mark.asyncio
async def test_board_includes_sj_line_authority_after_loading(client: AsyncClient):
    token = await _login(client, "auth.lead")
    jid = await _job(client, token)
    h = {"Authorization": f"Bearer {token}"}
    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ-AUTH",
            accurate_sj_line_id="SL-A",
            so_line_id="SO-A",
            qty_physical="40",
            idempotency_key="auth-load-40xxxx",
        ),
    )
    assert load.status_code == 200, load.text
    board = await client.get(
        f"/api/v1/production/jobs/{jid}/board", headers=h
    )
    assert board.status_code == 200, board.text
    rows = board.json()["sj_line_authority"]
    assert len(rows) == 1
    assert rows[0]["qty_sj_pcs"] == "100"
    assert rows[0]["loading_confirmed"] == "40"
    assert rows[0]["loading_net"] == "40"
    assert rows[0]["remaining_loading"] == "60"
    assert Decimal(rows[0]["remaining_loading"]) == Decimal("60")


@pytest.mark.asyncio
async def test_effective_permissions_helper_driver_kepala(client: AsyncClient):
    """Effective users.permissions — not role-name inference."""
    cases = [
        ("auth.helper", P.DELIVERY_LOADING_RETURN_REQUEST, True),
        ("auth.helper", P.DELIVERY_LOADING_RETURN_APPROVE, False),
        ("auth.helper", P.DELIVERY_MANAGE, False),
        ("auth.driver", P.DELIVERY_LOADING_RETURN_REQUEST, True),
        ("auth.driver", P.DELIVERY_MANAGE, True),
        ("auth.driver", P.DELIVERY_LOADING_RETURN_APPROVE, False),
        ("auth.kepala", P.DELIVERY_LOADING_RETURN_APPROVE, True),
        ("auth.kepala", P.DELIVERY_LOADING_RETURN_REQUEST, False),
        ("auth.noperm", P.DELIVERY_LOADING_RETURN_REQUEST, False),
        ("auth.noperm", P.DELIVERY_LOADING_RETURN_APPROVE, False),
    ]
    for user, perm, expect in cases:
        token = await _login(client, user)
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        have = set(me.json()["permissions"] or [])
        assert (perm in have) is expect, (user, perm, have)
