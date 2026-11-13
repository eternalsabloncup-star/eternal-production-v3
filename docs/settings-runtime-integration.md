# Settings runtime integration — workflow enforcement implemented, cutover HELD

Supersedes the isolated-only status of the earlier Settings reports. This local
package activates account management and Settings administration only when
`V3_SETTINGS_ENABLED=true`, after migration and explicit administrative bootstrap.
The flag defaults false. No deployment or Live database operation is included.

## Migration / identity bootstrap

Single graph: `0009 -> 0010 (payment evidence) -> 0011 (settings access) -> 0012 (task ownership)`.
Head is `20261116_0012`. Payment 0010 is unchanged. 0012 adds `task_ownerships`;
its downgrade is refused once rows exist. Settings 0011 adds six access tables and credential
state; no legacy field, receipt or production output is deleted or rewritten.
Existing users receive credential generation 1 without forced password change;
new accounts receive forced first-password change. No group, grant, membership
or Director is inferred from legacy usernames/roles.

Preflight checks missing/blank identities and hashes under a users-table lock.
Upgrade/downgrade is tested on disposable loopback PostgreSQL. Downgrade is refused
once bootstrapped/audited or credentials have changed: otherwise it could lose
revocations and audit. Disabling the Settings flag after bootstrap also rejects
legacy login/session authentication instead of resurrecting pre-cutover tokens.

Bootstrap has no HTTP endpoint. After independently verifying Owner identity,
an authorized operator may run from backend:

    python -m app.authorization.bootstrap --owner-user-id <verified-existing-id> --expected-username <exact-verified-username> --approval-reference <approved-record-reference>

The target must already exist and be active with migrated credentials. The tool
checks the explicit ID/username, locks the singleton, permits bootstrap once and
records an atomic audit. The approval reference records operator attestation;
it does not perform identity verification itself. No operational Owner identity
was assumed in this task. Only a clearly named sandbox identity was bootstrapped
for E2E. Two-party recovery remains unavailable.

## Runtime account/authentication contract

The existing `/api/v1/auth/login` handles managed accounts using the existing V3
PBKDF2/pepper and JWT secret/issuer/algorithm. Managed tokens carry an audience and
credential generation. Runtime /auth/me and all authenticated production requests
check the authoritative active account and generation when the feature is enabled.
Initial/reset passwords require change before any operation except /auth/me and
password change. Password/username/status changes revoke managed sessions.
Reactivation does not revive previous sessions. Failed and successful logins
retain auth audit; password fields are redacted from validation errors.

The earlier `/settings/session/login` harness is disabled in runtime; there is no
alternate public login. `/settings/session/password` remains the authenticated
password-change endpoint and requires the current password. Old legacy JWTs are
not accepted in managed mode; users must log in again after enabling it.

## Active Settings API (with flag enabled)

- GET capabilities, users (search/page), groups, group grants, user effective access,
  and access audit (page).
- POST users, groups, memberships, grants, revoke grant, activate/deactivate,
  password reset/force-change.
- PATCH user profile (username/display name only).
- POST session/password (current authenticated account, limited first-login flow).

Administrative mutations require system Director membership, expected revision,
reason, singleton serialization, last-admin protection and atomic audit. Extra
privilege fields are rejected. Selected assignment grant IDs must exist and belong
to the supplied branches. This validates scope references, NOT operator ownership.
There is no fallback between new and legacy permissions.

## Frontend

App uses /auth/me and the existing login endpoint to show first-password change,
Settings for Director, or an explicit pending-workflow-access state for newly
managed ordinary users. An added link from the existing Production Settings view
opens Users & Permission; all old Settings tabs remain. System Director is derived
from the backend response, never a role string. Backend remains authoritative.

Settings includes users, initial password, edit/status/reset, groups, checkbox
grants, branch/assignment scope, membership, effective-access preview and audit.
The page states that production grants are authoritative only when workflow enforcement is active (held outside the test sandbox).
It does not advertise a working production permission cutover. All grant writes
are real backend transactions; partial batch completion is disclosed.

## Workflow enforcement and held cutover

Status: implemented and tested in the sandbox; NOT active anywhere else.
`V3_WORKFLOW_AUTHORIZATION` is `legacy` (default) or `enforced`; `main.py` refuses
`enforced` unless Settings is enabled and `APP_ENV=test`. Switching it on in any
other environment needs a code change plus Owner approval.

In `enforced` mode all 48 legacy production endpoints (41 workflow, 4 payroll,
3 inbox) are resolved through `authorize_request`: capability + branch/assignment/
ownership from authoritative DB rows, no legacy-OR-new fallback, Director Full
Access, new roles default deny, unmapped production routes fail closed. Existing
approval rules (Payment P0, design/payment gates, SoD, helper verification) still
run after authorization and are never bypassed by Director.

Payment P0 (migration 0010, receipt evidence, gate from the ledger) is unchanged.
The legacy `payment_status` flag alone no longer opens the schedule gate; the old
Slice 1A test was updated to assert that.

### Transactions, revocation and 409
- Authorization takes `FOR SHARE` on `access_state`; every access writer takes it
  exclusively and bumps `revision`. A writer therefore waits for in-flight
  requests, and a request that began authorized completes atomically.
- Audit of all mutation endpoints found at most ONE commit per request (verified by
  counting real commits across the suite; unexercised endpoints checked statically).
  There is no legitimate multi-commit workflow in these 48 endpoints.
- Revision fence: every later transaction in the same request re-proves the
  authorized revision. If access changed BEFORE any step committed, the answer is
  409 "nothing was written". If it changed AFTER a step committed, the request is
  not failed retroactively: reads may finish, a further write is refused with 409
  "earlier step committed". Such a 409 therefore means "reconcile": check the
  record; the committed step is real. Retry only after reloading, and only with the
  same idempotency key.
- Bulk source sync (`POST /production/jobs/tasks`, `sync_ensure`) runs as one
  transaction in sorted SO order (consistent lock order), requires `job.create` per
  branch, and rolls back entirely on any failure. A concurrent-sync conflict or
  detected deadlock (SQLSTATE 23505 racing insert, 40P01, 40001 only; any other database error stays a 5xx)
  returns 409 `sync_conflict_nothing_written`; retries are idempotent.
- 409 codes: `access_changed_nothing_written` (safe to retry), `access_changed_reconcile`
  (an earlier step is committed: the UI says PERLU REKONSILIASI, clears cached boards and
  does not suggest a retry).
- Real PostgreSQL tests: concurrent opposite-order syncs, revoke during a running
  mutation (revoke waits, then next request is denied), mixed readers/writers,
  rollback on a failing job, retry after conflict.

### Export, print, payroll slip
Export/print are manual capabilities, never inferred from read grants. Backend
endpoints `GET /production/access/documents/{kind}` cover job.export, job.print,
task.export, report.production.export, payroll.export and payroll.print (the
payroll kinds need `run_id`, filter lines by branch and omit source event ids).
In enforced mode the browser print button asks the backend first for the last
computed run. The slip itself remains the SIMULATION/draft layout ("bukan slip
gaji resmi"); an official slip generated from run data is not built.

### Rollback and revocation limits
- Setting `V3_WORKFLOW_AUTHORIZATION=legacy` stops enforcement but does NOT
  restore old permissions: managed grants/revocations are kept and legacy
  `User.permissions` stay as they were (new users have none). Nothing is re-granted.
- Disabling the Settings flag after bootstrap rejects all sessions (no
  resurrection of pre-cutover tokens).
- Revocation takes effect on the next request; a request already holding its
  shared lock finishes first. Historical outputs and operator names are unchanged.
- Migration 0012 downgrade is refused once ownership rows exist; 0011 once bootstrapped.

### Shadow comparison / inventory (required before any Live enforcement)
`shadow.py` compares legacy permission+branch with scoped decisions; mismatch,
unknown permission or unresolved mapping (`job.read`, `delivery.manage`,
`tracking.read`) blocks cutover. Owner procedure with
`python -m app.authorization.inventory`:
1. `--preflight` prints plan and target; it never connects.
2. Non-loopback targets are refused (exit 3) without `--owner-approval-ref`.
   Connecting to Live requires explicit written Owner approval and a read-only
   DB role; this package never connects to Live itself.
3. `--summary` (counts) or full output (per numeric user id; no usernames, names,
   hashes, tokens, audit payloads). One READ ONLY snapshot, no writes.
4. Exit 0 clear; exit 2 BLOCKED: any narrowing, non-Director widening, unknown
   legacy permission or unresolved mapping. Each must be resolved by Owner decision
   (manual grants), never by automatic import.
Director widening is expected by policy and not blocking.

### Mapping decisions required from Owner (no mapping below is applied)

These three legacy permissions bundle several granular capabilities. The
"proposed" column is a candidate only; automatic import stays disabled and the
inventory reports every holder as blocking until Owner decides.

| Legacy privilege | Granular capabilities it covers today (code) | Sensitive data reachable | Proposed scope (candidate) | Narrowing / widening risk | Owner decision |
|---|---|---|---|---|---|
| `production.job.read` | `job.read`, `job.board.read`, `task.read`; engine also lets it reach `loading.authority.read` and `attachment.delivery.read` (list/download) | Board: payment receipts, bypass reasons, events, prep events, evidence refs, design reasons/file names (field-gated by `payment.evidence.read` / `audit.production.read`); SJ loading authority; delivery attachment bytes | `job.read` + `task.read` per branch; `job.board.read` per branch; evidence/audit/attachment/loading-authority stay manual-only | Narrowing: holders lose attachment download, loading authority and sensitive board fields unless granted. Widening: none if manual-only is kept | Which holders keep board/attachment/authority access; per-branch only? |
| `production.delivery.manage` | `loading.record`, `loading.cancel_confirmation`, `delivery.pod.record`, `delivery.sj.cancel_local`; also `attachment.delivery.create` and (OR rule) `attachment.delivery.read` | POD/return photos, SJ identifiers, delivery attachments | One grant per action, branch-scoped; attachment create/read manual-only; consider `own` ownership for courier/loading roles | Narrowing: attachment read and cancel actions need separate grants. Widening: a bundle holder would receive nothing automatically (no auto-import) | Which roles get cancel/`sj_cancel`; attachment read for couriers? |
| `production.tracking.read` | `tracking.read`, `tracking.link.create` | Tracking event fields; creating a live customer tracking link (token handed to a customer) | `tracking.read` per branch; `tracking.link.create` separate and manual (externally shareable) | Narrowing: link creation lost unless granted. Widening: none | Is link creation a separate approval-level capability? Which event fields are visible? |

Open blockers: Owner-reviewed inventory of real data; mapping decisions for the
three review-required permissions; Accurate Inbox scoped pagination scans at most `V3_INBOX_SCOPED_SCAN_MAX_PAGES`
(default 50) upstream pages of 100 because the gateway has no branch filter; `total` is the
user's own-branch count and only when the list was exhausted, else `null`
(`scan_incomplete: true`); `has_more` is true only when a further visible row was found.

## Tests / E2E boundaries

`frontend/scripts/settings-runtime-e2e.py` runs Chromium against a seeded local
sandbox, blocks nonlocal browser requests and uses synthetic credentials only.
It covers Director login, account/group creation, default deny, scoped grants,
membership, initial-password change, relogin, unauthorized direct API, persisted
grant revocation/effective-access refresh, and audit. It runs in `legacy` mode.
Workflow allow-to-deny, stable ownership, cross-branch denial and export/print are
covered by `workflow-permission-e2e.py`, which needs the backend started with
`V3_WORKFLOW_AUTHORIZATION=enforced` (sandbox `APP_ENV=test` only).

The test harness needs an explicitly migrated/seeded disposable PostgreSQL
sandbox, backend on 127.0.0.1:8100 and Vite on 127.0.0.1:5173. Playwright/Chromium
are test tools, not application dependencies. Do not run the script against Live.

Next action: Owner review, then the read-only inventory above. No Git publication,
production migration or enforced-mode activation is authorized by this document.

## Final local verification

See the final report for counts. Backend full suite, frontend suite/build and the
Chromium E2E scripts run against disposable loopback sandboxes only. The two
Settings E2E lines marked BLOCKED are fixed text in the legacy-mode script; the
workflow scenarios are covered by `workflow-permission-e2e.py` (enforced sandbox).
Migration head: 20261116_0012. Payment migration 0010 unchanged.
