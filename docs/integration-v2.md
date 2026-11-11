# ERP V2 Integration Contract

Status: **sandbox foundation in V3** — fixture-only adapter; no live ERP V2 connections.

Evidence basis (Owner handoff): ERP V2 commit `79c548ebadf6fbca22bb379c8984d618c900b451`.

## Ownership boundaries

### ERP V2 owns (canonical)

- Customers
- Products
- Sales Orders
- Official Accurate document references / Accurate inbound
- Canonical user identities and branch scope (enforced inside V2)
- Surat Jalan / deliveries authority

V3 must not introduce a second official Sales Order authority or a second official Surat Jalan authority.

### ETERNAL PRODUCTION V3 will own

- Future production workflow state (not implemented yet)
- V3-local audit/event history for those workflows
- Adapter-side read receipts (in-memory for sandbox)

## Verified V2 HTTP contracts (path-level)

API prefix: `/api`

| Method | Path | Notes |
|---|---|---|
| GET | `/api/auth/me` | Returns `user_id`, `username`, `display_name`, `role`, `permissions`. **Does not** expose `branch_ids`. |
| GET | `/api/masters/customers` | Customer list |
| GET | `/api/masters/customers/{customer_id}` | Customer detail |
| GET | `/api/masters/products` | Product list |
| GET | `/api/sales-orders` | `list[SOOut]`; supports **status** filter; **no** pagination contract |
| GET | `/api/sales-orders/{so_id}` | Detail includes lines with stable line IDs and product IDs |

Auth: Bearer JWT · permission-based · branch scope enforced by ERP V2 · **no** approved service-to-service credential contract.

### Explicit non-endpoints (do not invent)

- No verified `GET /api/masters/products/{product_id}`
- Sandbox product-by-id resolution uses an **authorized fixture catalog only**

## Stable reference candidates

- `sales_order_id`
- `sales_order_line_id`
- `customer_id`
- `product_id`
- `branch_id`
- `production_job_id` (V2 legacy only — CDA / Live Tracking still depend on V2 Production Job)

## V3 sandbox adapter

Package: `backend/app/integration/`

- `ErpV2ReadAdapter` — read-only protocol
- `FixtureErpV2ReadAdapter` — local fixtures, `allows_network=False`
- Refs: `CustomerRef`, `ProductRef`, `SalesOrderRef`, `SalesOrderLineRef`
- `MeProfile` — verified `/auth/me` fields only
- `AuthContext` — **TEST/SANDBOX ONLY**; carries `simulated_branch_ids` and owner/approver harness sets. These are **not** live `/auth/me` claims.
- `InMemoryReadReceiptStore` — read audit without business tables

### Fail-closed rules

- Missing/invalid session → unauthorized
- Missing sandbox permission label → forbidden
- SO branch not in `AuthContext.simulated_branch_ids` → forbidden (never infer from user-selected branch alone)
- SO not owner/approver (fixture rules) → forbidden
- Simulated upstream deny → `IntegrationUpstreamForbidden`
- Never treat unverified JWT claims as broad access

Sandbox permission labels (`fixture.*.read`) are **local only** and are not claimed to be live V2 permission strings.

## Known gaps (block production live integration)

1. Full response schemas beyond verified ID/status/`/auth/me` fields
2. Live permission string names
3. How V3 obtains branch scope at runtime (not present on `/auth/me`)
4. Service-to-service credential contract
5. Compatibility mapping for `production_job_id` before CDA / Live Tracking
6. Staging URL / non-prod credential process
7. Cloud Agent still cannot read private ERP V2 GitHub source directly

## Integration style

- API-based only; no shared PostgreSQL with V2
- Sandbox/local/CI: fixtures only; no network to V2 production
- Live HTTP adapter: Owner approval required; out of current implementation

## Explicit non-goals (current phase)

- No live ERP V2 HTTP client
- No shared V2 database credentials
- No business workflow tables / migrations
- No Accurate calls
- No second Sales Order / Surat Jalan system of record
- No workflow UI
