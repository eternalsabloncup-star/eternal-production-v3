"""G4 finalize — primeOwing mapping + census reconcile fail-closed."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["GATEWAY_MODE"] = "fixture"
os.environ["GATEWAY_M2M_TOKEN"] = "test-m2m-token"
os.environ.pop("ACCURATE_API_TOKEN", None)

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.normalize import map_prime_owing_status, normalize_sales_invoice  # noqa: E402
from app.reconcile import reconcile_id_pages  # noqa: E402

get_settings.cache_clear()


def test_primeowing_zero_full_partial_director_classes():
    z = normalize_sales_invoice({"id": 1, "number": "A", "totalAmount": 1000, "primeOwing": 0})
    assert z["financial_payment_status"] == "Lunas"
    assert z["owing_class"] == "ZERO"
    assert z["outstanding_amount"] == "0.00"
    assert z["owing_source_key"] == "primeOwing"

    f = normalize_sales_invoice({"id": 2, "number": "B", "totalAmount": 1000, "primeOwing": 1000})
    assert f["financial_payment_status"] == "Belum Bayar"
    assert f["owing_class"] == "FULL"
    assert f["outstanding_amount"] == "1000.00"

    p = normalize_sales_invoice({"id": 3, "number": "C", "totalAmount": 1000, "primeOwing": 250})
    assert p["financial_payment_status"] == "Sebagian"
    assert p["owing_class"] == "PARTIAL"
    assert p["outstanding_amount"] == "250.00"
    assert p["paid_amount"] == "750.00"


def test_total_amount_alone_never_becomes_owing():
    row = normalize_sales_invoice({"id": 4, "number": "D", "totalAmount": 999})
    assert row["outstanding_amount"] is None
    assert row["financial_payment_status"] is None
    assert row["owing_known"] is False
    label, cls = map_prime_owing_status(owing=None, invoice_total="999")
    assert label is None and cls is None


def test_negative_owing_fail_closed():
    row = normalize_sales_invoice({"id": 5, "number": "E", "totalAmount": 100, "primeOwing": -1})
    assert row["financial_payment_status"] is None
    assert row["outstanding_amount"] is None


def test_census_scan_pass_director_shape_but_not_atomic_universe():
    # Simulate Director G4B counts at small scale: unique == claimed, no dups.
    pages = [[{"accurate_id": str(i)} for i in range(1, 101)]]
    pages.append([{"accurate_id": str(i)} for i in range(101, 201)])
    recon = reconcile_id_pages(
        pages,
        claimed_total=200,
        page_count_claimed=2,
        failed_pages=0,
        metadata_errors=0,
        first_page_stable=True,
    )
    assert recon["scanned_rows"] == 200
    assert recon["unique_ids"] == 200
    assert recon["duplicate_ids"] == 0
    assert recon["missing_ids"] == 0
    assert recon["census_scan_pass"] is True
    assert recon["full_universe_verified"] is False
    assert recon["atomic_snapshot_guaranteed"] is False


def test_census_fail_closed_on_duplicates_or_failed_pages():
    pages = [[{"accurate_id": "1"}, {"accurate_id": "1"}]]
    recon = reconcile_id_pages(pages, claimed_total=1, first_page_stable=True)
    assert recon["duplicate_ids"] == 1
    assert recon["census_scan_pass"] is False
    assert recon["incomplete"] is True

    recon2 = reconcile_id_pages(
        [[{"accurate_id": "1"}]],
        claimed_total=1,
        failed_pages=1,
        first_page_stable=True,
    )
    assert recon2["census_scan_pass"] is False


@pytest.mark.asyncio
async def test_integration_coverage_director_live_evidence_flags():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get(
            "/integration-coverage",
            headers={"Authorization": "Bearer test-m2m-token"},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["outstanding"]["status"] == "DIRECTOR_LIVE_EVIDENCE"
        assert body["outstanding"]["owing_field"] == "primeOwing"
        assert body["sj_coverage"]["census_scan_pass_director"] is True
        assert body["sj_coverage"]["atomic_snapshot_guaranteed"] is False
        assert body["sj_coverage"]["full_accurate_sj_universe"] is False
