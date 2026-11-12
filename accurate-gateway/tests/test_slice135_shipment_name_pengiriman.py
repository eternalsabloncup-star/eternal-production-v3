"""Step 135 — shipment.name is proven Pengiriman (Live + Owner UI DIAMBIL)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.contracts import so_detail
from app.normalize import _expedition_from_shipment, normalize_sales_order

ROOT = Path(__file__).resolve().parents[2]


def _load_probe():
    path = ROOT / "scripts" / "slice90_four_field_live_probe.py"
    spec = importlib.util.spec_from_file_location("slice90_135", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_shipment_name_maps_diambil_not_pic_or_address():
    raw = {
        "id": 17,
        "number": "SO/SYN/135",
        "shipment": {
            "id": 9,
            "name": "DIAMBIL",
            "picName": "Orang PIC",
            "picPhoneNumber": "0800000000",
            "shipAddress": "Jl. Bukan Metode",
        },
        "charField4": "Normal",
        "charField5": "Non - Buffer",
        "detailItem": [
            {"salesmanList": [{"salesman": {"name": "Penjual"}}], "quantity": 1}
        ],
    }
    assert _expedition_from_shipment(raw) == "DIAMBIL"
    mapped = so_detail(normalize_sales_order(raw))
    assert mapped["expedition"] == "DIAMBIL"
    assert mapped["sales"] == "Penjual"
    assert mapped["urgent_state"] == "normal"
    assert mapped["buffer_stock"] is False


def test_shipment_empty_name_and_non_dict_safe():
    assert (
        _expedition_from_shipment({"shipment": {"id": 1, "picName": "X"}}) is None
    )
    assert _expedition_from_shipment({"shipment": {"name": "  "}}) is None
    assert _expedition_from_shipment({"shipment": None}) is None
    assert _expedition_from_shipment({"shipment": 12}) is None
    assert _expedition_from_shipment({"shipment": "OUTLET"}) == "OUTLET"
    # Never invent from sibling logistics-only keys.
    assert (
        normalize_sales_order(
            {
                "id": 1,
                "number": "SO/SYN/135E",
                "shipment": {
                    "id": 1,
                    "picName": "PIC",
                    "shipAddress": "Alamat",
                },
                "detailItem": [],
            }
        )["expedition"]
        is None
    )


def test_native_expedition_key_still_wins_over_shipment():
    mapped = normalize_sales_order(
        {
            "id": 2,
            "number": "SO/SYN/135N",
            "shippingMethodName": "JNE",
            "shipment": {"name": "DIAMBIL"},
            "detailItem": [],
        }
    )
    assert mapped["expedition"] == "JNE"


def test_probe_marks_shipment_name_mapped_without_values():
    mod = _load_probe()
    raw = {
        "id": 3,
        "number": "SO/SYN/135P",
        "shipment": {
            "id": 1,
            "name": "DIAMBIL",
            "picName": "PIC",
            "shipAddress": "Addr",
        },
        "charField4": "Urgent",
        "charField5": "Buffer",
        "detailItem": [{"salesmanName": "Alpha"}, {"salesmanName": "Beta"}],
    }
    ship = mod.discover_pengiriman_paths(raw)
    assert ship["shipment_mapped_to_expedition"] is True
    assert "shipment.name" in ship["mapped_native_paths_present"]
    assert ship["proven_json_path"] == "shipment.name"
    report = mod.build_discovery_report(raw, "SO/SYN/135P")
    peng = next(r for r in report["four_field_matrix"] if r["field"] == "Pengiriman")
    assert peng["resolved"] is True
    assert peng["shipment_mapped_to_expedition"] is True
    blob = json.dumps(report) + json.dumps(ship)
    assert "DIAMBIL" not in blob
    assert "PIC" not in blob
