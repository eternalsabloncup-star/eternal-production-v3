# Internal gateway URL — deployment plan (same-host loopback)

**PR:** #2 · **Branch:** `cursor/v49-live-phase1-3e4e`  
**NO MERGE · NO DEPLOY** until live probe PASS + Owner approval.  
**ERP V1:** do not modify.

## Planned V3 client setting

```text
V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091
GATEWAY_MODE=live
```

`V3_ACCURATE_READ_GATEWAY_TOKEN` must equal `GATEWAY_M2M_TOKEN` on the gateway process.

## 1. Route prefix expected by the V3 client (verified)

`ReadGateway` concatenates `base_url.rstrip("/") + path` with **no** extra API prefix:

| Client call | Request URL with this plan |
|-------------|----------------------------|
| `GET /sales-orders` | `http://127.0.0.1:8091/sales-orders` |
| `GET /sales-orders/{number}` | `http://127.0.0.1:8091/sales-orders/{number}` |
| `GET /receipts/{id}` | `http://127.0.0.1:8091/receipts/{id}` |
| `GET /delivery-notes/{id}` | `http://127.0.0.1:8091/delivery-notes/{id}` |

Gateway FastAPI mounts those paths at root (`accurate-gateway/app/routes.py`).  
**Do not** set the base URL to `…/gateway`, `…/api`, or `…/v1` — that would 404.

Trailing slash on the env value is stripped by the client.

## 2. Loopback policy (same host / network namespace only)

`check_configuration` allows `http` **only** when hostname is `127.0.0.1` or `localhost`. Any other host must be `https`.

This plan is valid **only** when:

- V3 API (`epv3-api`) and `epv3-accurate-gateway` share the same host (or the same network namespace, e.g. both bind in one Docker network with gateway reachable as loopback from the API container), and  
- the gateway listens on `127.0.0.1:8091` (see `docker-compose.yml` publish `127.0.0.1:8091:8091`).

If the API runs on a different host/VM than the gateway, **do not** use this URL — use an internal HTTPS base URL instead.

## 3. Reachability from this agent runtime (checked)

Transient local process with `GATEWAY_MODE=live` (no Accurate secrets injected into this VM):

| Check | Result |
|-------|--------|
| `GET http://127.0.0.1:8091/health` | `200` · `mode=live` · `live_credentials_present=false` · `live_verified=false` · `fixture_fallback_in_live=false` |
| `GET http://127.0.0.1:8091/sales-orders` (M2M) | `503` `accurate_credentials_missing` — **fail-closed, no fixtures** |

Interpretation:

- Loopback TCP to `:8091` works **when the gateway process is running** on this host.  
- Gateway was **not** persistently running before/after the check — ops must keep `epv3-accurate-gateway` up on the intended V3 host.  
- Accurate Online connectivity was **not** proven (`live_verified=false`). Do not claim live Accurate success.

## 4. Six Cursor-stored secrets → intended runtime

Names present in Cursor personal store and bound to this app (values never printed):

1. `ACCURATE_API_TOKEN`  
2. `ACCURATE_SIGNATURE_SECRET`  
3. `GATEWAY_M2M_TOKEN`  
4. `V3_ACCURATE_READ_GATEWAY_TOKEN`  
5. `V3_JWT_SECRET`  
6. `V3_PASSWORD_PEPPER`  

| Surface | Status |
|---------|--------|
| Cursor Secrets store (bound) | All six **present** (names only verified) |
| Published-app secret binding | Bound; values inject only into that publish runtime when Owner has saved them |
| This Cloud Agent VM env | Accurate + M2M tokens **absent**; JWT + pepper present as env keys; URL **absent** |
| Biznet / systemd V3 host | **Not configured in this run** — Owner must copy the six into the host env file (`mode 600`) separately |

`V3_ACCURATE_READ_GATEWAY_URL` is a non-secret setting (bound for Owner entry). Planned value: `http://127.0.0.1:8091`.

## 5. Live mode — no fixture fallback

Always set `GATEWAY_MODE=live` for cutover / Phase 5 claims.

- Missing Accurate token/secret → `503 accurate_credentials_missing`  
- Never serve fixture SO / demo receipt / mock SJ in live  
- Probe: `GATEWAY_MODE=live python3 scripts/phase5_live_probe.py` — refuse fixture mode  

## 6. Accurate connectivity claim

**Not successful.** Live probe has not passed. `live_verified` remains false until Accurate credentials are available to the gateway process **and** `phase5_live_probe.py` exits 0.

## 7. Remaining blockers

1. Inject Accurate API Token + Signature Secret into the **gateway process env** on the V3 host (Cursor store ≠ auto-inject into agent VM or bare VPS).  
2. Inject matching M2M token into both gateway and V3 API (`GATEWAY_M2M_TOKEN` = `V3_ACCURATE_READ_GATEWAY_TOKEN`).  
3. Persist `V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091` on the V3 API host (same-host only).  
4. Keep gateway listening on `127.0.0.1:8091` under systemd/compose.  
5. Run `phase5_live_probe.py` to PASS before any live Accurate success claim.  
6. VPS DNS/TLS / isolated Postgres / Owner cutover approval — still outstanding; **no merge, no deploy** from this task.  
