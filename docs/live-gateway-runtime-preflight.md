# Live gateway runtime preflight (PR #2)

**Date check:** Cloud Agent run on `cursor/v49-live-phase1-3e4e`  
**Stop gate:** No merge / no deploy. ERP V1 untouched. No fixture fallback for live claims.

## Verdict

**NOT READY for live Accurate probe from this Cloud Agent.**  
Cursor App Secrets (7 names saved/bound) are **not** injected into this agent VM for Accurate/M2M/URL. Live probe cannot run safely here.

## 1. Where Cursor Secrets go

| Surface | Injects the 7 App Secrets? | Evidence |
|---------|----------------------------|----------|
| This Cloud Agent VM | **No** (Accurate/M2M/URL) | Process env: those keys `MISSING`. `CLOUD_AGENT_INJECTED_SECRET_NAMES` = `ETERNAL_ACTIONS_TOKEN` only |
| Cursor **publish-app** runtime | **Yes** (when published) | All 7 bound + values saved in personal store; publish service injects on publish/redeploy |
| Biznet / systemd V3 host | **No** (automatic) | App Secrets do not sync to VPS. Owner must copy into host `EnvironmentFile` |

`V3_JWT_SECRET` / `V3_PASSWORD_PEPPER` happen to be `PRESENT` in this agent process env but are **not** listed in `CLOUD_AGENT_INJECTED_SECRET_NAMES` — do not treat that as a supported injection path for Accurate credentials.

## 2. Presence matrix (values never printed)

| Name | This agent env | Gateway process (pid on :8091) | Cursor App Secret bound |
|------|----------------|--------------------------------|-------------------------|
| `ACCURATE_API_TOKEN` | MISSING | MISSING | yes |
| `ACCURATE_SIGNATURE_SECRET` | MISSING | MISSING | yes |
| `GATEWAY_M2M_TOKEN` | MISSING | PRESENT (local reachability placeholder only — not Owner secret) | yes |
| `V3_ACCURATE_READ_GATEWAY_TOKEN` | MISSING | MISSING | yes |
| `V3_JWT_SECRET` | PRESENT | PRESENT | yes |
| `V3_PASSWORD_PEPPER` | PRESENT | PRESENT | yes |
| `V3_ACCURATE_READ_GATEWAY_URL` | MISSING | MISSING | yes |
| `GATEWAY_MODE` | MISSING | `live` | n/a (non-secret) |

## 3–4. Pair checks (no values shown)

| Check | Result |
|-------|--------|
| M2M tokens match (`GATEWAY_M2M_TOKEN` == `V3_ACCURATE_READ_GATEWAY_TOKEN`) | **UNVERIFIED** — both `MISSING` in agent env; Cursor store cannot be read for comparison |
| JWT ≠ Password Pepper | **PASS** in agent env (both PRESENT and differ) |

Owner must re-check M2M equality when writing the host env file.

## 5. Gateway startup / `GATEWAY_MODE`

| Source | Behavior |
|--------|----------|
| `accurate-gateway` settings default | `fixture` |
| `docker-compose.yml` | `GATEWAY_MODE: ${GATEWAY_MODE:-fixture}`; does **not** pass `ACCURATE_SIGNATURE_SECRET` |
| Transient process on `127.0.0.1:8091` | `GATEWAY_MODE=live`, `live_credentials_present=false`, `live_verified=false`, `fixture_fallback_in_live=false` |

Live mode is correctly fail-closed without Accurate creds. Compose still defaults to fixture unless overridden.

## 6. Safest injection method (no git / no chat / no logs)

1. **Keep** the seven values only in Cursor Secrets (already done).  
2. **Production V3 host (intended runtime):** Owner creates a host-only env file, e.g. `/etc/epv3/epv3.env`, mode `600`, root:epv3, **never** committed.  
3. Point **systemd** units to `EnvironmentFile=/etc/epv3/epv3.env` for `epv3-api` and `epv3-accurate-gateway`.  
4. Required keys in that file:
   - `GATEWAY_MODE=live`
   - `ACCURATE_API_TOKEN`, `ACCURATE_SIGNATURE_SECRET`
   - `GATEWAY_M2M_TOKEN` **and** identical `V3_ACCURATE_READ_GATEWAY_TOKEN`
   - `V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091` (same-host only)
   - `V3_JWT_SECRET`, `V3_PASSWORD_PEPPER` (must differ)
5. Restart units; confirm `/health` shows `mode=live` and `live_credentials_present=true`.  
6. Run `GATEWAY_MODE=live python3 scripts/phase5_live_probe.py` on that host — sanitized evidence only.

**Do not:** paste into PR/chat, commit `.env`, echo into CI logs, or rely on publish-app secrets for Biznet systemd.

## 7. Can this Cloud Agent run a temporary live probe?

**No.** Accurate API Token, Signature Secret, M2M pair, and gateway URL are `MISSING` here. Starting a probe would only exit `2` / fail-closed — and inventing tokens is forbidden.

Optional later path (Owner choice): add the seven names as **Cloud Agent–injected** secrets for this environment (distinct from publish-app bindings), then re-run the agent. Until then, probe only on the V3 host after §6.

## 8. Exact Owner next action (stop here)

1. On the V3 production host, create `/etc/epv3/epv3.env` (`chmod 600`) with the seven Cursor Secret values + `GATEWAY_MODE=live`.  
2. Confirm M2M pair equality and JWT ≠ pepper while pasting.  
3. Wire systemd `EnvironmentFile` for API + gateway; bind gateway to `127.0.0.1:8091`.  
4. Reply on PR #2 when that is done — agent can then guide a read-only live probe **on that host** (still no merge/deploy).  

Until step 1–3 complete: **stop** — no live Accurate success claim.
