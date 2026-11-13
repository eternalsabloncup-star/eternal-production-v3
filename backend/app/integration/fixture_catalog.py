"""Authorized local fixture catalog for ERP V2 sandbox reads.

Not a live API dump. Field keys used for visibility match verified stable ID
candidates and the known SO status filter. No Surat Jalan authority is modeled.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.integration.models import (
    CustomerRef,
    ProductRef,
    SalesOrderLineRef,
    SalesOrderRef,
)
from app.integration.refs import EXTERNAL_SYSTEM_ERP_V2

# Sandbox-only permission labels (NOT verified live V2 permission strings).
PERM_CUSTOMERS_READ = "fixture.customers.read"
PERM_PRODUCTS_READ = "fixture.products.read"
PERM_SALES_ORDERS_READ = "fixture.sales_orders.read"


@dataclass(frozen=True, slots=True)
class FixtureSalesOrderRecord:
    sales_order_id: str
    customer_id: str
    branch_id: str
    status: str
    owner_user_id: str
    approver_user_ids: tuple[str, ...]
    lines: tuple[tuple[str, str], ...]  # (sales_order_line_id, product_id)
    force_upstream_forbidden: bool = False


CUSTOMERS: dict[str, CustomerRef] = {
    "cust-100": CustomerRef(EXTERNAL_SYSTEM_ERP_V2, "cust-100"),
    "cust-200": CustomerRef(EXTERNAL_SYSTEM_ERP_V2, "cust-200"),
}

PRODUCTS: dict[str, ProductRef] = {
    "prod-10": ProductRef(EXTERNAL_SYSTEM_ERP_V2, "prod-10"),
    "prod-20": ProductRef(EXTERNAL_SYSTEM_ERP_V2, "prod-20"),
    "prod-30": ProductRef(EXTERNAL_SYSTEM_ERP_V2, "prod-30"),
}

SALES_ORDERS: dict[str, FixtureSalesOrderRecord] = {
    "so-1": FixtureSalesOrderRecord(
        sales_order_id="so-1",
        customer_id="cust-100",
        branch_id="branch-a",
        status="open",
        owner_user_id="user-owner",
        approver_user_ids=("user-approver",),
        lines=(
            ("sol-1a", "prod-10"),
            ("sol-1b", "prod-20"),
        ),
    ),
    "so-2": FixtureSalesOrderRecord(
        sales_order_id="so-2",
        customer_id="cust-200",
        branch_id="branch-b",
        status="closed",
        owner_user_id="user-other",
        approver_user_ids=(),
        lines=(("sol-2a", "prod-30"),),
    ),
    "so-forbidden": FixtureSalesOrderRecord(
        sales_order_id="so-forbidden",
        customer_id="cust-100",
        branch_id="branch-a",
        status="open",
        owner_user_id="user-other",
        approver_user_ids=(),
        lines=(("sol-fx", "prod-10"),),
        force_upstream_forbidden=True,
    ),
}


def to_sales_order_ref(record: FixtureSalesOrderRecord) -> SalesOrderRef:
    lines = tuple(
        SalesOrderLineRef(
            external_system=EXTERNAL_SYSTEM_ERP_V2,
            sales_order_line_id=line_id,
            product_id=product_id,
        )
        for line_id, product_id in record.lines
    )
    return SalesOrderRef(
        external_system=EXTERNAL_SYSTEM_ERP_V2,
        sales_order_id=record.sales_order_id,
        customer_id=record.customer_id,
        branch_id=record.branch_id,
        status=record.status,
        lines=lines,
    )
