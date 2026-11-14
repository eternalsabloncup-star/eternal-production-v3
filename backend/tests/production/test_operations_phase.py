"""Quantity integrity, machine capacity, operator identity, delivery schedule and reports."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401

J = "/api/v1/production/jobs"
O = "/api/v1/production/ops"


async def _job_with_lines(client, h, so, lines, branch="branch-a", gates=True):
    r = await client.post(
        J, headers=h,
        json={
            "accurate_so_number": so, "branch_id": branch,
            "line_items": [
                {"accurate_line_id": lid, "quantity": qty, "production_process": "print"}
                for lid, qty in lines
            ],
        },
    )
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    if gates:
        d = await client.post(f"{J}/{jid}/design/versions", headers=h, json={"file_name": "a.pdf", "storage_key": f"d-{so}"})
        await client.post(f"{J}/design/versions/{d.json()['id']}/decision", headers=h,
                          json={"decision": "approved", "bypass": True, "reason": "test setup bypass"})
        p = await client.post(f"{J}/{jid}/payment/bypass", headers=h, json={"reason": "ops test bypass"})
        assert p.status_code == 200, p.text
    return jid


def _asg(line="L1", qty="10", pass_no=1, machine="M1", day=None, **extra):
    return {
        "so_line_id": line, "color_pass": pass_no, "operator_name": "Op", "machine_name": machine,
        "work_date": str(day or date.today()), "qty_planned": qty, **extra,
    }


@pytest.mark.strict_line_qty
async def test_schedule_cap_per_line_and_pass(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-CAP", [("L1", "100")])
    assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="60"))).status_code == 200
    ok = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="40", machine="M2"))
    assert ok.status_code == 200, ok.text
    over = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="1", machine="M3"))
    assert over.status_code == 409 and "melebihi qty PO" in over.text
    # Pass 2 prints the same cups: its own cap, never summed with pass 1.
    p2 = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", pass_no=2, machine="M4"))
    assert p2.status_code == 200, p2.text
    p2_over = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="1", pass_no=2, machine="M5"))
    assert p2_over.status_code == 409
    # Cancelling the remainder frees capacity again.
    cancel = await client.post(f"{J}/schedule/assignments/{ok.json()['id']}/cancel-remaining", headers=h, json={"reason": "reduce"})
    assert cancel.status_code == 200, cancel.text
    again = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="40", machine="M6"))
    assert again.status_code == 200, again.text


@pytest.mark.strict_line_qty
async def test_schedule_rejects_unsynced_line(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-UNSYNC", [("L1", "10")])
    r = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="NOPE", qty="1"))
    assert r.status_code == 409 and "belum tersinkron" in r.text


@pytest.mark.strict_line_qty
async def test_concurrent_assignments_never_exceed_cap(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-RACE", [("L1", "100")])
    rs = await asyncio.gather(*(
        client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="30", machine=f"M{i}"))
        for i in range(6)
    ))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 3 and codes.count(409) == 3, codes
    board = await client.get(f"{J}/{jid}/board", headers=h)
    planned = sum(float(a["qty_planned"]) for a in board.json()["assignments"])
    assert planned == 90


@pytest.mark.strict_line_qty
async def test_concurrent_transfer_of_same_remainder_moves_once(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-XFER", [("L1", "100")])
    a = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100"))
    body = {"operator_name": "Dewi", "machine_name": "M9", "work_date": str(date.today()), "reason": "move"}
    rs = await asyncio.gather(*(client.post(f"{J}/schedule/assignments/{a.json()['id']}/transfer-remaining", headers=h, json=body) for _ in range(4)))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 1 and codes.count(409) == 3, codes
    board = await client.get(f"{J}/{jid}/board", headers=h)
    active = sum(float(x["qty_planned"]) - float(x.get("qty_cancelled_remaining", 0)) for x in board.json()["assignments"])
    assert active == 100


@pytest.mark.strict_line_qty
async def test_machine_capacity_default_and_multicolor(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-MCH", [("L1", "100"), ("L2", "100")])
    m = await client.post(f"{O}/machines", headers=h, json={"branch_id": "branch-a", "name": "M1", "capacity_per_shift": "100"})
    assert m.status_code == 200, m.text
    d = await client.post(f"{O}/machines", headers=h, json={"branch_id": "branch-a", "name": "SEMI-1", "kind": "semi_auto"})
    assert float(d.json()["capacity_per_shift"]) == 17000 and d.json()["kind"] == "semi_auto"
    assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="L1", qty="60"))).status_code == 200
    # Same cups, second colour pass on the same machine/day does not double the load.
    assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="L1", qty="60", pass_no=2))).status_code == 200
    over = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="L2", qty="50"))
    assert over.status_code == 409 and "Kapasitas mesin" in over.text
    nxt = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="L2", qty="40"))
    assert nxt.status_code == 200, nxt.text
    unknown = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="L2", qty="1", machine="GHOST"))
    assert unknown.status_code == 409 and "tidak terdaftar" in unknown.text
    listing = await client.get(f"{O}/machines", headers=h)
    assert listing.json()["enforced"] is True and float(listing.json()["default_capacity_per_shift"]) == 17000
    patched = await client.patch(f"{O}/machines/{m.json()['id']}", headers=h, json={"capacity_per_shift": "500"})
    assert float(patched.json()["capacity_per_shift"]) == 500


@pytest.mark.strict_line_qty
async def test_concurrent_machine_capacity_across_jobs(client: AsyncClient):
    h = await _login(client)
    j1 = await _job_with_lines(client, h, "SO-MC1", [("L1", "100")])
    j2 = await _job_with_lines(client, h, "SO-MC2", [("L1", "100")])
    await client.post(f"{O}/machines", headers=h, json={"branch_id": "branch-a", "name": "M1", "capacity_per_shift": "100"})
    rs = await asyncio.gather(*(
        client.post(f"{J}/{j}/schedule/assignments", headers=h, json=_asg(qty="60")) for j in (j1, j2, j1 and j2)
    ))
    assert sorted(r.status_code for r in rs).count(200) == 1


@pytest.mark.strict_line_qty
async def test_operator_identity_branch_and_role(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-OPID", [("L1", "100")])
    users = {}
    from app.db.session import get_session_factory
    from app.models.user import User
    async with get_session_factory()() as s:
        from sqlalchemy import select
        for name in ("msj.lead", "msj.other", "return.req"):
            users[name] = (await s.scalar(select(User).where(User.username == name))).id
    ok = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="10", operator_user_id=users["msj.lead"]))
    assert ok.status_code == 200, ok.text
    wrong_branch = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="10", machine="M2", operator_user_id=users["msj.other"]))
    assert wrong_branch.status_code == 409
    no_role = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="10", machine="M3", operator_user_id=users["return.req"]))
    assert no_role.status_code == 409
    ghost = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="10", machine="M4", operator_user_id=99999))
    assert ghost.status_code == 422
    names = await client.get(f"{O}/assignees?branch=branch-a&kind=operator", headers=h)
    assert [i["username"] for i in names.json()["items"]] == ["msj.lead"]


@pytest.mark.strict_line_qty
async def test_operator_tasks_only_for_assigned_operator(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.user import User
    from app.services.production import permissions as P
    async with get_session_factory()() as s:
        for name in ("op.one", "op.two"):
            s.add(User(username=name, display_name=name, role="operator", password_hash=hash_password("secret-pass"),
                       permissions=[P.JOB_READ, P.OUTPUT_CONFIRM], branch_ids=["branch-a"], is_active=True))
        await s.commit()
        from sqlalchemy import select
        one = (await s.scalar(select(User).where(User.username == "op.one"))).id
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-OPT", [("L1", "100")])
    a = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", operator_user_id=one))
    assert a.status_code == 200, a.text
    def operator_tasks(body):
        return [t for t in body["tasks"] if t["role"] == "Operator"]
    lead_all = operator_tasks((await client.get(f"{J}/tasks", headers=h)).json())
    h1, h2 = await _login(client, "op.one"), await _login(client, "op.two")
    mine = operator_tasks((await client.get(f"{J}/tasks", headers=h1)).json())
    other = operator_tasks((await client.get(f"{J}/tasks", headers=h2)).json())
    assert len(mine) == len(lead_all) and other == []


@pytest.mark.strict_loading_cap
async def test_loading_limited_by_packed_qty_sj_and_remaining(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "5")])
    over = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="6", idempotency_key="cap-six-1"))
    assert over.status_code == 409 and "packing sah" in over.text
    ok = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="5", idempotency_key="cap-five-1"))
    assert ok.status_code == 200, ok.text
    replay = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="5", idempotency_key="cap-five-1"))
    assert replay.status_code == 200 and replay.json()["id"] == ok.json()["id"]
    more = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="1", idempotency_key="cap-one-1"))
    assert more.status_code == 409
    rs = await asyncio.gather(*(client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="1", idempotency_key=f"cap-race-{i}")) for i in range(3)))
    assert all(r.status_code == 409 for r in rs)


async def test_pod_needs_name_photos_and_signatures(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10", idempotency_key="pod-load-1"))
    assert load.status_code == 200, load.text
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    short = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "pod-short-1", ids, receiver="A"))
    assert short.status_code == 422 and "minimal 2" in short.text
    body = pod_body("SJ1", "4", "pod-miss-01", ids)
    body.pop("attachment_pod_sig_recipient", None)
    missing = await client.post(f"{J}/{jid}/pod", headers=h, json=body)
    assert missing.status_code in (409, 422), missing.text
    good = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "pod-ok-001", ids, receiver="Budi"))
    assert good.status_code == 200, good.text
    again = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "pod-ok-001", ids, receiver="Budi"))
    assert again.status_code == 200 and again.json()["id"] == good.json()["id"]


async def test_delivery_schedule_plan_reschedule_partial_and_report(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    assert (await client.get(f"{O}/deliveries", headers=h)).json()["items"] == []
    load = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10", idempotency_key="dl-load-1"))
    assert load.status_code == 200, load.text
    rows = (await client.get(f"{O}/deliveries", headers=h)).json()["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["accurate_sj_number"] and row["customer_name"] is None and row["address"] is None
    assert tuple(float(row[k]) for k in ("qty_sj", "qty_loaded", "qty_delivered", "qty_remaining_to_deliver")) == (4000, 10, 0, 10)
    assert row["schedule_status"] == "belum_dijadwalkan" and row["delivery_status"] == "belum_dikirim"
    assert row["courier_name"] is None
    tomorrow = str(date.today() + timedelta(days=1))
    plan = {"accurate_sj_id": "SJ1", "planned_date": tomorrow, "idempotency_key": "plan-1"}
    first = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json=plan)
    assert first.status_code == 200 and first.json()["rescheduled"] is False, first.text
    replay = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json=plan)
    assert replay.json()["replay"] is True and replay.json()["event_id"] == first.json()["event_id"]
    clash = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json={**plan, "planned_date": str(date.today())})
    assert clash.status_code == 409
    no_reason = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json={**plan, "idempotency_key": "plan-2", "planned_date": str(date.today())})
    assert no_reason.status_code == 422
    past = str(date.today() - timedelta(days=2))
    moved = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json={**plan, "idempotency_key": "plan-3", "planned_date": past, "reason": "customer minta"})
    assert moved.status_code == 200 and moved.json()["rescheduled"] is True
    hist = (await client.get(f"{O}/jobs/{jid}/delivery-plan-history?accurate_sj_id=SJ1", headers=h)).json()["items"]
    assert [x["new_date"] for x in hist] == [tomorrow, past] and hist[1]["previous_date"] == tomorrow
    row = (await client.get(f"{O}/deliveries?status=terlambat", headers=h)).json()["items"][0]
    assert row["planned_date"] == past
    bad_courier = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json={**plan, "idempotency_key": "plan-4", "planned_date": tomorrow, "reason": "x", "courier_user_id": 99999})
    assert bad_courier.status_code == 422
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "dl-pod-01", ids, receiver="Siti"))
    assert pod.status_code == 200, pod.text
    row = (await client.get(f"{O}/deliveries", headers=h)).json()["items"][0]
    assert (row["delivery_status"], float(row["qty_delivered"]), float(row["qty_remaining_to_deliver"]), row["recipient_name"]) == ("sebagian", 4, 6, "Siti")
    assert row["po_complete"] is False
    ids2 = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod2 = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "6", "dl-pod-02", ids2, receiver="Siti"))
    assert pod2.status_code == 200, pod2.text
    row = (await client.get(f"{O}/deliveries", headers=h)).json()["items"][0]
    assert float(row["qty_remaining_to_deliver"]) == 0 and row["po_complete"] is True
    done_plan = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=h, json={**plan, "idempotency_key": "plan-5", "planned_date": tomorrow, "reason": "late"})
    assert done_plan.status_code == 409
    rep = (await client.get(f"{O}/reports/summary", headers=h)).json()
    assert rep["source"] == "production_events"
    assert [float(rep["totals"][k]) for k in ("output", "packing", "loading_net", "pod")] == [10, 10, 10, 10]
    assert float(rep["by_branch"]["branch-a"]["pod"]) == 10
    other = await _login(client, "msj.other")
    assert (await client.get(f"{O}/deliveries", headers=other)).json()["items"] == []
    assert (await client.get(f"{O}/reports/summary", headers=other)).json()["totals"]["pod"] in ("0", "0.000", 0)
    denied = await client.post(f"{O}/jobs/{jid}/delivery-plan", headers=other, json={**plan, "idempotency_key": "plan-x"})
    assert denied.status_code == 403


async def test_accurate_qty_drift_keeps_scheduled_qty(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-DRIFT", [("L1", "100")])
    await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="50"))
    sync = {"sync_ensure": True, "jobs": [{"accurate_so_number": "SO-DRIFT", "branch_id": "branch-a",
                                           "line_items": [{"accurate_line_id": "L1", "quantity": "30"}]}]}
    r = await client.post(f"{J}/tasks", headers=h, json=sync)
    assert r.status_code == 200, r.text
    summary = next(j for j in r.json()["jobs"] if j["accurate_so_number"] == "SO-DRIFT")
    assert summary["qty_drift"] == [{"so_line_id": "L1", "po_qty": "100.000", "accurate_qty": "30.000"}]
    # Unscheduled job: Accurate change simply updates the quantity.
    jid2 = await _job_with_lines(client, h, "SO-DRIFT2", [("L1", "100")], gates=False)
    sync["jobs"][0]["accurate_so_number"] = "SO-DRIFT2"
    r2 = await client.post(f"{J}/tasks", headers=h, json=sync)
    s2 = next(j for j in r2.json()["jobs"] if j["accurate_so_number"] == "SO-DRIFT2")
    assert s2["qty_drift"] == [] and jid2
