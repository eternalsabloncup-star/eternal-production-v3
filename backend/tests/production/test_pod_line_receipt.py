"""POD is an SJ total. Per-item qty exists only when an actual line receipt is stored."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body, sj_line_item
from tests.production.test_buffer_monitor import B, _flag, _rows
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401
from tests.production.test_operations_phase import J, O


def _line(sj_line, so_line, qty):
    return {"accurate_sj_line_id": sj_line, "so_line_id": so_line, "qty_physical": qty}


async def test_single_item_partial_pod_uses_the_sj_qty(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-ONE", lines=[("L1", "10")], synced=True)
    await _flag(jid)
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10",
        idempotency_key="one-load-01"))).status_code == 200
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "4", "one-pod-0001", ids))).status_code == 200
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] == "4" and row["delivered_state"] == "VERIFIED"
    assert row["buffer_status"] == "Sebagian diambil/terkirim"


async def test_full_pod_with_valid_line_relation(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-FULL", lines=[("L1", "10")], synced=True)
    await _flag(jid)
    await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10", idempotency_key="full-load-1"))
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    body = pod_body("SJ1", "10", "full-pod-0001", ids)
    body["lines"] = [_line("SL1", "L1", "10")]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=body)).status_code == 200
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] == "10" and row["buffer_status"] == "Selesai diambil/terkirim"


async def test_two_item_receipt_is_the_actual_qty_and_replay_does_not_double(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-LINE", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    client._msj["catalog"]["SJ-MIX"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=10),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=20),
    ]
    for line, sj_line, qty, key in (("L1", "A", "10", "line-load-a1"), ("L2", "B", "20", "line-load-b1")):
        assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id="SJ-MIX", accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty,
            idempotency_key=key))).status_code == 200
    ids = await upload_pod_bundle(client, jid, "SJ-MIX", headers=h)
    body = pod_body("SJ-MIX", "15", "line-pod-0001", ids)
    body["lines"] = [_line("A", "L1", "6"), _line("B", "L2", "9")]
    first = await client.post(f"{J}/{jid}/pod", headers=h, json=body)
    assert first.status_code == 200, first.text
    replay = await client.post(f"{J}/{jid}/pod", headers=h, json=body)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    other = dict(body, lines=[_line("A", "L1", "7"), _line("B", "L2", "8")])
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=other)).status_code == 409
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["L1"]["delivered"] == "6" and rows["L2"]["delivered"] == "9"
    assert rows["L1"]["delivered_state"] == "VERIFIED"
    listed = (await client.get(f"{O}/deliveries", headers=h)).json()
    assert Decimal(next(i["qty_delivered"] for i in listed["items"] if i["accurate_sj_id"] == "SJ-MIX")) == Decimal("15")
    report = (await client.get(f"{O}/reports/summary", headers=h)).json()
    assert Decimal(report["totals"]["pod"]) == Decimal("15")


async def test_cancelled_sj_drops_pod_from_item_and_report_without_rewriting_it(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-CAN", lines=[("L1", "10")], synced=True)
    await _flag(jid)
    await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="10", idempotency_key="can-load-01"))
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "10", "can-pod-0001", ids))).status_code == 200
    before = Decimal((await client.get(f"{O}/reports/summary", headers=h)).json()["totals"]["pod"])
    async with get_session_factory()() as s:
        pod = await s.scalar(select(ProductionEvent).where(ProductionEvent.idempotency_key == "can-pod-0001"))
        original = pod.qty_physical
        s.add(ProductionEvent(job_id=jid, event_type="sj_cancelled", accurate_sj_id="SJ1", qty_physical=0,
                              idempotency_key=f"can-sj-{jid}", actor_user_id=1, reason="dibatalkan"))
        await s.commit()
    async with get_session_factory()() as s:
        pod = await s.scalar(select(ProductionEvent).where(ProductionEvent.idempotency_key == "can-pod-0001"))
        assert pod.qty_physical == original
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] is None and row["delivered_state"] == "UNVERIFIED"
    after = Decimal((await client.get(f"{O}/reports/summary", headers=h)).json()["totals"]["pod"])
    assert before - after == Decimal("10")


async def test_unverified_item_qty_is_not_counted_as_zero_in_a_sum(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-UNK", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    client._msj["catalog"]["SJ-MIX"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=10),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=20),
    ]
    for line, sj_line, qty, key in (("L1", "A", "10", "unk-load-a1"), ("L2", "B", "20", "unk-load-b1")):
        await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id="SJ-MIX", accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty, idempotency_key=key))
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="pod", qty_physical=Decimal("15"), accurate_sj_id="SJ-MIX",
                              idempotency_key="unk-pod-legacy", actor_user_id=1, reason="receiver:Lama"))
        await s.commit()
    items = (await _rows(client, h))["items"]
    assert all(i["delivered"] is None for i in items)
    verified = [Decimal(i["delivered"]) for i in items if i["delivered_state"] == "VERIFIED"]
    assert sum(verified, Decimal(0)) == 0
    assert Decimal((await client.get(f"{O}/reports/summary", headers=h)).json()["totals"]["pod"]) == Decimal("15")


async def _two_loaded(client, h, so, qty_a, qty_b, sj):
    jid = await _seed_packed(client, h, so=so, lines=[("L1", qty_a), ("L2", qty_b)], synced=True)
    await _flag(jid)
    client._msj["catalog"][sj] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=int(qty_a)),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=int(qty_b)),
    ]
    for line, sj_line, qty, key in (("L1", "A", qty_a, f"{sj}-a"), ("L2", "B", qty_b, f"{sj}-b")):
        assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id=sj, accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty, idempotency_key=key))).status_code == 200
    return jid


async def test_multi_item_explicit_zero_is_verified_and_replay_does_not_double(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent

    h = await _login(client)
    jid = await _two_loaded(client, h, "SO-ZERO", "1000", "1000", "SJ-ZERO")
    ids = await upload_pod_bundle(client, jid, "SJ-ZERO", headers=h)
    body = pod_body("SJ-ZERO", "1000", "zero-pod-0001", ids)
    body["lines"] = [_line("A", "L1", "1000"), _line("B", "L2", "0")]
    first = await client.post(f"{J}/{jid}/pod", headers=h, json=body)
    assert first.status_code == 200, first.text
    replay = await client.post(f"{J}/{jid}/pod", headers=h, json=body)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    async with get_session_factory()() as s:
        ev = await s.scalar(select(ProductionEvent).where(ProductionEvent.id == first.json()["id"]))
        assert '"explicit_zero":true' in (ev.payload_json or "")
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["L1"]["delivered"] == "1000" and rows["L1"]["delivered_state"] == "VERIFIED"
    assert rows["L2"]["delivered"] == "0" and rows["L2"]["delivered_state"] == "VERIFIED"
    blank = pod_body("SJ-ZERO", "1000", "zero-pod-blank", ids)
    blank["lines"] = [_line("A", "L1", "1000"), {"accurate_sj_line_id": "B", "so_line_id": "L2", "qty_physical": None}]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=blank)).status_code == 422
    again = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert again["L1"]["delivered"] == "1000" and again["L2"]["delivered"] == "0"


async def test_multi_item_split_600_400_and_bad_sum_or_missing_line(client: AsyncClient):
    h = await _login(client)
    jid = await _two_loaded(client, h, "SO-SPLIT", "600", "400", "SJ-SPLIT")
    ids = await upload_pod_bundle(client, jid, "SJ-SPLIT", headers=h)
    bad_sum = pod_body("SJ-SPLIT", "1000", "split-bad-sum1", ids)
    bad_sum["lines"] = [_line("A", "L1", "600"), _line("B", "L2", "300")]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=bad_sum)).status_code == 422
    missing = pod_body("SJ-SPLIT", "600", "split-missing1", ids)
    missing["lines"] = [_line("A", "L1", "600")]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=missing)).status_code == 422
    ok = pod_body("SJ-SPLIT", "1000", "split-ok-0001", ids)
    ok["lines"] = [_line("A", "L1", "600"), _line("B", "L2", "400")]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=ok)).status_code == 200
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["L1"]["delivered"] == "600" and rows["L2"]["delivered"] == "400"


async def test_pod_lines_rejected_without_permission_or_from_another_branch(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.user import User
    from app.services.production import permissions as P

    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-POD-SCOPE", lines=[("L1", "10")], synced=True)
    await _flag(jid)
    async with get_session_factory()() as s:
        s.add(User(username="pod.reader", display_name="r", role="x", password_hash=hash_password("secret-pass"),
                   permissions=[P.JOB_READ], branch_ids=["branch-a"], is_active=True))
        await s.commit()
    denied = await client.post(f"{J}/{jid}/pod", headers=await _login(client, "pod.reader"), json={"accurate_sj_id": "SJ1", "qty_physical": "1", "idempotency_key": "scope-pod-01", "receiver_name": "Budi", "attachment_pod_photo_1": 1, "attachment_pod_photo_2": 2, "attachment_pod_sig_sender": 3, "attachment_pod_sig_recipient": 4, "lines": [_line("SL1", "L1", "1")]})
    assert denied.status_code == 403
    assert (await _rows(client, await _login(client, "msj.other")))["items"] == []
