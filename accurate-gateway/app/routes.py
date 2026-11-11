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


@router.get("/sales-orders/{number}")
async def get_sales_order(
    number: str,
    settings: GatewaySettings = Depends(get_settings),
) -> dict[str, Any]:
    mode = _mode(settings)
    if mode == "fixture":
        row = fixtures.get_sales_order(number)
        if row is None:
            raise HTTPException(
                404,
                detail={
                    "code": "document_not_found",
                    "message": f"SO {number} tidak ada di fixture",
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
        row = await _require_live_ready(settings).get_sales_order(number)
    except AccurateUpstreamError as exc:
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
