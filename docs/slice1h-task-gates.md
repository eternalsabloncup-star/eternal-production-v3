# Slice 1H — Official Task Generation & Scheduling Gates

## Root cause

1. **Tugas Tim was frontend-synthetic** (`TASK_DEFS` / `flow31` / stage heuristics). Footer showed “Data simulasi 3 PO”.
2. **`processSnapshot: null`** while `production_process` was set → `effectiveLineMode` fell back to demo catalog → wrong print/non-print.
3. **`Terproses` → `stage='run'`** marked Prepare Cup selesai without schedule evidence.
4. **Gates** were demo-local; payment must never be inferred from PO/processing status.

## Data sources (V3 PostgreSQL only)

| Concern | Tables / fields |
|---|---|
| Job + gates | `production_jobs.design_status`, `payment_status`, `processing_status` |
| Line process | `job_line_qtys.production_process` (`print` / `non_print` / `unknown`) |
| Design | `design_versions` (upload ≠ approval) |
| Payment evidence | `payment_receipt_refs` via Accurate sales-receipt gateway; `payment_bypasses` |
| Schedule | `schedule_assignments` |
| Prep | `prep_states` (screener / helper) |
| Sample / output | `sample_versions`, `production_events` |

Accurate Live inbox remains **read-only**. Internal actions use V3 jobs.

## Canonical task states

Each visible task has exactly one of: **`pending` | `blocked` | `actionable` | `done`**.

API: `GET|POST /api/v1/production/jobs/tasks` → `source: "v3_official"`.

Stable business id: `{accurate_so_number}::{kind}[::{so_line_id]`.

## Accurate payment evidence

- Open payment gate only via `record_payment_receipt` → `require_valid_receipt` (gateway) **or** authorized bypass.
- Draft / void / unlinked / unverifiable receipts **do not** open the gate.
- If gateway cannot verify: API returns **503/409** — UI must not synthetic-open. Report **BLOCKED** until gateway credentials are available in the environment.

## Task formation rules

1. **Upload Design** — print lines only; available without payment; done when a design file exists or design bypassed/approved.
2. **Approval Design** — separate; actionable only when a **pending** design version exists; never auto-approve on upload.
3. **Penjadwalan** — visible when payment approved/bypassed; **blocked** if design not approved/bypassed; create still uses `gates_open_for_schedule`.
4. **Screen + Prepare Cup** — only after valid schedule assignment(s); parallel.
5. **Downstream** (sample / print / packing) — only after prep evidence.
6. **Non-cetak** — `stockprep` / `stockpack` only; **no** fake screen/sample/print. Non-print-only skips design gate when session lines are known.

## Frontend

- Map `production_process` → `processSnapshot` (`PRINT` / `NON_PRINT` / `UNKNOWN`).
- Live empty `sourceLines` stay empty (no demo invent).
- Live Tugas Tim reads `__V3_OFFICIAL_TASKS__` from the tasks API; Upload vs Approval cards split; footer shows official source.
- Gate display synced from `design_status` / `payment_status` independently.

## No migration

Read-model + ensure_job on existing schema only. No DB migration, no VPS change, no public deploy.
