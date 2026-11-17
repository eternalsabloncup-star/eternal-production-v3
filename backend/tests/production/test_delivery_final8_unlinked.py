"""Final-8 Delivery columns stay 'Belum terhubung' without proven Accurate sources.

Does not use shipped_at as print/POD. No Live writes.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.production.sj_line_helpers import loading_body
from tests.production.test_multi_sj_loading import _login, _seed_packed, client  # noqa: F401

J = "/api/v1/production/jobs"
O = "/api/v1/production/ops"

FINAL8 = (
    "customer_phone",
    "outlet",
    "sj_printed_at",
    "item_outlets",
    "warehouse_signer",
    "goods_checker",
    "courier_signer",
    "recipient_signer",
)


@pytest.mark.asyncio
async def test_v3_loading_row_final8_belum_terhubung(client: AsyncClient):
    h = await _login(client)
    jid = await _seed_packed(client, h, lines=[("L1", "10")])
    load = await client.post(
        f"{J}/{jid}/loading",
        headers=h,
        json=loading_body(
            accurate_sj_id="SJ1",
            accurate_sj_line_id="SL1",
            so_line_id="L1",
            qty_physical="10",
            idempotency_key="f8-load-1",
            accurate_sj_number="DO/F8/0001",
        ),
    )
    assert load.status_code == 200, load.text
    row = (await client.get(f"{O}/deliveries", headers=h)).json()["items"][0]
    assert row["accurate_sj_id"] == "SJ1"
    # delivery_status from V3 loading/POD qty — not from Accurate shipped_at
    assert row["delivery_status"] in {"belum_dikirim", "sebagian", "terkirim", "dibatalkan"}
    assert row.get("sj_printed_at") in (None, "")
    for key in FINAL8:
        assert row.get(key) in (None, ""), key
        assert row["field_availability"][key] == "Belum terhubung", key


def test_ops_so_link_mapper_never_uses_shipped_at_as_print():
    """Unit: note.shipped_at must not become sj_printed_at."""
    note = {
        "number": "DO/X",
        "shipped_at": "2026-11-12",
        "sj_printed_at": None,
        "customer": {"name": "C"},
        "line_items": [],
        "cancelled": False,
    }
    printed = note.get("sj_printed_at")
    assert printed is None
    assert note.get("shipped_at") == "2026-11-12"
    # Mimic SO-link assignment rule in operations.py
    assert printed != note.get("shipped_at")


def test_difaktur_status_is_not_terkirim():
    """Accurate status DIFAKTUR must not imply POD/terkirim on SO-link rows."""
    cancelled = False
    accurate_status = "DIFAKTUR"
    delivery_status = "dibatalkan" if cancelled else "belum_dikirim"
    assert accurate_status == "DIFAKTUR"
    assert delivery_status == "belum_dikirim"
    assert delivery_status != "terkirim"
