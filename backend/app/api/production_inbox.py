"""Production V3 Accurate inbox — read-only intake with V3 auth + WO status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    PERM_INBOX_READ,
    PERM_ORDER_READ,
    get_current_user,
    require_permissions,
    user_can_access_branch,
)
from app.db.session import get_db_session
from app.models.user import User
from app.models.work_order import WorkOrder
from app.services.accurate_read_gateway import (
    ReadGateway,
    get_sales_order,
    list_sales_orders,
)
from app.services.production import permissions as P

router = APIRouter(prefix="/production", tags=["production-intake"])


def get_gateway() -> ReadGateway:
    return ReadGateway()


async def _status_map(
    session: AsyncSession, po_numbers: list[str]
) -> dict[str, str]:
    if not po_numbers:
        return {}
    result = await session.execute(
        select(WorkOrder).where(WorkOrder.accurate_so_number.in_(po_numbers))
    )
    out: dict[str, str] = {}
    for wo in result.scalars().all():
        status = (
            wo.processing_status
            if wo.processing_status in {"Baru", "Terproses"}
            else "Baru"
        )
        out[wo.accurate_so_number] = status
    return out


SCOPED_SCAN_PAGE_SIZE = 100


async def _scoped_inbox(gateway, session, user, page, limit, keyword) -> dict:
    """The gateway paginates across ALL branches and has no branch filter, so a
    branch-scoped page is assembled from consecutive upstream pages.

    Work is bounded by V3_INBOX_SCOPED_SCAN_MAX_PAGES upstream pages per request.
    - total is the caller's own-branch count and only reported when the upstream
      list was exhausted; otherwise it is null (never estimated, never the upstream
      total, so other branches' volume is not disclosed).
    - has_more is true only when a further visible row was actually found.
    - scan_incomplete tells the client the budget ended before the list did, so an
      empty or short page may not be the end."""
    from app.core.config import get_settings
    max_pages = get_settings().inbox_scoped_scan_max_pages
    needed = page * limit + 1
    rows: list[dict] = []
    upstream = 0
    seen = 0
    exhausted = False
    last_provenance = {
        "source": "accurate_gateway",
        "mode": "unverified",
        "live_verified": None,
        "filter_incomplete": False,
    }
    while len(rows) < needed:
        if upstream >= max_pages:
            break
        upstream += 1
        data = await list_sales_orders(
            gateway, page=upstream, limit=SCOPED_SCAN_PAGE_SIZE, keyword=keyword
        )
        last_provenance = {
            "source": data.get("source") or "accurate_gateway",
            "mode": data.get("mode") or "unverified",
            "live_verified": data.get("live_verified"),
            "filter_incomplete": bool(data.get("filter_incomplete")),
        }
        page_rows = data["rows"]
        seen += len(page_rows)
        rows.extend(
            r for r in page_rows if user_can_access_branch(user, r.get("branch_id"))
        )
        try:
            reported_total = (
                int(data["total"]) if data.get("total") is not None else None
            )
        except (TypeError, ValueError):
            reported_total = None
        if last_provenance["filter_incomplete"]:
            # Upstream total is not a trustworthy end-of-list signal under
            # incomplete filters — stop this page fetch without claiming exhaustion.
            if not page_rows:
                break
            continue
        if not page_rows:
            # Empty page with remaining reported total is NOT a complete inventory.
            if reported_total is None or seen >= reported_total:
                exhausted = True
            break
        if reported_total is not None and seen >= reported_total:
            exhausted = True
            break
    start = (page - 1) * limit
    scoped = rows[start : start + limit]
    statuses = await _status_map(session, [str(r["po_number"]) for r in scoped])
    for row in scoped:
        row["production_status"] = statuses.get(row["po_number"], "Baru")
    total = len(rows) if exhausted else None
    return {
        "rows": scoped,
        "total": total,
        "gateway_total": total,
        "page": page,
        "pageSize": limit,
        "page_count": len(scoped),
        "has_more": len(rows) > start + limit,
        "scan_incomplete": not exhausted and len(rows) < needed,
        "filtered_by_branch": True,
        "source": last_provenance["source"],
        "mode": last_provenance["mode"],
        "live_verified": last_provenance["live_verified"],
        "filter_incomplete": last_provenance["filter_incomplete"],
    }


def _inbox_requires_scoped_scan(user: User) -> bool:
    """Non-Direktur must not see cross-branch Accurate totals.

    Enforced path uses workflow context.director. Legacy (no context) falls back
    to role id — never treat missing context as Direktur.
    """
    from app.authorization.workflow import context

    ctx = context(user)
    if ctx is not None:
        return not bool(getattr(ctx.access, "director", False))
    role = str(getattr(user, "role", "") or "").strip().lower()
    return role not in {"direktur", "director"}


@router.get("/inbox")
async def inbox(
    page: int = Query(1, ge=1, le=100000),
    limit: int = Query(50, ge=1, le=100),
    keyword: str = Query("", max_length=120),
    gateway: ReadGateway = Depends(get_gateway),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(PERM_INBOX_READ)),
):
    if _inbox_requires_scoped_scan(user):
        return await _scoped_inbox(gateway, session, user, page, limit, keyword)
    data = await list_sales_orders(
        gateway, page=page, limit=limit, keyword=keyword
    )
    gateway_total = int(data.get("total") or 0)
    scoped = [
        row
        for row in data["rows"]
        if user_can_access_branch(user, row.get("branch_id"))
    ]
    statuses = await _status_map(session, [str(r["po_number"]) for r in scoped])
    for row in scoped:
        row["production_status"] = statuses.get(row["po_number"], "Baru")
    data["rows"] = scoped
    data["gateway_total"] = gateway_total
    # Preserve gateway server-side total for pagination; page length is len(rows).
    data["total"] = gateway_total
    data["page_count"] = len(scoped)
    data["filtered_by_branch"] = True
    return data


@router.get("/orders/{so_number:path}")
async def order_detail(
    so_number: str,
    gateway: ReadGateway = Depends(get_gateway),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(PERM_ORDER_READ)),
):
    detail = await get_sales_order(gateway, so_number)
    if not user_can_access_branch(user, detail.get("branch_id")):
        raise HTTPException(403, "Cabang dokumen di luar lingkup akses")
    statuses = await _status_map(session, [str(detail["po_number"])])
    detail["production_status"] = statuses.get(detail["po_number"], "Baru")
    return detail


@router.get("/permissions/catalog")
async def permissions_catalog(
    user: User = Depends(get_current_user),
):
    """Permission catalog + stable role-default mapping (config only; not live grants)."""
    _ = user
    return P.permission_catalog_payload()
