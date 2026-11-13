# Payment P0 integration unblock — local candidate

Baseline HEAD: 32ee01cd858fa13e1f55c16380748d0a3b0a007d.
No Settings source, Settings migration, runtime auth cutover, Live access or Git
publication is included. The 15 Settings files are protected by SHA-256 comparison.

## Effective payment gate

`services/production/payment_gate.py` evaluates a single SQL snapshot:
- approved: at least one valid, evidence_verified, positive receipt for this job;
- bypassed: otherwise at least one active bypass;
- pending: otherwise.

Summary, board, official task rows/job summaries, portal JSON/HTML and scheduling
use this evaluator. GET paths do not update the denormalized job mirror. Payment
mutations may update that mirror, but stale mirror values no longer authorize or
misreport a gate in these read paths. Task batching avoids an extra query per job.
Portal tracking responses explicitly disable caching.

Design remains independent. Non-print skips the design gate only under the
existing classification rules; payment still needs evidence or an active bypass.
No production output/history is deleted or rewritten.

## Explicit receipt revalidation

POST `/api/v1/production/jobs/payment/receipts/{receipt_id}/revalidate` takes
`reason` and `idempotency_key`. Existing payment.record permission and branch
checks apply. The job lock serializes this action against scheduling and other
payment changes. There is no role-string addition or Settings integration.

The receipt is fetched from the permitted gateway source and its canonical ID,
SO identity, branch, status, provenance and positive amount are validated. An
identity change is rejected for review, not silently reassigned. Legacy receipts
are not automatically trusted. Invalidated/reversed rows cannot be revived.

Rejected evidence or unavailable verification clears evidence_verified while
preserving historical amount/status and output events; a remaining valid receipt
or active bypass can still keep the gate open. This deliberately fails closed on
an explicit revalidation outage. A new request key is needed for a later attempt.

The result has `verified`, `verification_error`, `payment_status`, and receipt ID.
HTTP 200 means the verification operation completed, NOT that evidence passed.
The UI checks `verified` and displays rejection rather than a false approval.
The event records prior amount/verification and the new result/provenance in the
same transaction. Replay does not revive evidence or claim a subsequently
invalidated receipt is currently verified. No Accurate payment/receivable status
is changed.

## Cache behavior

Payment mutation invalidates affected board/job and official task caches, including
when selection changes while the request is pending. Task refresh is read-only
(no ensure-job synchronization on this path). Request generations discard stale
board/job/task responses. External task refresh invalidates/reloads the open board
when it observes a changed gate. Refresh failure clears the old approval display
and reports that payment was saved but refresh failed.

There is no Accurate cancellation webhook, polling service or new receipt discovery
API in this package. Upstream changes become known through explicit revalidation;
other clients must refresh to see committed local changes. These are residual
freshness limits, not a claim of real-time upstream reconciliation.

## Migration 0010

Parent remains 20261113_0009. Schema is unchanged: evidence_verified defaults false,
nullable request key, active receipt unique index and per-job request unique index.
Preflight now reports duplicate receipt rows and affected job IDs, plus invalid
blank identities. No automatic deduplication, provenance inference or history
rewrite occurs. Upgrade locks the receipt table before preflight through DDL so
writes cannot race between the check and index creation.

Disposable PostgreSQL tests exercise actual Alembic upgrade/downgrade, positive,
zero/negative historical amounts, inactive history, active duplicates, blank IDs,
constraint enforcement, late-DDL rollback and competing receipt writes. Downgrade
preserves original rows but necessarily drops new verification/idempotency fields;
it is not a safe rollback to old application gate behavior without separate review.
No sanitized operational dataset has been supplied; representativeness is limited
to these synthetic boundary cases. The migration lock may block writers and needs
an operational window if deployment is later authorized.

## Scope and gates

Baseline Alembic drift remains separate and was not repaired. Existing bypass
permission enforcement is unchanged; Settings role/group enforcement remains a
separate integration task. The pure task-derivation helper retains its legacy
argument compatibility, while every database-backed task caller passes computed
payment status explicitly.

The local candidate can be reviewed as the P0 parent for subsequent Settings work;
this does not activate a database schema or authorize release. Owner acceptance of
this exact WIP baseline is the next step. Settings migration/auth integration and
production rollout remain separate tasks.
