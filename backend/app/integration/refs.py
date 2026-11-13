"""Stable external reference helpers for ERP V2 entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.integration.models import (
    CustomerRef,
    ProductRef,
    SalesOrderLineRef,
    SalesOrderRef,
)

EXTERNAL_SYSTEM_ERP_V2 = "erp_v2"

DocumentType = Literal[
    "customer",
    "product",
    "sales_order",
    "sales_order_line",
]


@dataclass(frozen=True, slots=True)
class ExternalRef:
    external_system: str
    document_type: DocumentType
    external_id: str
    branch_id: str | None = None


def customer_external_ref(ref: CustomerRef) -> ExternalRef:
    return ExternalRef(
        external_system=ref.external_system,
        document_type="customer",
        external_id=ref.customer_id,
    )


def product_external_ref(ref: ProductRef) -> ExternalRef:
    return ExternalRef(
        external_system=ref.external_system,
        document_type="product",
        external_id=ref.product_id,
    )


def sales_order_external_ref(ref: SalesOrderRef) -> ExternalRef:
    return ExternalRef(
        external_system=ref.external_system,
        document_type="sales_order",
        external_id=ref.sales_order_id,
        branch_id=ref.branch_id,
    )


def sales_order_line_external_ref(
    line: SalesOrderLineRef,
    *,
    branch_id: str | None = None,
) -> ExternalRef:
    return ExternalRef(
        external_system=line.external_system,
        document_type="sales_order_line",
        external_id=line.sales_order_line_id,
        branch_id=branch_id,
    )
