# Hasil E2E Enam Role — Fase 3

**Tanggal:** 2026-11-16 (Asia/Jakarta)
**HEAD committed:** `d110f5fb3b63605ca4e0ecada36c701cc732f6da`
**Checkpoint:** sticky Output idempotency + harness enforced browser (PR #15)
**Mode:** checkpoint commit · DB disposable · Production authz **tidak** diaktifkan enforced
**Urutan kontrak backend (terbukti):** design → payment → schedule → screener → helper → sample → sample decide → output → helper-verify → packing → loading → POD

## Ringkasan

| Lapisan | Hasil |
|---------|-------|
| API mutasi 6 role + deny + qty + tracking | **30/30 PASS** (`test_fase3_e2e_six_role_workflow.py`) |
| Browser mutasi UI (legacy disposable `:8013`) | **11/11 PASS_MUTATION** (baseline dipertahankan) |
| Browser mutasi UI **enforced** (`:8014`) | **14/14 PASS_MUTATION** (`scripts/fase3_e2e_browser_enforced.mjs`) |
| Output sticky idempotency (browser + DB) | **PASS** — 1 event qty=40; double-click/retry tanpa POST kedua; replay key → **409**, count tetap 1 |
| Enforced Production Live | **TIDAK diaktifkan** |
| Accurate write / SJ list-all | **BLOCKED** (kontrak) |

Artifact: `/tmp/epv3-e2e-enforced-run.log`, `/tmp/epv3-e2e-8014.log`

## Browser enforced (bukti)

**Auth mode aktual login:** `workflow_authorization=enforced`, `settings_enabled=true`.
**DB:** disposable PostgreSQL eksklusif (`epv3_e2e_enf_*_test`), `APP_ENV=test`.
**ScopedGrant:** ROLE_PACKS per role test di `branch-a` saja; `e2e.nogrant` tanpa grant; `e2e.wrongbranch` grant `branch-b` saja. Direktur = bootstrap Director Full Access. Tidak ada auto-grant ke user existing.

| Role | Aksi UI | HTTP | DB / efek | Verdict |
|------|---------|------|-----------|---------|
| System | Login | 200 | `system_director=true`, mode enforced | PASS_MUTATION |
| Designer | Upload desain | 200 | versions 0→1 | PASS_MUTATION |
| Direktur | design-bypass + pay-bypass | 200/200 | design/payment bypassed | PASS_MUTATION |
| Kepala Produksi | Assignment | 200 | assignment_id=1 | PASS_MUTATION |
| Screener | Prep screen | 200 | prep_screener | PASS_MUTATION |
| Helper | Prep helper | 200 | prep_helper | PASS_MUTATION |
| Operator | Sample upload | 200 | sample pending | PASS_MUTATION |
| Kepala Produksi | Sample approve | 200 | sample approved | PASS_MUTATION |
| Operator | Output + sticky idem | 200 / short-circuit / short-circuit | events=1; qty=40 | PASS_MUTATION |
| Helper | Verify + packing | 200/200 | helper_verified, packing_batch | PASS_MUTATION |
| Driver | load-authority + load + POD | 200/200/200 | loading, pod | PASS_MUTATION |
| NoGrant | GET job | 403 | Capability denied: job.read | PASS_MUTATION |
| WrongBranch | GET job branch-a | 403 | Resource scope denied | PASS_MUTATION |
| Designer | pay-bypass | 403 | ditolak | PASS_MUTATION |

Tidak ada fallback legacy: server di-boot dengan `V3_WORKFLOW_AUTHORIZATION=enforced`; login body mengonfirmasi mode yang sama.

## Idempotency Output UI

| Cek | Bukti | Hasil |
|-----|-------|-------|
| Sticky key satu logical submit | slot `out::1\|1\|40\|1\|L1`, key `out-…` committed | PASS |
| (1) Double-click dicegah frontend | `dup.hit=null` (short-circuit latch/sticky), DB tetap 1 | PASS |
| (2) Replay key mencapai backend | POST ulang key yang sama → HTTP **409**; count tetap 1 | PASS |
| Retry setelah sukses (ulang submit UI) | `retry.hit=null`, DB tetap 1 | PASS |
| UNIQUE constraint | `uq_production_events_idempotency` tetap | PASS |
| Draft restore qty/lot | `DELIVERY_DRAFT_IDS` mencakup `v3-out-*` agar re-render tidak mint key baru | PASS |
| 409 reconcile di FE | catch status 409 → loadBoard + cocokkan event → commit sticky | terpasang |

### RISIKO RESIDUAL — retry jaringan (skenario 3)

Belum diuji end-to-end browser: respons server **sudah sukses** tetapi klien kehilangan jawaban (timeout / drop) sebelum `stickyIdemCommit`, lalu user menekan ulang.

Mitigasi kode yang ada: sticky key sama → backend UNIQUE → **409** → FE rekonsiliasi ke board.
**Klaim:** skenario (1) dan (2) PASS; skenario (3) **belum terbukti di harness browser** — jangan dianggap PASS penuh untuk seluruh retry network.

## Regresi lokal (putaran ini)

| Cek | Hasil |
|-----|-------|
| Browser enforced 6 role + negatif + idem | **14/14 PASS_MUTATION** |
| Pytest authz packs + activation + runtime + concurrency + output correction idem | **52 passed** |
| Frontend Vitest penuh | **223 passed** (41 files) |
| Frontend build + routing/security | **PASS** |
| `git diff --check` | **PASS** |
| Live migration / Live writes / Production enforced | **TIDAK dijalankan** |
