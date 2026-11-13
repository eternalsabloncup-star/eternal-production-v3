# Slice 1F addendum — Live Tracking (no migration)

**ERP V1** `eternal-packaging`: still **404 / unverified**. No V1 calls.

## Parity vs blocker

| Need | Status |
|---|---|
| Public customer tracking URL/token | **BLOCKER** — requires DB token store + owner-approved public endpoint (not implemented) |
| Staff auth timeline `GET /production/jobs/{id}/tracking` | Exists; used only by V3 contextual **track-refresh**, not Inbox Live Tracking button |
| Inbox Live Tracking button | Opens official allowlisted URL **only if** Backend already attached one to the PO/job; otherwise **"Tracking belum tersedia"** |

## Behavior

- No demo / SIMULASI OFFLINE drawer.
- No invented progress; no job/state mutation on open.
- No PO-as-token; no secrets in logs.
- No new public unauthenticated endpoints in this slice.
