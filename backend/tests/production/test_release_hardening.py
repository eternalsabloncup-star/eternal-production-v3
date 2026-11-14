"""Release hardening: drift acknowledgement, payroll run list, task visibility, production defaults."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401
from tests.production.test_operations_phase import J, O, _asg, _job_with_lines


async def _drifted_job(client, h, so):
    jid = await _job_with_lines(client, h, so, [("L1", "100")])
    assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="50"))).status_code == 200
    sync = {"sync_ensure": True, "jobs": [{"accurate_so_number": so, "branch_id": "branch-a",
                                           "line_items": [{"accurate_line_id": "L1", "quantity": "30"}]}]}
    assert (await client.post(f"{J}/tasks", headers=h, json=sync)).status_code == 200
    return jid


async def test_qty_drift_acknowledge_contract(client: AsyncClient):
    h = await _login(client)
    jid = await _drifted_job(client, h, "SO-ACK")
    url = f"{O}/jobs/{jid}/qty-drift/acknowledge"
    body = {"so_line_id": "L1", "reason": "Customer konfirmasi qty 30", "idempotency_key": "ack-key-0001"}
    short = await client.post(url, headers=h, json={**body, "reason": "x", "idempotency_key": "ack-key-0002"})
    assert short.status_code == 422
    ok = await client.post(url, headers=h, json=body)
    assert ok.status_code == 200 and ok.json()["replay"] is False, ok.text
    replay = await client.post(url, headers=h, json=body)
    assert replay.status_code == 200 and replay.json() == {"id": ok.json()["id"], "replay": True}
    other_line = await client.post(url, headers=h, json={**body, "so_line_id": "L9"})
    assert other_line.status_code == 409
    no_diff = await client.post(url, headers=h, json={**body, "so_line_id": "L9", "idempotency_key": "ack-key-0003"})
    assert no_diff.status_code == 409
    board = (await client.get(f"{J}/{jid}/board", headers=h)).json()
    line = next(x for x in board["job_lines"] if x["so_line_id"] == "L1")
    assert line["accurate_qty"] and Decimal(str(line["po_qty"])) == Decimal("100")
    assert line["drift_acknowledged"] is True


async def test_qty_drift_acknowledge_is_branch_and_permission_scoped(client: AsyncClient):
    h = await _login(client)
    jid = await _drifted_job(client, h, "SO-ACK2")
    other = await _login(client, "msj.other")
    r = await client.post(f"{O}/jobs/{jid}/qty-drift/acknowledge", headers=other,
                          json={"so_line_id": "L1", "reason": "tidak berwenang", "idempotency_key": "ack-other-01"})
    assert r.status_code in (403, 404)


async def test_payroll_runs_list_read_only_and_branch_scoped(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.production.payroll import PayrollLine, PayrollRun
    from app.models.user import User
    from app.services.production import permissions as P

    async with get_session_factory()() as s:
        for name, branches, perms in (
            ("pay.a", ["branch-a"], [P.PAYROLL_READ]),
            ("pay.b", ["branch-b"], [P.PAYROLL_READ]),
            ("pay.none", ["branch-a"], [P.JOB_READ]),
        ):
            s.add(User(username=name, display_name=name, role="payroll", password_hash=hash_password("secret-pass"),
                       permissions=perms, branch_ids=branches, is_active=True))
        for branch, amount in (("branch-a", "1500.00"), ("branch-b", "700.00")):
            run = PayrollRun(period_start=date(2026, 11, 1), period_end=date(2026, 11, 7), branch_id=branch,
                             status="finalized", idempotency_key=f"run-{branch}", created_by=1, rate_snapshot_json="{}")
            s.add(run)
            await s.flush()
            s.add(PayrollLine(run_id=run.id, operator_name="Op", branch_id=branch, amount_gross=Decimal(amount),
                              source_event_ids="[]", rate_snapshot_json="{}"))
        await s.commit()
        before = len((await s.scalars(select(PayrollRun))).all())
    a = await client.get(f"{O}/payroll/runs", headers=await _login(client, "pay.a"))
    assert a.status_code == 200
    assert [(i["branch_id"], i["amount_gross_total"]) for i in a.json()["items"]] == [("branch-a", "1500.00")]
    b = await client.get(f"{O}/payroll/runs", headers=await _login(client, "pay.b"))
    assert [i["branch_id"] for i in b.json()["items"]] == ["branch-b"]
    assert (await client.get(f"{O}/payroll/runs", headers=await _login(client, "pay.none"))).status_code == 403
    assert (await client.post(f"{O}/payroll/runs", headers=await _login(client, "pay.a"), json={})).status_code in (404, 405)
    async with get_session_factory()() as s:
        assert len((await s.scalars(select(PayrollRun))).all()) == before


async def test_operator_vs_manager_task_visibility(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.user import User
    from app.services.production import permissions as P

    async with get_session_factory()() as s:
        for name in ("vis.op", "vis.other"):
            s.add(User(username=name, display_name=name, role="operator", password_hash=hash_password("secret-pass"),
                       permissions=[P.JOB_READ, P.OUTPUT_CONFIRM], branch_ids=["branch-a"], is_active=True))
        await s.commit()
        uid = (await s.scalar(select(User).where(User.username == "vis.op"))).id
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-VIS", [("L1", "100")])
    asg = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", operator_user_id=uid))
    assert asg.status_code == 200, asg.text
    aid = asg.json()["id"]
    assert (await client.post(f"{J}/{jid}/prep/screener", headers=h, json={
        "so_line_id": "L1", "qty": "1", "po_qty": "100", "screen_size": "kecil", "evidence_ref": "scr",
        "idempotency_key": f"vis-scr-{jid}", "assignment_id": aid})).status_code == 200
    assert (await client.post(f"{J}/{jid}/prep/helper", headers=h, json={
        "so_line_id": "L1", "qty": "100", "po_qty": "100", "evidence_ref": "help",
        "idempotency_key": f"vis-help-{jid}", "assignment_id": aid})).status_code == 200
    smp = await client.post(f"{J}/{jid}/samples", headers=h, json={
        "file_name": "s.jpg", "storage_key": f"s-{jid}", "assignment_id": aid})
    assert smp.status_code == 200, smp.text
    assert (await client.post(f"{J}/samples/{smp.json()['id']}/decision", headers=h, json={
        "decision": "approved", "bypass": True, "reason": "test setup bypass"})).status_code == 200

    def roles(body):
        return {t["role"] for t in body["tasks"]}

    manager = (await client.get(f"{J}/tasks", headers=h)).json()
    op = (await client.get(f"{J}/tasks", headers=await _login(client, "vis.op"))).json()
    other = (await client.get(f"{J}/tasks", headers=await _login(client, "vis.other"))).json()
    assert "Operator" in roles(manager)
    assert roles(op) <= {"Operator"} and "Operator" in roles(op)
    assert roles(other) == set()


@pytest.mark.production_defaults
def test_production_safety_defaults_are_on():
    from app.services.production import engine

    assert engine.REQUIRE_SYNCED_LINE_QTY is True
    assert engine.ENFORCE_LOADING_PACKING_CAP is True


@pytest.mark.production_defaults
async def test_default_config_concurrent_schedule_and_loading_never_exceed(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-DEF", [("L1", "100")])
    rs = await asyncio.gather(*(client.post(f"{J}/{jid}/schedule/assignments", headers=h,
                                            json=_asg(qty="30", machine=f"MD{i}")) for i in range(6)))
    assert sorted(r.status_code for r in rs).count(200) == 3
    assert all(r.status_code in (200, 409) for r in rs)
    unsynced = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="NOPE", qty="1", machine="MX"))
    assert unsynced.status_code == 409

    pj = await _seed_packed(client, h, lines=[("L1", "5")], synced=True)
    lrs = await asyncio.gather(*(client.post(f"{J}/{pj}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="3",
        idempotency_key=f"def-race-{i}")) for i in range(4)))
    assert sorted(r.status_code for r in lrs).count(200) == 1
    over = await client.post(f"{J}/{pj}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="3", idempotency_key="def-over-1"))
    assert over.status_code == 409
    ids = await upload_pod_bundle(client, pj, "SJ1", headers=h)
    pods = await asyncio.gather(*(client.post(f"{J}/{pj}/pod", headers=h, json=pod_body("SJ1", "3", f"def-pod-{i:03d}", ids, receiver="Budi"))
                                  for i in range(3)))
    assert sorted(r.status_code for r in pods).count(200) <= 3
    over_pod = await client.post(f"{J}/{pj}/pod", headers=h, json=pod_body("SJ1", "9", "def-pod-over", ids, receiver="Budi"))
    assert over_pod.status_code in (409, 422)
