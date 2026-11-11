"""Sandbox ERP V2 fixture adapter tests — no network."""

from __future__ import annotations

import socket

import pytest

from app.integration.errors import (
    IntegrationForbidden,
    IntegrationNotFound,
    IntegrationUnauthorized,
    IntegrationUpstreamForbidden,
)
from app.integration.fixture_adapter import FixtureErpV2ReadAdapter
from app.integration.fixture_catalog import (
    PERM_CUSTOMERS_READ,
    PERM_PRODUCTS_READ,
    PERM_SALES_ORDERS_READ,
)
from app.integration.models import AuthContext, MeProfile
from app.integration.receipts import InMemoryReadReceiptStore
from app.integration.refs import (
    EXTERNAL_SYSTEM_ERP_V2,
    customer_external_ref,
    product_external_ref,
    sales_order_external_ref,
    sales_order_line_external_ref,
)


def _me(
    *,
    user_id: str = "user-owner",
    permissions: tuple[str, ...] = (
        PERM_CUSTOMERS_READ,
        PERM_PRODUCTS_READ,
        PERM_SALES_ORDERS_READ,
    ),
) -> MeProfile:
    return MeProfile(
        user_id=user_id,
        username="owner",
        display_name="Owner User",
        role="sales",
        permissions=permissions,
    )


def _auth(
    *,
    user_id: str = "user-owner",
    branches: frozenset[str] = frozenset({"branch-a"}),
    permissions: tuple[str, ...] | None = None,
    owned: frozenset[str] = frozenset(),
    approver: frozenset[str] = frozenset(),
    session_token: str | None = "session-ok",
    me: MeProfile | None | object = ...,
) -> AuthContext:
    profile: MeProfile | None
    if me is ...:
        profile = _me(
            user_id=user_id,
            permissions=permissions
            or (PERM_CUSTOMERS_READ, PERM_PRODUCTS_READ, PERM_SALES_ORDERS_READ),
        )
    else:
        profile = me  # type: ignore[assignment]
    return AuthContext(
        session_token=session_token,
        me=profile,
        simulated_branch_ids=branches,
        simulated_owned_sales_order_ids=owned,
        simulated_approver_sales_order_ids=approver,
    )


@pytest.fixture
def adapter() -> FixtureErpV2ReadAdapter:
    return FixtureErpV2ReadAdapter(InMemoryReadReceiptStore())


def test_customer_and_product_lookup(adapter: FixtureErpV2ReadAdapter) -> None:
    auth = _auth()
    customer = adapter.get_customer(auth, "cust-100")
    product = adapter.get_product(auth, "prod-10")
    assert customer.customer_id == "cust-100"
    assert product.product_id == "prod-10"
    assert customer.external_system == EXTERNAL_SYSTEM_ERP_V2


def test_sales_order_with_multiple_lines(adapter: FixtureErpV2ReadAdapter) -> None:
    so = adapter.get_sales_order(_auth(), "so-1")
    assert so.sales_order_id == "so-1"
    assert len(so.lines) == 2
    assert {line.sales_order_line_id for line in so.lines} == {"sol-1a", "sol-1b"}
    assert {line.product_id for line in so.lines} == {"prod-10", "prod-20"}


def test_list_sales_orders_status_filter_no_pagination(
    adapter: FixtureErpV2ReadAdapter,
) -> None:
    auth = _auth(branches=frozenset({"branch-a", "branch-b"}), user_id="user-owner")
    # owner only sees so-1 by ownership; grant approver visibility for so-2 via harness
    auth = _auth(
        user_id="user-owner",
        branches=frozenset({"branch-a", "branch-b"}),
        owned=frozenset({"so-2"}),
    )
    open_orders = adapter.list_sales_orders(auth, status="open")
    assert [o.sales_order_id for o in open_orders] == ["so-1"]
    closed = adapter.list_sales_orders(auth, status="closed")
    assert [o.sales_order_id for o in closed] == ["so-2"]


def test_missing_and_invalid_session(adapter: FixtureErpV2ReadAdapter) -> None:
    with pytest.raises(IntegrationUnauthorized):
        adapter.get_customer(
            AuthContext(session_token=None, me=None),
            "cust-100",
        )
    with pytest.raises(IntegrationUnauthorized):
        adapter.get_customer(
            AuthContext(session_token="", me=_me()),
            "cust-100",
        )
    with pytest.raises(IntegrationUnauthorized):
        adapter.get_customer(
            AuthContext(session_token="tok", me=None),
            "cust-100",
        )


def test_branch_mismatch(adapter: FixtureErpV2ReadAdapter) -> None:
    auth = _auth(branches=frozenset({"branch-b"}))  # so-1 is branch-a
    with pytest.raises(IntegrationForbidden, match="Branch scope mismatch"):
        adapter.get_sales_order(auth, "so-1")


def test_owner_approver_visibility_restrictions(
    adapter: FixtureErpV2ReadAdapter,
) -> None:
    # Same branch, but neither owner nor approver for so-1
    stranger = _auth(user_id="user-stranger", branches=frozenset({"branch-a"}))
    with pytest.raises(IntegrationForbidden, match="not visible"):
        adapter.get_sales_order(stranger, "so-1")

    approver = _auth(user_id="user-approver", branches=frozenset({"branch-a"}))
    so = adapter.get_sales_order(approver, "so-1")
    assert so.sales_order_id == "so-1"

    # Harness-simulated approver grant without matching fixture approver_user_ids
    granted = _auth(
        user_id="user-stranger",
        branches=frozenset({"branch-a"}),
        approver=frozenset({"so-1"}),
    )
    assert adapter.get_sales_order(granted, "so-1").sales_order_id == "so-1"


def test_forbidden_upstream_result(adapter: FixtureErpV2ReadAdapter) -> None:
    auth = _auth(user_id="user-owner", branches=frozenset({"branch-a"}))
    with pytest.raises(IntegrationUpstreamForbidden):
        adapter.get_sales_order(auth, "so-forbidden")
    assert adapter.receipts.all()[-1].result == "upstream_forbidden"


def test_missing_product(adapter: FixtureErpV2ReadAdapter) -> None:
    with pytest.raises(IntegrationNotFound, match="Product not found"):
        adapter.get_product(_auth(), "prod-missing")


def test_missing_permission_fail_closed(adapter: FixtureErpV2ReadAdapter) -> None:
    auth = _auth(permissions=(PERM_CUSTOMERS_READ,))  # no products/SO
    with pytest.raises(IntegrationForbidden, match="Missing permission"):
        adapter.get_product(auth, "prod-10")
    with pytest.raises(IntegrationForbidden, match="Missing permission"):
        adapter.get_sales_order(auth, "so-1")


def test_external_reference_consistency(adapter: FixtureErpV2ReadAdapter) -> None:
    auth = _auth()
    customer = adapter.get_customer(auth, "cust-100")
    product = adapter.get_product(auth, "prod-10")
    so = adapter.get_sales_order(auth, "so-1")

    assert customer_external_ref(customer).external_id == "cust-100"
    assert product_external_ref(product).document_type == "product"
    so_ref = sales_order_external_ref(so)
    assert so_ref.external_system == EXTERNAL_SYSTEM_ERP_V2
    assert so_ref.branch_id == "branch-a"
    line_ref = sales_order_line_external_ref(so.lines[0], branch_id=so.branch_id)
    assert line_ref.external_id == "sol-1a"
    assert line_ref.document_type == "sales_order_line"


def test_no_http_network_access(adapter: FixtureErpV2ReadAdapter) -> None:
    assert adapter.allows_network is False
    assert adapter.http_client is None
    assert adapter.base_url is None
    assert not hasattr(adapter, "session")

    original_create = socket.socket

    def _blocked(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Network socket opened by fixture adapter")

    socket.socket = _blocked  # type: ignore[misc]
    try:
        adapter.list_customers(_auth())
        adapter.list_products(_auth())
        adapter.list_sales_orders(_auth(), status="open")
        adapter.get_sales_order(_auth(), "so-1")
    finally:
        socket.socket = original_create  # type: ignore[misc]


def test_no_duplicate_so_or_sj_authority(adapter: FixtureErpV2ReadAdapter) -> None:
    """Fixture adapter is a read projection of V2 SO IDs — not a second SO/SJ ledger."""
    so = adapter.get_sales_order(_auth(), "so-1")
    assert so.external_system == EXTERNAL_SYSTEM_ERP_V2
    # No surat jalan / delivery create surface on adapter
    assert not hasattr(adapter, "create_sales_order")
    assert not hasattr(adapter, "create_surat_jalan")
    assert not hasattr(adapter, "create_delivery")
    field_names = set(so.__slots__)
    assert "surat_jalan" not in field_names
    assert "delivery_id" not in field_names
