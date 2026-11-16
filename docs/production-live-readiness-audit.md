# Production Live Readiness Audit — Function First Iterasi 1B

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16  
**Repository:** `eternalsabloncup-star/eternal-production-v3`  
**Branch:** `cursor/epv3-production-schedule-83bf`  
**Committed HEAD (expected):** `244a0c262b49f90fe172f58581acce4d8945fde3`  
**Worktree:** `/tmp/epv3-fase1b-wt`  
**Authz Production:** `legacy` (enforced **tidak** diaktifkan)  
**PR #15:** OPEN · **PR #14:** HOLD  
**Git putaran ini:** **NO COMMIT / NO PUSH** (WIP lokal)

> Jangan memakai matriks visual 29/39 sebagai klaim Production siap.

---

## A. Klasifikasi item (final)

| Aturan | Status |
|---|---|
| Prepare Cup/Screen hanya `production_process=print` dari sumber canonical (`JobLineQty` / Accurate sync) | **TEGAK** |
| `UNKNOWN` **tidak** otomatis menjadi PRINT saat prep | **DIPERBAIKI 1B** |
| Line tanpa `JobLineQty` → 409 + alasan sinkron canonical | **TEGAK** |
| `non_print` → 409 (bukan print-chain) | **TEGAK** |
| Mapping canonical | `sync_job_lines_from_so_detail` / seed `line_items.production_process` — **bukan** aksi prep |

---

## B. Prepare Cup kontrak

| Item | Keputusan |
|---|---|
| Event | Reuse `role=helper` (`PrepState`/`PrepEvent` + mirror `prep_helper`) |
| API | `prep_kind=prepare_cup`, label `Prepare Cup` |
| Paralel | Independen vs Prepare Screen setelah jadwal sah |
| Sample gate | Kedua READY **per line print** terjadwal |
| PIC | Helper + grant `production.prep.helper` + cabang sah — **bukan** auto-grant nama role |

---

## C. Lapisan bukti (pisah)

| Lapisan | Hasil putaran 1B | Bukti |
|---|---|---|
| **Implementasi selesai (lokal WIP)** | YA | `prep.py`, `engine.py`, `workflow.py`, `production.html` |
| **API tested** | PASS | Prepare Cup suite, workflow E2E, six-role API, authz 221 |
| **Browser tested (full mutation)** | **11/11 PASS_MUTATION** | `scripts/fase3_e2e_browser_mutation.mjs` · DB `epv3_e2e_bm_*_test` · log `/tmp/epv3-ff1b-browser-mut2.log` |
| **Browser six-role harness** | Login + Kerjakan + deny · `PASS_CLICK_NO_MUTATE` | `fase3_e2e_six_role_browser.mjs` — **bukan** klaim mutasi penuh per role |
| **Accurate fixture** | Dipakai (SJ/receipt stub server) | mutation_server monkeypatch |
| **Accurate sandbox/real** | **BELUM** | Inbox 403 tanpa gateway; SJ list-all BLOCKED |
| **Production deployment readiness** | **TIDAK** | P0 Accurate + enforced HOLD |

### Alur browser mutation (bukti HTTP + DB)

Designer upload → Direktur design/pay bypass → Kepala schedule → Screener screen → Helper cup → Operator sample → Kepala approve → Operator output → Helper verify+pack → Driver loading+POD → Designer pay-bypass **403**.

Event ledger: `prep_screener`, `prep_helper`, `output_confirmed`, `output_helper_verified`, `packing_batch`, `loading`, `pod`.

API negatif (disposable :8013): designer/screener tanpa `prep.helper` → **403**; line tanpa JobLineQty → **409 UNKNOWN/hilang**.

---

## D. Cancel / revisi SO

| Kasus | Hasil |
|---|---|
| Cancel setelah Screen+Cup (`confirm_review`) | PASS — histori `PrepState`/`PrepEvent` tetap |
| Mutasi pada job cancelled | Ditolak |
| Job revisi line-id baru | Event lama **tidak** membuka sample; prep ulang wajib |
| Revisi line-id sama versi berbeda | Model line belum punya version key terpisah → **P1** dokumentasi |

---

## E. Regresi putaran 1B

| Suite | Hasil |
|---|---|
| Prepare Cup + workflow + six-role API focused | **21 PASS** |
| `tests/authorization/` | **221 PASS** |
| `tests/production/` penuh | **292 PASS** (setelah seed klasifikasi print di fixture terkait) |
| Frontend Vitest | **225 PASS** |
| Frontend build | **PASS** |
| `git diff --check` | **PASS** |
| Browser mutation full | **11/11 PASS_MUTATION** |
| Browser six-role click harness | **ok=true** (6 role; click/deny, bukan full mutate) |

---

## F. P0 / P1 / BLOCKED

| ID | Item | Prioritas |
|---|---|---|
| F3-029 | Accurate SJ list-all | **BLOCKED P0** |
| F3-037 | Enforced Live activation | **BLOCKED P0** (PR #14 HOLD) |
| Accurate inbox tanpa gateway | 403 runtime | **P1** |
| Line revision versioning model | Belum ada version key terpisah | **P1** |
| Visual nonkritis | Ditunda | HOLD |

---

## G. Verdict

**SIAP GIT** untuk checkpoint Function First 1B (setelah Owner izinkan commit).  
**Bukan** READY FOR LIVE. Staging smoke Owner masih diperlukan setelah push.
