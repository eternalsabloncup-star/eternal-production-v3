"""Step 90 — offline four-field probe (synthetic only, no network)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "slice90_four_field_live_probe.py"

SYN_SO = "SO/SYN/90/000001"
SYN_EXPECTED = {
    "so_number": SYN_SO,
    "sales": "Synthetic Penjual",
    "expedition": "DIAMBIL",
    "urgent_state": "normal",
    "buffer_stock": False,
}

FORBIDDEN = [
    "PO/12/11/2026/000017",
    "GAYO",
    "Dimas",
    "HIJAU ARMY",
]


def _load():
    spec = importlib.util.spec_from_file_location("slice90_probe", PROBE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_syntax_check_only():
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--syntax-check-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["executed_live"] is False
    blob = proc.stdout + proc.stderr
    for marker in FORBIDDEN:
        assert marker not in blob


def test_four_field_matrix_paths_no_values_leaked():
    mod = _load()
    raw = {
        "id": 90,
        "number": SYN_SO,
        "createdUserName": "Creator Must Not Leak As Sales",
        "charField4": "Normal",
        "charField5": "Non - Buffer",
        "shippingMethodName": "DIAMBIL",
        "detailItem": [
            {
                "id": 1,
                "itemNo": "SYN-ITEM",
                "quantity": 1,
                "salesman": {"name": "Synthetic Penjual"},
            }
        ],
    }
    report = mod.build_four_field_report(raw, SYN_EXPECTED, SYN_SO)
    assert report["ok"] is True
    by_field = {row["field"]: row for row in report["four_field_matrix"]}
    assert by_field["Sales"]["json_path"] == "detailItem[].salesman"
    assert by_field["Sales"]["present"] is True
    assert by_field["Sales"]["classification"] == "mapped"
    assert by_field["Sales"]["verification"] == "MATCH"
    assert by_field["Pengiriman"]["json_path"] == "shippingMethodName"
    assert by_field["Pengiriman"]["verification"] == "MATCH"
    assert by_field["Status"]["json_path"] == "charField4"
    assert by_field["Status"]["classification"] == "normal"
    assert by_field["Status"]["verification"] == "MATCH"
    assert by_field["Buffer"]["json_path"] == "charField5"
    assert by_field["Buffer"]["classification"] == "non_buffer"
    assert by_field["Buffer"]["verification"] == "MATCH"
    blob = json.dumps(report)
    assert "Synthetic Penjual" not in blob
    assert "DIAMBIL" not in blob
    assert "Normal" not in blob or "normal" in blob  # classification only
    assert "Non - Buffer" not in blob
    assert "Creator" not in blob
    assert SYN_SO not in blob
    for marker in FORBIDDEN:
        assert marker not in blob


def test_pengiriman_candidate_path_reported_as_unknown_not_mapped():
    mod = _load()
    raw = {
        "id": 91,
        "number": SYN_SO,
        "shipmentName": "DIAMBIL",
        "charField4": "Normal",
        "charField5": "Non - Buffer",
        "detailItem": [{"salesman": {"name": "Synthetic Penjual"}}],
    }
    report = mod.build_four_field_report(raw, SYN_EXPECTED, SYN_SO)
    peng = next(r for r in report["four_field_matrix"] if r["field"] == "Pengiriman")
    assert peng["json_path"] == "UNKNOWN"
    assert "shipmentName" in peng["unproven_candidate_paths_present"]
    assert peng["classification"] == "unknown_path_candidate_only"
    assert peng["verification"] == "UNKNOWN"
    assert "DIAMBIL" not in json.dumps(report)


def test_sales_absent_and_cf_absent():
    mod = _load()
    raw = {"id": 92, "number": SYN_SO, "detailItem": [{"id": 1, "quantity": 1}]}
    report = mod.build_four_field_report(raw, SYN_EXPECTED, SYN_SO)
    by_field = {row["field"]: row for row in report["four_field_matrix"]}
    assert by_field["Sales"]["json_path"] == "UNKNOWN"
    assert by_field["Sales"]["verification"] == "UNKNOWN"
    assert by_field["Status"]["present"] is False
    assert by_field["Buffer"]["present"] is False
