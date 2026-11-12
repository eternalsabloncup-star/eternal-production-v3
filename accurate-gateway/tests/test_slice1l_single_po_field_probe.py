"""Step 43B — sanitized probe unit tests (synthetic fixtures only, no network)."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "slice1l_single_po_field_probe.py"

SYN_SO = "SO/SYN/000001"
SYN_EXPECTED = {
    "so_number": SYN_SO,
    "sales": "Synthetic Salesperson",
    "expedition": "SYN-COURIER",
    "delivery_zone": "ZONE-A",
    "urgent_state": "normal",
    "buffer_stock": False,
    "total_quantity": 30,
    "line_count": 2,
    "lines": [
        {
            "item_code": "SYN-ITEM-001",
            "qty": 10,
            "unit": "PCS",
            "process": "print",
            "color": "SYN-RED",
        },
        {
            "item_code": "SYN-ITEM-002",
            "qty": 20,
            "unit": "PCS",
            "process": "non_print",
            "color": "SYN-CLEAR",
        },
    ],
}

# Patterns that must never appear in the probe module (real Eternal business refs).
FORBIDDEN_IN_PROBE = [
    "PO/11/11/2026/",
    "HIJAU ARMY",
    "AD MELIORA",
    "Dimas Aji",
    "100003",
    "100460",
]


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "slice1l_single_po_field_probe", PROBE_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load_probe()


@pytest.fixture
def expected_path(tmp_path, probe):
    path = tmp_path / "expected.json"
    path.write_text(json.dumps(SYN_EXPECTED), encoding="utf-8")
    return path


def test_sources_have_no_real_eternal_pii():
    probe_text = PROBE_PATH.read_text(encoding="utf-8")
    example = (
        ROOT / "scripts" / "examples" / "slice1l_expected.synthetic.example.json"
    ).read_text(encoding="utf-8")
    for marker in FORBIDDEN_IN_PROBE:
        assert marker not in probe_text
        assert marker not in example
    assert "TARGET_SO_NUMBER" not in probe_text
    assert "_PDF" not in probe_text


def test_syntax_check_only_no_network(probe):
    env = os.environ.copy()
    env.pop("ACCURATE_API_TOKEN", None)
    env.pop("ACCURATE_SIGNATURE_SECRET", None)
    proc = subprocess.run(
        [sys.executable, str(PROBE_PATH), "--syntax-check-only"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["executed_live"] is False
    assert payload["http"]["executed_methods"] == []
    blob = proc.stdout + proc.stderr
    for marker in FORBIDDEN_IN_PROBE:
        assert marker not in blob


def test_missing_expected_file(probe, tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(probe.ExpectedFileError) as ei:
        probe.load_expected_file(str(missing), SYN_SO)
    assert ei.value.code == "expected_file_missing"
    sanitized = probe._sanitize_exc(ei.value)
    blob = json.dumps(sanitized)
    assert sanitized["message"] == "redacted"
    assert str(missing) not in blob
    assert SYN_SO not in blob


def test_invalid_expected_json(probe, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises(probe.ExpectedFileError) as ei:
        probe.load_expected_file(str(bad), SYN_SO)
    assert ei.value.code == "expected_json_invalid"
    assert probe._sanitize_exc(ei.value)["message"] == "redacted"


def test_expected_so_mismatch(probe, expected_path):
    with pytest.raises(probe.ExpectedFileError) as ei:
        probe.load_expected_file(str(expected_path), "SO/OTHER/999")
    assert ei.value.code == "expected_so_mismatch"
    out = probe._sanitize_exc(ei.value)
    blob = json.dumps(out)
    assert "SO/OTHER" not in blob
    assert SYN_SO not in blob


def test_expected_duplicate_item_code(probe, tmp_path):
    data = json.loads(json.dumps(SYN_EXPECTED))
    data["lines"].append(dict(data["lines"][0]))
    data["line_count"] = 3
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(probe.ExpectedFileError) as ei:
        probe.load_expected_file(str(path), SYN_SO)
    assert ei.value.code == "expected_duplicate_item_code"


def test_expected_nan_infinity_rejected(probe, tmp_path):
    for idx, token in enumerate(("NaN", "Infinity", "-Infinity")):
        data = json.loads(json.dumps(SYN_EXPECTED))
        data["lines"][0]["qty"] = token
        path = tmp_path / f"nf_{idx}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(probe.ExpectedFileError) as ei:
            probe.load_expected_file(str(path), SYN_SO)
        assert ei.value.code == "expected_qty_non_finite"


def test_qty_validity_nan_infinity(probe):
    assert probe.qty_validity({"quantity": float("nan")})["contract"] == "UNKNOWN_invalid"
    assert probe.qty_validity({"quantity": float("inf")})["contract"] == "UNKNOWN_invalid"
    assert probe.qty_validity({"quantity": 0})["contract"] == "official_zero"
    assert probe.qty_validity({"quantity": 10})["contract"] == "valid_nonzero"


def test_item_order_independent_matching(probe, expected_path):
    expected = probe.load_expected_file(str(expected_path), SYN_SO)
    # Reverse Accurate detail order vs expected lines order
    # Slice 1N Owner ordinals: H CF3 zona, CF4 status, CF5 buffer; L CF1 proses, CF2 warna.
    raw = {
        "id": 42,
        "number": SYN_SO,
        "statusName": "OPEN",
        "customer": {"id": 1, "name": "Synthetic Customer"},
        "salesmanList": [{"salesman": {"name": "Synthetic Salesperson"}}],
        "charField3Name": "Zona Pengiriman",
        "charField3": "ZONE-A",
        "charField4Name": "Status Pesanan",
        "charField4": "Normal",
        "charField5Name": "Buffer / Non-Buffer",
        "charField5": "Non-Buffer",
        "detailItem": [
            {
                "id": 2,
                "itemNo": "SYN-ITEM-002",
                "detailName": "Second",
                "quantity": 20,
                "itemUnit": "PCS",
                "charField1Name": "Proses",
                "charField1": "Tidak Cetak",
                "charField2Name": "Warna",
                "charField2": "SYN-CLEAR",
            },
            {
                "id": 1,
                "itemNo": "SYN-ITEM-001",
                "detailName": "First",
                "quantity": 10,
                "itemUnit": "PCS",
                "charField1Name": "Proses",
                "charField1": "Cetak",
                "charField2Name": "Warna",
                "charField2": "SYN-RED",
            },
        ],
    }
    probe._HTTP_METHODS_EXECUTED.clear()
    report = probe.build_report(raw, expected, SYN_SO)
    assert report["ok"] is True
    assert report["total_quantity"]["pdf_compare"] == "MATCH"
    assert report["line_count"]["pdf_compare"] == "MATCH"
    assert report["header_fields"]["delivery_zone"]["pdf_compare"] == "MATCH"
    assert report["header_fields"]["status_pesanan"]["pdf_compare"] == "MATCH"
    assert report["header_fields"]["buffer"]["pdf_compare"] == "MATCH"
    assert (
        report["header_fields"]["delivery_zone"]["matching_parser_source"]
        == "owner_accurate_configuration"
    )
    assert report["header_fields"]["expedition"]["pdf_compare"] == "UNKNOWN"
    by_hash = {i["item_code_hash"]: i for i in report["items"]}
    h1 = probe._item_code_hash("SYN-ITEM-001")
    h2 = probe._item_code_hash("SYN-ITEM-002")
    assert by_hash[h1]["pdf_compare"]["qty"] == "MATCH"
    assert by_hash[h1]["pdf_compare"]["process"] == "MATCH"
    assert by_hash[h1]["pdf_compare"]["color"] == "MATCH"
    assert by_hash[h2]["pdf_compare"]["process"] == "MATCH"
    assert by_hash[h1]["parser_sources"]["process_source"] == "owner_accurate_configuration"
    blob = json.dumps(report)
    assert "SYN-ITEM-001" not in blob
    assert "Synthetic Salesperson" not in blob
    assert "Synthetic Customer" not in blob
    assert SYN_SO not in blob


def test_duplicate_accurate_item_codes_hashed(probe, expected_path):
    expected = probe.load_expected_file(str(expected_path), SYN_SO)
    raw = {
        "id": 7,
        "number": SYN_SO,
        "detailItem": [
            {"id": 1, "itemNo": "SYN-ITEM-001", "quantity": 10, "itemUnit": "PCS"},
            {"id": 2, "itemNo": "SYN-ITEM-001", "quantity": 10, "itemUnit": "PCS"},
            {"id": 3, "itemNo": "SYN-ITEM-002", "quantity": 20, "itemUnit": "PCS"},
        ],
    }
    probe._HTTP_METHODS_EXECUTED.clear()
    report = probe.build_report(raw, expected, SYN_SO)
    blob = json.dumps(report)
    assert "SYN-ITEM-001" not in blob
    assert report["identity"]["duplicate_item_code_count"] == 1
    assert report["identity"]["duplicate_item_code_hashes"] == [
        probe._item_code_hash("SYN-ITEM-001")
    ]


def test_sanitize_exc_no_pii_or_token(probe):
    class AccurateUpstreamError(Exception):
        def __init__(self):
            self.code = "accurate_http_error"
            self.message = (
                "Bearer SECRETTOKEN999 customer=ACME "
                f"so={SYN_SO} path=/etc/epv3/secret.json"
            )

    out = probe._sanitize_exc(AccurateUpstreamError())
    blob = json.dumps(out)
    assert out["message"] == "redacted"
    assert "SECRETTOKEN999" not in blob
    assert "ACME" not in blob
    assert SYN_SO not in blob
    assert "/etc/epv3" not in blob


def test_unlabeled_custom_field_not_semantic(probe, expected_path):
    """Non-approved unlabeled slots stay non-authoritative; Slice 1N ordinals may map."""
    expected = probe.load_expected_file(str(expected_path), SYN_SO)
    raw = {
        "id": 3,
        "number": SYN_SO,
        # Unapproved header slots (expedition still blocked).
        "charField1": "SYN-COURIER",
        "charField2": "ZONE-A",
        # Slice 1N Owner ordinals without companion labels.
        "charField3": "ZONE-A",
        "charField4": "Normal",
        "charField5": "Non-Buffer",
        "detailItem": [
            {
                "id": 1,
                "itemNo": "SYN-ITEM-001",
                "quantity": 10,
                "itemUnit": "PCS",
                "charField1": "Cetak",
                "charField2": "SYN-RED",
            },
            {
                "id": 2,
                "itemNo": "SYN-ITEM-002",
                "quantity": 20,
                "itemUnit": "PCS",
                "charField1": "Tidak Cetak",
                "charField2": "SYN-CLEAR",
            },
        ],
    }
    probe._HTTP_METHODS_EXECUTED.clear()
    report = probe.build_report(raw, expected, SYN_SO)
    assert report["header_fields"]["expedition"]["pdf_compare"] == "UNKNOWN"
    assert report["header_fields"]["delivery_zone"]["pdf_compare"] == "MATCH"
    assert report["header_fields"]["status_pesanan"]["pdf_compare"] == "MATCH"
    assert report["header_fields"]["buffer"]["pdf_compare"] == "MATCH"
    by_slot = {s["slot"]: s for s in report["header_charField_slots"]}
    assert by_slot["charField1"]["semantic_mapping"] == "unlabeled_value_not_authoritative"
    assert by_slot["charField2"]["semantic_mapping"] == "unlabeled_value_not_authoritative"
    assert by_slot["charField3"]["semantic_mapping"] == "owner_approved_ordinal:delivery_zone"
    assert by_slot["charField4"]["semantic_mapping"] == "owner_approved_ordinal:order_priority"
    assert by_slot["charField5"]["semantic_mapping"] == "owner_approved_ordinal:buffer"


def test_identity_mismatch_hides_numbers(probe, expected_path):
    expected = probe.load_expected_file(str(expected_path), SYN_SO)
    raw = {"id": 1, "number": "SO/OTHER/000002", "detailItem": []}
    report = probe.build_report(raw, expected, SYN_SO)
    assert report["ok"] is False
    assert report["blocker"] == "document_number_mismatch"
    blob = json.dumps(report)
    assert "SO/OTHER" not in blob
    assert SYN_SO not in blob
