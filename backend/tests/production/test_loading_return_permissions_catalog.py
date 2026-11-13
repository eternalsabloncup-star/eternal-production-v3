"""Permission catalog + Helper/Kepala default mapping (no live DB grants)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.db_url_guard import (
    database_name,
    is_test_database_url,
    resolve_test_database_urls,
)

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
                username="perm.viewer",
                display_name="Perm Viewer",
                role="ops",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ],
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


async def _token(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "perm.viewer", "password": "secret-pass"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_catalog_includes_loading_return_codes():
    payload = P.permission_catalog_payload()
    codes = {row["code"] for row in payload["permissions"]}
    assert P.DELIVERY_LOADING_RETURN_REQUEST in codes
    assert P.DELIVERY_LOADING_RETURN_APPROVE in codes
    assert payload["loading_return"]["request_default_roles"] == ["driver", "helper"]
    assert payload["loading_return"]["approve_default_roles"] == ["kepala_produksi"]


def test_role_defaults_do_not_blanket_grant():
    assert P.default_loading_return_permissions_for_role("helper") == [
        P.DELIVERY_LOADING_RETURN_REQUEST,
        P.OUTPUT_HELPER_VERIFY,
    ]
    assert P.default_loading_return_permissions_for_role("driver") == [
        P.DELIVERY_LOADING_RETURN_REQUEST
    ]
    assert P.default_loading_return_permissions_for_role("kepala_produksi") == [
        P.DELIVERY_LOADING_RETURN_APPROVE
    ]
    assert P.default_loading_return_permissions_for_role("ops") == []
    assert P.default_loading_return_permissions_for_role("Kepala Produksi") == []
    merged = P.merge_role_default_permissions([P.JOB_READ], "helper")
    assert merged == [
        P.JOB_READ,
        P.DELIVERY_LOADING_RETURN_REQUEST,
        P.OUTPUT_HELPER_VERIFY,
    ]


@pytest.mark.asyncio
async def test_permissions_catalog_endpoint(client: AsyncClient):
    token = await _token(client)
    r = await client.get(
        "/api/v1/production/permissions/catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    codes = {row["code"] for row in body["permissions"]}
    assert P.DELIVERY_LOADING_RETURN_REQUEST in codes
    assert P.DELIVERY_LOADING_RETURN_APPROVE in codes
    assert body["role_defaults"]["helper"] == [
        P.DELIVERY_LOADING_RETURN_REQUEST,
        P.OUTPUT_HELPER_VERIFY,
    ]
    assert body["role_defaults"]["kepala_produksi"] == [
        P.DELIVERY_LOADING_RETURN_APPROVE
    ]
