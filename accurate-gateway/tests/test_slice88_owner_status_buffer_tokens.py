"""Step 88: Owner Others Info screenshot tokens for Status Pesanan + Buffer.

UI evidence (not API wire proof):
  Status Pesanan = \"Normal\"
  Buffer / Non-Buffer = \"Non - Buffer\"
Owner config: Header CF4 = Status Pesanan, Header CF5 = Buffer / Non-Buffer.
"""

from __future__ import annotations

from app.contracts import so_detail
from app.normalize import (
    _parse_buffer_stock,
    _parse_urgent_state,
    normalize_sales_order,
    normalize_sales_order_list_item,
)


def test_owner_screenshot_status_normal_not_unknown():
    assert _parse_urgent_state("Normal") == "normal"
    assert _parse_urgent_state("Urgent") == "approved_urgent"
    assert _parse_urgent_state("weird-token") is None


def test_owner_screenshot_non_space_hyphen_buffer():
    # Exact UI token from Owner Others Info screenshot.
    assert _parse_buffer_stock("Non - Buffer") is False
    assert _parse_buffer_stock("Non-Buffer") is False
    assert _parse_buffer_stock("Buffer") is True
    assert _parse_buffer_stock("Not-A-Buffer-Token") is None


def test_cf4_cf5_path_with_exact_owner_ui_tokens():
    raw = {
        "id": 8801,
        "number": "SO/SYN/88/OTHERS",
        "charField4": "Normal",
        "charField5": "Non - Buffer",
        "createdUserName": "Must Not Affect Sales",
        "detailItem": [],
    }
    mapped = so_detail(normalize_sales_order(raw))
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False
    # Sales/Expedition unchanged by this screenshot.
    assert mapped["sales"] is None
    assert mapped["expedition"] is None


def test_list_item_same_owner_tokens():
    row = normalize_sales_order_list_item(
        {
            "id": 8802,
            "number": "SO/SYN/88/LIST",
            "charField4": "Normal",
            "charField5": "Non - Buffer",
        }
    )
    assert row["urgent_state"] == "normal"
    assert row["buffer_stock"] is False


def test_hyphen_and_space_normalization_matrix():
    for token in (
        "Non-Buffer",
        "Non - Buffer",
        "Non  -  Buffer",
        "non-buffer",
        "NON - BUFFER",
        "Non_Buffer",
    ):
        assert _parse_buffer_stock(token) is False, token
