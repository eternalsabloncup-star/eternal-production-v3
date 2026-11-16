# Production Live Readiness Audit — Function First Iterasi 4 (Authorization & Migration)

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**HEAD:** `ffaf747ba7802afd5903b0327910f4c15e59d9cf`
**Worktree:** `/tmp/epv3-fase1b-wt`
**Authz Production:** `legacy` (enforced **tidak** diaktifkan)
**PR #15:** OPEN · **PR #14:** HOLD
**Git putaran ini:** NO COMMIT (WIP lokal inventory credential blocker saja)

Detail authz/migration: [`production-authz-migration-readiness-audit.md`](./production-authz-migration-readiness-audit.md).
Detail Accurate (Iterasi 3): [`production-accurate-integration-audit.md`](./production-accurate-integration-audit.md).
Detail Delivery Integrity (Iterasi 2): [`production-delivery-integrity-audit.md`](./production-delivery-integrity-audit.md).

> Jangan memakai matriks visual sebagai klaim Production siap Live.

---

## A. Ringkas status Live

| Lapisan | Status |
|---|---|
| Workflow authz default | **legacy** |
| Enforced disposable (test) | **PASS** (14/14 browser + suite authz) |
| Enforced Live | **BLOCKED** — butuh keputusan Direktur + grant manual |
| Migrasi Live | **BLOCKED** — hanya rehearsal disposable |
| Accurate read-only nyata | **BLOCKED** (credential VM kosong) |
| SJ list-all Accurate | **BLOCKED** — `accurate_sj_list_endpoint=null` |

---

## B. Authorization readiness (Iterasi 4)

| Item | Bukti |
|---|---|
| Endpoint mapped fail-closed | **74** handler (`WORKFLOW` 58 + payroll/inbox/settings) |
| Direktur Full Access | tes packs + browser enforced |
| Tanpa grant / wrong branch | 403 API + browser |
| Pengaturan user/grant/audit | API `/settings/*` (Direktur) |
| Inventory missing credential | **blocking** (WIP `inventory.py`) |
| Migration rehearsal | upgrade head → dump → downgrade in-use blocked → restore OK |

---

## C. Regresi putaran 4 (lokal)

| Suite | Hasil |
|---|---|
| Authorization | **222 PASS** |
| Production | **300 PASS** |
| Accurate Gateway fixture | **159 PASS** |
| Frontend Vitest | **225 PASS** |
| Frontend build | **PASS** |
| Six-role browser | **PASS** (`PASS_CLICK_NO_MUTATE`) |
| Enforced browser | **14/14 PASS_MUTATION** |
| Migration rehearsal disposable | **PASS** (restore; bukan klaim downgrade aman) |
| `git diff --check` | **PASS** |
| Real Accurate / Live enforced | **BLOCKED** |

---

## D. P0 / P1 / BLOCKED

| ID | Item | Prioritas |
|---|---|---|
| AUTH-INV-01 | Missing `AccountCredential` cutover blocker | **P0 fixed WIP** |
| AUTH-GRANT-01 | Grant manual pra-aktivasi | **P0 Owner** |
| F3-037 | Enforced Live | **BLOCKED P0** |
| F3-029 / ACC-04 | Accurate SJ list-all | **BLOCKED P0** |
| ACC-05 | Real/sandbox Accurate di VM | **BLOCKED P0** |
| AUTH-FLAT-01 | OR-bundle legacy sensitif | **P1** |
| Invoice/outstanding Accurate | financial UNKNOWN | **P1** kontrak |

---

## E. Keputusan Direktur (wajib sebelum Live enforced)

1. Persetujuan eksplisit mode `enforced` + approval ref.
2. Persetujuan matriks grant per jabatan & cabang (tanpa auto-import).
3. Persetujuan prosedur backup/restore (bukan alembic downgrade in-use).
4. Persetujuan urutan merge/deploy (PR #15 vs HOLD #14).

---

## F. Verdict

**READY FOR STAGING** (authz disposable + fixture/gateway staging Owner).
**NOT READY FOR LIVE** / **NOT READY FOR LIVE APPROVAL** untuk menyalakan enforced Production atau migrasi Live.
