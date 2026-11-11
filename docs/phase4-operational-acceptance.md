# Phase 4 — Operational Acceptance (fixture mode)

**Scope:** V49 frontend + PostgreSQL backend + Accurate gateway (fixture).  
**Not claimed:** live Accurate Online verification.  
**ERP V1:** untouched; parity still unverified.

## A. HEAD / PR

See latest commit on `cursor/v49-live-phase1-3e4e` / PR #2.

Migrations (single head): `0001` → `0005` (baseline → users/WO → auth audit → phase2 workflow → prep/payroll).

## B. Browser E2E (fixture)

Script: `scripts/phase4_acceptance_smoke.sh`  
Evidence: `/tmp/epv3-p4-browser.json`, `/tmp/epv3-p4-api-report.json`

- Opens `production.html`, confirms live-runtime presence
- Browser fetch: login → inbox page 1 (expects total ≥ 70 from fixture gateway)

## C. Automated tests

| Suite | Result |
|-------|--------|
| `tests/production/test_phase4_acceptance.py` | full workflow, permissions, concurrency, 70-SO inbox |
| Prior phase 2/3.1/3.2 + gateway pytest | retained |
| CI | must stay green on push |

## D. Quantity reconciliation

Validated in phase4 full workflow: multi-operator + 2 color passes; partial outputs; duplicate idempotency → 409; correction delta; verified reject; packing ≤ available; loading/POD qty.

## E. Permissions / security

- Cross-branch job create → 403  
- Limited role cannot upload design → 403  
- Cancelled receipt / cancelled SJ → 409 fail-closed (enforce on)  
- Payment bypass audited (`payment_bypass_authorized`)

## F. Performance (fixture)

- ≥ 70 SO in gateway fixtures (`SO-P4-001`…`070`)  
- Server-side `page`/`limit` on gateway + inbox  
- Simultaneous multi-user inbox pages + 20 concurrent by-so lookups (local thresholds)

## G. V49 button acceptance matrix

Mode legend: **PASS** = exercised against fixture stack; **FAIL** = defect; **NOT TESTED** = no automated/browser exercise this round; **BLOCKED-LIVE** = needs live Accurate.

| V49 action (`live-runtime`) | API | Fixture result | Notes |
|-----------------------------|-----|----------------|-------|
| Open workflow / ensure job | `POST /jobs`, `GET by-so` | PASS | |
| design-upload | `POST .../design/versions` | PASS | |
| design-approve | `POST .../decision` | PASS | |
| design-reject | decision rejected | NOT TESTED | API exists |
| design-customer | customer_approval | NOT TESTED | |
| design-bypass | bypass+reason | PASS (phase2/4 paths) | |
| pay-receipt | `POST .../payment/receipts` | PASS | fixture RCP-OK-1; **not live** |
| pay-bypass | bypass+audit | PASS | |
| pay-revoke | revoke bypass | NOT TESTED this round | covered earlier phase2 |
| pay-invalidate | invalidate+audit | PASS (phase3.1) | |
| asg-create | schedule assignments | PASS | multi-op / multi-pass |
| asg-cancel | cancel-remaining | PASS (phase2) | |
| asg-transfer | transfer-remaining | NOT TESTED | API exists |
| prep-screen | prep/screener | PASS | |
| prep-helper | prep/helper | PASS | |
| sample-upload / approve / reject | samples | PASS approve; reject NOT TESTED | |
| out-confirm | outputs | PASS | dup idempotency 409 |
| out-correct | corrections | PASS | |
| rej-record / rej-verify | rejects | PASS | |
| pack | packing | PASS | overpack guarded |
| load | loading | PASS | cancelled SJ 409 |
| pod | pod | PASS | re-verify SJ |
| sj-cancel | sj/cancel | PASS | history preserved |
| track-refresh | board/tracking | PASS | |
| rate-set / rate-get / payroll-run | payroll | PASS (phase2.1) | OT still unverified vs V1 |
| Inbox pagination | `GET /inbox` | PASS | ≥70 SO fixture |
| Demo/sim handlers | — | PASS (neutralized) | cannot fake success |

## H. Remaining blockers

1. **Live Accurate** credentials (`ACCURATE_API_TOKEN`, `ACCURATE_DATABASE_ID`, `GATEWAY_MODE=live`, HTTPS URL) — Owner  
2. **ERP V1 source parity** unread — business decisions on OT/attendance, historical SJ semantics unresolved formally  
3. Some V49 buttons only API-covered / not browser-clicked this round (see NOT TESTED)  
4. No production deploy / DNS / VPS in this phase  

## I. Staging readiness

**Fixture staging: YES** — deployable for operational dry-run.  
**Live Accurate staging: NO** until Owner credentials + live smoke.  
**Production: NO** — stop gate holds (no merge/deploy from this agent).
