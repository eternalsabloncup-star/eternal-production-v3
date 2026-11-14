"""Monitoring Buffer: buffer-only, row per item, official quantities only, scoped."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, update

from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body, sj_line_item
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401
from tests.production.test_operations_phase import J, O, _asg, _job_with_lines

B = f"{O}/buffer"


async def _flag(jid, value=True):
    from app.db.session import get_session_factory
    from app.models.production.job import ProductionJob

    async with get_session_factory()() as s:
        await s.execute(update(ProductionJob).where(ProductionJob.id == jid).values(buffer_stock=value, customer_name="Outlet X"))
        await s.commit()


async def _rows(client, h, **params):
    r = await client.get(B, headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_only_buffer_jobs_multi_item_rows_and_unknown_not_zero(client: AsyncClient):
    h = await _login(client)
    buf = await _job_with_lines(client, h, "SO-BUF", [("L1", "100"), ("L2", "50")], gates=False)
    non = await _job_with_lines(client, h, "SO-NON", [("L1", "10")], gates=False)
    unk = await _job_with_lines(client, h, "SO-UNK", [("L1", "10")], gates=False)
    await _flag(buf, True)
    await _flag(non, False)
    body = await _rows(client, h)
    sos = [i["accurate_so_number"] for i in body["items"]]
    assert sorted(sos) == ["SO-BUF", "SO-BUF"] and body["total"] == 2 and unk
    first = next(i for i in body["items"] if i["so_line_id"] == "L1")
    assert first["total_buffer"] == "100" and first["customer_name"] == "Outlet X"
    assert first["done_gesut"] == "0" and first["delivered"] is None and first["buffer_status"] == "Belum mulai"
    assert [i["so_line_id"] for i in (await _rows(client, h, page=1, page_size=1))["items"]] == ["L1"]
    assert (await _rows(client, h, q="NON"))["items"] == []


async def test_buffer_job_without_synced_lines_has_unverified_quantities(client: AsyncClient):
    h = await _login(client)
    r = await client.post(J, headers=h, json={"accurate_so_number": "SO-BUF-NL", "branch_id": "branch-a", "buffer_stock": True})
    assert r.status_code == 200, r.text
    items = (await _rows(client, h))["items"]
    assert len(items) == 1 and items[0]["total_buffer"] is None and items[0]["done_gesut"] is None and items[0]["delivered"] is None


async def test_buffer_quantities_follow_packing_loading_and_partial_pod(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-BUF-FLOW", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    row = lambda body, ln: next(i for i in body["items"] if i["so_line_id"] == ln)  # noqa: E731
    b = await _rows(client, h)
    assert row(b, "L1")["done_gesut"] == "10" and row(b, "L1")["ready_warehouse"] == "10" and row(b, "L1")["buffer_status"] == "Ready gudang"
    load = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10", idempotency_key="buf-load-001"))
    assert load.status_code == 200, load.text
    b = await _rows(client, h)
    assert row(b, "L1")["ready_warehouse"] == "0" and row(b, "L2")["ready_warehouse"] == "20"
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    pod = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "buf-pod-0001", ids))
    assert pod.status_code == 200, pod.text
    b = await _rows(client, h)
    assert row(b, "L1")["delivered"] == "4" and row(b, "L1")["buffer_status"] == "Sebagian diambil/terkirim"
    assert row(b, "L2")["delivered"] is None and row(b, "L2")["delivered_state"] == "UNVERIFIED"


async def test_multicolor_not_double_counted(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-BUF-MC", [("L1", "100")])
    await _flag(jid)
    for p, m in ((1, "M1"), (2, "M2")):
        r = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", pass_no=p, machine=m))
        assert r.status_code == 200, r.text
    async with get_session_factory()() as s:
        for p, q in ((1, "80"), (2, "60")):
            s.add(ProductionEvent(job_id=jid, event_type="output_helper_verified", so_line_id="L1",
                                  qty_physical=Decimal(q), color_pass=p, idempotency_key=f"mc-hv-{p}-{jid}", actor_user_id=1))
        await s.commit()
    items = (await _rows(client, h))["items"]
    assert items[0]["done_gesut"] == "60" and items[0]["remaining_gesut"] == "40"


async def test_buffer_branch_and_role_isolation(client: AsyncClient):
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-BUF-ISO", [("L1", "10")], gates=False)
    await _flag(jid)
    other = await _login(client, "msj.other")
    assert (await _rows(client, other))["items"] == []
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.user import User

    async with get_session_factory()() as s:
        s.add(User(username="no.read", display_name="n", role="x", password_hash=hash_password("secret-pass"),
                   permissions=[], branch_ids=["branch-a"], is_active=True))
        await s.commit()
    assert (await client.get(B, headers=await _login(client, "no.read"))).status_code == 403
    assert (await client.post(B, headers=h, json={})).status_code in (404, 405)


async def test_multi_item_sj_without_line_receipt_stays_unverified(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-BUF-SJ", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    client._msj["catalog"]["SJ-MIX"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=10),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=20),
    ]
    for line, sj_line, qty, key in (("L1", "A", "10", "mix-load-a1"), ("L2", "B", "20", "mix-load-b1")):
        r = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id="SJ-MIX", accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty, idempotency_key=key))
        assert r.status_code == 200, r.text
    ids = await upload_pod_bundle(client, jid, "SJ-MIX", headers=h)
    pod = await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ-MIX", "15", "mix-pod-0001", ids))
    assert pod.status_code == 422, pod.text
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="pod", qty_physical=Decimal("15"), accurate_sj_id="SJ-MIX",
                              idempotency_key="mix-pod-legacy", actor_user_id=1, reason="receiver:Lama"))
        await s.commit()
    body = await _rows(client, h)
    row = lambda ln: next(i for i in body["items"] if i["so_line_id"] == ln)  # noqa: E731
    assert row("L1")["delivered"] is None and row("L2")["delivered"] is None
    assert row("L1")["delivered_state"] == "UNVERIFIED" and row("L2")["delivered_state"] == "UNVERIFIED"
    assert row("L1")["ready_warehouse"] == "0" and row("L1")["integrity"] is None
    listed = await client.get(f"{O}/deliveries", headers=h)
    sj = next(i for i in listed.json()["items"] if i["accurate_sj_id"] == "SJ-MIX")
    assert Decimal(sj["qty_delivered"]) == Decimal("15")


async def test_unmapped_sj_pod_stays_unknown_and_conflict_is_not_zero(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-BUF-BAD", [("L1", "10")], gates=False)
    await _flag(jid)
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="packing_batch", so_line_id="L1", qty_physical=Decimal("5"),
                              idempotency_key=f"bad-pack-{jid}", actor_user_id=1))
        s.add(ProductionEvent(job_id=jid, event_type="loading", so_line_id="L1", qty_physical=Decimal("8"),
                              accurate_sj_id="SJ-X", accurate_sj_line_id="SLX", idempotency_key=f"bad-load-{jid}",
                              actor_user_id=1, payload_json="{}"))
        s.add(ProductionEvent(job_id=jid, event_type="pod", qty_physical=Decimal("8"), accurate_sj_id="SJ-X",
                              idempotency_key=f"bad-pod-{jid}", actor_user_id=1))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] is None and row["ready_warehouse"] is None
    assert row["integrity"] == "INTEGRITY_CONFLICT" and "packing" in row["integrity_detail"]
    assert row["done_gesut"] == "0"
