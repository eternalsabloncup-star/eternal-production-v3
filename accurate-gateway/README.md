# Accurate Read-Only Gateway (Production V3)

Independent HTTPS-facing service that Production V3 calls with a dedicated M2M token.
Never loads ERP V1 credentials or databases.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | none |
| GET | `/sales-orders` | Bearer `GATEWAY_M2M_TOKEN` |
| GET | `/sales-orders/{number}` | Bearer |
| GET | `/receipts/{id}` | Bearer |
| GET | `/delivery-notes/{id}` | Bearer |

## Modes

- `GATEWAY_MODE=fixture` (default): deterministic local corpus for CI / staging dry-run. `live_verified=false`.
- `GATEWAY_MODE=live`: Accurate Online via `ACCURATE_API_TOKEN` + `ACCURATE_DATABASE_ID` (open-db session). Fail closed if missing.

## Env

```
GATEWAY_M2M_TOKEN=...          # shared with V3_ACCURATE_READ_GATEWAY_TOKEN
GATEWAY_MODE=fixture|live
ACCURATE_API_TOKEN=...         # Accurate API token (Owner)
ACCURATE_DATABASE_ID=...       # Accurate DB id for open-db
ACCURATE_ACCOUNT_BASE=https://account.accurate.id
```

## Run

```bash
pip install -r requirements.txt
GATEWAY_M2M_TOKEN=dev uvicorn app.main:app --port 8091
pytest -q
```
