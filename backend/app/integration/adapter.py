"""Read-only ERP V2 adapter protocol."""

from __future__ import annotations

from typing import Protocol

from app.integration.models import (
    AuthContext,
    CustomerRef,
    ProductRef,
    SalesOrderRef,
)


class ErpV2ReadAdapter(Protocol):
    """Narrow read-only surface for Customer / Product / Sales Order."""

    def get_customer(self, auth: AuthContext, customer_id: str) -> CustomerRef: ...

    def list_customers(self, auth: AuthContext) -> list[CustomerRef]: ...

    def get_product(self, auth: AuthContext, product_id: str) -> ProductRef: ...

    def list_products(self, auth: AuthContext) -> list[ProductRef]: ...

    def get_sales_order(self, auth: AuthContext, sales_order_id: str) -> SalesOrderRef: ...

    def list_sales_orders(
        self,
        auth: AuthContext,
        *,
        status: str | None = None,
    ) -> list[SalesOrderRef]: ...
