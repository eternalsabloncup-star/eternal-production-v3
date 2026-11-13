"""Slice 1K — POD four-attachment evidence + screener screen_size."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from tests.db_url_guard import resolve_test_database_urls
from tests.production.pod_attach_helpers import (
    PNG_1X1,
    pod_body,
    upload_pod_bundle,
)

_async_url, _sync_url = resolve_test_database_urls()
os.environ["DATABASE_URL"] = _async_url
os.environ["DATABASE_URL_SYNC"] = _sync_url
os.environ["APP_ENV"] = "test"
os.environ["V3_JWT_SECRET"] = "v3_test_jwt_secret_not_from_v1"
os.environ["V3_PASSWORD_PEPPER"] = "v3_test_password_pepper_distinct"
_attach_root = Path("/tmp/epv3_slice1k_attachments")
_attach_root.mkdir(parents=True, exist_ok=True)
os.environ["V3_ATTACHMENT_ROOT"] = str(_attach_root)

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
    P.DELIVERY_MANAGE,
]


@pytest.fixture
async def client_1k():
    get_settings.cache_clear()
    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            User(
                username="slice1k.lead",
                display_name="Slice1K",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="slice1k.other",
                display_name="OtherBranch",
                role="driver",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS,
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        await session.commit()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/v1/auth/login",
            json={"username": "slice1k.lead", "password": "secret-pass"},
        )
        assert login.status_code == 200, login.text
        ac.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield ac
    await dispose_engine()
    get_settings.cache_clear()


async def _seed_packed_job(client: AsyncClient) -> tuple[int, str]:
    job = (
        await client.post(
            "/api/v1/production/jobs",
            json={
                "accurate_so_number": "SO/1K/POD",
                "branch_id": "branch-a",
                "customer_name": "POD Cust",
                "line_items": [
                    {
                        "accurate_line_id": "L1",
                        "quantity": "100",
                        "production_process": "print",
                    }
                ],
            },
        )
    ).json()
    jid = job["id"]
    design = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/design/versions",
            json={"file_name": "d.pdf", "storage_key": "d"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{design['id']}/decision",
        json={"decision": "approved"},
    )
    await client.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass", json={"reason": "test"}
    )
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            json={
                "so_line_id": "L1",
                "color_pass": 1,
                "operator_name": "A",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "100",
            },
        )
    ).json()
    scr = await client.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "100",
            "screen_size": "besar",
            "evidence_ref": "scr",
            "idempotency_key": "scr-1k-pod",
            "assignment_id": asg["id"],
        },
    )
    assert scr.status_code == 200, scr.text
    assert scr.json()["screen_size"] == "besar"
    await client.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        json={
            "so_line_id": "L1",
            "qty": "100",
            "po_qty": "100",
            "evidence_ref": "hlp",
            "idempotency_key": "hlp-1k-pod",
        },
    )
    sample = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/samples",
            json={"file_name": "s.jpg", "storage_key": "s", "assignment_id": asg["id"]},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/samples/{sample['id']}/decision",
        json={"decision": "approved"},
    )
    assert (
        await client.post(
            f"/api/v1/production/jobs/{jid}/outputs",
            json={
                "assignment_id": asg["id"],
                "qty_physical": "100",
                "color_pass": 1,
                "idempotency_key": "out-1k-100",
            },
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/production/jobs/{jid}/packing",
            json={
                "so_line_id": "L1",
                "qty_physical": "100",
                "idempotency_key": "pack-1k-100",
            },
        )
    ).status_code == 200
    return jid, "SJ-1K-1"


@pytest.mark.asyncio
async def test_screen_size_required_and_invalid_rejected(client_1k: AsyncClient):
    job = (
        await client_1k.post(
            "/api/v1/production/jobs",
            json={
                "accurate_so_number": "SO/1K/SCR",
                "branch_id": "branch-a",
                "line_items": [
                    {
                        "accurate_line_id": "L1",
                        "quantity": "10",
                        "production_process": "print",
                    }
                ],
            },
        )
    ).json()
    jid = job["id"]
    design = (
        await client_1k.post(
            f"/api/v1/production/jobs/{jid}/design/versions",
            json={"file_name": "d.pdf", "storage_key": "d"},
        )
    ).json()
    await client_1k.post(
        f"/api/v1/production/jobs/design/versions/{design['id']}/decision",
        json={"decision": "approved"},
    )
    await client_1k.post(
        f"/api/v1/production/jobs/{jid}/payment/bypass", json={"reason": "t"}
    )
    # Before schedule — blocked
    early = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "10",
            "screen_size": "kecil",
            "evidence_ref": "e",
            "idempotency_key": "scr-early-1k",
        },
    )
    assert early.status_code == 409, early.text
    await client_1k.post(
        f"/api/v1/production/jobs/{jid}/schedule/assignments",
        json={
            "so_line_id": "L1",
            "color_pass": 1,
            "operator_name": "A",
            "machine_name": "M",
            "work_date": str(date.today()),
            "qty_planned": "10",
        },
    )
    bad = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "10",
            "screen_size": "medium",
            "evidence_ref": "e",
            "idempotency_key": "scr-bad-size",
        },
    )
    assert bad.status_code == 422
    ok = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "1",
            "po_qty": "10",
            "screen_size": "kecil",
            "evidence_ref": "e",
            "idempotency_key": "scr-ok-size",
        },
    )
    assert ok.status_code == 200
    corr = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/prep/screener",
        json={
            "so_line_id": "L1",
            "qty": "2",
            "po_qty": "10",
            "screen_size": "besar",
            "evidence_ref": "e2",
            "idempotency_key": "scr-corr-size",
            "as_correction": True,
            "reason": "size fix",
        },
    )
    assert corr.status_code == 200
    assert corr.json()["screen_size"] == "besar"
    board = await client_1k.get(f"/api/v1/production/jobs/{jid}/board")
    assert board.status_code == 200
    states = board.json()["prep_states"]
    assert any(s.get("screen_size") == "besar" for s in states)
    hist = board.json()["prep_events"]
    assert any(e.get("screen_size") == "kecil" for e in hist)
    assert any(e.get("screen_size") == "besar" for e in hist)


@pytest.mark.asyncio
async def test_pod_requires_four_attachments_and_partials(client_1k: AsyncClient):
    jid, sj = await _seed_packed_job(client_1k)
    # Missing attachments → 422
    missing = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json={
            "accurate_sj_id": sj,
            "qty_physical": "10",
            "idempotency_key": "pod-miss-1k",
            "receiver_name": "Budi",
            "attachment_pod_photo_1": 1,
            "attachment_pod_photo_2": 2,
            "attachment_pod_sig_sender": 3,
            "attachment_pod_sig_recipient": 4,
        },
    )
    assert missing.status_code in {404, 409, 422}

    empty_name_ids = await upload_pod_bundle(client_1k, jid, sj)
    empty_name = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "10", "pod-empty-name", empty_name_ids, receiver="  "),
    )
    assert empty_name.status_code == 422

    # No loading
    ids = await upload_pod_bundle(client_1k, jid, sj)
    no_load = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "10", "pod-noload", ids),
    )
    assert no_load.status_code == 409

    load = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/loading",
        json={
            "accurate_sj_id": sj,
            "accurate_sj_number": sj,
            "qty_physical": "50",
            "idempotency_key": "load-1k-50",
        },
    )
    assert load.status_code == 200, load.text

    # Wrong SJ on attachments
    wrong = await upload_pod_bundle(client_1k, jid, "OTHER-SJ")
    bad_sj = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "10", "pod-wrongsj", wrong),
    )
    assert bad_sj.status_code == 409

    # Partial 1
    p1 = await upload_pod_bundle(client_1k, jid, sj)
    ok1 = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "20", "pod-part-1", p1),
    )
    assert ok1.status_code == 200, ok1.text
    # Idempotent
    again = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "20", "pod-part-1", p1),
    )
    assert again.status_code == 200
    assert again.json()["id"] == ok1.json()["id"]

    # Bound attachments cannot be reused
    reuse = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "10", "pod-reuse", p1),
    )
    assert reuse.status_code == 409

    # Over remaining
    p_over = await upload_pod_bundle(client_1k, jid, sj)
    over = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "40", "pod-over", p_over),
    )
    assert over.status_code == 409

    # Second partial fills remaining 30
    p2 = await upload_pod_bundle(client_1k, jid, sj)
    ok2 = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "30", "pod-part-2", p2),
    )
    assert ok2.status_code == 200, ok2.text

    # Cancelled SJ blocks
    await client_1k.post(
        f"/api/v1/production/jobs/{jid}/sj/cancel",
        json={
            "accurate_sj_id": sj,
            "reason": "supersede",
            "idempotency_key": "cancel-1k",
        },
    )
    p3 = await upload_pod_bundle(client_1k, jid, sj)
    cancelled = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/pod",
        json=pod_body(sj, "1", "pod-cancel", p3),
    )
    assert cancelled.status_code == 409

    # Branch isolation
    login_b = await client_1k.post(
        "/api/v1/auth/login",
        json={"username": "slice1k.other", "password": "secret-pass"},
    )
    token_b = login_b.json()["access_token"]
    denied = await client_1k.post(
        f"/api/v1/production/jobs/{jid}/attachments",
        headers={"Authorization": f"Bearer {token_b}"},
        data={"accurate_sj_id": sj, "purpose": "pod_photo_1"},
        files={"file": ("x.png", PNG_1X1, "image/png")},
    )
    assert denied.status_code == 403

    # Tugas Tim delivery evidence
    tasks = await client_1k.get("/api/v1/production/jobs/tasks")
    assert tasks.status_code == 200
    kinds = {
        t["kind"]: t["state"]
        for t in tasks.json()["tasks"]
        if t["accurate_so_number"] == "SO/1K/POD"
    }
    assert kinds.get("loading") == "done"
    assert kinds.get("delivery") == "done"


def test_alembic_upgrade_downgrade_isolated():
    """Slice 1K revision upgrade/downgrade on isolated test DB only (not VPS)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    sync = os.environ["DATABASE_URL_SYNC"]
    assert any(x in sync for x in ("test", "epv3", "127.0.0.1", "localhost"))
    eng = create_engine(sync)
    with eng.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        # Drop 1K objects so upgrade can recreate them from revision 0006 stamp.
        conn.execute(text("ALTER TABLE prep_events DROP COLUMN IF EXISTS screen_size"))
        conn.execute(text("ALTER TABLE prep_states DROP COLUMN IF EXISTS screen_size"))
        conn.execute(text("DROP TABLE IF EXISTS production_attachments CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.stamp(cfg, "20261112_0006")
    command.upgrade(cfg, "head")
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='prep_states'"
                )
            )
        }
        assert "screen_size" in cols
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            )
        }
        assert "production_attachments" in tables
    command.downgrade(cfg, "20261112_0006")
    with eng.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='prep_states'"
                )
            )
        }
        assert "screen_size" not in cols
    command.upgrade(cfg, "head")
    eng.dispose()
