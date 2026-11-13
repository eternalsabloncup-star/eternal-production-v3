# Settings runtime integration — PARTIAL, workflow cutover held

Supersedes the isolated-only status of the earlier Settings reports. This local
package activates account management and Settings administration only when
`V3_SETTINGS_ENABLED=true`, after migration and explicit administrative bootstrap.
The flag defaults false. No deployment or Live database operation is included.

## Migration / identity bootstrap

Single graph: `20261113_0009 -> 20261114_0010 -> 20261115_0011`.
Payment 0010 is unchanged. Settings 0011 adds six access tables and credential
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
The page explicitly states that new production grants are not yet authoritative.
It does not advertise a working production permission cutover. All grant writes
are real backend transactions; partial batch completion is disclosed.

## Shadow comparison and held cutover

`authorization/shadow.py` generates transient compatibility candidates and compares
legacy permission+branch decisions to scoped evaluator decisions. It never writes
grants or serves as an authorization fallback. PostgreSQL tests cover matched
input/correction scopes, cross-branch denials, assignment scope differences and
unresolved job.read mapping. A mismatch or unresolved mapping blocks cutover.

Known blockers remain:
- `job.read`, delivery attachments and tracking responses need endpoint/field-level
  mapping; broad legacy payload access must not silently become granular grants.
- Historical operator_name is not an identity. A real ownership/delegation model
  and mappings for production roles are not implemented by this package.
- Workflow entrypoints still use existing legacy authorization. Director Full
  Access works in the evaluator and Settings administration, NOT across all legacy
  workflow endpoints yet. New group grants are stored but not applied there.
- Export/print grants remain manual and stored; new runtime export enforcement is
  part of the held workflow cutover.

Existing legacy workflow permissions remain authoritative without OR fallback.
New users have empty legacy permissions/branches and cannot accidentally gain
workflow access from group names, multiple groups, or a client payload.

## Tests / E2E boundaries

`frontend/scripts/settings-runtime-e2e.py` runs Chromium against a seeded local
sandbox, blocks nonlocal browser requests and uses synthetic credentials only.
It covers Director login, account/group creation, default deny, scoped grants,
membership, initial-password change, relogin, unauthorized direct API, persisted
grant revocation/effective-access refresh, and audit. Workflow allow-to-deny and
actual assignment ownership are explicitly BLOCKED until cutover, not counted as
passing E2E steps.

The test harness needs an explicitly migrated/seeded disposable PostgreSQL
sandbox, backend on 127.0.0.1:8100 and Vite on 127.0.0.1:5173. Playwright/Chromium
are test tools, not application dependencies. Do not run the script against Live.

Next action: resolve and approve the remaining workflow mapping and stable
assignment ownership contract, then implement/shadow-test that integration before
allowing production authorization cutover. This package is PARTIAL, not READY FOR
PR/release. No Git publication or production migration is authorized here.

## Final local verification

- Backend combined focused suite: 207 PASS (122 Settings/auth/migration tests and
  85 Payment P0/direct workflow regressions).
- Frontend complete suite: 172 PASS; build/routing/security checks PASS.
- Chromium E2E account/Settings scenarios PASS; workflow cutover scenarios BLOCKED
  as described above, not reported as passing.
- Schema comparison on the migrated sandbox: zero Settings differences; the nine
  previously identified baseline Alembic operations remain outside scope.
- Migration head: 20261115_0011 only. Payment migration 0010 hash unchanged.
- Earlier failures were resolved: schema metadata registration for legacy test
  teardown, schema-aware rollback guard, App effect placement, and browser selector.
