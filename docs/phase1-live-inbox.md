# Phase 1 — Live Accurate Inbox (V3)

## Implemented
- V49 UI served at `/production.html` (design SoT from `01_FRONTEND_V49`)
- Login shell (React/Vite) issues **V3-only** JWT (`V3_JWT_SECRET`)
- Read-only Accurate gateway adapter (`V3_ACCURATE_READ_GATEWAY_*`)
- Authenticated inbox + SO detail with branch fail-closed filtering
- Inbox `production_status` ∈ {`Baru`,`Terproses`} from V3 `work_orders` table
- Sandbox ERP V2 fixture adapter retained (non-live)

## Fail-closed
- Missing gateway URL/token → HTTP 503
- Insecure gateway URL → HTTP 503
- Missing `V3_JWT_SECRET` → login/auth 503
- Missing/invalid session → 401
- Branch outside `user.branch_ids` → row hidden / detail 403

## Not live until configured
- Real Accurate SO validation (e.g. `PO/11/11/2026/000006`) requires Owner-bound gateway secrets
- Workflow mutation buttons remain non-authoritative (no canonical write APIs yet)
- Domain `https://produksieternalpackaging.id` DNS/TLS/staging not provisioned by this change

## Never
- Copy ERP V1 `JWT_SECRET`, human JWT, or Accurate credentials into V3
- Connect to ERP V1 production database
- Treat frontend stage simulation as production status
