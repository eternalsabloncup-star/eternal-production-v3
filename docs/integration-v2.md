# ERP V2 Integration Contract (Proposed)

Status: **documentation only** — no live ERP V2 connections in V3 yet.

## Ownership boundaries

### ERP V2 owns (canonical)

- Customers
- Products
- Sales Orders
- Official Accurate document references
- Canonical user identities and branch scope

V3 must not introduce a second official Sales Order authority or a second official Surat Jalan authority.

### ETERNAL PRODUCTION V3 will own

- Future production workflow state (planning, execution, shop-floor progression, V3-specific operational records)
- V3-local audit/event history for those workflows
- Adapter-side idempotency keys and integration receipts for calls made by V3

## Integration style

Preferred approach: **API-based integration**.

- V3 reads V2-owned master/document data through a versioned HTTP API (or approved gateway), not by sharing PostgreSQL tables.
- V3 writes back only through explicit V2 APIs when a production outcome must update V2-owned documents.
- Direct SQL against V2 databases is forbidden.

## Authentication and permission (future)

- Reuse V2 canonical user identities; do not invent a parallel user directory as system-of-record.
- Propagate branch scope from V2 auth/session claims into V3 authorization checks.
- Map V2 roles/permissions into V3 capability checks at the service boundary.
- Tokens/credentials for V2 must come from environment/secret stores — never hardcoded, never requested from Owner chat during routine work.

## Stable external document references

When V3 stores a reference to a V2 document, persist stable identifiers only, for example:

- `external_system = "erp_v2"`
- `document_type` (e.g. `sales_order`, `surat_jalan`)
- `external_id` / `external_number`
- optional `branch_id`
- optional content hash / `updated_at` observed at read time

Do not duplicate V2 line-item authority in a way that can diverge silently from V2.

## Data consistency and idempotency

- Reads from V2 are eventually consistent relative to V2 commits; V3 must tolerate stale reads and re-fetch when mutating.
- Any V3 → V2 write must send an idempotency key so retries do not create duplicate documents/events.
- V3 should store integration attempt receipts (key, status, response id) for audit and replay safety.
- Conflict policy: V2 remains authoritative for Customers, Products, Sales Orders, Accurate refs, identities, and branch scope.

## Read-only mock / sandbox adapter

Until live integration is approved, V3 should depend on a narrow adapter interface, for example:

```text
ErpV2ReadAdapter
  - get_customer(external_id) -> CustomerRef | NotFound
  - get_product(external_id) -> ProductRef | NotFound
  - get_sales_order(external_id) -> SalesOrderRef | NotFound
  - get_user_branch_scope(user_external_id) -> BranchScope
```

Rules:

- Default local/dev/test implementations are **mock/sandbox** and read-only.
- No network calls to V2 production from local or CI.
- Live adapter implementation is out of scope until Owner approval.

## Future migration mapping requirements

When migrating Production from ERP V2 into V3:

1. Inventory V2 production entities and identify which remain V2-owned vs become V3-owned.
2. Publish an explicit ID mapping table (`v2_id` → `v3_id`) for migrated workflow records.
3. Preserve Accurate / official document references without rewriting V2 document numbers.
4. Provide dry-run and rollback criteria before any cutover.
5. Keep dual-run read checks against V2 APIs until Owner signs off.

## Explicit non-goals (now)

- No live ERP V2 HTTP client
- No shared V2 database credentials
- No copied V2 production ORM models as V3 schema
- No second Sales Order / Surat Jalan system of record
