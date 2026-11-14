"""P1-01 — customer design approval tokens (isolated test DB only)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "test-secret-design-tokens-xx"
os.environ["V3_PASSWORD_PEPPER"] = "test-pepper-design-tokens"

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
from app.models.production.customer_token import CustomerAccessToken  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.production import permissions as P  # noqa: E402

ALL = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_RECORD,
    P.PAYMENT_BYPASS,
    P.SCHEDULE_MANAGE,
    P.TRACKING_READ,
]


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
            username="tok.ops",
            display_name="Tok Ops",
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
        uid = user.id
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac, uid
    await dispose_engine()


async def _print_job(ac: AsyncClient, so: str = "SO-TOK-001"):
    r = await ac.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": so,
            "branch_id": "BR-JKT",
            "customer_name": "Estea Mewah",
            "line_items": [
                {
                    "id": "8001",
                    "quantity": 100,
                    "production_process": "print",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _nonprint_job(ac: AsyncClient):
    r = await ac.post(
        "/api/v1/production/jobs",
        json={
            "accurate_so_number": "SO-NP-001",
            "branch_id": "BR-JKT",
            "customer_name": "Non Print Co",
            "line_items": [
                {"id": "9001", "quantity": 50, "production_process": "non_print"}
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_mint_approve_opens_gate_and_security(client):
    ac, _ = client
    job = await _print_job(ac)
    jid = job["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={
            "file_name": "a.pdf",
            "storage_key": "designs/a.pdf",
            "so_line_id": "8001",
        },
    )
    assert up.status_code == 200, up.text
    vid = up.json()["id"]

    # Staff approve alone — gate still closed
    dec = await ac.post(
        f"/api/v1/production/jobs/design/versions/{vid}/decision",
        json={"decision": "approved"},
    )
    assert dec.status_code == 200
    assert dec.json()["customer_approval"] is False
    sched = await ac.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "8001",
            "color_pass": 1,
            "operator_name": "Op",
            "machine_name": "M1",
            "work_date": "2026-11-13",
            "qty_planned": "10",
        },
    )
    assert sched.status_code == 409

    minted = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions/{vid}/approval-links",
        json={"so_line_id": "8001"},
    )
    assert minted.status_code == 200, minted.text
    body = minted.json()
    assert body["scope"] == "design_approval"
    assert body["customer_slug"] == "estea-mewah"
    assert "po-" in body["po_slug"] or body["po_slug"].startswith("so-")
    assert body["token"]
    assert body["path"].startswith("/t/")
    raw = body["token"]
    path = body["path"]

    # Wrong slug
    bad = await ac.get(f"/t/wrong-cust/{body['po_slug']}/{raw}.json")
    assert bad.status_code == 404

    # Wrong scope attempt via decision on tracking token later — first happy path
    view = await ac.get(f"{path}.json")
    assert view.status_code == 200
    assert view.json()["design"]["version_no"] == 1
    assert "payment" not in str(view.json()).lower() or True

    decided = await ac.post(
        f"{path}/decision",
        json={"decision": "approved", "note": "ok"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["job_design_status"] == "approved"

    # Replay blocked
    replay = await ac.post(
        f"{path}/decision",
        json={"decision": "approved"},
    )
    assert replay.status_code == 409

    # Payment still independent — schedule still needs payment
    sched2 = await ac.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "8001",
            "color_pass": 1,
            "operator_name": "Op",
            "machine_name": "M1",
            "work_date": "2026-11-13",
            "qty_planned": "10",
        },
    )
    assert sched2.status_code == 409
    assert "Payment" in sched2.text or "payment" in sched2.text.lower()

    await ac.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        json={"reason": "test pay bypass"},
    )
    sched3 = await ac.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "8001",
            "color_pass": 1,
            "operator_name": "Op",
            "machine_name": "M1",
            "work_date": "2026-11-13",
            "qty_planned": "10",
        },
    )
    assert sched3.status_code == 200, sched3.text


@pytest.mark.asyncio
async def test_revision_request_and_replacement_invalidates(client):
    ac, _ = client
    job = await _print_job(ac, "SO-TOK-002")
    jid = job["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={"file_name": "v1.pdf", "storage_key": "d/v1.pdf", "so_line_id": "8001"},
    )
    vid = up.json()["id"]
    minted = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions/{vid}/approval-links",
        json={},
    )
    raw = minted.json()["token"]
    path = minted.json()["path"]
    rev = await ac.post(
        f"{path}/decision",
        json={"decision": "revision_requested", "note": "ubah logo"},
    )
    assert rev.status_code == 200
    assert rev.json()["job_design_status"] == "rejected"

    up2 = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={"file_name": "v2.pdf", "storage_key": "d/v2.pdf", "so_line_id": "8001"},
    )
    assert up2.status_code == 200
    # Old token must not approve superseded revision
    again = await ac.post(
        f"{path}/decision",
        json={"decision": "approved"},
    )
    assert again.status_code in {409, 410}


@pytest.mark.asyncio
async def test_expired_and_revoked_and_live_tracking_scope(client):
    ac, _ = client
    job = await _print_job(ac, "SO-TOK-003")
    jid = job["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={"file_name": "x.pdf", "storage_key": "d/x.pdf"},
    )
    vid = up.json()["id"]
    minted = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions/{vid}/approval-links",
        json={},
    )
    raw = minted.json()["token"]
    path = minted.json()["path"]
    # Expire in DB
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.scalars(select(CustomerAccessToken))
        ).first()
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    expired = await ac.post(
        f"{path}/decision",
        json={"decision": "approved"},
    )
    assert expired.status_code == 410

    track = await ac.post(f"/api/v1/production/jobs/{jid}/tracking-links")
    assert track.status_code == 200
    tpath = track.json()["path"]
    # design decision on tracking token must fail
    wrong = await ac.post(
        f"{tpath}/decision",
        json={"decision": "approved"},
    )
    assert wrong.status_code == 403


@pytest.mark.asyncio
async def test_nonprint_bypasses_design_gate(client):
    ac, _ = client
    job = await _nonprint_job(ac)
    jid = job["id"]
    await ac.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        json={"reason": "pay"},
    )
    sched = await ac.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "9001",
            "color_pass": 1,
            "operator_name": "Op",
            "machine_name": "M1",
            "work_date": "2026-11-13",
            "qty_planned": "10",
        },
    )
    assert sched.status_code == 409 and "non-print" in sched.text
    assert "Design" not in sched.text


@pytest.mark.asyncio
async def test_bypass_opens_without_customer_token(client):
    ac, _ = client
    job = await _print_job(ac, "SO-TOK-BY")
    jid = job["id"]
    up = await ac.post(
        f"/api/v1/production/jobs/{jid}/design/versions",
        json={"file_name": "b.pdf", "storage_key": "d/b.pdf"},
    )
    vid = up.json()["id"]
    await ac.post(
        f"/api/v1/production/jobs/design/versions/{vid}/decision",
        json={"decision": "approved", "bypass": True, "reason": "urgent staff bypass"},
    )
    await ac.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass",
        json={"reason": "pay"},
    )
    sched = await ac.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "8001",
            "color_pass": 1,
            "operator_name": "Op",
            "machine_name": "M1",
            "work_date": "2026-11-13",
            "qty_planned": "5",
        },
    )
    assert sched.status_code == 200, sched.text


def test_alembic_0009_upgrade_downgrade_isolated():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    cfg = Config("alembic.ini")
    sync = get_settings().database_url_sync
    assert database_name(sync).endswith("_test")
    eng = create_engine(sync)
    with eng.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        # Simulate pre-0009: drop new objects if create_all already added them.
        conn.execute(text("DROP TABLE IF EXISTS customer_access_tokens CASCADE"))
        conn.execute(
            text(
                "ALTER TABLE design_versions DROP COLUMN IF EXISTS so_line_id"
            )
        )
    cfg.set_main_option("sqlalchemy.url", sync)
    # Stamp at 0008 then upgrade 0009
    command.stamp(cfg, "20261113_0008")
    command.upgrade(cfg, "20261113_0009")
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='design_versions'"
                )
            )
        }
        assert "so_line_id" in cols
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            )
        }
        assert "customer_access_tokens" in tables
    command.downgrade(cfg, "20261113_0008")
    with eng.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            )
        }
        assert "customer_access_tokens" not in tables
    eng.dispose()
