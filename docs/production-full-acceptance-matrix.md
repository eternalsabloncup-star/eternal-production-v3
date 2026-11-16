# Production Full Acceptance Matrix — Function First Iterasi 5

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**HEAD:** `9d52ef7ed296131604f25e98539e85c5f51139d4`
**Branch:** `cursor/epv3-production-schedule-83bf` · **PR #15 OPEN** · **PR #14 HOLD**
**Authz Production:** `legacy` · Enforced hanya disposable
**DB bukti:** PostgreSQL disposable (`*_test`) saja

Status: **PASS** / **FAIL** / **BLOCKED** / **NOT TESTED**
Fixture ≠ integrasi Accurate nyata.

---

## A. Full workflow (happy path)

| ID | Fitur | Role/PIC | Permission (enforced) | Branch | Endpoint (ringkas) | Model/event | Prasyarat | Expected | Browser | API | DB | Hasil | Sev bila gagal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ACC-WF-01 | Inbox/PO → job | Kepala / sistem | `inbox.read` / `job.create` | scoped | inbox + job | `ProductionJob` | SO available | job aktif | API-led seed | PASS pytest | PASS | **PASS** (disposable seed) | P0 |
| ACC-WF-02 | Design upload | Designer | `design.version.create` | job branch | `POST .../design/versions` | `DesignVersion` | job aktif | version pending | **PASS_MUTATION** | PASS | versions=1 | **PASS** | P0 |
| ACC-WF-03 | Design/payment bypass | Direktur | Full Access | lintas | design decision + payment bypass | events bypass | Direktur | bypassed | **PASS_MUTATION** | PASS | design+payment bypassed | **PASS** | P0 |
| ACC-WF-04 | Schedule assignment | Kepala | `schedule.assignment.create` | job branch | `POST .../schedule/assignments` | `ScheduleAssignment` | payment ok / bypass | assignment | **PASS_MUTATION** | PASS | assignment_id | **PASS** | P0 |
| ACC-WF-05 | Prep Screen | Screener | `prep.screener.record` | job branch | `POST .../prep/screener` | `prep_screener` | schedule | screen ready | **PASS_MUTATION** | PASS | prep_screener | **PASS** | P0 |
| ACC-WF-06 | Prep Cup/Helper | Helper | `prep.helper.record` | job branch | `POST .../prep/helper` | `prep_helper` | schedule | helper ready | **PASS_MUTATION** | PASS | prep_helper | **PASS** | P0 |
| ACC-WF-07 | Sample upload | Operator | `sample.version.create` | job branch | `POST .../samples` | sample pending | prep | sample pending | **PASS_MUTATION** | PASS | sample pending | **PASS** | P0 |
| ACC-WF-08 | Sample approval | Kepala | `sample.decision.record` | job branch | `POST .../samples/{id}/decision` | approved | sample | approved | **PASS_MUTATION** | PASS | approved | **PASS** | P0 |
| ACC-WF-09 | Output | Operator | `output.record` | job branch | `POST .../outputs` | `output_confirmed` | sample ok | qty tercatat | **PASS_MUTATION** qty=40 events=1 | PASS | event tunggal | **PASS** | P0 |
| ACC-WF-10 | Verification | Helper | `output.helper.verify` | job branch | `POST .../helper-verifications` | `output_helper_verified` | output | verified≤output | **PASS_MUTATION** | PASS | verified | **PASS** | P0 |
| ACC-WF-11 | Packing | Helper | `packing.record` | job branch | `POST .../packing` | `packing_batch` | verified | packed≤verified | **PASS_MUTATION** | PASS | packing | **PASS** | P0 |
| ACC-WF-12 | Loading + SJ by-id | Driver | `loading.record` + authority read | job branch | loading-authority + loading | `loading` | packed + SJ id | loaded≤packed | **PASS_MUTATION** | PASS | loading | **PASS** (SJ by-id / fixture) | P0 |
| ACC-WF-13 | POD | Driver | `delivery.pod.record` | job branch | `POST .../pod` | `pod` | loading | pod≤loading | **PASS_MUTATION** | PASS | pod | **PASS** | P0 |

Bukti browser: `/tmp/epv3-i5-mut-browser.log` — **11/11 PASS_MUTATION**, `ok=true`.

---

## B. Enam role + negatif akses

| ID | Skenario | Expected | Browser | API | Hasil |
|---|---|---|---|---|---|
| ACC-ROLE-01..06 | Kepala/Designer/Screener/Helper/Operator/Driver tugas masing-masing | klik/tugas sesuai; deny bypass | six-role **PASS_CLICK_NO_MUTATE** + deny 403; mutation full path PASS | packs HTTP PASS | **PASS** |
| ACC-ROLE-07 | Direktur Full Access lintas cabang | boleh A+B | enforced browser PASS | packs PASS | **PASS** |
| ACC-ROLE-08 | NoGrant | 403 | enforced browser 403 | PASS | **PASS** |
| ACC-ROLE-09 | WrongBranch | 403 scope | enforced browser 403 | packs PASS | **PASS** |
| ACC-ROLE-10 | User inactive | login/akses ditolak | NOT TESTED browser | foundation/runtime PASS | **PASS** (API) / **BROWSER NOT TESTED** |
| ACC-ROLE-11 | Missing credential cutover | blocking inventory | — | inventory test PASS | **PASS** |

---

## C. Multi-branch

| ID | Skenario | Hasil | Bukti |
|---|---|---|---|
| ACC-MB-01 | Job branch-a vs branch-b | **PASS** | `test_fase3_enforced_role_packs` + enforced seed BRANCH_A/B |
| ACC-MB-02 | Operator scope cabang sendiri | **PASS** | packs + WrongBranch 403 |
| ACC-MB-03 | Direktur lintas | **PASS** | packs + enforced Direktur |
| ACC-MB-04 | List/detail/summary/count scoped | **PASS** (API/pytest) | production + authz suites |
| ACC-MB-05 | Export scoped | **PASS** bila endpoint mapped `job.export` | mapped; browser export **NOT TESTED** |
| ACC-MB-06 | Mutasi cabang lain | **PASS** 403 | WrongBranch / packs |

---

## D. Produksi kompleks

| ID | Skenario | Hasil | Catatan |
|---|---|---|---|
| ACC-CX-01 | Satu SO satu line | **PASS** | browser mutation + workflow e2e |
| ACC-CX-02 | Multi-line / multi-SJ | **PASS** | `test_multi_sj_loading` + related |
| ACC-CX-03 | PRINT vs NON_PRINT | **PASS** (API) | classification/workflow tests; browser non-print path **NOT TESTED** |
| ACC-CX-04 | UNKNOWN classification | **PASS** (API) | pytest classification |
| ACC-CX-05 | Multi-operator / partial schedule | **PASS** (API) | schedule/operations suites |
| ACC-CX-06 | Screen dulu / Cup dulu / salah satu belum READY | **PASS** (API) | prep gates |
| ACC-CX-07 | Sample tolak vs approve | **PASS** (API approve browser; reject API) | |
| ACC-CX-08 | Output parsial + retry idempotency | **PASS** | browser sticky + `test_output_correction_idempotency` |
| ACC-CX-09 | Reject / qty verify / packing parsial | **PASS** (API) | hardening/acceptance |
| ACC-CX-10 | Loading/POD parsial | **PASS** (API) | multi_sj / pod tests |
| ACC-CX-11 | Cancelled job mutation | **PASS** (API) | `test_job_lifecycle_cancel` |

---

## E. Quantity invariant

| ID | Invariant | Hasil | Bukti |
|---|---|---|---|
| ACC-QTY-01 | Output event tunggal pada retry | **PASS** | browser `events=1;qty=40` |
| ACC-QTY-02 | Verified ≤ Output ≤ ordered (gates) | **PASS** (API) | phase4 / hardening |
| ACC-QTY-03 | Packed ≤ Verified; Loaded ≤ Packed; POD ≤ Loaded | **PASS** (API+browser chain) | mutation + multi_sj |
| ACC-QTY-04 | No double-count multi-SJ | **PASS** | `test_multi_sj_loading` |
| ACC-QTY-05 | Concurrency / identical idempotency | **PASS** | release/phase31/idempotency tests |

---

## F. Negative gates (backend)

| ID | Gate | Hasil |
|---|---|---|
| ACC-NEG-01 | Payment belum lolos | **PASS** (API) |
| ACC-NEG-02 | Design belum siap | **PASS** (API) |
| ACC-NEG-03 | Schedule / prep / sample belum sah | **PASS** (API) |
| ACC-NEG-04 | Over-qty output/verify/pack/load/POD | **PASS** (API) |
| ACC-NEG-05 | POD tanpa bukti wajib | **PASS** (API pod/screen) |
| ACC-NEG-06 | Permission / wrong branch | **PASS** browser+API |
| ACC-NEG-07 | Gateway unavailable | **PASS** fail-closed gateway tests (fixture); real **BLOCKED** |
| ACC-NEG-08 | Designer payment bypass | **PASS** 403 browser |

---

## G. Network & recovery

| ID | Skenario | Hasil |
|---|---|---|
| ACC-REC-01 | Double-click / duplicate idempotency | **PASS** browser + API |
| ACC-REC-02 | Same key different payload | **PASS** (API) |
| ACC-REC-03 | Refresh + retry | **PASS** browser (sticky key / single event) |
| ACC-REC-04 | HTTP timeout / lost response UI honesty | **PASS** parsial (Vitest offline/restore); full browser chaos **NOT TESTED** |
| ACC-REC-05 | Concurrent request | **PASS** (API hardening) |
| ACC-REC-06 | DB txn failure recovery | **PASS** (API) / Live **NOT TESTED** |

---

## H. Accurate integration

| ID | Lapisan | Hasil |
|---|---|---|
| ACC-ACC-01 | Fixture Gateway | **PASS** 159 |
| ACC-ACC-02 | Staging Gateway Owner | **BLOCKED** di VM (tidak diklaim) |
| ACC-ACC-03 | Real read-only | **BLOCKED** (tidak ada credential terkonfigurasi di worktree) |
| ACC-ACC-04 | SJ by-id | **PASS** fixture / kontrak |
| ACC-ACC-05 | SJ list-all | **BLOCKED** — **COVERAGE TERBATAS** (`accurate_sj_list_endpoint=null`; hanya by-id) |
| ACC-ACC-06 | Live write | **NOT TESTED** (dilarang) |

---

## I. Enforced disposable & migrasi

| ID | Skenario | Hasil |
|---|---|---|
| ACC-ENF-01 | Full workflow `authMode=enforced` | **PASS** 14/14 |
| ACC-ENF-02 | Fail-closed / grants manual | **PASS** |
| ACC-ENF-03 | Production tetap legacy | **PASS** default config |
| ACC-MIG-01 | Upgrade → `20261120_0017` | **PASS** |
| ACC-MIG-02 | Backup / restore integrity | **PASS** |
| ACC-MIG-03 | Downgrade Settings in-use | **BLOCKED** by design (`RuntimeError`) — rollback = restore |

---

## J. Ringkas hitungan

| Status | Perkiraan skenario inti |
|---|---|
| PASS | ~55+ (workflow+role+branch+qty+neg+enf+mig+fixture) |
| BLOCKED | Accurate real/staging/SJ-list-all; Live enforced |
| NOT TESTED | Browser non-print full path; browser export; chaos timeout penuh; Live |

Detail naratif: [`production-full-acceptance-report.md`](./production-full-acceptance-report.md).
