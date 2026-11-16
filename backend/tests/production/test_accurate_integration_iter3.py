"""Function First Iterasi 3 — Accurate integration honesty + inbox empty-page."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from tests.db_url_guard import (
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)

_async_url, _sync_url = resolve_test_database_urls()
assert is_test_database_url(_async_url)
assert database_name(_async_url).endswith("_test")
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_accurate_iter3"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_accurate_iter3"

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.accurate_read_gateway import (  # noqa: E402
    _gateway_provenance,
    list_sales_orders,
)

get_settings.cache_clear()


def test_provenance_never_labels_fixture_as_live():
    assert _gateway_provenance({"source": "fixture", "live_verified": False}) == {
        "source": "fixture",
        "mode": "fixture",
        "live_verified": False,
        "filter_incomplete": False,
    }
    live = _gateway_provenance({"source": "accurate_live", "live_verified": True})
    assert live["mode"] == "live" and live["live_verified"] is True
    unknown = _gateway_provenance({"rows": []})
    assert unknown["mode"] == "unverified"
    assert unknown["live_verified"] is None


@pytest.mark.asyncio
async def test_list_sales_orders_propagates_fixture_mode():
    class _Gw:
        async def get(self, path, *, params=None):
            return {
                "rows": [
                    {
                        "number": "SO/FIX/1",
                        "accurate_id": "1",
                        "branch_id": "branch-a",
                        "customer": "Cust",
                    }
                ],
                "total": 1,
                "source": "fixture",
                "live_verified": False,
            }

    data = await list_sales_orders(_Gw(), page=1, limit=50, keyword="")
    assert data["mode"] == "fixture"
    assert data["live_verified"] is False
    assert data["source"] == "fixture"
    assert data["rows"][0]["po_number"] == "SO/FIX/1"


@pytest.fixture
async def client():
    await dispose_engine()
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        session.add(
            User(
                username="acc.op",
                display_name="Op",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=["production.inbox.read", "production.job.read"],
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
async def test_scoped_inbox_empty_page_with_remaining_total_is_incomplete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Empty upstream page + remaining total must NOT claim complete empty inventory."""

    class _Gw:
        def __init__(self):
            self.calls = 0

        async def get(self, path, *, params=None):
            self.calls += 1
            page = int((params or {}).get("page") or 1)
            if page == 1:
                return {
                    "rows": [],
                    "total": 40,
                    "source": "accurate_live",
                    "live_verified": True,
                }
            return {
                "rows": [
                    {
                        "number": f"SO/LATE/{page}",
                        "branch_id": "branch-a",
                        "customer": "C",
                    }
                ],
                "total": 40,
                "source": "accurate_live",
                "live_verified": True,
            }

    from app.api.production_inbox import get_gateway

    gw = _Gw()
    client._transport.app.dependency_overrides[get_gateway] = lambda: gw  # type: ignore[attr-defined]
    monkeypatch.setenv("V3_INBOX_SCOPED_SCAN_MAX_PAGES", "3")
    get_settings.cache_clear()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "acc.op", "password": "secret-pass"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await client.get("/api/v1/production/inbox?page=1&limit=20", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == []
    assert body["total"] is None
    assert body["scan_incomplete"] is True
    assert body["mode"] == "live"
    assert body["live_verified"] is True
    # Stop after empty page — do not invent further pages as success.
    assert gw.calls == 1
