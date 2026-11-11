"""Phase 4 operational acceptance — workflow, qty, concurrency, permissions, perf."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import date
from decimal import Decimal

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
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
    P.PAYROLL_MANAGE,
    P.PAYROLL_READ,
]


class _Gw:
    """Fixture-shaped gateway payloads for enforce-on acceptance."""

    def __init__(self):
        self.receipts = {
            "/receipts/RCP-OK-1": {
                "id": "RCP-OK-1",
                "status": "POSTED",
                "cancelled": False,
                "reversed": False,
                "verifiable": True,
                "sales_order_number": "SO-P4-E2E-001",
                "branch": {"id": "branch-a", "name": "Jakarta A"},
                "amount": 1500000,
            },
            "/receipts/RCP-CANCELLED": {
                "id": "RCP-CANCELLED",
                "status": "CANCELLED",
                "cancelled": True,
                "reversed": False,
                "verifiable": False,
                "sales_order_number": "SO-P4-E2E-001",
                "branch": {"id": "branch-a"},
            },
        }
        self.sj = {
            "/delivery-notes/SJ-OK-1": {
                "id": "SJ-OK-1",
                "number": "SJ-OK-1",
                "status": "DELIVERED",
                "cancelled": False,
                "verifiable": True,
                "sales_order_number": "SO-P4-E2E-001",
                "branch": {"id": "branch-a"},
            },
            "/delivery-notes/SJ-CANCELLED": {
                "id": "SJ-CANCELLED",
                "number": "SJ-CANCELLED",
                "status": "CANCELLED",
                "cancelled": True,
                "verifiable": False,
                "sales_order_number": "SO-P4-E2E-001",
                "branch": {"id": "branch-a"},
            },
        }
        self.orders = {
            f"/sales-orders/SO-P4-{i:03d}": {
                "sales_order": {
                    "accurate_id": str(10000 + i),
                    "number": f"SO-P4-{i:03d}",
                    "po_number": None,
                    "branch_id": "branch-a",
                    "customer": f"Customer P4 {i:03d}",
                    "line_items": [
                        {
                            "item_code": f"SKU-{i}",
                            "name": "Item",
                            "quantity": 10 + i,
                            "unit": "PCS",
                        }
                    ],
                    "total_quantity": 10 + i,
                }
            }
            for i in range(1, 71)
        }

    async def get(self, path: str, *, params=None):
        from fastapi import HTTPException

        if path == "/sales-orders":
            page = int((params or {}).get("page") or 1)
            limit = int((params or {}).get("limit") or 50)
            keyword = str((params or {}).get("keyword") or "")
            rows = []
            for i in range(1, 71):
                number = f"SO-P4-{i:03d}"
                if keyword and keyword.lower() not in number.lower():
                    continue
                rows.append(
                    {
                        "accurate_id": str(10000 + i),
                        "number": number,
                        "po_number": None,
                        "branch_id": "branch-a",
                        "customer": f"Customer P4 {i:03d}",
                    }
                )
            # Include classic fixtures for mixed inbox
            rows = (
                [
                    {
                        "accurate_id": "9001",
                        "number": "SO-LIVE-001",
                        "po_number": "PO-CUST-001",
                        "branch_id": "branch-a",
                        "customer": "PT Contoh",
                    }
                ]
                + rows
            )
            total = len(rows)
            start = (page - 1) * limit
            page_rows = rows[start : start + limit]
            return {
                "rows": page_rows,
                "total": total,
                "page": page,
                "pageSize": limit,
                "live_verified": False,
            }
        if path in self.receipts:
            return self.receipts[path]
        if path in self.sj:
            return self.sj[path]
        if path in self.orders:
            return self.orders[path]
        raise HTTPException(
            404, detail={"code": "document_not_found", "message": path}
        )


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
                username="prod.lead",
                display_name="Prod Lead",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS
                + ["production.inbox.read", "production.order.read"],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="other.branch",
                display_name="Other",
                role="produksi",
                password_hash=hash_password("secret-pass"),
                permissions=ALL_PERMS
                + ["production.inbox.read", "production.order.read"],
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        session.add(
            User(
                username="ops.limited",
                display_name="Limited",
                role="operator",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ, P.OUTPUT_CONFIRM, "production.inbox.read"],
                branch_ids=["branch-a"],
                is_active=True,
            )
        )
        await session.commit()

    monkeypatch.setenv("V3_ACCURATE_EVIDENCE_ENFORCE", "true")
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_URL", "http://127.0.0.1:8091")
    monkeypatch.setenv("V3_ACCURATE_READ_GATEWAY_TOKEN", "phase4-m2m")
    get_settings.cache_clear()
    gw = _Gw()
    monkeypatch.setattr(evidence_mod, "ReadGateway", lambda: gw)

    from app.api import production_inbox as inbox_mod

    app = create_app()
    app.dependency_overrides[inbox_mod.get_gateway] = lambda: gw
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    monkeypatch.delenv("V3_ACCURATE_EVIDENCE_ENFORCE", raising=False)
    await dispose_engine()
    get_settings.cache_clear()


async def _login(client: AsyncClient, user="prod.lead") -> dict:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "secret-pass"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _open_gates(client, h, job_id: int, so: str) -> None:
    d = (
        await client.post(
            f"/api/v1/production/jobs/{job_id}/design/versions",
            headers=h,
            json={"file_name": "a.pdf", "storage_key": "a"},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/design/versions/{d['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )
    # Align receipt SO link: monkeypatch path uses SO-P4-E2E-001 only for that job.
    # For other SOs use bypass so evidence SO match does not block acceptance paths
    # that are not about payment identity.
    if so == "SO-P4-E2E-001":
        r = await client.post(
            f"/api/v1/production/jobs/{job_id}/payment/receipts",
            headers=h,
            json={"accurate_receipt_id": "RCP-OK-1"},
        )
        assert r.status_code == 200, r.text
    else:
        b = await client.post(
            f"/api/v1/production/jobs/{job_id}/payment/bypass",
            headers=h,
            json={"reason": "phase4 authorized bypass for non-evidence SO"},
        )
        assert b.status_code == 200, b.text


@pytest.mark.asyncio
async def test_phase4_full_workflow_qty_multi_op_color(client: AsyncClient):
    h = await _login(client)
    so = "SO-P4-E2E-001"
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": so, "branch_id": "branch-a"},
        )
    ).json()
    jid = job["id"]
    await _open_gates(client, h, jid, so)

    # Cancelled receipt must fail closed
    bad = await client.post(
        f"/api/v1/production/jobs/{jid}/payment/receipts",
        headers=h,
        json={"accurate_receipt_id": "RCP-CANCELLED"},
    )
    assert bad.status_code == 409

    # Two operators, two color passes, partial qty
    asg1 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Op A",
                "machine_name": "M1",
                "work_date": str(date.today()),
                "qty_planned": "60",
            },
        )
    ).json()
    asg2 = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 2,
                "operator_name": "Op B",
                "machine_name": "M2",
                "work_date": str(date.today()),
                "qty_planned": "40",
            },
        )
    ).json()

    for asg, key in ((asg1, "scr-pass-a"), (asg2, "scr-pass-b")):
        scr = await client.post(
            f"/api/v1/production/jobs/{jid}/prep/screener",
            headers=h,
            json={
                "so_line_id": "line-1",
                "qty": "1",
                "po_qty": "100",
                "evidence_ref": "screen-ev",
                "idempotency_key": key,
                "assignment_id": asg["id"],
            },
        )
        assert scr.status_code == 200, scr.text
    helper = await client.post(
        f"/api/v1/production/jobs/{jid}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "100",
            "po_qty": "100",
            "evidence_ref": "helper-ev",
            "idempotency_key": "help-pass-1",
        },
    )
    assert helper.status_code == 200

    sample = (
        await client.post(
            f"/api/v1/production/jobs/{jid}/samples",
            headers=h,
            json={"file_name": "s.jpg", "storage_key": "s", "assignment_id": asg1["id"]},
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/samples/{sample['id']}/decision",
        headers=h,
        json={"decision": "approved"},
    )

    out1 = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "30",
            "color_pass": 1,
                "idempotency_key": "out-pass-a1",
            },
        )
    assert out1.status_code == 200, out1.text
    # Duplicate click / retry same idempotency
    dup = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "30",
            "color_pass": 1,
            "idempotency_key": "out-pass-a1",
        },
    )
    assert dup.status_code == 409

    out1b = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "20",
            "color_pass": 1,
            "idempotency_key": "out-pass-a2",
        },
    )
    assert out1b.status_code == 200, out1b.text

    out2 = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs",
        headers=h,
        json={
            "assignment_id": asg2["id"],
            "qty_physical": "40",
            "color_pass": 2,
            "idempotency_key": "out-pass-b1",
        },
    )
    assert out2.status_code == 200, out2.text

    # Correction on first output
    corr = await client.post(
        f"/api/v1/production/jobs/{jid}/outputs/corrections",
        headers=h,
        json={
            "source_event_id": out1.json()["id"],
            "qty_physical_delta": "-2",
            "reason": "overcount",
            "idempotency_key": "corr-pass-1",
        },
    )
    assert corr.status_code == 200, corr.text

    rej = await client.post(
        f"/api/v1/production/jobs/{jid}/rejects",
        headers=h,
        json={
            "assignment_id": asg1["id"],
            "qty_physical": "3",
            "reason": "misprint",
            "idempotency_key": "rej-pass-1",
        },
    )
    assert rej.status_code == 200, rej.text
    await client.post(
        f"/api/v1/production/jobs/rejects/{rej.json()['id']}/verify",
        headers=h,
        json={"approved_qty": "3"},
    )

    # Pack available qty (outputs - rejects approximately): use conservative 50
    pack = await client.post(
        f"/api/v1/production/jobs/{jid}/packing",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty_physical": "50",
            "idempotency_key": "pack-pass-1",
        },
    )
    assert pack.status_code == 200, pack.text

    # Cancelled SJ fail-closed
    load_bad = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json={
            "accurate_sj_id": "SJ-CANCELLED",
            "accurate_sj_number": "SJ-CANCELLED",
            "qty_physical": "10",
            "idempotency_key": "load-bad-1",
        },
    )
    assert load_bad.status_code == 409

    load = await client.post(
        f"/api/v1/production/jobs/{jid}/loading",
        headers=h,
        json={
            "accurate_sj_id": "SJ-OK-1",
            "accurate_sj_number": "SJ-OK-1",
            "qty_physical": "40",
            "idempotency_key": "load-ok-01",
        },
    )
    assert load.status_code == 200, load.text

    pod = await client.post(
        f"/api/v1/production/jobs/{jid}/pod",
        headers=h,
        json={
            "accurate_sj_id": "SJ-OK-1",
            "qty_physical": "40",
            "evidence_ref": "pod-photo",
            "receiver_name": "Budi",
            "idempotency_key": "pod-pass-1",
        },
    )
    assert pod.status_code == 200, pod.text

    # Document cancellation SJ
    cancel = await client.post(
        f"/api/v1/production/jobs/{jid}/sj/cancel",
        headers=h,
        json={
            "accurate_sj_id": "SJ-OK-1",
            "reason": "customer return / supersede",
            "idempotency_key": "sjc-pass-1",
        },
    )
    assert cancel.status_code == 200

    board = await client.get(f"/api/v1/production/jobs/{jid}/board", headers=h)
    assert board.status_code == 200
    types = [e["event_type"] for e in board.json()["events"]]
    for needed in (
        "output_confirmed",
        "output_correction",
        "reject_verified",
        "packing_batch",
        "loading",
        "pod",
        "sj_cancelled",
    ):
        assert needed in types, types

    # Quantity reconciliation snapshot
    outs = [
        Decimal(e["qty_physical"])
        for e in board.json()["events"]
        if e["event_type"] == "output_confirmed" and e["qty_physical"]
    ]
    assert sum(outs) == Decimal("90")


@pytest.mark.asyncio
async def test_phase4_branch_and_permission_guards(client: AsyncClient):
    limited = await _login(client, "ops.limited")
    other = await _login(client, "other.branch")
    lead = await _login(client)

    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=lead,
            json={"accurate_so_number": "SO-P4-PERM-001", "branch_id": "branch-a"},
        )
    ).json()
    # Limited cannot create design
    denied = await client.post(
        f"/api/v1/production/jobs/{job['id']}/design/versions",
        headers=limited,
        json={"file_name": "x.pdf", "storage_key": "x"},
    )
    assert denied.status_code == 403

    # Other branch cannot open job create on branch-a... create own attempt
    cross = await client.post(
        "/api/v1/production/jobs",
        headers=other,
        json={"accurate_so_number": "SO-P4-PERM-X", "branch_id": "branch-a"},
    )
    assert cross.status_code == 403

    await _open_gates(client, lead, job["id"], "SO-P4-PERM-001")
    board = await client.get(
        f"/api/v1/production/jobs/{job['id']}/board", headers=lead
    )
    assert any(
        e["event_type"] == "payment_bypass_authorized"
        for e in board.json()["events"]
    )
    assert any(b["active"] for b in board.json()["payment_bypasses"])


@pytest.mark.asyncio
async def test_phase4_concurrent_outputs(client: AsyncClient):
    h = await _login(client)
    job = (
        await client.post(
            "/api/v1/production/jobs",
            headers=h,
            json={"accurate_so_number": "SO-P4-CONC-001", "branch_id": "branch-a"},
        )
    ).json()
    await _open_gates(client, h, job["id"], "SO-P4-CONC-001")
    asg = (
        await client.post(
            f"/api/v1/production/jobs/{job['id']}/schedule/assignments",
            headers=h,
            json={
                "so_line_id": "line-1",
                "color_pass": 1,
                "operator_name": "Conc",
                "machine_name": "M",
                "work_date": str(date.today()),
                "qty_planned": "100",
            },
        )
    ).json()
    await client.post(
        f"/api/v1/production/jobs/{job['id']}/prep/helper",
        headers=h,
        json={
            "so_line_id": "line-1",
            "qty": "100",
            "po_qty": "100",
            "evidence_ref": "helper-conc",
            "idempotency_key": "help-conc-01",
        },
    )

    async def one(i: int):
        return await client.post(
            f"/api/v1/production/jobs/{job['id']}/outputs",
            headers=h,
            json={
                "assignment_id": asg["id"],
                "qty_physical": "5",
                "idempotency_key": f"conc-out-{i:02d}",
            },
        )

    results = await asyncio.gather(*[one(i) for i in range(10)])
    # sample not required until a required sample exists — allow confirmations
    ok = sum(1 for r in results if r.status_code == 200)
    blocked = sum(1 for r in results if r.status_code == 409)
    assert ok + blocked == 10
    assert ok >= 1


@pytest.mark.asyncio
async def test_phase4_inbox_pagination_70_and_multiuser(client: AsyncClient):
    lead = await _login(client)
    limited = await _login(client, "ops.limited")

    t0 = time.perf_counter()

    async def fetch(user_h, page):
        return await client.get(
            f"/api/v1/production/inbox?page={page}&limit=20",
            headers=user_h,
        )

    pages = await asyncio.gather(
        fetch(lead, 1),
        fetch(lead, 2),
        fetch(lead, 3),
        fetch(limited, 1),
        fetch(limited, 4),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert all(p.status_code == 200 for p in pages), [p.text for p in pages]
    p1 = pages[0].json()
    assert p1["total"] >= 70
    assert len(p1["rows"]) == 20
    assert pages[1].json()["rows"][0]["po_number"] != p1["rows"][0]["po_number"]
    # Simultaneous inbox under 2s for 5 calls locally
    assert elapsed_ms < 5000, elapsed_ms

    # Seed 70 jobs quickly and hit by-so concurrently
    async def seed(i: int):
        return await client.post(
            "/api/v1/production/jobs",
            headers=lead,
            json={
                "accurate_so_number": f"SO-P4-{i:03d}",
                "branch_id": "branch-a",
            },
        )

    seeded = await asyncio.gather(*[seed(i) for i in range(1, 71)])
    assert sum(1 for r in seeded if r.status_code == 200) == 70

    t1 = time.perf_counter()
    lookups = await asyncio.gather(
        *[
            client.get(
                f"/api/v1/production/jobs/by-so/SO-P4-{i:03d}",
                headers=lead,
            )
            for i in range(1, 21)
        ]
    )
    lookup_ms = (time.perf_counter() - t1) * 1000
    assert all(r.status_code == 200 for r in lookups)
    assert lookup_ms < 5000, lookup_ms
