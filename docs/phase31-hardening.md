# Phase 3.1 hardening notes

## Accurate evidence

- Paths required on read gateway: `/receipts/{id}`, `/delivery-notes/{id}`
- Non-test environments **always** enforce verification for:
  - recording payment receipts
  - loading against SJ
- Escape hatch: audited payment **bypass** (reason + permission). Loading has **no** silent bypass — blocked until SJ verifies or gateway is ready.
- Capability probe: `GET /api/v1/production/jobs/evidence/capability`
- Flag: `V3_ACCURATE_EVIDENCE_ENFORCE=true` forces enforce even in `APP_ENV=test`

## Payroll

- Gross includes: color-pass buckets + linked screener units from confirmed ledger only
- **Excluded (unverified):** `daily`, `overtime` — no attendance/OT timesheet source
- ERP V1 source unread → `v1_parity: unverified` on payroll run payload

## Frontend

- Receipt invalidate UI: reason + `confirm()` + `PAYMENT_REVOKE` server check + audit event
- Demo/sim handlers neutralized so they cannot fake success or mutate authoritative state

## V1 parity

ERP V1 (`eternal-packaging`) remains inaccessible (404). Rules marked **unverified** where V1 source was required.
