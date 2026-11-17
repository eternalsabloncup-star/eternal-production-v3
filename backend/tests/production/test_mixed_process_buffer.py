"""Gesut applies only to print lines. Non-print stays in fulfillment and is not invented stock."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle
from tests.production.sj_line_helpers import loading_body, sj_line_item
from tests.production.test_buffer_monitor import _flag, _rows
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401
from tests.production.test_operations_phase import J, O, _asg, _job_with_lines


async def _lines(client, h, so, specs):
    r = await client.post(J, headers=h, json={
        "accurate_so_number": so, "branch_id": "branch-a", "buffer_stock": True,
        "line_items": [
            {"accurate_line_id": lid, "quantity": qty, "production_process": process}
            for lid, qty, process in specs
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _pay(client, h, jid):
    paid = await client.post(f"{J}/{jid}/payment/bypass", headers=h, json={"reason": "otorisasi pembayaran non-print"})
    assert paid.status_code == 200, paid.text


async def test_print_only_gesut_target_equals_po_qty(client: AsyncClient):
    h = await _login(client)
    await _lines(client, h, "SO-PRINT", [("105595", "2000", "print")])
    row = (await _rows(client, h))["items"][0]
    assert row["gesut_target"] == "2000" and row["done_gesut"] == "0" and row["remaining_gesut"] == "2000"
    assert row["ready_warehouse"] is None and row["ready_state"] == "UNVERIFIED"
    assert row["delivered"] is None and row["delivered_state"] == "UNVERIFIED"
    assert row["buffer_status"] == "Belum mulai"


async def test_non_print_has_no_gesut_and_no_invented_stock(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-NP", [("105596", "2000", "non_print")])
    from app.db.session import get_session_factory
    from app.models.production.job import ProductionJob
    async with get_session_factory()() as s:
        await s.execute(update(ProductionJob).where(ProductionJob.id == jid).values(notes="KIRIM 1.000PCS DULU"))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["gesut_target"] == "0" and row["done_gesut"] == "0" and row["remaining_gesut"] == "0"
    assert row["buffer_status"] == "Tidak perlu gesut"
    assert row["fulfillment_qty"] == "2000"
    assert row["ready_warehouse"] is None and row["delivered"] is None
    assert row["delivered_state"] == "UNVERIFIED"


async def test_mixed_po_gesut_2000_fulfillment_4000(client: AsyncClient):
    h = await _login(client)
    await _lines(client, h, "PO/12/11/2026/000011", [("105595", "2000", "print"), ("105596", "2000", "non_print")])
    body = await _rows(client, h)
    rows = {i["so_line_id"]: i for i in body["items"]}
    assert rows["105595"]["gesut_target"] == "2000" and rows["105595"]["remaining_gesut"] == "2000"
    assert rows["105596"]["gesut_target"] == "0" and rows["105596"]["remaining_gesut"] == "0"
    assert rows["105596"]["buffer_status"] == "Tidak perlu gesut"
    assert body["totals"]["fulfillment_qty"] == "4000"
    assert body["totals"]["gesut_target"] == "2000"
    assert body["totals"]["remaining_gesut"] == "2000"
    assert body["totals"]["fulfillment_unverified_qty"] == "4000"
    assert body["totals"]["fulfillment_outstanding_verified"] is None
    assert rows["105595"]["delivered"] is None and rows["105596"]["delivered"] is None
    assert rows["105595"]["ready_warehouse"] is None and rows["105596"]["ready_warehouse"] is None


async def test_unknown_process_is_not_zero_gesut(client: AsyncClient):
    h = await _login(client)
    await _lines(client, h, "SO-UNK-PROC", [("L1", "10", "unknown")])
    row = (await _rows(client, h))["items"][0]
    assert row["gesut_target"] is None and row["remaining_gesut"] is None and row["done_gesut"] is None
    assert row["fulfillment_qty"] == "10"
    assert (await _rows(client, h))["totals"]["remaining_gesut"] is None


async def test_print_partial_packing_loading_and_pod(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-PART", lines=[("L1", "10")], synced=True)
    await _flag(jid)
    loaded = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ1", accurate_sj_line_id="SL1", so_line_id="L1", qty_physical="4", idempotency_key="part-load-01"))
    assert loaded.status_code == 200, loaded.text
    row = (await _rows(client, h))["items"][0]
    assert row["done_gesut"] == "10" and row["ready_warehouse"] == "6"
    ids = await upload_pod_bundle(client, jid, "SJ1", headers=h)
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ1", "3", "part-pod-0001", ids))).status_code == 200
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] == "3" and row["buffer_status"] == "Sebagian diambil/terkirim"


async def test_multicolor_print_uses_the_lowest_pass(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-MC", [("L1", "100")])
    await _flag(jid)
    for pass_no, machine in ((1, "M1"), (2, "M2")):
        assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", pass_no=pass_no, machine=machine))).status_code == 200
    async with get_session_factory()() as s:
        for pass_no, qty in ((1, "80"), (2, "60")):
            s.add(ProductionEvent(job_id=jid, event_type="output_helper_verified", so_line_id="L1", qty_physical=Decimal(qty),
                                  color_pass=pass_no, idempotency_key=f"mix-mc-{pass_no}-{jid}", actor_user_id=1))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["done_gesut"] == "60" and row["remaining_gesut"] == "40"


async def test_multi_item_pod_without_line_proof_stays_unverified(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-MIXPOD", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    client._msj["catalog"]["SJ-MIX"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=10),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=20),
    ]
    for line, sj_line, qty, key in (("L1", "A", "10", "mx-load-a1"), ("L2", "B", "20", "mx-load-b1")):
        assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id="SJ-MIX", accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty, idempotency_key=key))).status_code == 200
    ids = await upload_pod_bundle(client, jid, "SJ-MIX", headers=h)
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ-MIX", "15", "mx-pod-0001", ids))).status_code == 422
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["L1"]["delivered"] is None and rows["L2"]["delivered"] is None
    assert rows["L1"]["remaining_gesut"] == "0"


async def test_loading_without_packing_is_integrity_conflict(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    h = await _login(client)
    jid = await _lines(client, h, "SO-CONF", [("L1", "10", "print")])
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="loading", so_line_id="L1", qty_physical=Decimal("4"),
                              accurate_sj_id="SJ-X", accurate_sj_line_id="SLX", idempotency_key=f"conf-load-{jid}",
                              actor_user_id=1, payload_json='{"authorized_base":"10"}'))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["integrity"] == "INTEGRITY_CONFLICT" and row["ready_warehouse"] is None
    assert "packing" in row["integrity_detail"]


async def _verify(jid, line, qty):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="output_helper_verified", so_line_id=line, qty_physical=Decimal(qty),
                              color_pass=1, idempotency_key=f"ready-{line}-{qty}-{jid}", actor_user_id=1))
        await s.commit()


@pytest.mark.strict_loading_cap
async def test_print_output_is_gesut_and_ready_follows_packing(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-P800", [("L1", "2000", "print")])
    await _verify(jid, "L1", "1500")
    row = (await _rows(client, h))["items"][0]
    assert row["done_gesut"] == "1500" and row["remaining_gesut"] == "500"
    assert row["ready_warehouse"] is None and row["buffer_status"] == "Proses gesut"
    client._msj["catalog"]["SJ-P800"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=2000)]  # type: ignore[attr-defined]
    bare = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-P800", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="1", idempotency_key="p800-before-pack"))
    assert bare.status_code == 409 and "packing sah" in bare.text
    over = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "1501", "idempotency_key": "p800-pack-over"})
    assert over.status_code == 409
    packed = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "1000", "idempotency_key": "p800-pack-1000"})
    assert packed.status_code == 200, packed.text
    row = (await _rows(client, h))["items"][0]
    assert row["ready_warehouse"] == "1000" and row["buffer_status"] == "Ready gudang"
    ok = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-P800", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="600", idempotency_key="p800-load-600"))
    assert ok.status_code == 200, ok.text
    row = (await _rows(client, h))["items"][0]
    assert row["ready_warehouse"] == "400" and row["delivered_state"] == "UNVERIFIED"
    again = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-P800", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="401", idempotency_key="p800-load-over"))
    assert again.status_code == 409 and "packing sah" in again.text


@pytest.mark.strict_loading_cap
async def test_non_print_ready_only_after_warehouse_confirmation(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-WH", [("L1", "2000", "non_print")])
    await _pay(client, h, jid)
    assert (await _rows(client, h))["items"][0]["ready_warehouse"] is None
    client._msj["catalog"]["SJ-WH"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=2000)]  # type: ignore[attr-defined]
    blocked = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-WH", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="1", idempotency_key="wh-before-ready"))
    assert blocked.status_code == 409 and "UNVERIFIED" in blocked.text
    bare = await client.post(f"{J}/{jid}/packing", headers=h, json={"so_line_id": "L1", "qty_physical": "2000", "idempotency_key": "wh-no-evidence"})
    assert bare.status_code == 422
    ok = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "2000", "idempotency_key": "wh-full-0001", "evidence_ref": "cek-fisik-01"})
    assert ok.status_code == 200, ok.text
    replay = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "2000", "idempotency_key": "wh-full-0001", "evidence_ref": "cek-fisik-01"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == ok.json()["id"]
    mismatch = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "1", "idempotency_key": "wh-full-0001", "evidence_ref": "cek-fisik-01"})
    assert mismatch.status_code == 409
    row = (await _rows(client, h))["items"][0]
    assert row["ready_warehouse"] == "2000" and row["gesut_target"] == "0" and row["delivered"] is None
    assert row["buffer_status"] == "Tidak perlu gesut · Ready gudang"
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-WH", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="2000", idempotency_key="wh-load-ok"))).status_code == 200
    assert (await _rows(client, h))["items"][0]["ready_warehouse"] == "0"
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-WH", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="1", idempotency_key="wh-load-over"))).status_code == 409
    ids = await upload_pod_bundle(client, jid, "SJ-WH", headers=h)
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=pod_body("SJ-WH", "2000", "wh-pod-full1", ids))).status_code == 200
    done = (await _rows(client, h))["items"][0]
    assert done["delivered"] == "2000" and done["buffer_status"] == "Tidak perlu gesut · Selesai diambil/terkirim"


async def test_partial_non_print_confirmation_does_not_double_count(client: AsyncClient):
    import asyncio
    h = await _login(client)
    jid = await _lines(client, h, "SO-WHP", [("L1", "2000", "non_print")])
    await _pay(client, h, jid)
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "700", "idempotency_key": "wh-part-0700", "evidence_ref": "cek-a"})).status_code == 200
    assert (await _rows(client, h))["items"][0]["ready_warehouse"] == "700"
    raced = await asyncio.gather(
        client.post(f"{J}/{jid}/packing", headers=h, json={"so_line_id": "L1", "qty_physical": "800", "idempotency_key": "wh-race-a001", "evidence_ref": "cek-b"}),
        client.post(f"{J}/{jid}/packing", headers=h, json={"so_line_id": "L1", "qty_physical": "800", "idempotency_key": "wh-race-b001", "evidence_ref": "cek-c"}),
    )
    assert sorted(r.status_code for r in raced) == [200, 409]
    assert (await _rows(client, h))["items"][0]["ready_warehouse"] == "1500"


async def test_warehouse_confirmation_respects_permission_and_branch(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.session import get_session_factory
    from app.models.user import User
    from app.services.production import permissions as P
    h = await _login(client)
    jid = await _lines(client, h, "SO-SCOPE", [("L1", "100", "non_print")])
    async with get_session_factory()() as s:
        s.add(User(username="wh.reader", display_name="w", role="x", password_hash=hash_password("secret-pass"),
                   permissions=[P.JOB_READ], branch_ids=["branch-a"], is_active=True))
        await s.commit()
    body = {"so_line_id": "L1", "qty_physical": "10", "idempotency_key": "wh-scope-01", "evidence_ref": "cek"}
    assert (await client.post(f"{J}/{jid}/packing", headers=await _login(client, "wh.reader"), json=body)).status_code == 403
    assert (await client.post(f"{J}/{jid}/packing", headers=await _login(client, "msj.other"), json=body)).status_code == 403


async def test_multi_item_pod_must_name_every_loaded_line(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, so="SO-EVERY", lines=[("L1", "10"), ("L2", "20")], synced=True)
    await _flag(jid)
    client._msj["catalog"]["SJ-EV"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="A", so_line_id="L1", quantity=10),
        sj_line_item(accurate_sj_line_id="B", so_line_id="L2", quantity=20),
    ]
    for line, sj_line, qty, key in (("L1", "A", "10", "ev-load-a1"), ("L2", "B", "20", "ev-load-b1")):
        assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
            accurate_sj_id="SJ-EV", accurate_sj_line_id=sj_line, so_line_id=line, qty_physical=qty, idempotency_key=key))).status_code == 200
    ids = await upload_pod_bundle(client, jid, "SJ-EV", headers=h)
    partial = pod_body("SJ-EV", "6", "ev-pod-partial", ids)
    partial["lines"] = [{"accurate_sj_line_id": "A", "so_line_id": "L1", "qty_physical": "6"}]
    assert (await client.post(f"{J}/{jid}/pod", headers=h, json=partial)).status_code == 422
    full = pod_body("SJ-EV", "15", "ev-pod-both01", ids)
    full["lines"] = [
        {"accurate_sj_line_id": "A", "so_line_id": "L1", "qty_physical": "6"},
        {"accurate_sj_line_id": "B", "so_line_id": "L2", "qty_physical": "9"},
    ]
    saved = await client.post(f"{J}/{jid}/pod", headers=h, json=full)
    assert saved.status_code == 200, saved.text
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["L1"]["delivered"] == "6" and rows["L2"]["delivered"] == "9"
    assert (await _rows(client, h))["totals"]["fulfillment_outstanding_verified"] == "15"
    report = (await client.get(f"{O}/reports/summary", headers=h)).json()
    assert Decimal(report["totals"]["pod"]) == Decimal("15")


@pytest.mark.strict_loading_cap
async def test_unknown_process_loading_is_rejected_and_legacy_history_stays(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    h = await _login(client)
    jid = await _lines(client, h, "SO-UNK-LOAD", [("L1", "10", "unknown")])
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="packing_batch", so_line_id="L1", qty_physical=Decimal("10"),
                              idempotency_key=f"unk-pack-{jid}", actor_user_id=1, evidence_ref="packing-lama"))
        await s.commit()
    client._msj["catalog"]["SJ-UNK"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=10)]  # type: ignore[attr-defined]
    denied = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-UNK", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="10", idempotency_key="unk-load-new"))
    assert denied.status_code == 409 and "belum resmi" in denied.text
    assert (await client.post(f"{J}/{jid}/loading", headers=await _login(client, "msj.other"), json=loading_body(
        accurate_sj_id="SJ-UNK", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="10", idempotency_key="unk-load-branch"))).status_code == 403
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="loading", so_line_id="L1", qty_physical=Decimal("4"),
                              accurate_sj_id="SJ-OLD", accurate_sj_line_id="SLO", idempotency_key=f"unk-old-load-{jid}",
                              actor_user_id=1, payload_json='{"authorized_base":"10"}'))
        s.add(ProductionEvent(job_id=jid, event_type="pod", qty_physical=Decimal("4"), accurate_sj_id="SJ-OLD",
                              idempotency_key=f"unk-old-pod-{jid}", actor_user_id=1, reason="receiver:Lama"))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["delivered"] == "4" and row["delivered_state"] == "VERIFIED"
    assert row["gesut_target"] is None


async def test_other_branch_sees_no_mixed_rows(client: AsyncClient):
    h = await _login(client)
    await _lines(client, h, "SO-ISO", [("L1", "10", "print"), ("L2", "10", "non_print")])
    assert (await _rows(client, await _login(client, "msj.other")))["items"] == []


@pytest.mark.strict_loading_cap
async def test_non_print_packs_without_print_chain(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-NP-DIRECT", [("L1", "2000", "non_print")])
    scheduled = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="2000"))
    assert scheduled.status_code == 409 and "non-print" in scheduled.text
    screen = await client.post(f"{J}/{jid}/prep/screener", headers=h, json={
        "so_line_id": "L1", "qty": "1", "po_qty": "2000", "screen_size": "kecil",
        "evidence_ref": "scr", "idempotency_key": "np-scr-01"})
    assert screen.status_code == 409 and "non-print" in screen.text
    sample = await client.post(f"{J}/{jid}/samples", headers=h, json={"file_name": "s.jpg", "storage_key": "s-np"})
    assert sample.status_code == 409 and "non-print" in sample.text
    unpaid = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "800", "idempotency_key": "np-unpaid-01", "evidence_ref": "cek"})
    assert unpaid.status_code == 409 and "Payment" in unpaid.text
    await _pay(client, h, jid)
    packed = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "800", "idempotency_key": "np-pack-800", "evidence_ref": "cek-fisik"})
    assert packed.status_code == 200, packed.text
    row = (await _rows(client, h))["items"][0]
    assert row["gesut_target"] == "0" and row["done_gesut"] == "0" and row["ready_warehouse"] == "800"
    over = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "1201", "idempotency_key": "np-pack-over", "evidence_ref": "cek-2"})
    assert over.status_code == 409
    tasks = (await client.get(f"{J}/tasks", headers=h, params={"so": "SO-NP-DIRECT"})).json()["tasks"]
    kinds = {t["kind"] for t in tasks}
    assert "stockpack" in kinds
    assert {"stockprep", "schedule", "screen", "prepare", "sample", "print", "design_upload"}.isdisjoint(kinds)


@pytest.mark.strict_loading_cap
async def test_mixed_non_print_ships_while_print_stays_in_production(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-MIX-SHIP", [("P1", "2000", "print"), ("N1", "2000", "non_print")])
    await _pay(client, h, jid)
    blocked_np = await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(line="N1", qty="2000"))
    assert blocked_np.status_code == 409 and "non-print" in blocked_np.text
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "N1", "qty_physical": "500", "idempotency_key": "mix-np-pack", "evidence_ref": "cek"})).status_code == 200
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["P1"]["gesut_target"] == "2000" and rows["P1"]["ready_warehouse"] is None
    assert rows["N1"]["gesut_target"] == "0" and rows["N1"]["ready_warehouse"] == "500"
    body = await _rows(client, h)
    assert body["totals"]["fulfillment_qty"] == "4000" and body["totals"]["gesut_target"] == "2000"
    client._msj["catalog"]["SJ-MIXSHIP"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="SN", so_line_id="N1", quantity=2000),
        sj_line_item(accurate_sj_line_id="SP", so_line_id="P1", quantity=2000),
    ]
    shipped = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-MIXSHIP", accurate_sj_line_id="SN", so_line_id="N1", qty_physical="200", idempotency_key="mix-np-load"))
    assert shipped.status_code == 200, shipped.text
    assert (await _rows(client, h))["items"]
    rows = {i["so_line_id"]: i for i in (await _rows(client, h))["items"]}
    assert rows["N1"]["ready_warehouse"] == "300"
    print_load = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-MIXSHIP", accurate_sj_line_id="SP", so_line_id="P1", qty_physical="1", idempotency_key="mix-print-load"))
    assert print_load.status_code == 409 and "packing sah" in print_load.text


@pytest.mark.strict_loading_cap
async def test_unknown_and_missing_line_cannot_pack_or_load(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-UNK-PACK", [("L1", "10", "unknown")])
    await _verify(jid, "L1", "10")
    await _pay(client, h, jid)
    packed = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "10", "idempotency_key": "unk-pack-api", "evidence_ref": "x"})
    assert packed.status_code == 409 and "belum resmi" in packed.text
    client._msj["catalog"]["SJ-UNK2"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=10)]  # type: ignore[attr-defined]
    loaded = await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-UNK2", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="1", idempotency_key="unk-load-api"))
    assert loaded.status_code == 409 and "belum resmi" in loaded.text
    bare = await client.post(J, headers=h, json={"accurate_so_number": "SO-NOLINE", "branch_id": "branch-a"})
    assert bare.status_code == 200, bare.text
    client._msj["catalog"]["SJ-NOLINE"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=10)]  # type: ignore[attr-defined]
    missing = await client.post(f"{J}/{bare.json()['id']}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-NOLINE", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="1", idempotency_key="noline-load"))
    assert missing.status_code == 409 and "JobLineQty" in missing.text


@pytest.mark.strict_loading_cap
async def test_print_packing_respects_multicolor_and_rejects(client: AsyncClient):
    from app.db.session import get_session_factory
    from app.models.production.event import ProductionEvent
    h = await _login(client)
    jid = await _job_with_lines(client, h, "SO-MC-PACK", [("L1", "100")])
    await _flag(jid)
    for pass_no, machine in ((1, "M1"), (2, "M2")):
        assert (await client.post(f"{J}/{jid}/schedule/assignments", headers=h, json=_asg(qty="100", pass_no=pass_no, machine=machine))).status_code == 200
    async with get_session_factory()() as s:
        s.add(ProductionEvent(job_id=jid, event_type="output_helper_verified", so_line_id="L1", qty_physical=Decimal("80"),
                              color_pass=1, idempotency_key=f"mc-ok-1-{jid}", actor_user_id=1))
        s.add(ProductionEvent(job_id=jid, event_type="output_helper_verified", so_line_id="L1", qty_physical=Decimal("60"),
                              color_pass=2, idempotency_key=f"mc-ok-2-{jid}", actor_user_id=1))
        s.add(ProductionEvent(job_id=jid, event_type="reject_verified", so_line_id="L1", qty_physical=Decimal("10"),
                              color_pass=2, idempotency_key=f"mc-bad-2-{jid}", actor_user_id=1))
        await s.commit()
    row = (await _rows(client, h))["items"][0]
    assert row["done_gesut"] == "50" and row["ready_warehouse"] is None
    over = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "51", "idempotency_key": "mc-pack-over"})
    assert over.status_code == 409
    ok = await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "50", "idempotency_key": "mc-pack-ok"})
    assert ok.status_code == 200, ok.text
    assert (await _rows(client, h))["items"][0]["ready_warehouse"] == "50"


async def _loading_card(client, h, so):
    body = (await client.get(f"{J}/tasks", headers=h, params={"so": so})).json()
    cards = [t for t in body["tasks"] if t["kind"] == "loading"]
    assert len(cards) == 1
    assert cards[0]["id"] == f"{so}::loading"
    return cards[0]


@pytest.mark.strict_loading_cap
async def test_mixed_po_loading_card_is_not_fully_ready(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-CARD-MIX", [("P1", "2000", "print"), ("N1", "2000", "non_print")])
    await _pay(client, h, jid)
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "N1", "qty_physical": "500", "idempotency_key": "card-mix-pack", "evidence_ref": "cek"})).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-MIX")
    assert card["state"] == "partial"
    lines = {ln["so_line_id"]: ln for ln in card["lines"]}
    assert lines["N1"]["status"] == "Siap Loading" and lines["N1"]["ready_qty"] == "500"
    assert lines["N1"]["sj_remaining_qty"] is None
    assert lines["P1"]["status"] == "Menunggu Packing" and lines["P1"]["ready_qty"] is None
    client._msj["catalog"]["SJ-CARD"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="SN", so_line_id="N1", quantity=2000),
        sj_line_item(accurate_sj_line_id="SP", so_line_id="P1", quantity=2000),
    ]
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-CARD", accurate_sj_line_id="SP", so_line_id="P1", qty_physical="1", idempotency_key="card-print-load"))).status_code == 409
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-CARD", accurate_sj_line_id="SN", so_line_id="N1", qty_physical="200", idempotency_key="card-np-load"))).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-MIX")
    assert card["state"] == "partial"
    n1 = {ln["so_line_id"]: ln for ln in card["lines"]}["N1"]
    assert n1["status"] == "Loading Parsial" and n1["ready_qty"] == "300" and n1["sj_remaining_qty"] == "1800"
    assert {ln["so_line_id"]: ln for ln in card["lines"]}["P1"]["status"] == "Menunggu Packing"


@pytest.mark.strict_loading_cap
async def test_partial_packing_keeps_ready_qty_on_the_line(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-CARD-PART", [("L1", "2000", "non_print")])
    await _pay(client, h, jid)
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "L1", "qty_physical": "500", "idempotency_key": "card-part-pack", "evidence_ref": "cek"})).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-PART")
    assert card["state"] == "actionable"
    line = card["lines"][0]
    assert line["status"] == "Siap Loading" and line["ready_qty"] == "500" and line["packed_qty"] == "500"
    client._msj["catalog"]["SJ-PART"] = [sj_line_item(accurate_sj_line_id="SL", so_line_id="L1", quantity=2000)]  # type: ignore[attr-defined]
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-PART", accurate_sj_line_id="SL", so_line_id="L1", qty_physical="200", idempotency_key="card-part-load"))).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-PART")
    assert card["state"] == "partial"
    line = card["lines"][0]
    assert line["status"] == "Loading Parsial" and line["ready_qty"] == "300" and line["loaded_qty"] == "200"
    assert line["sj_remaining_qty"] == "1800"


@pytest.mark.strict_loading_cap
async def test_fully_packed_and_loaded_po_is_done_per_line(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-CARD-DONE", [("P1", "100", "print"), ("N1", "80", "non_print")])
    await _pay(client, h, jid)
    await _verify(jid, "P1", "100")
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "P1", "qty_physical": "100", "idempotency_key": "card-done-print"})).status_code == 200
    assert (await client.post(f"{J}/{jid}/packing", headers=h, json={
        "so_line_id": "N1", "qty_physical": "80", "idempotency_key": "card-done-np", "evidence_ref": "cek"})).status_code == 200
    client._msj["catalog"]["SJ-DONE"] = [  # type: ignore[attr-defined]
        sj_line_item(accurate_sj_line_id="SP", so_line_id="P1", quantity=100),
        sj_line_item(accurate_sj_line_id="SN", so_line_id="N1", quantity=80),
    ]
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-DONE", accurate_sj_line_id="SP", so_line_id="P1", qty_physical="100", idempotency_key="card-done-load-p"))).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-DONE")
    assert card["state"] == "partial"
    assert (await client.post(f"{J}/{jid}/loading", headers=h, json=loading_body(
        accurate_sj_id="SJ-DONE", accurate_sj_line_id="SN", so_line_id="N1", qty_physical="80", idempotency_key="card-done-load-n"))).status_code == 200
    card = await _loading_card(client, h, "SO-CARD-DONE")
    assert card["state"] == "done"
    lines = {ln["so_line_id"]: ln for ln in card["lines"]}
    assert lines["P1"]["status"] == "Sudah Loading" and lines["P1"]["ready_qty"] == "0" and lines["P1"]["sj_remaining_qty"] == "0"
    assert lines["N1"]["status"] == "Sudah Loading" and lines["N1"]["ready_qty"] == "0" and lines["N1"]["sj_remaining_qty"] == "0"


@pytest.mark.strict_loading_cap
async def test_unknown_line_does_not_make_the_po_ready(client: AsyncClient):
    h = await _login(client)
    jid = await _lines(client, h, "SO-CARD-UNK", [("P1", "10", "print"), ("U1", "10", "unknown")])
    await _pay(client, h, jid)
    card = await _loading_card(client, h, "SO-CARD-UNK")
    assert card["state"] == "blocked" and card["reason"] == "Belum terverifikasi"
    lines = {ln["so_line_id"]: ln for ln in card["lines"]}
    assert lines["U1"]["status"] == "Belum terverifikasi"
    assert lines["U1"]["ready_qty"] is None and lines["U1"]["sj_remaining_qty"] is None
    assert lines["P1"]["status"] == "Menunggu Packing"
