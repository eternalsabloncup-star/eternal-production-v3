"""Auth + branch-scoped inbox API tests against isolated Postgres."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test",
)
os.environ["DATABASE_URL_SYNC"] = os.environ.get(
    "TEST_DATABASE_URL_SYNC",
    "postgresql+psycopg2://epv3_test:epv3_test_local_only@127.0.0.1:5432/eternal_production_v3_test",
)
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_not_from_v1"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_distinct"
os.environ["V3_ACCURATE_READ_GATEWAY_URL"] = "http://127.0.0.1:9"
os.environ["V3_ACCURATE_READ_GATEWAY_TOKEN"] = "test-gateway-token"

from app.core.config import get_settings
from app.core.security import PERM_INBOX_READ, PERM_ORDER_READ, hash_password
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_session_factory
from app.main import create_app
from app.models.user import User
from app.models.work_order import WorkOrder

get_settings.cache_clear()


class FakeGateway:
    async def get(self, path, *, params=None):
        if path == "/sales-orders":
            return {
                "total": 3,
                "rows": [
                    {
                        "number": "SO/TEST/001",
                        "customer": "A",
                        "branch_id": "branch-a",
                    },
                    {
                        "number": "SO/TEST/002",
                        "customer": "B",
                        "branch_id": "branch-a",
                    },
                    {
                        "number": "SO/OTHER/009",
                        "customer": "X",
                        "branch_id": "branch-b",
                    },
                ],
            }
        return {
            "preview": {
                "accurate_id": "77",
                "number": "SO/TEST/001",
                "po_number": None,
                "customer": "A",
                "branch_id": "branch-a",
                "line_items": [
                    {"item_code": "SKU", "name": "Cup", "quantity": 100}
                ],
                "total_quantity": 100,
            }
        }


@pytest.fixture
async def api_client(monkeypatch: pytest.MonkeyPatch):
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
                username="inbox.user",
                display_name="Inbox User",
                role="produksi",
                password_hash=hash_password("secret-pass"),
                permissions=[PERM_INBOX_READ, PERM_ORDER_READ],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            WorkOrder(
                accurate_so_number="SO/TEST/002",
                accurate_id="acc-2",
                branch_id="branch-a",
                processing_status="Terproses",
            )
        )
        await session.commit()

    from app.api.production_inbox import get_gateway

    app = create_app()
    app.dependency_overrides[get_gateway] = lambda: FakeGateway()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await dispose_engine()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_and_me(api_client: AsyncClient) -> None:
    bad = await api_client.post(
        "/api/v1/auth/login", json={"username": "inbox.user", "password": "wrong"}
    )
    assert bad.status_code == 401

    ok = await api_client.post(
        "/api/v1/auth/login",
        json={"username": "inbox.user", "password": "secret-pass"},
    )
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["branch_ids"] == ["branch-a"]


@pytest.mark.asyncio
async def test_inbox_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/production/inbox")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_inbox_branch_filter_and_wo_status(api_client: AsyncClient) -> None:
    login = await api_client.post(
        "/api/v1/auth/login",
        json={"username": "inbox.user", "password": "secret-pass"},
    )
    token = login.json()["access_token"]
    response = await api_client.get(
        "/api/v1/production/inbox",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    # Test double / unconfigured gateway is not Accurate Live.
    assert payload["mode"] in {"unverified", "fixture", "live"}
    if payload["mode"] != "live":
        assert payload.get("live_verified") is not True
    numbers = [row["po_number"] for row in payload["rows"]]
    assert "SO/OTHER/009" not in numbers
    assert "SO/TEST/001" in numbers
    assert "SO/TEST/002" in numbers
    by_number = {row["po_number"]: row["production_status"] for row in payload["rows"]}
    assert by_number["SO/TEST/001"] == "Baru"
    assert by_number["SO/TEST/002"] == "Terproses"
