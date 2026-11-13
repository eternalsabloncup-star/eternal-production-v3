"""Step 133/135 — four-field lock from Live audit (offline, no network).

Live audit (Owner SO):
  Sales   → detailItem[].salesmanList (alt salesmanName)
  Status  → charField4
  Buffer  → charField5
  Pengiriman → shipment.name (Step 135 VERIFIED; logistics siblings ignored)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.contracts import so_detail
from app.normalize import _extract_sales, normalize_sales_order

ROOT = Path(__file__).resolve().parents[2]


def _load_probe():
    path = ROOT / "scripts" / "slice90_four_field_live_probe.py"
    spec = importlib.util.spec_from_file_location("slice90_133", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sales_live_path_detailitem_salesman_list():
    name, source = _extract_sales(
        {
            "createdUserName": "Creator",
            "detailItem": [
                {"salesmanList": [{"salesman": {"name": "Penjual A"}}]},
            ],
        }
    )
    assert name == "Penjual A"
    assert source == "detailItem.salesmanList"


def test_sales_alt_salesman_name_and_multi_and_empty():
    name, _ = _extract_sales(
        {
            "detailItem": [
                {"salesmanName": "Alpha"},
                {"salesmanList": [{"name": "Beta"}]},
                {"salesmanName": "Alpha"},
            ]
        }
    )
    assert name == "Alpha, Beta"
    empty_name, empty_src = _extract_sales(
        {"createdUserName": "Creator", "detailItem": [{"id": 1}]}
    )
    assert empty_name is None and empty_src is None


def test_status_buffer_cf4_cf5_owner_tokens():
    mapped = so_detail(
        normalize_sales_order(
            {
                "id": 1,
                "number": "SO/SYN/133",
                "charField4": "Normal",
                "charField5": "Non - Buffer",
                "detailItem": [
                    {
                        "quantity": 1,
                        "salesmanList": [{"salesman": {"name": "Penjual"}}],
                    }
                ],
            }
        )
    )
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False
    assert mapped["sales"] == "Penjual"

    urgent = so_detail(
        normalize_sales_order(
            {
                "id": 2,
                "number": "SO/SYN/133U",
                "charField4": "Urgent",
                "charField5": "Buffer",
                "detailItem": [],
            }
        )
    )
    assert urgent["urgent_state"] == "approved_urgent"
    assert urgent["buffer_stock"] is True


def test_pengiriman_shipment_name_maps_diambil():
    mapped = normalize_sales_order(
        {
            "id": 3,
            "number": "SO/SYN/133P",
            "shipment": {"id": 9, "name": "DIAMBIL"},
            "charField4": "Normal",
            "charField5": "Non-Buffer",
            "detailItem": [],
        }
    )
    # Step 135: shipment.name is proven Pengiriman.
    assert mapped["expedition"] == "DIAMBIL"
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False


def test_probe_reports_shipment_shape_without_values():
    mod = _load_probe()
    raw = {
        "id": 4,
        "number": "SO/SYN/133D",
        "shipment": {"id": 1, "name": "DIAMBIL", "code": "X"},
        "charField4": "Normal",
        "charField5": "Non - Buffer",
        "detailItem": [
            {"salesmanList": [{"salesman": {"name": "Penjual"}}]},
        ],
    }
    report = mod.build_discovery_report(raw, "SO/SYN/133D")
    peng = next(r for r in report["four_field_matrix"] if r["field"] == "Pengiriman")
    ship = mod.discover_pengiriman_paths(raw)
    assert ship["shipment_mapped_to_expedition"] is True
    assert ship["shipment_shape"]["value_type"] == "dict"
    assert ship["shipment_shape"]["has_name_key"] is True
    assert "name" in ship["shipment_shape"]["dict_keys"]
    assert peng["resolved"] is True
    blob = json.dumps(report) + json.dumps(ship)
    assert "DIAMBIL" not in blob
    assert "Penjual" not in blob


def test_contract_passes_four_fields_to_backend_shape():
    mapped = so_detail(
        normalize_sales_order(
            {
                "id": 5,
                "number": "SO/SYN/133C",
                "charField4": "Urgent",
                "charField5": "Buffer",
                "expedition": "OUTLET",
                "detailItem": [
                    {"salesmanList": [{"name": "Penjual"}], "quantity": 2}
                ],
            }
        )
    )
    assert mapped["sales"] == "Penjual"
    assert mapped["expedition"] == "OUTLET"  # only via proven native key
    assert mapped["urgent_state"] == "approved_urgent"
    assert mapped["buffer_stock"] is True
