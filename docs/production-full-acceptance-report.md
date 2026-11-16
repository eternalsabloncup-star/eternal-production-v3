# Production Full Acceptance Report — Function First Iterasi 5

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Worktree:** `/tmp/epv3-fase1b-wt`
**Branch / HEAD:** `cursor/epv3-production-schedule-83bf` @ `9d52ef7ed296131604f25e98539e85c5f51139d4`
**PR #15:** OPEN · **PR #14:** HOLD
**Authz Production:** `legacy` (enforced **tidak** diaktifkan di Live)
**Git putaran ini:** NO COMMIT / NO PUSH

Matriks: [`production-full-acceptance-matrix.md`](./production-full-acceptance-matrix.md).

---

## 1. Ringkasan eksekutif

Workflow operasional penuh (Design → Payment bypass Direktur → Schedule → Prep Screen∥Cup → Sample → Approval → Output → Verify → Pack → Loading/SJ → POD) terbukti pada PostgreSQL disposable dengan mutasi **UI → HTTP → event PostgreSQL**.

Enforced disposable 14/14 PASS. Enam role browser PASS setelah warm login. Regresi suite hijau (satu flake Alembic 0008 saat bentrok concurrent; ulang **300 PASS**).

**Accurate nyata / SJ list-all / Live enforced tetap BLOCKED.**
Verdict: **READY FOR STAGING** · **NOT READY FOR LIVE APPROVAL**.

---

## 2. Preflight

| Cek | Hasil |
|---|---|
| HEAD exact `9d52ef7…` | OK |
| Working tree awal bersih | OK |
| PR #15 OPEN / #14 HOLD | OK |
| Default authz `legacy` | OK |
| Tidak mencampur PR #14 | OK |

WIP akhir Iterasi 5 (lokal, belum commit): dokumen acceptance saja.

---

## 3. Bukti browser mutation (legacy disposable)

Log: `/tmp/epv3-i5-mut-browser.log` · API `:8013` · DB `epv3_e2e_bm_*_test`

| Role | Aksi | HTTP | DB after | Verdict |
|---|---|---|---|---|
| Designer | Upload desain | 200 | versions=1 | PASS_MUTATION |
| Direktur | Design+payment bypass | 200/200 | bypassed | PASS_MUTATION |
| Kepala | Assignment | 200 | assignment_id=1 | PASS_MUTATION |
| Screener | Prep screen | 200 | prep_screener | PASS_MUTATION |
| Helper | Prep helper | 200 | prep_helper | PASS_MUTATION |
| Operator | Sample | 200 | pending | PASS_MUTATION |
| Kepala | Sample approve | 200 | approved | PASS_MUTATION |
| Operator | Output qty | 200 | events=1 qty=40 | PASS_MUTATION |
| Helper | Verify+packing | 200/200 | verified+packing | PASS_MUTATION |
| Driver | Loading+POD | 200/200/200 | loading+pod | PASS_MUTATION |
| Designer | Payment bypass deny | 403 | unchanged | PASS_MUTATION |

**11/11 PASS** · `ok=true`.

---

## 4. Six-role & enforced

| Suite | Hasil | Catatan |
|---|---|---|
| Six-role browser | **PASS** 6× `PASS_CLICK_NO_MUTATE` + deny 403 | Cold-start login Kepala bisa 500/loop race → warm login lalu hijau (P2 residual) |
| Enforced browser | **14/14 PASS_MUTATION** `authMode=enforced` | NoGrant/WrongBranch/Designer bypass 403 |
| Role packs API | **5 PASS** | Direktur lintas cabang, deny tanpa grant |

---

## 5. Quantity, negatif, recovery

- Output retry/sticky: DB tetap **1 event / qty 40** (browser).
- Multi-SJ / loading / POD / cancel / phase4 / hardening / idempotency: **53 PASS** (modul fokus) + production full **300 PASS**.
- Invariant rantai Delivered≤Loaded≤Packed≤Verified≤Output: dijaga gate backend; dibuktikan rantai happy-path + pytest over-qty/negatif.
- Chaos timeout browser penuh: **NOT TESTED** (Vitest offline/recovery ada).

---

## 6. Multi-branch

Disposible enforced seed memakai `branch-a` / `branch-b`.
API packs + browser WrongBranch membuktikan isolasi. Export browser **NOT TESTED**.

---

## 7. Accurate

| Lapisan | Status |
|---|---|
| Fixture | **159 PASS** |
| Staging Gateway | **BLOCKED** (belum diklaim di VM) |
| Real read-only | **BLOCKED** (tanpa `.env` credential di worktree) |
| SJ list-all | **BLOCKED** — **COVERAGE TERBATAS** (by-id saja; list-all endpoint null) |
| Live write | dilarang / tidak diuji |

---

## 8. Migration / restore

DB `epv3_i5_mig_*_test`:

1. Upgrade → `20261120_0017` **PASS**
2. Seed user+branch **PASS**
3. `pg_dump` **PASS**
4. Downgrade Settings in-use → `RuntimeError` **BLOCKED by design**
5. Restore → version/seed utuh **PASS**
6. Drop disposable **PASS**

Rollback Live = **maintenance window + restore**, bukan Alembic downgrade.

---

## 9. Regresi

| Suite | Hasil |
|---|---|
| Authorization | **222 PASS** |
| Production | **300 PASS** (ulang setelah flake 0008) |
| Gateway fixture | **159 PASS** |
| Vitest | **225 PASS** |
| Frontend build | **PASS** |
| Browser mutation | **11/11** |
| Enforced browser | **14/14** |
| Migration/restore | **PASS** |
| `git diff --check` | **PASS** (docs tanpa trailing WS) |

Flake: `test_alembic_0008_upgrade_downgrade_isolated` gagal sekali saat bentrok concurrent migration rehearsal; isolasi ulang PASS. Severity **P2** lingkungan tes, bukan regresi produk terbuka.

---

## 10. Perubahan file (WIP, belum commit)

- `docs/production-full-acceptance-matrix.md` (baru)
- `docs/production-full-acceptance-report.md` (baru)
- `docs/production-live-readiness-audit.md` (diperbarui)

Tidak ada perubahan kontrak bisnis / frontend visual.

---

## 11. P0 / P1 / P2 / keputusan Direktur

| ID | Item | Sev |
|---|---|---|
| ACC-05 / F3-029 | Accurate real + SJ list-all | **BLOCKED P0** |
| F3-037 | Enforced Live + grant manual | **BLOCKED P0** |
| AUTH-GRANT-01 | Grant pra-aktivasi | **P0 Owner** |
| ACC-REC-04 | Chaos timeout browser penuh | **P2** |
| AUTH-E2E-01 | Cold-start six-role login race | **P2** |
| TEST-FLK-0008 | Alembic 0008 flake concurrent | **P2** |

Keputusan Direktur: staging Owner untuk Accurate; approval enforced; grant matrix; window restore.

---

## 12. Verdict

**READY FOR STAGING**
**NOT READY FOR LIVE APPROVAL** (P0 Accurate + Live enforced masih terbuka).
