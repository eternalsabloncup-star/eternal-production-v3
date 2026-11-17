# G4A/G4B Live Read-Only Probe — STOP Report

**WIB / Asia/Jakarta:** 2026-11-17  
**NO COMMIT · NO DEPLOY · NO VPS FILE WRITES · NO RESTART · NO LIVE WRITES**  
**Staging Acceptance:** HOLD

## 1. AccurateClient (signed request + host)

| Step | Behavior |
|---|---|
| Auth | Every call: `Authorization: Bearer`, `X-Api-Timestamp` (WIB), `X-Api-Signature` = Base64(HMAC-SHA256(secret, timestamp)) — `accurate_auth.auth_headers` |
| Host | `POST https://account.accurate.id/api/api-token.do` → `d.database.host` (+ optional `ACCURATE_DATABASE_ID` pin) |
| 308 | Manual follow; **re-sign** headers; never reuse stale signature |
| Business GET | `{host}/accurate/api/...` via `_request` |
| Writes | None in this probe |

## 2. Probe script (local only)

`scripts/g4ab_live_readonly_probe.py` — uses **`AccurateClient._request` only** (exists on VPS-deployed client). Does **not** call undeployed `/sales-invoices` or `/delivery-notes` list gateway routes. Caps: `page_size≤20`, `max_pages≤5` (default 5×2). Sanitized JSON only.

## 3. Agent execution result

| Check | Result |
|---|---|
| `ACCURATE_API_TOKEN` / `ACCURATE_SIGNATURE_SECRET` in agent VM | **UNSET** (`CLOUD_AGENT_INJECTED_SECRET_NAMES` = `ETERNAL_ACTIONS_TOKEN` only) |
| Probe exit | **2** — credentials missing |
| HTTP status G4A `sales-invoice/list.do` | **NOT CALLED** |
| HTTP status G4B `delivery-order/list.do` | **NOT CALLED** |
| VPS file write / restart | **NOT DONE** (would be required to drop script on VPS) |

## 4. Required to complete Live evidence (Owner)

**Pilih satu (tanpa paste secret ke chat):**

A. Inject `ACCURATE_API_TOKEN` + `ACCURATE_SIGNATURE_SECRET` (+ optional `ACCURATE_DATABASE_ID`) ke Cloud Agent environment ini, lalu jalankan ulang  
`GATEWAY_MODE=live python3 scripts/g4ab_live_readonly_probe.py`

B. Di VPS (env sudah ada): jalankan skrip yang sama **dari repo yang sudah ada** atau `python3 -` stdin — **tanpa** menulis file baru / restart — lalu kirim JSON sanitized ke agent.

## 5. Verdict (this turn)

| Gate | Verdict |
|---|---|
| **G4A Outstanding** | **BLOCKED** — Live list/detail invoice tidak diprobe (no agent credentials) |
| **G4B SJ list** | **BLOCKED** — Live list tidak diprobe; detail `120055` sudah terbukti Owner di VPS gateway, tetapi **bukan** bukti list/census |

Full coverage: **not claimed**.
