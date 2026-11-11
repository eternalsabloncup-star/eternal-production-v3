"""Typed refs and auth models for ERP V2 sandbox integration.

Verified live `/api/auth/me` fields (V2 HEAD handoff):
  user_id, username, display_name, role, permissions
  — does NOT include branch_ids.

AuthContext is TEST/SANDBOX ONLY. Simulated branch and visibility data are
explicit harness fields and must never be treated as live `/auth/me` claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MeProfile:
    """Verified `/api/auth/me` field set only."""

    user_id: str
    username: str
    display_name: str
    role: str
    permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Test-only authorization harness.

    `simulated_branch_ids` and ownership/approver sets are NOT from `/api/auth/me`.
    They exist so V3 can exercise fail-closed branch/visibility guards in fixtures.
    """

    session_token: str | None
    me: MeProfile | None
    simulated_branch_ids: frozenset[str] = field(default_factory=frozenset)
    simulated_owned_sales_order_ids: frozenset[str] = field(default_factory=frozenset)
    simulated_approver_sales_order_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class CustomerRef:
    external_system: str
    customer_id: str


@dataclass(frozen=True, slots=True)
class ProductRef:
    external_system: str
    product_id: str


@dataclass(frozen=True, slots=True)
class SalesOrderLineRef:
    external_system: str
    sales_order_line_id: str
    product_id: str


@dataclass(frozen=True, slots=True)
class SalesOrderRef:
    """SO reference using verified stable IDs + fixture visibility keys.

    `branch_id` / `customer_id` / `status` are required for sandbox visibility and
    the verified status filter behavior. They are not a claim of full SOOut schema.
    """

    external_system: str
    sales_order_id: str
    customer_id: str
    branch_id: str
    status: str
    lines: tuple[SalesOrderLineRef, ...]
