# Matriks Kesesuaian HTML Final — Eternal Production V3 (Fase 3)

**Diperbarui:** 2026-11-16 (Asia/Jakarta)
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**HEAD committed:** `d110f5fb3b63605ca4e0ecada36c701cc732f6da`
**Checkpoint:** sticky Output idempotency + enforced browser harness (PR #15)
**Checkpoint:** Fase 3 **PARSIAL** (bukan COMPLETE); Production **legacy**; target Final = **enforced**
**PR #15:** OPEN · **PR #14:** HOLD
**Dokumen:** `fase3-master-cabang-rancangan.md`, `fase3-e2e-enam-role-hasil.md`, `fase3-permission-role-matrix.md`

Acuan: Handoff Final + Backend V3 PostgreSQL. Klaim COMPLETE / 100% **dilarang**.

---

## Ringkasan kuantitatif

| Kategori | Jumlah | Keterangan |
|----------|--------|------------|
| SELESAI* | **25** | Tugas Tim disposable diperkuat (legacy 11/11 + enforced 14/14); hitungan modul Final tidak naik karena Live enforced tetap BLOCKED |
| PARSIAL | **11** | tidak ada modul PARSIAL yang ditutup penuh putaran ini |
| BLOCKED / BELUM ADA | **3** | SJ list-all, enforced Live, reskin penuh |
| **Total** | **39** | |
| **% SELESAI*** | **≈ 64%** (25/39) | |
| **% SELESAI*+PARSIAL** | **≈ 92%** (36/39) | |

| Modul | Status | Bukti |
|-------|--------|-------|
| Approval Payment Settings | SELESAI* | API+audit+tes |
| Monitoring Penerimaan | SELESAI* | sticky/sort + smoke |
| Jadwal Produksi API cetak-only | SELESAI* | `test_production_schedule_list` + smoke |
| Jadwal sheet multi-op / HOLD / filter | PARSIAL→tinggi | smoke buckets + sticky; parity kolom Final belum penuh |
| Kontrol qty | SELESAI* | KPI + Status Kerja |
| Jadwal Pengiriman SJ-centric | PARSIAL→tinggi | FE+API; Accurate list-all BLOCKED |
| Users/Grup/Grant/Audit + packs | SELESAI* | sandbox enforced + browser enforced ScopedGrant seed |
| Master Pengaturan agregat | PARSIAL→tinggi | Cabang writable lokal; Live apply BLOCKED |
| Master Cabang writable | SELESAI* (lokal) | migrasi 0017 + CRUD + UI + tes; Live apply BLOCKED |
| Tugas Tim 6 role | SELESAI* (disposable) | API 30/30; browser legacy 11/11; **browser enforced 14/14** + sticky Output idem (1 event / 409 replay); Live Accurate + Live enforced tetap terpisah |
| Inbox Accurate | PARSIAL | 403 tanpa gateway |
| Accurate SJ list-all | BLOCKED | gateway by-id only |
| Enforced Production | BLOCKED | approval + grant Live — disposable enforced E2E **bukan** aktivasi Production |
| Reskin HTML Final penuh | BLOCKED | disengaja |
| Browser smoke gap | SELESAI* / jalankan ulang | cabang baca-saja untuk kepala; writable untuk Direktur |

---

## Master Cabang

**Implementasi CRUD lokal: YA** — Alembic `20261120_0017`, API POST/PATCH, audit, UI Direktur.
**Live migration / seed: BLOCKED** sampai keputusan apply.
Kode immutable; soft-deactivate; tanpa auto-seed/auto-grant; `settings.branch.manage` Director-only.

## Accurate SJ

Kontrak resmi: `GET /delivery-notes/{id}` saja.
V3: Loading PG + `include_accurate_links` · **COVERAGE TERBATAS** · `accurate_sj_list_endpoint=null`.
Kebutuhan kontrak tambahan: endpoint list-all SJ Accurate (belum tersedia) — jangan dikarang.

## Enforced

Fondasi terintegrasi di #15. Uji sandbox PASS (termasuk deny branch.manage non-Direktur). Production **legacy**. Auto-import OFF.

## Bukti tes sesi Master Cabang (lokal, NO COMMIT)

| Lapisan | Hasil |
|---------|-------|
| Migrasi 0017 up/down disposable | PASS |
| CRUD + referential + orphan | PASS |
| Permission Direktur/karyawan legacy | PASS |
| Enforced packs + grant reject | PASS |
| FE Vitest | PASS (221) |
| FE build | PASS |
| Backend production+authz focused | PASS (300) |
| Browser smoke | lihat laporan run |
| `git diff --check` | PASS setelah koreksi doc |
| E2E API 6 role mutasi | PASS (30 skenario) |
| E2E browser 6 role klik | PASS_CLICK_NO_MUTATE (bukan PASS_MUTATE) |

### Keputusan masih diperlukan

1. Apply migrasi Master Cabang ke staging/Live?
2. Accurate list SJ?
3. Cutover enforced Production?
4. Grant manual Live per role pack?
5. Reskin Final penuh?
