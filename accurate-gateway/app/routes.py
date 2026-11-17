"""Read-only Accurate gateway routes for Production V3."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app import fixtures
from app.accurate_client import AccurateClient, AccurateUpstreamError
from app.auth import require_m2m
from app.config import GatewaySettings, get_settings
from app.contracts import delivery_note_contract, receipt_contract, so_detail, so_list_row

router = APIRouter(dependencies=[Depends(require_m2m)])


def _client(settings: GatewaySettings) -> AccurateClient:
    return AccurateClient(settings)


def _upstream_http(exc: AccurateUpstreamError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _mode(settings: GatewaySettings) -> str:
    """Only exact live|fixture. Unknown values fail closed (never silent fixture)."""
    mode = (settings.gateway_mode or "").strip().lower()
    if mode == "live":
        return "live"
    if mode in {"", "fixture"}:
        return "fixture"
    raise HTTPException(
        status_code=503,
        detail={
            "code": "gateway_mode_invalid",
            "message": "GATEWAY_MODE must be live or fixture",
        },
    )


def _require_live_ready(settings: GatewaySettings) -> AccurateClient:
    """Live mode: credentials required; never fall back to fixtures/demo data."""
    client = _client(settings)
    if not client.configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "accurate_credentials_missing",
                "message": (
                    "GATEWAY_MODE=live requires ACCURATE_API_TOKEN and "
                    "ACCURATE_SIGNATURE_SECRET — fixture fallback forbidden"
                ),
            },
        )
    return client


@router.get("/integration-coverage")
async def integration_coverage(
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    """G4 — declare proven Accurate read surfaces only (no invented endpoints)."""
    mode = _mode(settings)
    return {
        "service": "accurate-read-gateway",
        "mode": mode,
        "read_only": True,
        "live_writes": False,
        "docs_ref": [
            "Accurate OpenAPI: GET /api/sales-invoice/list.do|detail.do (sales_invoice_view)",
            "Accurate OpenAPI: GET /api/delivery-order/list.do|detail.do (delivery_order_view)",
            "SwaggerHub cpssoft/accurate-online-public-api",
        ],
        "proven_endpoints": [
            {"method": "GET", "path": "/sales-orders", "upstream": "sales-order/list.do"},
            {"method": "GET", "path": "/sales-orders/{key}", "upstream": "sales-order/detail.do"},
            {"method": "GET", "path": "/receipts/{id}", "upstream": "sales-receipt/detail.do"},
            {
                "method": "GET",
                "path": "/delivery-notes",
                "upstream": "delivery-order/list.do",
                "live_verified": True,
                "note": "Director Live census_scan_pass; gateway deploy separate",
            },
            {
                "method": "GET",
                "path": "/delivery-notes/{id}",
                "upstream": "delivery-order/detail.do",
                "lookup": "prefer Accurate internal id (detail.do?id=)",
                "live_verified": True,
            },
            {
                "method": "GET",
                "path": "/sales-invoices",
                "upstream": "sales-invoice/list.do",
                "live_verified": True,
                "owing_field": "primeOwing",
            },
            {
                "method": "GET",
                "path": "/sales-invoices/{id}",
                "upstream": "sales-invoice/detail.do",
                "live_verified": True,
                "owing_field": "primeOwing",
            },
        ],
        "outstanding": {
            "status": "DIRECTOR_LIVE_EVIDENCE",
            "gateway_endpoint": "GET /sales-invoices[/{id}]",
            "upstream_accurate_path": "/accurate/api/sales-invoice/list.do|detail.do",
            "owing_field": "primeOwing",
            "fail_closed": True,
            "live_verified": True,
            "live_sample_n": 20,
            "note": (
                "Director Live: primeOwing authoritative. Map Lunas/Belum Bayar/Sebagian "
                "only from valid owing; else UNKNOWN. totalAmount is never sisa piutang."
            ),
        },
        "sj_coverage": {
            "status": "DIRECTOR_LIVE_EVIDENCE",
            "list_endpoint": "GET /delivery-notes → delivery-order/list.do",
            "detail_endpoint": "GET /delivery-notes/{internal_id}",
            "discovery": [
                "delivery-order/list.do → internal id → detail.do",
                "pagination + dedup + metadata fail-closed",
                "V3 loading events / SO links (secondary)",
            ],
            "full_accurate_sj_universe": False,
            "census_scan_pass_director": True,
            "atomic_snapshot_guaranteed": False,
            "live_verified": True,
            "fail_closed": True,
        },
    }


@router.get("/sales-orders")
async def list_sales_orders(
    customer: str | None = Query(default=None),
    branch: str | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    mode = _mode(settings)
    needle = keyword or customer
    if mode == "fixture":
        items, total = fixtures.list_sales_orders(
            customer=needle,
            branch=branch,
            status=status,
            limit=limit,
            page=page,
        )
        rows = [so_list_row(r) for r in items]
        return {
            "rows": rows,
            "items": rows,  # dual key for older probes
            "total": total,
            "page": page,
            "pageSize": limit,
            "source": "fixture",
            "live_verified": False,
            "filter_incomplete": False,
        }
    # LIVE — fixtures unreachable on this branch
    try:
        listed = await _require_live_ready(settings).list_sales_orders(
            customer=needle,
            branch=branch,
            status=status,
            limit=limit,
            page=page,
        )
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    rows = [so_list_row(r) for r in listed["rows"]]
    accurate_total = listed.get("accurate_total")
    filter_incomplete = bool(listed.get("filter_incomplete"))
    # Prefer Accurate total; never invent a full filtered corpus from one page.
    if accurate_total is not None and not filter_incomplete:
        total_out: int | None = int(accurate_total)
    elif accurate_total is not None and filter_incomplete:
        # Upstream total is unfiltered / incomplete relative to local page filter.
        total_out = int(accurate_total)
    else:
        total_out = None
    return {
        "rows": rows,
        "items": rows,
        "total": total_out if total_out is not None else len(rows),
        "accurate_total": accurate_total,
        "page": listed.get("page", page),
        "pageSize": listed.get("page_size", limit),
        "source": "accurate_live",
        "live_verified": True,
        "filter_incomplete": filter_incomplete,
    }


@router.get("/sales-orders/{number:path}")
async def get_sales_order(
    number: str,
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    """Detail by Accurate document number or internal id (path may include '/')."""
    mode = _mode(settings)
    key = (number or "").strip()
    if mode == "fixture":
        row = fixtures.get_sales_order(key)
        if row is None and key.isdigit():
            # Allow fixture lookup by accurate_id as well as document number.
            for candidate in fixtures.FIXTURE_SALES_ORDERS.values():
                if str(candidate.get("accurate_id") or candidate.get("id") or "") == key:
                    row = fixtures.get_sales_order(str(candidate["number"]))
                    break
        if row is None:
            raise HTTPException(
                404,
                detail={
                    "code": "document_not_found",
                    "message": "SO tidak ada di fixture",
                },
            )
        detail = so_detail(row)
        return {
            "sales_order": detail,
            "preview": detail,
            "source": "fixture",
            "live_verified": False,
        }
    try:
        row = await _require_live_ready(settings).get_sales_order(key)
    except AccurateUpstreamError as exc:
        # Preserve upstream vs local distinction via error code (no document id logged).
        raise _upstream_http(exc) from exc
    detail = so_detail(row)
    links = detail.get("links") if isinstance(detail.get("links"), dict) else {}
    return {
        "sales_order": detail,
        "preview": detail,
        "source": "accurate_live",
        "live_verified": True,
        # Missing receipt/SJ refs are discovery gaps — not verification.
        "links_authoritative": False,
        "receipts_linked": bool(links.get("receipts_present") or links.get("receipt_ids")),
        "delivery_notes_linked": bool(
            links.get("delivery_notes_present") or links.get("delivery_note_ids")
        ),
    }


@router.get("/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    mode = _mode(settings)
    if mode == "fixture":
        row = fixtures.get_receipt(receipt_id)
        if row is None:
            raise HTTPException(
                404,
                detail={
                    "code": "document_not_found",
                    "message": f"Receipt {receipt_id} tidak ada di fixture",
                },
            )
        out = receipt_contract(row)
        out["source"] = "fixture"
        out["live_verified"] = False
        return out
    try:
        row = await _require_live_ready(settings).get_receipt(receipt_id)
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    out = receipt_contract(row)
    out["source"] = "accurate_live"
    out["live_verified"] = True
    return out


@router.get("/sales-invoices")
async def list_sales_invoices(
    keywords: str | None = Query(default=None),
    outstanding_only: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    """Outstanding source: official sales-invoice/list.do (live_verified only in live)."""
    from app.reconcile import reconcile_id_pages

    mode = _mode(settings)
    if mode == "fixture":
        items, total = fixtures.list_sales_invoices(
            keywords=keywords,
            outstanding_only=outstanding_only,
            limit=limit,
            page=page,
        )
        recon = reconcile_id_pages([items], claimed_total=total)
        return {
            "rows": items,
            "items": items,
            "total": total,
            "accurate_total": total,
            "page": page,
            "pageSize": limit,
            "source": "fixture",
            "live_verified": False,
            "reconciliation": recon,
            "filter_incomplete": bool(recon.get("incomplete")),
            "full_universe_verified": False,
        }
    try:
        listed = await _require_live_ready(settings).list_sales_invoices(
            keywords=keywords,
            outstanding_only=outstanding_only,
            limit=limit,
            page=page,
        )
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    rows = listed.get("rows") or []
    recon = reconcile_id_pages([rows], claimed_total=listed.get("accurate_total"))
    return {
        "rows": rows,
        "items": rows,
        "total": listed.get("accurate_total")
        if listed.get("accurate_total") is not None
        else len(rows),
        "accurate_total": listed.get("accurate_total"),
        "page": listed.get("page", page),
        "pageSize": listed.get("page_size", limit),
        "source": "accurate_live",
        "live_verified": True,
        "reconciliation": recon,
        "filter_incomplete": bool(
            listed.get("filter_incomplete") or recon.get("incomplete")
        ),
        "full_universe_verified": False,
    }


@router.get("/sales-invoices/{invoice_id}")
async def get_sales_invoice(
    invoice_id: str,
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    mode = _mode(settings)
    if mode == "fixture":
        row = fixtures.get_sales_invoice(invoice_id)
        if row is None:
            raise HTTPException(
                404,
                detail={
                    "code": "document_not_found",
                    "message": f"Invoice {invoice_id} tidak ada di fixture",
                },
            )
        out = dict(row)
        out["source"] = "fixture"
        out["live_verified"] = False
        out["verified"] = False
        return out
    try:
        row = await _require_live_ready(settings).get_sales_invoice(invoice_id)
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    out = dict(row)
    out["source"] = "accurate_live"
    out["live_verified"] = True
    # verified only when primeOwing mapped to a status (owing_known).
    out["verified"] = bool(out.get("owing_known"))
    return out


@router.get("/delivery-notes")
async def list_delivery_notes(
    keywords: str | None = Query(default=None),
    branch: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    """Official delivery-order/list.do — census not claimed from a single page."""
    from app.reconcile import reconcile_id_pages

    mode = _mode(settings)
    if mode == "fixture":
        items, total = fixtures.list_delivery_notes(
            keywords=keywords, branch=branch, limit=limit, page=page
        )
        recon = reconcile_id_pages([items], claimed_total=total)
        return {
            "rows": items,
            "items": items,
            "total": total,
            "accurate_total": total,
            "page": page,
            "pageSize": limit,
            "source": "fixture",
            "live_verified": False,
            "full_accurate_sj_universe": False,
            "atomic_snapshot_guaranteed": False,
            "reconciliation": recon,
            "filter_incomplete": bool(recon.get("incomplete")),
            "discovery": "list.do → internal id → detail.do",
        }
    try:
        listed = await _require_live_ready(settings).list_delivery_notes(
            keywords=keywords, branch=branch, limit=limit, page=page
        )
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    rows = listed.get("rows") or []
    recon = reconcile_id_pages([rows], claimed_total=listed.get("accurate_total"))
    return {
        "rows": rows,
        "items": rows,
        "total": listed.get("accurate_total")
        if listed.get("accurate_total") is not None
        else len(rows),
        "accurate_total": listed.get("accurate_total"),
        "page": listed.get("page", page),
        "pageSize": listed.get("page_size", limit),
        "source": "accurate_live",
        "live_verified": True,
        "full_accurate_sj_universe": False,
        "atomic_snapshot_guaranteed": False,
        "reconciliation": recon,
        "filter_incomplete": bool(
            listed.get("filter_incomplete") or recon.get("incomplete")
        ),
        "discovery": "list.do → internal id → detail.do",
    }


@router.get("/delivery-notes/{dn_id}")
async def get_delivery_note(
    dn_id: str,
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    mode = _mode(settings)
    if mode == "fixture":
        row = fixtures.get_delivery_note(dn_id)
        if row is None:
            raise HTTPException(
                404,
                detail={
                    "code": "document_not_found",
                    "message": f"SJ {dn_id} tidak ada di fixture",
                },
            )
        out = delivery_note_contract(row)
        out["source"] = "fixture"
        out["live_verified"] = False
        return out
    try:
        row = await _require_live_ready(settings).get_delivery_note(dn_id)
    except AccurateUpstreamError as exc:
        raise _upstream_http(exc) from exc
    out = delivery_note_contract(row)
    out["source"] = "accurate_live"
    out["live_verified"] = True
    return out
