# Settings continuation: isolated account service, API and UI

This document updates the account/API/UI status in
`settings-permission-foundation.md`. The original foundation files and 13 Payment
P0 files are preserved. No runtime entrypoint, migration or navigation is changed.

## Boundary

`app.authorization.api.router` is NOT registered in `app.main`. The React
`SettingsPanel` and `PasswordChangeForm` are NOT imported by App or production
navigation. The only router mounting is in isolated tests. No operational account,
Director bootstrap, or recovery is created. The recovery procedure remains blocked
pending approved two-party identity verification.

## Account service

`accounts.py` reuses existing V3 PBKDF2/pepper helpers and stores hashes only in
`User.password_hash`. New accounts have no legacy permissions, no branches and no
membership. Initial passwords require change. Password validation is 12-200
characters, and password reset/change cannot reuse the current password.

New additive ORM model `access_account_credentials` stores `user_id`, positive
credential `generation`, and `must_change_password`. This is a model definition,
NOT a migration or active schema. It is created only in the PostgreSQL test schema.
The future migration must explicitly initialize existing accounts; a missing row
never silently creates privileges or a usable managed session.

Create user, profile edit, reset/force change, and activation/deactivation require
Director system membership and expected global access revision. They use existing
foundation locks/savepoints/audit. Password changes verify the current password,
serialize against access changes, increment the credential generation, and require
login again. Reset, username changes, and activate/deactivate also invalidate old
managed sessions. Reactivation cannot resurrect a previous session.

## Isolated authentication harness

The unregistered `/settings/session/login` and `/settings/session/password` routes
exercise password lifecycle with the existing signing secret/issuer/algorithm,
but a dedicated `settings-foundation-isolated` audience. Legacy runtime rejects
these tokens, and this router rejects legacy tokens. Token claims carry credential
generation; permissions are always reloaded from the database. A first-login token
can only change its password, not administer Settings.

This is NOT a replacement runtime login. Production cutover must integrate these
checks into the existing auth flow and every authenticated route before any
managed accounts are created in an active database. Existing runtime session
revocation is unchanged and is NOT claimed as implemented by this package.
Login rate limiting and operational login auditing must be reviewed at integration;
the harness must not be published as an alternate public login endpoint.

## HTTP contract (unregistered prefix `/settings`)

- `POST /session/login`, `POST /session/password`: isolated lifecycle harness.
- `GET /capabilities`: capability metadata/revision.
- `GET /users?q=&offset=&limit=`: escaped username search, bounded page (max 100).
- `POST /users`: username, display_name, initial password, revision, reason.
- `PATCH /users/{id}`: username/display_name only, revision/reason.
- `POST /users/{id}/active`: boolean active, revision/reason.
- `POST /users/{id}/password-reset`: optional temporary password, revision/reason;
  omission forces change without replacing the existing hash.
- `GET/POST /groups`: list/create ordinary groups, empty by default.
- `POST /users/{id}/memberships`: group_id, active, revision/reason.
- `GET/POST /groups/{id}/grants`: inspect/add explicit scoped grants.
- `POST /grants/{id}/revoke`: revision/reason.
- `GET /users/{id}/effective-access`: current membership/grant provenance.
- `GET /access-audit?offset=&limit=`: bounded audit page, newest first.

All Settings administration routes require Director membership; ordinary users
cannot alter even their own grants. Requests reject extra fields including actor,
role, system privilege and profile permissions. Validation errors never echo the
request body. Unique/constraint errors return a generic 409, not SQL parameters.
Mutations use expected revision: replay with the old revision returns 409 rather
than duplicating the write. Request-key response replay is not implemented.

Create/reset/change responses do not return passwords or password hashes. The
optional reset password is never part of the audit before/after payload. Audit
failure rolls back credentials, generation, revision and account creation.

## Prepared UI

Uses existing React form patterns, `login`/`shell` classes and V3 CSS variables.
Features: users/search/create/profile/status, reset/force password change,
membership, empty groups, capability checkboxes by module, per-grant branch and
assignment scope, effective access and paged audit.

The injected API adapter performs real HTTP calls, rejects failed responses and
never writes tokens/passwords to localStorage. Confirmation precedes mutations.
Passwords are cleared on submit. Grant selection writes grants individually and
explicitly reports partial completion; successful grants are not automatically
retried. Refresh failure disables mutation until access is reloaded. System group
privileges are displayed as protected instead of editable checkboxes.

UI tests use jsdom and test DOM focus retention; these are NOT real-browser or
end-to-end API integration tests. There is no active navigation or operational UI.

## Outstanding dependencies / release gates

1. Accepted migration baseline separate from Payment 0010, plus isolated
   upgrade/downgrade and existing-account conversion tests.
2. Verified Director bootstrap identity; no automatic initial Director.
3. Runtime auth/credential integration, authorization shadow comparison and
   workflow integration without modifying unfinalized P0 WIP.
4. Real assignment/branch identity validation and delegation integration.
5. Browser/end-to-end tests against the integrated API, including login, expiry,
   permission refresh and password lifecycle.
6. Operational rate limits, audit retention, request-key idempotency if required,
   and user-list pagination UI beyond the current search page.

Existing workflow/evidence/qty/SoD rules remain untouched. No migration, cutover,
commit, push, PR, merge, deploy or Live access occurred in this package.
