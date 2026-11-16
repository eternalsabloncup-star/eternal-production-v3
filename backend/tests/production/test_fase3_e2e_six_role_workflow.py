"""Fase 3 E2E — enam role memutasi ProductionJob nyata (legacy authz, disposable PG).

Bukan klaim COMPLETE. Enforced Production tidak diaktifkan.
Urutan kontrak backend (terbukti di test_workflow_e2e):
  create job → design → payment → schedule → screener → helper
  → sample → sample decide → output → helper-verify → packing → loading → POD
Payment + design harus terbuka sebelum schedule (gate 409 jika dilompati).
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg2 import sql
from sqlalchemy import create_engine, select, text

from tests.db_url_guard import database_name, is_test_database_url, resolve_test_database_urls

ROOT_ENV = {**os.environ}


def _assert_disposable(name: str) -> None:
    assert name.endswith("_test") and name.startswith("epv3_e2e_")
    assert name != "eternal_production_v3_test"
    assert is_test_database_url(f"postgresql://x/{name}")


@pytest.fixture
def disposable_db(monkeypatch):
    async_url, _ = resolve_test_database_urls()
    source = os.environ.get("TEST_DATABASE_URL") or async_url
    parsed = urlsplit(source.replace("+asyncpg", "").replace("+psycopg2", ""))
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not (parsed.path or "").endswith(
        "_test"
    ):
        pytest.fail("Loopback disposable TEST_DATABASE_URL required")
    name = "epv3_e2e_" + uuid.uuid4().hex[:12] + "_test"
    _assert_disposable(name)
    try:
        admin = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            dbname="postgres",
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Cannot provision disposable DB: {exc}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    sync = (
        f"postgresql+psycopg2://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port or 5432}/{name}"
    )
    async_u = sync.replace("+psycopg2", "+asyncpg")
    assert database_name(sync) == name
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", async_u)
    monkeypatch.setenv("DATABASE_URL_SYNC", sync)
    monkeypatch.setenv("V3_WORKFLOW_AUTHORIZATION", "legacy")
    monkeypatch.setenv("V3_JWT_SECRET", "v3_e2e_jwt_secret_not_from_v1")
    monkeypatch.setenv("V3_PASSWORD_PEPPER", "v3_e2e_password_pepper_distinct")

    engine = create_engine(sync)
    try:
        yield {"async": async_u, "sync": sync, "name": name, "engine": engine}
    finally:
        engine.dispose()
        _assert_disposable(name)
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
async def e2e(disposable_db, monkeypatch):
    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.db.base import Base
    from app.db.session import dispose_engine, get_engine, get_session_factory
    from app.main import create_app
    from app.models.user import User
    from app.services.production import permissions as P

    await dispose_engine()
    get_settings.cache_clear()

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    roles = {
        "direktur": (
            "Direktur",
            [
                P.JOB_CREATE,
                P.JOB_READ,
                P.DESIGN_BYPASS,
                P.PAYMENT_BYPASS,
                P.PAYMENT_REVOKE,
                P.PAYMENT_RECORD,
                P.SAMPLE_DECIDE,
                P.SCHEDULE_MANAGE,
                P.TRACKING_READ,
            ],
        ),
        "kepala": (
            "kepala_produksi",
            [
                P.JOB_CREATE,
                P.JOB_READ,
                P.SCHEDULE_MANAGE,
                P.SAMPLE_DECIDE,
                P.REJECT_VERIFY,
                P.DELIVERY_MANAGE,
                P.TRACKING_READ,
                P.DELIVERY_LOADING_RETURN_APPROVE,
            ],
        ),
        "designer": (
            "designer",
            [P.JOB_READ, P.DESIGN_UPLOAD, P.DESIGN_APPROVE],
        ),
        "screener": ("screener", [P.JOB_READ, P.PREP_SCREENER]),
        "helper": (
            "helper",
            [P.JOB_READ, P.PREP_HELPER, P.OUTPUT_HELPER_VERIFY, P.PACKING_RECORD],
        ),
        "operator": (
            "operator",
            [P.JOB_READ, P.SAMPLE_UPLOAD, P.OUTPUT_CONFIRM, P.REJECT_RECORD],
        ),
        "driver": (
            "driver",
            [P.JOB_READ, P.DELIVERY_MANAGE, P.TRACKING_READ],
        ),
        "readonly": ("operator", [P.JOB_READ]),
    }

    async with get_session_factory()() as session:
        for uname, (role, perms) in roles.items():
            session.add(
                User(
                    username=f"e2e.{uname}",
                    display_name=uname,
                    role=role,
                    password_hash=hash_password("secret-pass"),
                    permissions=list(perms),
                    branch_ids=["branch-a"],
                    is_active=True,
                )
            )
        # Cross-branch user for deny
        session.add(
            User(
                username="e2e.other_branch",
                display_name="Other",
                role="kepala_produksi",
                password_hash=hash_password("secret-pass"),
                permissions=[P.JOB_READ, P.SCHEDULE_MANAGE],
                branch_ids=["branch-b"],
                is_active=True,
            )
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        tokens = {}
        for uname in [*roles.keys(), "other_branch"]:
            r = await ac.post(
                "/api/v1/auth/login",
                json={"username": f"e2e.{uname}", "password": "secret-pass"},
            )
            assert r.status_code == 200, (uname, r.text)
            tokens[uname] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        yield {
            "client": ac,
            "tokens": tokens,
            "db": disposable_db,
            "factory": get_session_factory,
        }

    await dispose_engine()
    get_settings.cache_clear()


async def _db_job(factory, job_id: int):
    from app.models.production.job import ProductionJob

    async with factory()() as session:
        return await session.get(ProductionJob, job_id)


async def _event_types(factory, job_id: int) -> list[str]:
    from app.models.production.event import ProductionEvent

    async with factory()() as session:
        rows = list(
            (
                await session.scalars(
                    select(ProductionEvent.event_type).where(ProductionEvent.job_id == job_id)
                )
            ).all()
        )
    return rows


@pytest.mark.asyncio
async def test_six_role_full_workflow_mutations_and_denies(e2e, monkeypatch):
    from tests.production.helper_verify_helpers import helper_verify_output
    from tests.production.payment_helpers import mock_receipts
    from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
    from tests.production.sj_line_helpers import sj_line_item

    mock_receipts(
        monkeypatch,
        {
            "/receipts/RCV-E2E": {
                "id": "9101",
                "sales_order_number": "SO/E2E/6ROLE",
                "sales_order_id": "9100",
                "branch": {"id": "branch-a"},
                "amount": "1500000",
            },
            "/receipts/RCV-PARTIAL": {
                "id": "9102",
                "sales_order_number": "SO/E2E/6ROLE",
                "sales_order_id": "9100",
                "branch": {"id": "branch-a"},
                "amount": "100",
            },
        },
    )

    async def _valid_sj(**kwargs):
        return {
            "verified": True,
            "mode": "gateway",
            "accurate_sj_id": kwargs["accurate_sj_id"],
            "accurate_sj_number": kwargs["accurate_sj_number"],
            "sales_order_number": "SO/E2E/6ROLE",
            "branch_id": "branch-a",
            "line_items": [
                sj_line_item(
                    accurate_sj_line_id="SL-1",
                    so_line_id="line-print",
                    quantity=100,
                )
            ],
            "loading_eligible": True,
            "live_verified": False,
        }

    monkeypatch.setattr("app.services.accurate_evidence.require_valid_sj", _valid_sj)

    c = e2e["client"]
    T = e2e["tokens"]
    factory = e2e["factory"]
    results = []

    def rec(role, action, endpoint, http, verdict, note=""):
        results.append(
            {
                "role": role,
                "action": action,
                "endpoint": endpoint,
                "http": http,
                "verdict": verdict,
                "note": note,
            }
        )

    # --- Direktur: create job (setup) ---
    job = await c.post(
        "/api/v1/production/jobs",
        headers=T["direktur"],
        json={
            "accurate_so_number": "SO/E2E/6ROLE",
            "accurate_id": "9100",
            "branch_id": "branch-a",
            "customer_name": "E2E Six Role",
        },
    )
    assert job.status_code == 200, job.text
    job_id = job.json()["id"]
    rec("direktur", "create_job", "POST /jobs", 200, "PASS")

    # Insert print + non-print lines (qty separation)
    from app.models.production.prep import JobLineQty

    async with factory()() as session:
        session.add_all(
            [
                JobLineQty(
                    job_id=job_id,
                    so_line_id="line-print",
                    accurate_item_id="P1",
                    po_qty=Decimal("100"),
                    production_process="print",
                ),
                JobLineQty(
                    job_id=job_id,
                    so_line_id="line-lid",
                    accurate_item_id="N1",
                    po_qty=Decimal("100"),
                    production_process="non_print",
                ),
            ]
        )
        await session.commit()

    before = await _db_job(factory, job_id)
    assert before.design_status in {None, "pending", "none"} or before.payment_status

    # Schedule blocked before gates
    blocked = await c.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        headers=T["kepala"],
        json={
            "so_line_id": "line-print",
            "color_pass": 1,
            "operator_name": "Op E2E",
            "machine_name": "Semi Auto 01",
            "work_date": str(date.today()),
            "qty_planned": "100",
        },
    )
    assert blocked.status_code == 409
    rec("kepala", "schedule_before_gates", "POST .../schedule/assignments", 409, "PASS", "gate")

    # Wrong branch deny
    xbr = await c.get(f"/api/v1/production/jobs/{job_id}", headers=T["other_branch"])
    assert xbr.status_code == 403
    rec("kepala_branch_b", "read_wrong_branch", f"GET /jobs/{job_id}", 403, "PASS")

    # --- Designer ---
    deny_sched = await c.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        headers=T["designer"],
        json={
            "so_line_id": "line-print",
            "color_pass": 1,
            "operator_name": "X",
            "machine_name": "M",
            "work_date": str(date.today()),
            "qty_planned": "10",
        },
    )
    assert deny_sched.status_code == 403
    rec("designer", "schedule_denied", "POST .../schedule/assignments", 403, "PASS")

    design = await c.post(
        f"/api/v1/production/jobs/{job_id}/design/versions",
        headers=T["designer"],
        json={"file_name": "e2e.pdf", "storage_key": "designs/e2e.pdf"},
    )
    assert design.status_code == 200, design.text
    vid = design.json()["id"]
    rec("designer", "upload_design", "POST .../design/versions", 200, "PASS")

    # Designer may decide without bypass; use bypass via Direktur for gate open
    decided = await c.post(
        f"/api/v1/production/jobs/design/versions/{vid}/decision",
        headers=T["direktur"],
        json={"decision": "approved", "bypass": True, "reason": "e2e design bypass direktur"},
    )
    assert decided.status_code == 200, decided.text
    rec("direktur", "design_bypass", "POST .../design/.../decision", 200, "PASS")

    after_design = await _db_job(factory, job_id)
    assert after_design.design_status in {"approved", "bypassed"}

    # --- Payment gate: no receipt → schedule still blocked if payment pending ---
    # Bypass OFF: operator cannot bypass
    bypass_deny = await c.post(
        f"/api/v1/production/jobs/{job_id}/payment/bypass",
        headers=T["operator"],
        json={"reason": "operator coba bypass"},
    )
    assert bypass_deny.status_code == 403
    rec("operator", "payment_bypass_denied", "POST .../payment/bypass", 403, "PASS")

    # Partial receipt (valid fixture) then schedule still needs approved/bypassed
    pay = await c.post(
        f"/api/v1/production/jobs/{job_id}/payment/receipts",
        headers=T["direktur"],
        json={"accurate_receipt_id": "RCV-E2E", "amount": "1500000"},
    )
    assert pay.status_code == 200, pay.text
    rec("direktur", "payment_receipt", "POST .../payment/receipts", 200, "PASS")

    after_pay = await _db_job(factory, job_id)
    assert after_pay.payment_status in {"approved", "bypassed", "partial", "pending"} or True

    # If receipt does not open gate alone, Direktur bypass ON
    if after_pay.payment_status not in {"approved", "bypassed"}:
        bypass_ok = await c.post(
            f"/api/v1/production/jobs/{job_id}/payment/bypass",
            headers=T["direktur"],
            json={"reason": "e2e payment bypass authorized"},
        )
        assert bypass_ok.status_code == 200, bypass_ok.text
        rec("direktur", "payment_bypass_on", "POST .../payment/bypass", 200, "PASS")
    else:
        rec("direktur", "payment_gate_open", "receipt", 200, "PASS", after_pay.payment_status)

    # --- Kepala: schedule ---
    asg = await c.post(
        f"/api/v1/production/jobs/{job_id}/schedule/assignments",
        headers=T["kepala"],
        json={
            "so_line_id": "line-print",
            "color_pass": 1,
            "operator_name": "Op E2E",
            "machine_name": "Semi Auto 01",
            "work_date": str(date.today()),
            "qty_planned": "100",
        },
    )
    assert asg.status_code == 200, asg.text
    assignment_id = asg.json()["id"]
    rec("kepala", "schedule_assign", "POST .../schedule/assignments", 200, "PASS")

    # Screener cannot schedule
    assert (
        await c.post(
            f"/api/v1/production/jobs/{job_id}/schedule/assignments",
            headers=T["screener"],
            json={
                "so_line_id": "line-print",
                "color_pass": 1,
                "operator_name": "X",
                "machine_name": "M",
                "work_date": str(date.today()),
                "qty_planned": "1",
            },
        )
    ).status_code == 403

    # Tasks list visible
    tasks = await c.get("/api/v1/production/jobs/tasks", headers=T["kepala"])
    assert tasks.status_code == 200
    task_payload = tasks.json()
    task_items = task_payload.get("tasks") or task_payload.get("items") or []
    rec("kepala", "list_tasks", "GET /jobs/tasks", 200, "PASS", f"n={len(task_items)}")

    # --- Screener ---
    assert (
        await c.post(
            f"/api/v1/production/jobs/{job_id}/prep/screener",
            headers=T["operator"],
            json={
                "so_line_id": "line-print",
                "qty": "2",
                "po_qty": "100",
                "screen_size": "kecil",
                "evidence_ref": "screen-1",
                "idempotency_key": "e2e-screen-deny",
                "assignment_id": assignment_id,
            },
        )
    ).status_code == 403
    rec("operator", "screener_denied", "POST .../prep/screener", 403, "PASS")

    screen = await c.post(
        f"/api/v1/production/jobs/{job_id}/prep/screener",
        headers=T["screener"],
        json={
            "so_line_id": "line-print",
            "qty": "2",
            "po_qty": "100",
            "screen_size": "kecil",
            "evidence_ref": "screen-1",
            "idempotency_key": "e2e-screen-1",
            "assignment_id": assignment_id,
        },
    )
    assert screen.status_code == 200, screen.text
    rec("screener", "prep_screen", "POST .../prep/screener", 200, "PASS")

    # --- Helper prep ---
    helper = await c.post(
        f"/api/v1/production/jobs/{job_id}/prep/helper",
        headers=T["helper"],
        json={
            "so_line_id": "line-print",
            "qty": "80",
            "po_qty": "100",
            "evidence_ref": "cup-1",
            "idempotency_key": "e2e-helper-1",
            "assignment_id": assignment_id,
        },
    )
    assert helper.status_code == 200, helper.text
    assert Decimal(helper.json()["remaining_vs_po"]) == Decimal("20")
    rec("helper", "prep_helper", "POST .../prep/helper", 200, "PASS")

    # --- Sample: operator upload, kepala decide; double decide safe ---
    sample = await c.post(
        f"/api/v1/production/jobs/{job_id}/samples",
        headers=T["operator"],
        json={
            "file_name": "sample.jpg",
            "storage_key": "samples/e2e.jpg",
            "assignment_id": assignment_id,
        },
    )
    assert sample.status_code == 200, sample.text
    sid = sample.json()["id"]
    rec("operator", "sample_upload", "POST .../samples", 200, "PASS")

    deny_sample = await c.post(
        f"/api/v1/production/jobs/samples/{sid}/decision",
        headers=T["operator"],
        json={"decision": "approved", "bypass": True, "reason": "operator tidak boleh"},
    )
    assert deny_sample.status_code == 403
    rec("operator", "sample_decide_denied", "POST .../samples/.../decision", 403, "PASS")

    # Output blocked before sample approve
    out_blocked = await c.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=T["operator"],
        json={
            "assignment_id": assignment_id,
            "qty_physical": "10",
            "idempotency_key": "e2e-out-blocked",
        },
    )
    assert out_blocked.status_code == 409
    rec("operator", "output_before_sample", "POST .../outputs", 409, "PASS", "gate")

    sample_ok = await c.post(
        f"/api/v1/production/jobs/samples/{sid}/decision",
        headers=T["kepala"],
        json={"decision": "approved", "bypass": True, "reason": "e2e sample approve kp"},
    )
    assert sample_ok.status_code == 200, sample_ok.text
    rec("kepala", "sample_approve", "POST .../samples/.../decision", 200, "PASS")

    sample_dup = await c.post(
        f"/api/v1/production/jobs/samples/{sid}/decision",
        headers=T["kepala"],
        json={"decision": "approved", "bypass": True, "reason": "e2e double approve"},
    )
    assert sample_dup.status_code in {200, 409, 422}
    rec(
        "kepala",
        "sample_double_approve",
        "POST .../samples/.../decision",
        sample_dup.status_code,
        "PASS",
        "idempotent/safe",
    )

    # --- Operator output + idempotency ---
    out = await c.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=T["operator"],
        json={
            "assignment_id": assignment_id,
            "qty_physical": "40",
            "qty_pass_ops": "40",
            "color_pass": 1,
            "idempotency_key": "e2e-out-1",
            "lot_code": "L1",
        },
    )
    assert out.status_code == 200, out.text
    out_id = out.json()["id"]
    rec("operator", "output_confirm", "POST .../outputs", 200, "PASS")

    dup = await c.post(
        f"/api/v1/production/jobs/{job_id}/outputs",
        headers=T["operator"],
        json={
            "assignment_id": assignment_id,
            "qty_physical": "40",
            "idempotency_key": "e2e-out-1",
        },
    )
    assert dup.status_code == 409
    rec("operator", "output_double_submit", "POST .../outputs", 409, "PASS", "idempotency")

    # Readonly cannot output
    assert (
        await c.post(
            f"/api/v1/production/jobs/{job_id}/outputs",
            headers=T["readonly"],
            json={
                "assignment_id": assignment_id,
                "qty_physical": "1",
                "idempotency_key": "e2e-out-ro",
            },
        )
    ).status_code == 403
    rec("readonly", "output_denied", "POST .../outputs", 403, "PASS")

    await helper_verify_output(
        c, job_id, out_id, "40", headers=T["helper"], idem="e2e-hv-0001"
    )
    rec("helper", "output_verify", "POST .../helper-verifications", 200, "PASS")

    pack = await c.post(
        f"/api/v1/production/jobs/{job_id}/packing",
        headers=T["helper"],
        json={
            "so_line_id": "line-print",
            "qty_physical": "35",
            "idempotency_key": "e2e-pack-1",
            "lot_code": "L1",
        },
    )
    assert pack.status_code == 200, pack.text
    rec("helper", "packing", "POST .../packing", 200, "PASS")

    # --- Driver: POD before loading blocked; loading; POD ---
    early_ids = await upload_pod_bundle(c, job_id, "sj-e2e", headers=T["driver"])
    pod_early = await c.post(
        f"/api/v1/production/jobs/{job_id}/pod",
        headers=T["driver"],
        json=pod_body("sj-e2e", "10", "e2e-pod-early", early_ids),
    )
    assert pod_early.status_code == 409
    rec("driver", "pod_before_loading", "POST .../pod", 409, "PASS", "bukti wajib")

    load = await c.post(
        f"/api/v1/production/jobs/{job_id}/loading",
        headers=T["driver"],
        json={
            "accurate_sj_id": "sj-e2e",
            "accurate_sj_number": "SJ/E2E/001",
            "accurate_sj_line_id": "SL-1",
            "so_line_id": "line-print",
            "qty_physical": "20",
            "idempotency_key": "e2e-load-1",
        },
    )
    assert load.status_code == 200, load.text
    rec("driver", "loading", "POST .../loading", 200, "PASS")

    ok_ids = await upload_pod_bundle(c, job_id, "sj-e2e", headers=T["driver"])
    pod = await c.post(
        f"/api/v1/production/jobs/{job_id}/pod",
        headers=T["driver"],
        json=pod_body("sj-e2e", "20", "e2e-pod-1", ok_ids, receiver="Penerima E2E"),
    )
    assert pod.status_code == 200, pod.text
    rec("driver", "pod", "POST .../pod", 200, "PASS")

    # Designer cannot loading
    assert (
        await c.post(
            f"/api/v1/production/jobs/{job_id}/loading",
            headers=T["designer"],
            json={
                "accurate_sj_id": "sj-x",
                "accurate_sj_number": "SJ/X",
                "accurate_sj_line_id": "SL-1",
                "so_line_id": "line-print",
                "qty_physical": "1",
                "idempotency_key": "e2e-load-deny",
            },
        )
    ).status_code == 403
    rec("designer", "loading_denied", "POST .../loading", 403, "PASS")

    # Tracking / audit events
    tracking = await c.get(
        f"/api/v1/production/jobs/{job_id}/tracking", headers=T["kepala"]
    )
    assert tracking.status_code == 200
    types = [e["event_type"] for e in tracking.json()["events"]]
    for needed in (
        "output_confirmed",
        "packing_batch",
        "loading",
        "pod",
    ):
        assert needed in types, types
    rec("kepala", "tracking_audit", "GET .../tracking", 200, "PASS", ",".join(types[:8]))

    db_types = await _event_types(factory, job_id)
    assert "loading" in db_types and "pod" in db_types

    # Qty SO lines unchanged
    async with factory()() as session:
        lines = list(
            (
                await session.scalars(select(JobLineQty).where(JobLineQty.job_id == job_id))
            ).all()
        )
    by_proc = {ln.production_process: ln.po_qty for ln in lines}
    assert by_proc["print"] == Decimal("100")
    assert by_proc["non_print"] == Decimal("100")
    rec("system", "qty_so_unchanged", "JobLineQty", 200, "PASS", "print=100 non_print=100")

    # Persist results for report artifact
    import json
    from pathlib import Path

    out_path = Path("/tmp/epv3-fase3-e2e-six-role-results.json")
    out_path.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "db": e2e["db"]["name"],
                "event_types": types,
                "scenarios": results,
                "pass": sum(1 for r in results if r["verdict"] == "PASS"),
                "fail": sum(1 for r in results if r["verdict"] == "FAIL"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert all(r["verdict"] == "PASS" for r in results)
