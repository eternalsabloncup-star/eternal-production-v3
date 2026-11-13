# Settings & Permission — independent foundation only

## Scope and blocker

Local package only; no runtime cutover, API registration, bootstrap, or recovery.
The active application still uses its existing authorization. These modules are
not imported by application startup or the Alembic environment.

Preflight: branch `codex/v3-remove-duplicate-scripts`, HEAD
`32ee01cd858fa13e1f55c16380748d0a3b0a007d`. Thirteen pre-existing Payment P0
files were preserved. Local migration 0010 follows 0009 but remains part of
untracked/unfinalized P0 WIP. No Settings migration parent was assumed and no
migration was written. Resolve the accepted P0 integration baseline before
introducing a descendant Settings migration or editing P0 workflow files.

## Implemented

- Catalog of granular capabilities and candidate mapping for all existing codes.
- Mapping inventory is read-only; it explicitly blocks automatic import. Board,
  tracking and attachment field/OR-rule mapping still requires resolution.
- Export/print and task-management capabilities are not auto-backfilled.
- Pure evaluator: active account, known capability, protected Director identity,
  default deny, and matching capability/branch/ownership within the same grant.
- Explicit global capabilities; no wildcard branch or implicit all-branch grant.
- Additive ORM definitions for access state/revision, groups, memberships, scoped
  grants and access audit, not registered with the application/migration runtime.
- Transactional services: create ordinary group, set membership, set user active,
  add/revoke scoped grant, and load authoritative effective access.
- Shared state lock for readers; exclusive state lock for access changes.
- Expected revision, Director-only administration, last-active-Director guard,
  and savepoint rollback of rejected mutations even if callers catch exceptions.
- Audit writes share the mutation transaction. No internal commit.

## Integration contract

Call mutators inside an explicit `async with session.begin()` block. Do not
perform unrelated pending writes before entering a mutation savepoint. Use
`load_access` in the same transaction as the protected business operation;
resource branch, assignment and owner IDs must come from trusted database rows,
not request assertions. Acquire the authorization state lock BEFORE business-row
locks. An allow decision never replaces existing workflow/evidence/qty/SoD or
idempotency validation.

Do not flatten scoped grants into `User.permissions` and `User.branch_ids`:
that would reintroduce cross-grant privilege escalation. Do not use an OR
fallback between legacy and new evaluators at cutover.

The global state lock is a conservative initial serialization mechanism; load
and lock-order testing is required before production integration. Every future
access writer, including bootstrap/recovery and group archival, must use it.

## Not implemented / not release-ready

- Settings migration and upgrade/downgrade tests.
- Credential version, password reset, first-login password change, account UI.
- HTTP schemas/routes, request idempotency, access audit pagination/export.
- Verified first-Director bootstrap; recovery remains disabled.
- Group rename/archive, grant editing/re-enabling, delegation lifecycle.
- Real ownership identity backfill and resource validation for selected IDs.
- Workflow authorization integration, runtime session revocation and UI refresh.
- Settings UI, export/print enforcement and browser typing/focus tests.
- Shadow comparison and legacy grant conversion; sensitive-field mapping.

There is no functioning Settings endpoint or new UI in this package. Do not
activate it through ad hoc table creation or manually setting a Director flag.

## Test boundaries

Foundation tests require an explicit loopback PostgreSQL TEST_DATABASE_URL with
an `_test` database name. They create and drop only a dedicated
`settings_foundation_test` schema. Test-only identities seed two Directors; this
is not an operational bootstrap implementation. ORM table creation tests are
NOT migration upgrade/downgrade tests.

Run from backend with the isolated test database:

    TEST_DATABASE_URL=<explicit loopback test URL> pytest -q tests/authorization/test_foundation.py

Acceptance includes catalog completeness, manual-only export, default deny,
Director/unknown capability, cross-grant/cross-branch and assignment denial,
management vs input separation, malformed grants, identity spoofing, atomic
access audit failure, revision conflict, revocation, last-admin concurrency,
shared/exclusive lock ordering, and database uniqueness constraints.

Next dependency: finalize the accepted P0/migration integration baseline, then
add the separate Settings migration and continue account/API/UI implementation.
No commit, push, PR, merge, deploy or Live access is authorized by this document.
