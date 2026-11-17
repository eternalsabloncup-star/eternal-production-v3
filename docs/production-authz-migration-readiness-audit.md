# Production Authorization & Migration Readiness — Function First Iterasi 4

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Worktree:** `/tmp/epv3-fase1b-wt`
**Branch:** `cursor/epv3-production-schedule-83bf`
**HEAD:** `ffaf747ba7802afd5903b0327910f4c15e59d9cf`
**Authz Production:** `legacy` (enforced **tidak** diaktifkan di Live)
**PR #15:** OPEN · **PR #14:** HOLD (paralel; tidak digabung)
**Batasan putaran:** NO COMMIT · NO PUSH · NO LIVE MIGRATION · NO LIVE ENFORCED

> Dokumen ini adalah bukti kesiapan cutover, bukan izin aktivasi Live.

---

## 1. Preflight

| Cek | Hasil |
|---|---|
| Worktree `/tmp/epv3-fase1b-wt` | OK |
| Branch `cursor/epv3-production-schedule-83bf` | OK |
| HEAD = `ffaf747…` | OK |
| Remote tip sama (sebelum WIP lokal) | OK |
| PR #15 OPEN | OK |
| PR #14 HOLD (tidak dicampur) | OK |
| WIP lokal Iterasi 4 | `inventory.py` + `test_inventory_missing_credential.py` (belum commit) |

---

## 2. Endpoint coverage (canonical)

Manifest fail-closed: `app/authorization/workflow_map.py`.

| Modul | Handler terpetakan |
|---|---|
| WORKFLOW (produksi) | 58 |
| PAYROLL | 4 |
| INBOX | 3 |
| SETTINGS_PROD (payment approval + cabang + mesin) | 9 |
| **Total mapped** | **74** |

Unmapped production route → **fail-closed** pada mode `enforced`.

### Alur bisnis → capability (ringkas)

| Tahap | Contoh handler | Capability enforced | Legacy OR-ish |
|---|---|---|---|
| Inbox | `inbox`, `order_detail` | `inbox.read`, `order.read` | sama |
| Design | `design_upload`, `design_decide`, link | `design.version.create`, `design.decision.record`, `design.approval_link.*` / bypass | `design.upload` / `approve` / `bypass` |
| Payment | receipt / bypass / revoke | `payment.receipt.*`, `payment.bypass.*` | `payment.record` / `bypass` / `revoke` |
| Schedule | assignment create/cancel/transfer | `schedule.assignment.*` | `schedule.manage` |
| Prep Screen ∥ Cup | `prep_screener`, `prep_helper` | `prep.screener.record`, `prep.helper.record` | `prep.screener` / `prep.helper` |
| Sample → Approval | upload / decide | `sample.version.create`, `sample.decision.record` | `sample.upload` / `decide` |
| Output | confirm / correct / reject | `output.*`, `reject.*` | `output.confirm` dll. |
| Verification | `helper_verify_output` | `output.helper.verify` | `output.helper_verify` |
| Packing | `packing_record` | `packing.record` | `packing.record` |
| Loading → POD | loading / POD / SJ cancel | `loading.*`, `delivery.pod.record`, `delivery.sj.cancel_local` | sering `delivery.manage` |
| Tracking | read / link | `tracking.read`, `tracking.link.create` | `tracking.read` (link ≠ read di enforced) |

**Mutasi tidak boleh hanya dilindungi tombol UI.** Bridge: `workflow.py` + dependency auth pada router; browser deny-probe + HTTP 403 diuji langsung.

### Settings / Pengaturan (Direktur)

Prefix `/settings` (`app/authorization/api.py`), gate `director`:

| Operasi | Endpoint |
|---|---|
| Buat user | `POST /settings/users` |
| Profil / role via grup | `PATCH /users/{id}`, `POST /users/{id}/memberships` |
| Aktif/nonaktif | `POST /users/{id}/active` |
| Reset password | `POST /users/{id}/password-reset` |
| Grup + grant + cabang | `POST /groups`, `POST /groups/{id}/grants` |
| Revoke grant | `POST /grants/{id}/revoke` |
| Akses efektif | `GET /users/{id}/effective-access` |
| Audit akses | `GET /access-audit` |
| Status cutover | `GET /authorization-status` |

Tidak ada auto-grant / auto-import (`automatic_import_allowed=false`).

---

## 3. Permission & grant matrix

Sumber paket jabatan: `docs/fase3-permission-role-matrix.md`, `role_packs.py`.

| Peran | Grant eksplisit (ringkas) | Dilarang tanpa grant |
|---|---|---|
| Direktur (`director` sistem) | Full Access lintas cabang | — (aksi sensitif diaudit) |
| Kepala Produksi | jadwal, sample decide, plan/SJ, evidence read | payment.bypass tanpa grant |
| Designer | design create/decide/link | payment.bypass, design.bypass |
| Screener | `prep.screener.*` | output / packing / POD |
| Helper | prep helper, verify, packing | loading / POD / screener tanpa grant |
| Operator | sample upload, output, reject | sample decide, POD |
| Driver | loading, POD, attachment, schedule read | sj.cancel, plan, output |
| Tanpa grant | — | seluruh capability → 403 |
| Wrong branch | grant cabang lain | Resource scope denied |
| Inactive | — | denied |

Karyawan: **tidak** ada auto-grant dari nama role; scope cabang wajib pada ScopedGrant.

---

## 4. Legacy vs enforced

| Aspek | Legacy (default Production) | Enforced (target; disposable/test + approval) |
|---|---|---|
| Default deploy | `V3_WORKFLOW_AUTHORIZATION=legacy` | tidak auto-on |
| Evaluasi | `User.permissions` (+ branch legacy) | ScopedGrant + cabang + ownership |
| Unmapped route | perilaku legacy | fail-closed |
| Direktur | legacy permissions luas / grup director | Full Access lintas cabang |
| Aktivasi Live | — | butuh Settings ON + `V3_WORKFLOW_ENFORCED_APPROVAL_REF` (bukan flip diam-diam) |
| Inventory cutover | read-only | blocking bila narrowing / widening non-director / unknown / **missing AccountCredential** |

Gate proses: `app/authorization/mode.py` — `enforced_startup_allowed`; status Direktur tidak mengaktifkan mode sendiri.

---

## 5. Cross-branch data security

| Permukaan | Temuan |
|---|---|
| Job / schedule / tasks / board | scope cabang pada evaluator + query |
| Delivery / loading / POD / SJ | capability + resource branch |
| Payment evidence | capability terpisah; bukan flatten dari `job.read` di enforced |
| Inbox list/total | legacy non-Direktur: scoped (perbaikan Iterasi 3); enforced: grant+branch |
| Export / summary / count | harus memakai scope yang sama dengan detail (diaudit di tes authz/production) |

Risiko residual: OR-bundle legacy (`delivery.manage`, field sensitif) tetap ada di mode legacy — cutover memakai paket manual, bukan flatten.

---

## 6. Migration readiness

| Item | Status |
|---|---|
| Rantai Alembic | `20261111_0001` → head `20261120_0017` (linear) |
| Settings `20261115_0011` | tabel access/grants/credentials; **tanpa** auto membership/grant |
| Cabang `20261120_0017` | `production_branches` (PK `code`) |
| Downgrade Settings in-use | `RuntimeError` — **bukan** jalur rollback aman |
| Strategi rollback teruji | `pg_dump` → drop/create DB disposable → `psql` restore |

### Rehearsal disposable (Iterasi 4)

DB: `epv3_mig_reh_f8a132302f_test` (loopback `*_test` saja).

1. Upgrade → head `20261120_0017` — **PASS**
2. Seed user + branch — **PASS**
3. `pg_dump` (~87 KB) — **PASS**
4. Set `access_state.bootstrapped=true`, `alembic downgrade` ke `20261114_0010` — **BLOCKED** `RuntimeError: Settings is in use…` (DDL transaksional; jangan andalkan downgrade Live)
5. Restore dari dump — **PASS** (`version=20261120_0017`, seed user/branch utuh)
6. Drop DB disposable — **PASS**
7. Live: **tidak** disentuh

Artifact dump contoh putaran sebelumnya: `/tmp/epv3_mig_reh_b436c09f21_test.sql`.

---

## 7. Negative authorization (enforced disposable)

| Kasus | Hasil |
|---|---|
| Tanpa grant → GET job | 403 `Capability denied: job.read` |
| Wrong branch | 403 `Resource scope denied` |
| Designer payment bypass | 403 |
| Helper ≠ Screener tanpa grant | ditolak (matrix HTTP packs) |
| Operator ≠ POD | ditolak |
| Driver ≠ Output | ditolak |
| User inactive | denied |
| Direktur Full Access + audit sensitif | PASS (design/payment bypass + status) |

Bukti browser enforced: `/tmp/epv3-authz4-enf-browser2.log` — **14/14 PASS_MUTATION**, `authMode=enforced`.

---

## 8. Browser E2E

| Suite | Hasil |
|---|---|
| Six-role (legacy API :8012) | **PASS** `ok=true`, 6× `PASS_CLICK_NO_MUTATE` + deny-probe bypass 403 (retry setelah race login cold-start) |
| Enforced browser | **14/14 PASS_MUTATION** |
| Permission-deny probes | 403 pada NoGrant / WrongBranch / Designer bypass |

Catatan P2: cold-start seed bisa `login_failed` sekali; ulang setelah API siap → hijau.

---

## 9. Regresi putaran 4

| Suite | Hasil |
|---|---|
| Authorization | **222 PASS** |
| Production | **300 PASS** |
| Accurate Gateway fixture | **159 PASS** |
| Frontend Vitest | **225 PASS** |
| Frontend build | **PASS** |
| `test_inventory_missing_credential` | **PASS** (setelah fix ORM) |
| `git diff --check` | **PASS** |
| Live Accurate / Live enforced | **BLOCKED** (disengaja) |

---

## 10. Perubahan lokal (WIP, belum commit)

| File | Perubahan |
|---|---|
| `backend/app/authorization/inventory.py` | Missing `AccountCredential` → blocking cutover + ringkasan count |
| `backend/tests/authorization/test_inventory_missing_credential.py` | Tes isolasi |

---

## 11. P0 / P1 / P2 / BLOCKED

| ID | Item | Prioritas |
|---|---|---|
| AUTH-INV-01 | Missing credential memblokir cutover review | **P0 fixed WIP** |
| F3-037 | Enforced Live tanpa persetujuan Direktur | **BLOCKED P0** |
| AUTH-GRANT-01 | Grant manual seluruh operator sebelum aktivasi | **P0 Owner** |
| AUTH-FLAT-01 | OR-bundle legacy sensitif bila tetap legacy lama | **P1** |
| AUTH-E2E-01 | Race login six-role cold-start | **P2** |
| ACC-04/05 | Accurate SJ list-all / credential VM | **BLOCKED** (di luar authz) |

---

## 12. Keputusan yang memerlukan Direktur

1. Menyetujui aktivasi `V3_WORKFLOW_AUTHORIZATION=enforced` di lingkungan non-test (isi `V3_WORKFLOW_ENFORCED_APPROVAL_REF`).
2. Menyetujui paket grant per jabatan + cabang sebelum cutover (tanpa auto-import).
3. Menyetujui window backup/restore operasional (bukan alembic downgrade).
4. Menyetujui merge/deploy terkait (PR #15 vs HOLD PR #14) — di luar wewenang agent.

---

## 13. Verdict

**READY FOR STAGING** — audit, tes enforced disposable, migration rehearsal restore, dan regresi lokal hijau.

**NOT READY FOR LIVE APPROVAL** / **NOT READY** untuk menyalakan enforced Production sampai keputusan Direktur + grant manual + inventory cutover clear di target yang disetujui.
