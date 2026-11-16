# Hasil E2E Enam Role — Fase 3

**Tanggal:** 2026-11-16 (Asia/Jakarta)  
**HEAD committed:** `a034a6f57e5e445907d3d96ba761983c95a5bcf6`  
**Mode:** NO COMMIT · DB disposable · Production authz **legacy** · enforced hanya sandbox terpisah  
**Urutan kontrak backend (terbukti):** design → payment → schedule → screener → helper → sample → sample decide → output → helper-verify → packing → loading → POD  
(Schedule sebelum payment/design = **409**)

## Ringkasan

| Lapisan | Hasil |
|---------|-------|
| API mutasi 6 role + deny + qty + tracking | **30/30 PASS** (`test_fase3_e2e_six_role_workflow.py`) |
| Browser mutasi UI Kerjakan→`data-v3`→HTTP→DB→audit | **11/11 PASS_MUTATION** (`scripts/fase3_e2e_browser_mutation.mjs`) |
| Browser click-only (baseline lama) | 6/6 PASS_CLICK_NO_MUTATE (digantikan klaim mutasi di atas) |
| Enforced Production Live | **TIDAK diaktifkan** |
| Browser enforced | **NOT_RUN** — butuh seed ScopedGrant per aksi; cover via pytest packs |
| Accurate write / SJ list-all | **BLOCKED** (kontrak) |

Artifact: `/tmp/epv3-fase3-e2e-six-role-results.json`, `/tmp/epv3-fase3-e2e-browser-mutation.json`

## Browser mutasi (bukti interaksi pengguna)

Jalur wajib: LOGIN → Tugas Tim → Kerjakan / Panel V3 → submit `data-v3` → HTTP 2xx → refresh/DB → audit.  
Fixture Accurate SJ hanya stub di server disposable `:8013` — aksi utama dari klik UI.

| Role | Aksi UI | HTTP | DB Before/After | Audit | Refresh | Verdict |
|------|---------|------|-----------------|-------|---------|---------|
| Designer | Kerjakan Upload desain → `design-upload` | 200 | versions 0→1 (status job pending hingga bypass) | versi desain | status tugas Selesai | PASS_MUTATION |
| Direktur | `design-bypass` + `pay-bypass` | 200/200 | design/payment → bypassed | ya | ya | PASS_MUTATION |
| Kepala Produksi | Kerjakan Atur jadwal → `asg-create` | 200 | assignment_id=1 | ya | ya | PASS_MUTATION |
| Screener | Kerjakan → `prep-screen` | 200 | prep_screener | ya | ya | PASS_MUTATION |
| Helper | Kerjakan → `prep-helper` | 200 | prep_helper | ya | ya | PASS_MUTATION |
| Operator | Kerjakan → `sample-upload` | 200 | sample pending | ya | ya | PASS_MUTATION |
| Kepala Produksi | `sample-approve` | 200 | sample approved | ya | ya | PASS_MUTATION |
| Operator | Kerjakan → `out-confirm` qty 40 | 200 | output_confirmed qty=40 | ya | ya | PASS_MUTATION |
| Helper | `out-helper-verify` + `pack` | 200/200 | output_helper_verified, packing_batch | ya | ya | PASS_MUTATION |
| Driver | Kerjakan → `load-authority` + `load` + `pod` | 200/200/200 | packing_batch, loading, pod | ya | ya | PASS_MUTATION |
| Designer | `pay-bypass` tanpa izin | 403 | unchanged | deny | ya | PASS_MUTATION |

Catatan: verifikasi tracking untuk role tanpa `tracking.read` memakai token Kepala (bukti DB), sementara mutasi tetap dari sesi role terkait di browser.

## Matriks skenario API

| Role | Aksi | Endpoint | Permission | HTTP | DB / efek | Audit | Browser | Verdict |
|------|------|----------|------------|------|-----------|-------|---------|---------|
| Direktur | create job | POST `/jobs` | job.create | 200 | job id ada | — | — | PASS |
| Kepala | schedule sebelum gate | POST `.../schedule/assignments` | schedule.manage | 409 | tidak berubah | gate | — | PASS |
| Cabang B | baca job A | GET `/jobs/{id}` | job.read salah cabang | 403 | — | — | — | PASS |
| Designer | schedule | POST schedule | — | 403 | — | — | — | PASS |
| Designer | upload desain | POST `.../design/versions` | design.upload | 200 | design pending | — | **PASS_MUTATION** | PASS |
| Direktur | design bypass | POST design decision | design.bypass | 200 | design bypassed | — | **PASS_MUTATION** | PASS |
| Operator | payment bypass | POST `.../payment/bypass` | — | 403 | — | — | deny 403 | PASS |
| Direktur | receipt / gate | POST receipts | payment.record | 200 | payment terbuka | payment_receipt_verified | — | PASS |
| Kepala | assignment | POST schedule | schedule.manage | 200 | assignment aktif | — | **PASS_MUTATION** | PASS |
| Kepala | list tasks | GET `/jobs/tasks` | job.read | 200 | tasks derived | — | UI | PASS |
| Operator | prep screener | POST prep/screener | — | 403 | — | — | — | PASS |
| Screener | prep screen | POST prep/screener | prep.screener | 200 | PrepState | prep_screener | **PASS_MUTATION** | PASS |
| Helper | prep helper | POST prep/helper | prep.helper | 200 | remaining_vs_po=20 | prep_helper | **PASS_MUTATION** | PASS |
| Operator | sample upload | POST samples | sample.upload | 200 | sample pending | — | **PASS_MUTATION** | PASS |
| Operator | sample decide | POST samples/decision | — | 403 | — | — | — | PASS |
| Operator | output sebelum sample | POST outputs | output.confirm | 409 | gate | — | — | PASS |
| Kepala | sample approve | POST samples/decision | sample.decide | 200 | sample approved | — | **PASS_MUTATION** | PASS |
| Kepala | double approve | POST samples/decision | sample.decide | 200/409/422 | aman | — | — | PASS |
| Operator | output | POST outputs | output.confirm | 200 | qty 40 | output_confirmed | **PASS_MUTATION** | PASS |
| Operator | double-submit | POST outputs idem | output.confirm | 409 | tidak double-count | — | API baseline | PASS |
| Readonly | output | POST outputs | job.read saja | 403 | — | — | — | PASS |
| Helper | verify + packing | helper-verifications / packing | helper_verify, packing | 200 | pack 35 | packing_batch | **PASS_MUTATION** | PASS |
| Driver | POD sebelum loading | POST pod | delivery.manage | 409 | wajib loading | — | — | PASS |
| Driver | loading | POST loading | delivery.manage | 200 | loading event | loading | **PASS_MUTATION** | PASS |
| Driver | POD + foto/ttd/nama | POST pod | delivery.manage | 200 | pod event | pod | **PASS_MUTATION** | PASS |
| Designer | loading | POST loading | — | 403 | — | — | deny | PASS |
| Kepala | tracking | GET tracking | tracking.read | 200 | events list | events | — | PASS |
| System | qty SO | JobLineQty | — | — | print=100 non_print=100 | — | — | PASS |

## Payment gate (API)

- Belum terbuka → schedule 409: PASS  
- Bypass operator ditolak 403: PASS  
- Receipt / bypass Direktur membuka gate: PASS  
- Bypass OFF di settings default (`bypass_enabled=false`) hingga diaktifkan: terbukti di seed browser  

## Enforced (sandbox terpisah, bukan Production)

- Packs HTTP matrix + AccessAudit + deny cross-branch: **PASS** (`test_fase3_enforced_role_packs` + `test_workflow_access`, 20 passed)
- Activation gate: **PASS** (`test_enforced_activation_gate`)
- Browser enforced end-to-end: **NOT_RUN** (penyebab: seed ScopedGrant/role packs per tombol UI belum dilengkapi di harness mutasi; bukan karena Production diaktifkan)
- Production tetap **legacy**
- Tidak ada fallback klaim legacy sebagai enforced

## Implementasi UI terkait mutasi browser

1. `production.html` — `openTask` mengarah ke `v3OpenWorkflow` bila official tasks / live inbox / `isLiveRuntime` / `v3-auth-ok` (bukan hanya `isLiveInbox`).
2. `live-runtime.js` — `window.isLiveRuntime` diekspos untuk binding di atas.
3. `engine.py` — `_resolve_operator` memakai `begin_nested()` agar kegagalan `load_access` (mis. tabel auth belum ada) tidak meracuni transaksi schedule (legacy tetap jalan).
4. Harness: `scripts/fase3_e2e_browser_mutation_server.py` + `scripts/fase3_e2e_browser_mutation.mjs`.

## Regresi lokal (disposable / APP_ENV=test)

| Cek | Hasil |
|-----|-------|
| `test_fase3_e2e_six_role_workflow` + master cabang + activation gate | 21 passed |
| Enforced packs + workflow access | 20 passed |
| Frontend Vitest penuh | 221 passed |
| Frontend build + routing/security checks | PASS |
| `git diff --check` | PASS |
| Live migration / Live writes / Production enforced | **TIDAK dijalankan** |
