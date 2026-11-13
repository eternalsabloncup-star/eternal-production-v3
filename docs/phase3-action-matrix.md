# Phase 3 — V49 action → API matrix (verified against source)

Branch contracts from `backend/app/api/production/workflow.py` + `payroll.py` (not docs alone).

| Action | Endpoint | Status |
|---|---|---|
| Lookup job by SO (read-only) | `GET /production/jobs/by-so/{so}` | **Wired** — PO detail uses this; never creates |
| Create job (explicit) | `POST /production/jobs` | **Wired** — “Mulai Proses V3” only |
| Job board / histories | `GET /production/jobs/{id}/board` | **Wired** — drawer refresh |
| Job summary | `GET /production/jobs/{id}` | Available |
| Design upload | `POST .../design/versions` | **Wired** |
| Design decide/bypass/customer | `POST .../design/versions/{id}/decision` | **Wired** |
| Payment receipt | `POST .../payment/receipts` | **Wired** |
| Payment bypass / revoke | bypass + revoke endpoints | **Wired** |
| Invalidate receipt | `POST .../payment/receipts/{id}/invalidate` | **Wired** — reason + confirm + audit event |
| Schedule create / cancel / transfer | schedule endpoints | **Wired** |
| Screener / helper prep | `POST .../prep/screener\|helper` | **Wired** |
| Sample upload / decide | samples endpoints | **Wired** |
| Output / correct / reject / verify | output/reject endpoints | **Wired** |
| Packing / loading / POD / SJ cancel | delivery endpoints | **Wired** |
| Tracking timeline | board.events / tracking | **Wired** |
| Payroll rates / runs | `/production/payroll/*` | **Wired** |
| Live Accurate receipt/SJ verification | — | **Unavailable** — identity refs only; no invent |
| Mapping Proses Barang / Production Approval | — | **Out of scope** (explicit) |
| Demo advance/pack/printOn | — | **Disabled** — redirects to V3 panel |

## Multi-PO controls

- Inbox `page` + `keyword` + limit 50
- Selected SO stored on drawer `data-v3-so`
- Board/job caches keyed by SO; purged for SO not on current page
- Idempotency keys on write actions; `inFlight` lock per action+SO
