"""Step 102 — --discover-only four-field probe (synthetic, no network)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "slice90_four_field_live_probe.py"

SYN_SO = "SO/SYN/102/000001"
FORBIDDEN = [
    "PO/12/11/2026/000017",
    "GAYO",
    "Synthetic Penjual",
    "DIAMBIL",
    "Non - Buffer",
]


def _load():
    spec = importlib.util.spec_from_file_location("slice90_probe_102", PROBE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _by_field(report):
    return {r["field"]: r for r in report["four_field_matrix"]}


def test_syntax_check_supports_discover_only():
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--syntax-check-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["supports_discover_only"] is True
    assert payload["executed_live"] is False


def test_discover_sales_header():
    mod = _load()
    raw = {
        "id": 1,
        "number": SYN_SO,
        "salesmanList": [{"salesman": {"name": "Synthetic Penjual"}}],
        "detailItem": [],
    }
    report = mod.build_discovery_report(raw, SYN_SO)
    assert report["mode"] == "discover"
    sales = _by_field(report)["Sales"]
    assert sales["json_path"] == "salesmanList"
    assert sales["classification"] == "mapped"
    assert "verification" not in sales
    assert "Synthetic Penjual" not in json.dumps(report)


def test_discover_sales_detail_item_and_multi():
    mod = _load()
    raw = {
        "id": 2,
        "number": SYN_SO,
        "detailItem": [
            {"salesman": {"name": "Synthetic Penjual"}},
            {"salesman": {"name": "Other Sales"}},
        ],
    }
    report = mod.build_discovery_report(raw, SYN_SO)
    sales = _by_field(report)["Sales"]
    assert sales["json_path"] == "detailItem[].salesman"
    assert "detailItem[].salesman" in sales["all_json_paths"]
    assert sales["classification"] == "mapped"
    blob = json.dumps(report)
    assert "Synthetic Penjual" not in blob
    assert "Other Sales" not in blob


def test_discover_pengiriman_native_mapped():
    mod = _load()
    raw = {
        "id": 3,
        "number": SYN_SO,
        "shippingMethodName": "DIAMBIL",
        "detailItem": [],
    }
    report = mod.build_discovery_report(raw, SYN_SO)
    peng = _by_field(report)["Pengiriman"]
    assert peng["json_path"] == "shippingMethodName"
    assert peng["resolved"] is True
    assert peng["classification"] == "mapped"
    assert "DIAMBIL" not in json.dumps(report)


def test_discover_pengiriman_candidate_only_not_resolved():
    mod = _load()
    raw = {
        "id": 4,
        "number": SYN_SO,
        "shipmentName": "DIAMBIL",
        "detailItem": [],
    }
    report = mod.build_discovery_report(raw, SYN_SO)
    peng = _by_field(report)["Pengiriman"]
    assert peng["json_path"] == "UNKNOWN"
    assert peng["resolved"] is False
    assert peng["classification"] == "unknown_path_candidate_only"
    assert "shipmentName" in peng["unproven_candidate_paths_present"]


def test_discover_cf4_cf5_classes():
    mod = _load()
    for token, urgent_cls in (("Normal", "normal"), ("Urgent", "urgent"), ("X", "unknown")):
        raw = {
            "id": 5,
            "number": SYN_SO,
            "charField4": token,
            "charField5": "Buffer",
            "detailItem": [],
        }
        report = mod.build_discovery_report(raw, SYN_SO)
        st = _by_field(report)["Status"]
        assert st["json_path"] == "charField4"
        assert st["classification"] == urgent_cls
        assert st["present"] is True

    for token, buf_cls in (
        ("Buffer", "buffer"),
        ("Non - Buffer", "non_buffer"),
        ("Non-Buffer", "non_buffer"),
        ("Nope", "unknown"),
    ):
        raw = {
            "id": 6,
            "number": SYN_SO,
            "charField4": "Normal",
            "charField5": token,
            "detailItem": [],
        }
        report = mod.build_discovery_report(raw, SYN_SO)
        bf = _by_field(report)["Buffer"]
        assert bf["json_path"] == "charField5"
        assert bf["classification"] == buf_cls
        assert "Non - Buffer" not in json.dumps(report)


def test_discover_missing_fields():
    mod = _load()
    raw = {"id": 7, "number": SYN_SO, "detailItem": [{"id": 1, "quantity": 1}]}
    report = mod.build_discovery_report(raw, SYN_SO)
    by = _by_field(report)
    assert by["Sales"]["json_path"] == "UNKNOWN"
    assert by["Pengiriman"]["json_path"] == "UNKNOWN"
    assert by["Status"]["present"] is False
    assert by["Buffer"]["present"] is False


def test_discover_identity_mismatch_sanitized():
    mod = _load()
    raw = {"id": 8, "number": "SO/OTHER/999", "detailItem": []}
    report = mod.build_discovery_report(raw, SYN_SO)
    assert report["ok"] is False
    assert report["blocker"] == "document_number_mismatch"
    blob = json.dumps(report)
    assert SYN_SO not in blob
    assert "SO/OTHER" not in blob


def test_cli_discover_requires_so_without_expected(tmp_path):
    # Without live env this should fail closed before network — still no expected required.
    proc = subprocess.run(
        [
            sys.executable,
            str(PROBE),
            "--discover-only",
            "--so-number",
            SYN_SO,
            "--env-file",
            str(tmp_path / "missing.env"),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit non-zero due to missing env / not live — but blocker must NOT be expected_file.
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload.get("blocker") != "expected_file_required_unless_discover_only"
    assert payload.get("blocker") != "so_number_and_expected_required"
    for marker in FORBIDDEN:
        assert marker not in proc.stdout + proc.stderr
