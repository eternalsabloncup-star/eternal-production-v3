"""Focused: HTML escape + invalid token must not leak job/customer data."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "test-secret-portal-html-xx"
os.environ["V3_PASSWORD_PEPPER"] = "test-pepper-portal-html-xx"

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

ALL = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.TRACKING_READ,
]

XSS_NAME = 'Acme<script>alert(1)</script>&"Co'
XSS_FILE = 'evil<svg onload=alert(1)>.pdf'


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
        user = User(
            username="html.ops",
            display_name="HTML Ops",
            role="kepala_produksi",
            password_hash=hash_password("x"),
            permissions=ALL,
            branch_ids=["BR-JKT"],
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token(user)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac
    await dispose_engine()


async def _mint_link(ac: AsyncClient) -> tuple[str, str]:
    job = await ac.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO/<XSS>-001",
            "branch_id": "BR-JKT",
            "customer_name": XSS_NAME,
            "line_items": [
                {"id": "8001", "quantity": 10, "production_process": "print"}
            ],
        },
    )
    assert job.status_code == 200, job.text
    jid = job.json()["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={
            "file_name": XSS_FILE,
            "storage_key": "designs/evil.pdf",
            "so_line_id": "8001",
        },
    )
    assert up.status_code == 200, up.text
    vid = up.json()["id"]
    minted = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions/{vid}/approval-links",
        json={"so_line_id": "8001"},
    )
    assert minted.status_code == 200, minted.text
    return minted.json()["path"], job.json()["customer_name"]


@pytest.mark.asyncio
async def test_html_escapes_dynamic_customer_and_filename(client: AsyncClient):
    path, _ = await _mint_link(client)
    # Public HTML must not require staff auth.
    r = await client.get(path, headers={})
    assert r.status_code == 200
    html = r.text
    # Raw tags must not appear; escaped entities are required.
    assert "<script>alert(1)</script>" not in html
    assert "<svg onload=" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "evil&lt;svg onload=alert(1)&gt;.pdf" in html
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("referrer-policy") == "no-referrer"


@pytest.mark.asyncio
async def test_invalid_token_html_does_not_leak_customer_or_po(client: AsyncClient):
    path, customer = await _mint_link(client)
    # Valid path prefix, garbage token.
    parts = path.strip("/").split("/")
    # /t/{cust}/{po}/{token}
    bad = f"/t/{parts[1]}/{parts[2]}/not-a-real-token-zzzzzzzz"
    r = await client.get(bad, headers={})
    assert r.status_code in {404, 410}
    html = r.text.lower()
    assert "tautan tidak berlaku" in html
    assert customer.lower() not in html
    assert "so/<xss>-001".lower() not in html
    assert XSS_FILE.lower() not in html
    assert "<script>" not in html


@pytest.mark.asyncio
async def test_wrong_slug_with_valid_token_no_leak(client: AsyncClient):
    path, customer = await _mint_link(client)
    parts = path.strip("/").split("/")
    token = parts[3]
    bad = f"/t/wrong-customer/{parts[2]}/{token}"
    r = await client.get(bad, headers={})
    assert r.status_code == 404
    assert customer not in r.text
    assert XSS_FILE not in r.text
    j = await client.get(f"{bad}.json", headers={})
    assert j.status_code == 404
    body = j.text.lower()
    assert "estea" not in body
    assert customer.lower() not in body
    assert "design" not in body or "detail" in body
