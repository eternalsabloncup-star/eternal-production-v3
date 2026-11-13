"""Fixture-only ERP V2 read adapter — zero network access."""

from __future__ import annotations

from app.integration.errors import (
    IntegrationForbidden,
    IntegrationNotFound,
    IntegrationUnauthorized,
    IntegrationUpstreamForbidden,
)
from app.integration.fixture_catalog import (
    CUSTOMERS,
    PERM_CUSTOMERS_READ,
    PERM_PRODUCTS_READ,
    PERM_SALES_ORDERS_READ,
    PRODUCTS,
    SALES_ORDERS,
    FixtureSalesOrderRecord,
    to_sales_order_ref,
)
from app.integration.models import AuthContext, CustomerRef, ProductRef, SalesOrderRef
from app.integration.receipts import InMemoryReadReceiptStore


class FixtureErpV2ReadAdapter:
    """Local authorized catalog. Guarantees no HTTP client / network I/O."""

    def __init__(self, receipts: InMemoryReadReceiptStore | None = None) -> None:
        self._receipts = receipts or InMemoryReadReceiptStore()
        # Explicit non-network marker for tests.
        self.http_client = None
        self.base_url = None
        self.allows_network = False

    @property
    def receipts(self) -> InMemoryReadReceiptStore:
        return self._receipts

    def get_customer(self, auth: AuthContext, customer_id: str) -> CustomerRef:
        self._require_session(auth, operation="get_customer")
        self._require_permission(auth, PERM_CUSTOMERS_READ, operation="get_customer")
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            self._receipts.record(
                operation="get_customer",
                external_ids=(customer_id,),
                auth_subject=self._subject(auth),
                result="not_found",
            )
            raise IntegrationNotFound(f"Customer not found: {customer_id}")
        self._receipts.record(
            operation="get_customer",
            external_ids=(customer_id,),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return customer

    def list_customers(self, auth: AuthContext) -> list[CustomerRef]:
        self._require_session(auth, operation="list_customers")
        self._require_permission(auth, PERM_CUSTOMERS_READ, operation="list_customers")
        items = list(CUSTOMERS.values())
        self._receipts.record(
            operation="list_customers",
            external_ids=tuple(c.customer_id for c in items),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return items

    def get_product(self, auth: AuthContext, product_id: str) -> ProductRef:
        """Resolve product from authorized fixture catalog.

        There is no verified live GET `/api/masters/products/{product_id}`.
        """
        self._require_session(auth, operation="get_product")
        self._require_permission(auth, PERM_PRODUCTS_READ, operation="get_product")
        product = PRODUCTS.get(product_id)
        if product is None:
            self._receipts.record(
                operation="get_product",
                external_ids=(product_id,),
                auth_subject=self._subject(auth),
                result="not_found",
            )
            raise IntegrationNotFound(f"Product not found: {product_id}")
        self._receipts.record(
            operation="get_product",
            external_ids=(product_id,),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return product

    def list_products(self, auth: AuthContext) -> list[ProductRef]:
        self._require_session(auth, operation="list_products")
        self._require_permission(auth, PERM_PRODUCTS_READ, operation="list_products")
        items = list(PRODUCTS.values())
        self._receipts.record(
            operation="list_products",
            external_ids=tuple(p.product_id for p in items),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return items

    def get_sales_order(self, auth: AuthContext, sales_order_id: str) -> SalesOrderRef:
        self._require_session(auth, operation="get_sales_order")
        self._require_permission(auth, PERM_SALES_ORDERS_READ, operation="get_sales_order")
        record = SALES_ORDERS.get(sales_order_id)
        if record is None:
            self._receipts.record(
                operation="get_sales_order",
                external_ids=(sales_order_id,),
                auth_subject=self._subject(auth),
                result="not_found",
            )
            raise IntegrationNotFound(f"Sales order not found: {sales_order_id}")
        self._assert_sales_order_visible(auth, record, operation="get_sales_order")
        ref = to_sales_order_ref(record)
        self._receipts.record(
            operation="get_sales_order",
            external_ids=(sales_order_id,),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return ref

    def list_sales_orders(
        self,
        auth: AuthContext,
        *,
        status: str | None = None,
    ) -> list[SalesOrderRef]:
        """Mirror verified list contract: status filter, list result, no pagination."""
        self._require_session(auth, operation="list_sales_orders")
        self._require_permission(auth, PERM_SALES_ORDERS_READ, operation="list_sales_orders")
        results: list[SalesOrderRef] = []
        for record in SALES_ORDERS.values():
            if status is not None and record.status != status:
                continue
            if not self._is_sales_order_visible(auth, record):
                continue
            if record.force_upstream_forbidden:
                continue
            results.append(to_sales_order_ref(record))
        self._receipts.record(
            operation="list_sales_orders",
            external_ids=tuple(r.sales_order_id for r in results),
            auth_subject=self._subject(auth),
            result="ok",
        )
        return results

    def _require_session(self, auth: AuthContext, *, operation: str) -> None:
        if not auth.session_token or auth.me is None:
            self._receipts.record(
                operation=operation,
                auth_subject=None,
                result="unauthorized",
            )
            raise IntegrationUnauthorized("Missing or invalid session")

    def _require_permission(
        self,
        auth: AuthContext,
        permission: str,
        *,
        operation: str,
    ) -> None:
        assert auth.me is not None
        if permission not in auth.me.permissions:
            self._receipts.record(
                operation=operation,
                auth_subject=self._subject(auth),
                result="forbidden",
            )
            raise IntegrationForbidden(f"Missing permission: {permission}")

    def _is_sales_order_visible(
        self,
        auth: AuthContext,
        record: FixtureSalesOrderRecord,
    ) -> bool:
        """Simulate V2 SO visibility: permission (already checked) + branch + owner/approver.

        Branch membership comes only from explicit AuthContext.simulated_branch_ids
        (test harness), never from invented `/auth/me` branch claims.
        """
        assert auth.me is not None
        if record.branch_id not in auth.simulated_branch_ids:
            return False
        if record.force_upstream_forbidden:
            return False
        user_id = auth.me.user_id
        if record.owner_user_id == user_id:
            return True
        if user_id in record.approver_user_ids:
            return True
        if record.sales_order_id in auth.simulated_owned_sales_order_ids:
            return True
        if record.sales_order_id in auth.simulated_approver_sales_order_ids:
            return True
        return False

    def _assert_sales_order_visible(
        self,
        auth: AuthContext,
        record: FixtureSalesOrderRecord,
        *,
        operation: str,
    ) -> None:
        assert auth.me is not None
        if record.force_upstream_forbidden:
            self._receipts.record(
                operation=operation,
                external_ids=(record.sales_order_id,),
                auth_subject=self._subject(auth),
                result="upstream_forbidden",
            )
            raise IntegrationUpstreamForbidden(
                f"Upstream forbidden for sales order: {record.sales_order_id}"
            )
        if record.branch_id not in auth.simulated_branch_ids:
            self._receipts.record(
                operation=operation,
                external_ids=(record.sales_order_id,),
                auth_subject=self._subject(auth),
                result="forbidden",
            )
            raise IntegrationForbidden(
                f"Branch scope mismatch for sales order: {record.sales_order_id}"
            )
        if not self._is_sales_order_visible(auth, record):
            self._receipts.record(
                operation=operation,
                external_ids=(record.sales_order_id,),
                auth_subject=self._subject(auth),
                result="forbidden",
            )
            raise IntegrationForbidden(
                f"Sales order not visible to caller: {record.sales_order_id}"
            )

    @staticmethod
    def _subject(auth: AuthContext) -> str | None:
        return auth.me.user_id if auth.me else None
