"""Production V3 Accurate inbox — read-only intake with V3 auth + WO status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    PERM_INBOX_READ,
    PERM_ORDER_READ,
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


@router.get("/inbox")
async def inbox(
    page: int = Query(1, ge=1, le=100000),
    limit: int = Query(50, ge=1, le=100),
    keyword: str = Query("", max_length=120),
    gateway: ReadGateway = Depends(get_gateway),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permissions(PERM_INBOX_READ)),
):
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
