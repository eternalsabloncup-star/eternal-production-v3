# Step 148 — Update existing Private Staging (preflight only)

**STOP:** No checkout restart, no `systemctl`, no `alembic upgrade`, no Accurate write, no ERP V1 touch from this document’s execution section until Owner explicitly approves the next step.

## Inventory (Owner-stated VPS)

| Item | Value |
|---|---|
| API | `127.0.0.1:8100` |
| Accurate Gateway | `127.0.0.1:8091` |
| Private Staging Proxy | `127.0.0.1:8180` |
| Database | `eternal_production_v3` (V3-only; not V1) |
| Service user | `epv3` |
| Current source (stated) | `df954f8f9df6` |
| Target source | `cb3e2eae89ae` on `cursor/v49-live-phase1-3e4e` (PR #2 Draft) |
| Backup path (stated) | `/var/backups/epv3-staging/v3-before-update-20261112-182412.dump` |

Agent cannot SSH the VPS. Backup readability and live Alembic revision must be confirmed by Owner/ops on the host.

## Exact source HEAD (repo / PR tip)

- Target: **`cb3e2eae89ae`** (`cb3e2eae89ae9533578fe8c54907ad9fa47bc5e1`)
- Ancestor: `df954f8f9df6` ⊂ history of target (**18** commits between)
- Isolation: V3 ports `8100` / `8091` / proxy `8180` — never ERP V1 `:8000`

## Alembic: current vs target

| Ref | Code head revision |
|---|---|
| Repo at `cb3e2eae89ae` | **`20261112_0007`** (single head) |
| Likely DB at `df954f8` deploy | **`20261112_0006` or `20261112_0007`** — **must read** `alembic_version` on staging DB |

`20261112_0007` adds:

- table `production_attachments` (POD private evidence)
- columns `prep_states.screen_size`, `prep_events.screen_size`

HEAD backend **imports** these models. Full tip update without `0007` applied will break POD / screener paths that touch the new table/columns.

### Owner preflight (read-only on VPS)

```bash
# As ops — print revision only (no upgrade)
sudo -u epv3 bash -lc 'cd /opt/epv3/src/eternal-production-v3/backend && . ../.venv/bin/activate 2>/dev/null || true; alembic current'
# or:
sudo -u postgres psql -d eternal_production_v3 -c 'SELECT version_num FROM alembic_version;'
```

| If current | Action |
|---|---|
| `20261112_0007` | Schema matches tip — code update may proceed **without** migration |
| `20261112_0006` (or older) | **STOP** — need Owner approval to run `alembic upgrade 20261112_0007` |
| unexpected / multiple heads | **STOP** — do not deploy |

## Backup & rollback readiness

### Verify backup (Owner on VPS — no secret dump to chat)

```bash
sudo ls -la /var/backups/epv3-staging/v3-before-update-20261112-182412.dump
sudo file /var/backups/epv3-staging/v3-before-update-20261112-182412.dump
# Optional: list-only restore check
sudo -u postgres pg_restore -l /var/backups/epv3-staging/v3-before-update-20261112-182412.dump | head
```

### Source rollback

1. Keep tag/ref of pre-update tree: `df954f8f9df6` (or `git rev-parse HEAD` before fetch).
2. On failure: `git checkout --force df954f8f9df6` in the existing V3 source tree only; rebuild frontend; restart **existing** units only after health fail.

### DB rollback

1. Prefer restore into a **scratch** DB first to validate dump.
2. Only then restore `eternal_production_v3` from the dump (Owner-approved window).
3. Never restore into ERP V1 databases.

## Security preflight (existing staging — no service restart)

| Check | Expect |
|---|---|
| Proxy `8180` | Loopback / private only; forwards to V3 UI+API; auth gate intact |
| API `8100` | Bound `127.0.0.1`; `/api/v1/health` + `/api/v1/ready` |
| Gateway `8091` | Bound `127.0.0.1`; M2M only; `GATEWAY_MODE=live` read-only |
| DB | Role for V3 DB only; no V1 DSN in `/etc/epv3/*.env` |
| POD dir | `V3_ATTACHMENT_ROOT` owned by `epv3`, mode `750`, not world-readable |
| Frontend | Same-origin `/api/v1`; no `:8000`; `v3-auth-gate` (CI already PASS) |

Do **not** `cat` env files into chat.

## Deployment sequence (prepared — not executed)

0. Confirm backup readable + note `alembic current`.  
1. If current ≠ `0007` → **STOP** for Owner migration approval (see below).  
2. If current = `0007` (or after approved migrate):  
   a. `git fetch` + `git checkout --detach cb3e2eae89ae` (or track branch tip) in **existing** `/opt/epv3/...` tree only.  
   b. Install deps in existing venvs if needed (`pip`/`npm ci`) — no new systemd units.  
   c. `npm run build` frontend → sync into existing static root.  
   d. Restart **existing** `epv3-api` + `epv3-accurate-gateway` only.  
   e. Health: `curl -sS http://127.0.0.1:8100/api/v1/health` and `/ready`; gateway health if exposed.  
   f. Smoke via proxy `8180` login + Inbox four columns.  
3. On health fail → source rollback to `df954f8f9df6` + restart; DB restore only if schema/data corrupted.

## VPS changes required (when approved)

- Source tip → `cb3e2eae89ae`  
- Frontend dist rebuild  
- Possible Alembic `0007` (Owner gate)  
- Restart existing API + gateway units  
- **No** second staging stack, **no** new ports, **no** PR merge, **no** production, **no** ERP V1 edits  

## Migration approval gate

If staging DB is behind tip schema:

```text
NEED OWNER APPROVAL: alembic upgrade 20261112_0007
DB: eternal_production_v3
Backup: /var/backups/epv3-staging/v3-before-update-20261112-182412.dump
Effect: create production_attachments + screen_size columns
Rollback: alembic downgrade 20261112_0006 OR restore dump
```

**Do not run until Owner replies with explicit approval for this revision on this DB.**

## Verdict

| Scope | Status |
|---|---|
| Preflight playbook / rollback plan | **READY** |
| Execute code update without knowing DB revision | **BLOCKED** |
| Execute Alembic `20261112_0007` | **BLOCKED** (needs dedicated Owner approval) |
| Full staging update to `cb3e2eae89ae` | **BLOCKED** until Owner confirms backup + `alembic current` (+ migrate approval if `< 0007`) |
