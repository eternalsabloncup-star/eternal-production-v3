# Accurate Read-Only Gateway (Production V3)

Independent HTTPS-facing service that Production V3 calls with a dedicated M2M token.
Never loads ERP V1 credentials or databases.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | none |
| GET | `/sales-orders` | Bearer `GATEWAY_M2M_TOKEN` |
| GET | `/sales-orders/{key}` | Bearer — Accurate SO number or internal id (`detail.do` requires `id`) |
| GET | `/receipts/{id}` | Bearer |
| GET | `/delivery-notes/{id}` | Bearer |

## Modes

- `GATEWAY_MODE=fixture` (default): deterministic local corpus for CI. `live_verified=false`.
- `GATEWAY_MODE=live`: Accurate Online API Token 1.0.3. **Never falls back to fixtures** on missing creds or upstream errors.

## Live auth (API Token 1.0.3)

Every Accurate request:

- `Authorization: Bearer <ACCURATE_API_TOKEN>`
- `X-Api-Timestamp` (`dd/MM/yyyy HH:mm:ss`, Asia/Jakarta)
- `X-Api-Signature` Base64(HMAC-SHA256(Signature Secret, timestamp))

Host + database id from `POST https://account.accurate.id/api/api-token.do` (`d.database.*`).  
`ACCURATE_DATABASE_ID` is optional pin only. HTTP 308 re-signs.

## Env

```
GATEWAY_M2M_TOKEN=...                 # secret — shared with V3_ACCURATE_READ_GATEWAY_TOKEN
GATEWAY_MODE=fixture|live
ACCURATE_API_TOKEN=...                # secret — replacement token only
ACCURATE_SIGNATURE_SECRET=...         # secret
ACCURATE_DATABASE_ID=                 # optional pin
ACCURATE_ACCOUNT_BASE=https://account.accurate.id
```

See `docs/live-credential-readiness.md`.

## Run

```bash
pip install -r requirements.txt
GATEWAY_M2M_TOKEN=dev uvicorn app.main:app --port 8091
pytest -q
```
