# Step 140 — Private Staging readiness (plan only)

**Branch:** `cursor/v49-live-phase1-3e4e` (PR #2 Draft — do **not** merge to `main` for staging)  
**STOP:** No VPS change, no systemd enable, no Nginx cutover, no Alembic on staging/VPS, no Accurate write from this step.

## 1. Isolation from ERP V1 / production

| Layer | V3 Private Staging | Forbidden |
|---|---|---|
| Host / vhost | `produksieternalpackaging.id` (planned) | Do not edit `produksi.eternalpackaging.id` (ERP V1) |
| API bind | `127.0.0.1:8100` behind Nginx TLS | Public bind without TLS; port **8000** (V1) |
| Gateway | `127.0.0.1:8091` M2M loopback | Sharing V1 Accurate/JWT secrets |
| Database | `eternal_production_v3_staging` / role `epv3_stg` | Any V1 DB role, schema, or data |
| Attachments | Dedicated `V3_ATTACHMENT_ROOT` | ERP V1 paths / public anonymous URLs |
| Auth | V3 JWT + `/auth/me` gate | V1 session cookies / V1 JWT secret |

Frontend checks (CI): same-origin `/api/v1`, no `:8000`, early `v3-auth-gate` — **PASS** offline.

## 2. Services & database (planned)

```text
Nginx (TLS, private/auth front door)
  ├─ /api/v1/* → 127.0.0.1:8100   epv3-api (uvicorn)  ← checkout PR branch
  └─ /*        → frontend/dist

epv3-accurate-gateway → 127.0.0.1:8091
  GATEWAY_MODE=live (Owner creds in /etc/epv3/gateway.env or epv3.env)
  GATEWAY_M2M_TOKEN == V3_ACCURATE_READ_GATEWAY_TOKEN

PostgreSQL (isolated)
  eternal_production_v3_staging  OWNER epv3_stg

POD storage
  V3_ATTACHMENT_ROOT=/var/lib/epv3/attachments   (mode 750, app user only)
```

**URL staging:** planned `https://produksieternalpackaging.id` — **not reachable / not confirmed live from agent VM** (HTTP probe failed). Treat as **not provisioned** until Owner confirms DNS/TLS/systemd.

## 3. Branch policy

- Deploy **from** `cursor/v49-live-phase1-3e4e` (or a staging tag of that tip).
- **Do not** merge PR #2 to `main` as a precondition for Private Staging.
- Last CI-green remote tip: `9498a192d849`. Local audit tip may be ahead (Step 139) — push only on Owner instruction.

## 4. Alembic `20261112_0007` readiness

| Item | Status |
|---|---|
| Revision content | `production_attachments` + `screen_size` columns; additive; `downgrade()` drops them |
| Isolated test up/down | Verified in CI / local pytest |
| Staging/VPS apply | **BLOCKED** until explicit Owner approval |
| Pre-approval | Confirm staging DB empty/dedicated; backup; dry-run `alembic heads` = single head |

## 5. Secrets / env checklist (Owner)

- [ ] `DATABASE_URL` / `_SYNC` → staging DB only  
- [ ] `V3_JWT_SECRET` ≠ `V3_PASSWORD_PEPPER` (V3-only)  
- [ ] `V3_ACCURATE_READ_GATEWAY_URL=http://127.0.0.1:8091`  
- [ ] Matching M2M tokens  
- [ ] `GATEWAY_MODE=live` + Accurate token/signature (read-only)  
- [ ] `V3_ATTACHMENT_ROOT` private path  
- [ ] Staging user accounts with `branch_ids`  
- [ ] Env file mode `600`, not in git  

## 6. Blockers (prevent staging from running today)

1. **No agent VPS/deploy authority** — Step 140 stops before host changes.  
2. **Staging URL/systemd/Nginx** not confirmed up from this environment.  
3. **Alembic 0007** must not run without Owner approval (POD/screener schema).  
4. **Accurate Live credentials** on staging host are Owner-held (`/etc/epv3/...`).  
5. **List `shipment` Live gate** — optional confirm; enrich fallback covers Inbox Pengiriman.  

## 7. End-to-end test checklist (after Owner brings staging up)

### Accurate Inbox + four columns
- [ ] Login required (unauthenticated → `/`)  
- [ ] Sales / Pengiriman / Status Pesanan / Buffer display for current page  
- [ ] List missing `shipment` → detail enrich fills Pengiriman (concurrency ≤3, no invent)  
- [ ] Enrich fail → Retry; page/filter change drops stale applies  
- [ ] Filters, column reorder, pagination do not duplicate unbounded detail calls  

### Jadwal Produksi
- [ ] Default V1 column layout / Kolom Tampil  
- [ ] Sticky No PO + Pelanggan  
- [ ] Print-before-ACC visibility vs save gates  

### Approval Sampel
- [ ] Upload vs approval separated  
- [ ] Reject/revise path  

### Tugas Tim
- [ ] Official V3 jobs (not demo-only) when Live  
- [ ] Role/stage filters  

### Kontrol Produksi
- [ ] Qty integrity; unverified qty not treated as zero  

### Loading
- [ ] Loading remaining gates POD  

### Jadwal Pengiriman
- [ ] Schedule filters (hari ini/besok/semua) without inventing SJ  

### POD + status pengiriman
- [ ] 4 attachments + recipient + Loading sisa  
- [ ] Branch isolation on upload/download  
- [ ] Compliant POD marks delivery; legacy without attachments does not  

### Cross-cutting
- [ ] No calls to ERP V1 `:8000`  
- [ ] No Accurate writes from UI  
- [ ] Branch-scoped API 403 for foreign `branch_id`  

## 8. Verdict

**BLOCKED** for Private Staging *execution* (deploy/migrate/Live) until Owner provisions host + approves Alembic 0007.  

**READY** for Owner-led staging bring-up using this plan and PR branch (no merge required).
