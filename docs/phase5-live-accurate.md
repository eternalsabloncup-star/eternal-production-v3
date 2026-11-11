# Phase 5 — Direct Live Accurate + Production Prep

**Decision:** Skip separate staging; go toward real Accurate Online.  
**Gate:** No merge / production cutover without live connectivity proof + Owner approval.  
**ERP V1:** untouched (DB, domain, Nginx, services).

## A. Branch / HEAD

See PR #2 latest commit on `cursor/v49-live-phase1-3e4e`.

## B. Live Accurate connectivity status

**Status: BLOCKED — credentials not present in agent environment.**

Required for live (independent V3 machine credentials — never ERP V1):

| Variable | Purpose |
|----------|---------|
| `ACCURATE_API_TOKEN` | Accurate Online API Token (Bearer) |
| `ACCURATE_SIGNATURE_SECRET` | Signature Secret for HMAC-SHA256 (`X-Api-Signature`) |
| `ACCURATE_DATABASE_ID` | Optional pin vs `api-token.do` → `d.database.id` |
| `GATEWAY_MODE=live` | Disables fixture corpus |
| `GATEWAY_M2M_TOKEN` | Gateway M2M (= `V3_ACCURATE_READ_GATEWAY_TOKEN`) |
| `V3_ACCURATE_READ_GATEWAY_URL` | HTTPS URL of deployed gateway |

Auth (API Token doc 1.0.3): every request sends `Authorization: Bearer`, `X-Api-Timestamp` (`dd/MM/yyyy HH:mm:ss` Asia/Jakarta), and Base64 `X-Api-Signature`. Host resolved via `POST /api/api-token.do`. HTTP 308 re-signs (no stale redirect).

Probe (fail-closed, no fixtures):

```bash
GATEWAY_MODE=live \
ACCURATE_API_TOKEN=… ACCURATE_DATABASE_ID=… \
python3 scripts/phase5_live_probe.py
```

Optional Owner-supplied document ids for receipt/SJ checks:

- `PHASE5_LIVE_RECEIPT_ID`
- `PHASE5_LIVE_SJ_ID`
- `PHASE5_LIVE_CANCELLED_RECEIPT_ID`
- `PHASE5_LIVE_CANCELLED_SJ_ID`

Sanitized evidence path: `/tmp/epv3-p5-live-evidence.json` (hashes/suffixes only).

## C–D. SO / receipt / SJ / Inbox

**Not executed against live Accurate** — blocked on credentials.  
Fixture results from Phase 4 must not be treated as live verification.

## E. Tests / CI

- Existing Phase 1–4 suites remain green on prior HEAD.
- Live probe exits `2` without credentials (expected).

## F. Production infrastructure readiness (prep only — not applied)

Target: `https://produksieternalpackaging.id`

```text
Internet → Nginx TLS (new vhost only)
             ├─ /api/v1/* → 127.0.0.1:8100  epv3-api
             ├─ /gateway/* → 127.0.0.1:8091 epv3-accurate-gateway (or internal-only)
             └─ /* → V49 frontend dist

PostgreSQL (isolated):
  eternal_production_v3          role epv3_app     ← V3 only
  <ERP V1 databases>                               ← DO NOT TOUCH
```

### Checklist (Owner/ops on VPS)

1. DNS A/AAAA for `produksieternalpackaging.id` → Biznet VPS (Owner)
2. TLS cert (certbot) on **new** Nginx vhost only
3. Create isolated DB/role; `alembic upgrade head`
4. Deploy `epv3-api` + `epv3-accurate-gateway` systemd units (loopback bind)
5. Env file mode `600`: JWT ≠ pepper; M2M; Accurate token+db id; `GATEWAY_MODE=live`
6. `V3_ACCURATE_EVIDENCE_ENFORCE=true`
7. Nightly `pg_dump` of V3 DB only; retain ≥7 days
8. Rollback: stop V3 units + disable V3 vhost; leave V1 intact

See also `docs/staging-biznet.md` (reuse as production prep sketches; do not apply without approval).

### Read-only verification rules

- Gateway exposes GET only
- Probe sets `write_attempted=false`
- No manual PO import path in V3 intake
- Inbox statuses from V3 WO mirror only (`Baru`/`Terproses`) — never invented Accurate production state

## G. Remaining blockers

1. Accurate API token + database id (Owner — secure form)
2. Shared M2M gateway token + HTTPS gateway URL
3. V3 JWT secret + password pepper (distinct)
4. VPS access / DNS / TLS for `produksieternalpackaging.id`
5. Isolated V3 PostgreSQL provisioned on host
6. Explicit Owner approval after live probe PASS

## H. Owner approval actions

1. Add the 7 secret values in the Cursor secure form (Accurate + gateway + V3 auth)
2. Provide VPS access (or apply checklist) without touching ERP V1
3. Point DNS + issue TLS
4. After agent re-runs `phase5_live_probe.py` successfully: approve merge/cutover separately
