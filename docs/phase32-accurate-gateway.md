# Phase 3.2 — Accurate Read-Only Gateway

## A. Architecture

```
Browser (V49) → Production V3 API → accurate-gateway (M2M Bearer)
                                      └─ fixture corpus  OR  Accurate Online (open-db + API)
```

- Service path: `accurate-gateway/` (independent FastAPI app, own Dockerfile).
- V3 client: `backend/app/services/accurate_read_gateway.py`.
- Evidence enforce: `backend/app/services/accurate_evidence.py`.
- No ERP V1 credentials, JWT, or databases are read or reused.

## B. Endpoint contracts (gateway → V3)

### `GET /sales-orders`
Query: `page`, `limit`, `keyword` | `customer`, `branch`, `status`  
Response:
```json
{
  "rows": [{ "number", "po_number", "accurate_id", "customer", "branch_id", "status", ... }],
  "total": 1,
  "page": 1,
  "pageSize": 50,
  "source": "fixture|accurate_live",
  "live_verified": false
}
```

### `GET /sales-orders/{number}`
```json
{
  "sales_order": {
    "po_number", "number", "customer", "branch_id",
    "line_items": [{ "item_code", "name", "quantity", "unit", ... }],
    "total_quantity": 100,
    "links": { "receipt_ids": [], "delivery_note_ids": [] }
  },
  "source": "...",
  "live_verified": false
}
```

### `GET /receipts/{id}`
Fields: `id`, `number`, `status`, `sales_order_number`, `amount`, `currency`,
`paid_at`, `customer`, `branch`, `cancelled`, `reversed`, `verifiable`,
`source`, `live_verified`.

### `GET /delivery-notes/{id}`
Fields: `id`, `number`, `status`, `sales_order_number`, `customer`, `branch`,
`shipped_at`, `cancelled`, `verifiable`, `line_items`, `source`, `live_verified`.

## C. Payment & SJ validation rules

| Check | Receipt | SJ / Loading / POD |
|-------|---------|---------------------|
| Missing / 404 | 409 fail-closed | 409 fail-closed |
| Gateway down / unconfigured | 503 (bypass audited escape for payment) | 503 block loading |
| `cancelled` / `reversed` / `verifiable=false` | 409 | 409 |
| Invalid status (void/draft/…) | 409 | 409 |
| SO number mismatch vs job | 409 | 409 |
| Branch mismatch vs job | 409 | 409 |
| SJ number mismatch (id vs number) | — | 409 |
| Payment bypass | Requires `production.payment.bypass`, non-empty reason, actor; audit event `payment_bypass_authorized` | — |

POD re-verifies SJ against gateway using the SJ number from the prior loading event.

## D. Authentication & security

- Gateway M2M: `Authorization: Bearer <GATEWAY_M2M_TOKEN>` (same value as `V3_ACCURATE_READ_GATEWAY_TOKEN`).
- V3→gateway URL must be HTTPS (or localhost HTTP only).
- Upstream Accurate: Bearer API token + `X-Session-ID` after `open-db.do`; bounded retries (3) on transport/5xx; fail-closed.
- Read-only: gateway exposes GET only.

## E. Tests & CI

- `accurate-gateway/tests/test_gateway.py` — M2M, contracts, cancel/reverse/mismatch, live-without-creds, concurrency.
- `backend/tests/production/test_phase32_accurate_gateway.py` — evidence rules + bypass audit.
- CI job `accurate-gateway` runs fixture-mode pytest.

## F. Remaining credentials / prerequisites (Owner)

Live Accurate verification is **not** claimed until these exist on the gateway host:

1. `ACCURATE_API_TOKEN` — Accurate Online API token (machine, not human session).
2. `ACCURATE_DATABASE_ID` — database id accepted by `oauth/open-db.do`.
3. `GATEWAY_MODE=live`.
4. `GATEWAY_M2M_TOKEN` / `V3_ACCURATE_READ_GATEWAY_TOKEN` shared secret.
5. `V3_ACCURATE_READ_GATEWAY_URL` pointing at the deployed gateway (HTTPS).
6. Network egress from gateway host to `account.accurate.id` and tenant Accurate host.

ERP V1 source parity remains **unverified** (V1 source not readable from this environment).

## G–I

See PR deliverable notes for browser↔backend↔gateway evidence, HEAD, and staging readiness.
