# Slice 1K — POD attachments + Screener screen_size

Baseline: `32c1dd7` → this slice on `cursor/v49-live-phase1-3e4e`.

## Schema (Alembic `20261112_0007`)

- `production_attachments` — private POD evidence rows
- `prep_states.screen_size`, `prep_events.screen_size` — `kecil|besar` (NULL = unknown)

**Do not apply to VPS/staging/ops without Owner approval.** Isolated test DB / `create_all` only in CI agent.

## Storage

- Local private root: `V3_ATTACHMENT_ROOT` (default `backend/var/attachments`)
- Auth required for upload/download; branch isolation; MIME allow-list; 5MB; SHA-256
- No public anonymous URLs; no ERP V1 path reuse

## POD contract

`record_pod` requires four unbound attachments (`pod_photo_1/2`, `pod_sig_sender/recipient`) + receiver name + Loading remaining. Atomic bind on commit. Legacy single `evidence_ref` POD rows remain readable and do **not** mark Pengiriman done.

## Screener

Canonical size on PrepState/PrepEvent. Required after valid schedule assignment on the line. Corrections append history.

## Staging readiness

Code/test ready. **Staging deploy BLOCKED** until Owner approves Alembic 0007 + attachment root config.
