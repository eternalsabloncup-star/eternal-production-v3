# Live credential readiness (Production V3)

**Stop gate:** No merge/deploy until live probe PASS + Owner approval.  
**ERP V1:** untouched. Never copy V1 tokens/secrets/DB URLs.

## 1. Eight live configuration values

| # | Name | Kind | Required for live | Notes |
|---|------|------|-------------------|-------|
| 1 | `ACCURATE_API_TOKEN` | **Secret** | Yes | Replacement API Token only — revoke any previously exposed token |
| 2 | `ACCURATE_SIGNATURE_SECRET` | **Secret** | Yes | Signature Secret for HMAC-SHA256 (`X-Api-Signature`) |
| 3 | `ACCURATE_DATABASE_ID` | Non-secret pin (optional) | No | Host + id come from `POST /api/api-token.do`. Set only to pin/assert identity |
| 4 | `GATEWAY_M2M_TOKEN` | **Secret** | Yes | Machine token V3 → gateway |
| 5 | `V3_ACCURATE_READ_GATEWAY_TOKEN` | **Secret** | Yes | Must equal `GATEWAY_M2M_TOKEN` |
| 6 | `V3_ACCURATE_READ_GATEWAY_URL` | Non-secret setting | Yes | Same-host plan: `http://127.0.0.1:8091` (no path prefix). Other hosts require HTTPS. See `docs/internal-gateway-url.md` |
| 7 | `V3_JWT_SECRET` | **Secret** | Yes (V3 API) | Distinct from pepper; never V1 JWT |
| 8 | `V3_PASSWORD_PEPPER` | **Secret** | Yes (V3 API) | Must differ from `V3_JWT_SECRET` |

Also set (non-secret): `GATEWAY_MODE=live`, `ACCURATE_ACCOUNT_BASE=https://account.accurate.id`, `V3_ACCURATE_EVIDENCE_ENFORCE=true`.

## 2. Fail-closed live mode

When `GATEWAY_MODE=live`:

- Missing token/secret → HTTP **503** `accurate_credentials_missing`
- Upstream/connectivity failure → **502/404** from Accurate adapter
- **Never** serves fixture SO / demo receipts / mock SJ
- Invalid `GATEWAY_MODE` (not `live`|`fixture`) → **503** `gateway_mode_invalid`

## 3. Exposed token policy

Any API Token that appeared in a screenshot/chat is **compromised**.

1. Revoke it in Accurate Online (Accurate Store / API Token).  
2. Issue a **new** token + confirm Signature Secret for that app.  
3. Store only in the Owner secret store / server env (`mode 600`) — never commit, never paste into chat.

## 4. Secure configuration procedure (replacement credentials)

1. Owner creates/rotates Accurate API Token for the **V3** integration app (not ERP V1).  
2. Copy **API Token** and **Signature Secret** into the Cursor Secrets page or VPS env file — values never enter git/PR/logs.  
3. Set `GATEWAY_MODE=live` on the gateway host.  
4. Do **not** require manual DB id unless pinning: gateway calls `POST https://account.accurate.id/api/api-token.do` with signed headers and uses `d.database.host` (+ `d.database.id`).  
5. Point V3 at the gateway: `V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091` (same host only; client paths `/sales-orders`, `/receipts/{id}`, `/delivery-notes/{id}` — no extra prefix) + matching M2M token.  
6. Run `GATEWAY_MODE=live python3 scripts/phase5_live_probe.py` — expects sanitized evidence only.  
7. Confirm `live_verified=true` in probe output before any cutover approval. Never claim Accurate connectivity without that PASS.

## 5. Tests

- `accurate-gateway/tests/test_live_fail_closed.py` — live never calls fixtures  
- `test_api_token_auth.py` — HMAC / api-token.do / 308 re-sign (fake creds)  
- `test_live_probe_gate.py` — probe refuses fixture / missing secrets  
