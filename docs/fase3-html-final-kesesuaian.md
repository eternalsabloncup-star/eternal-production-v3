# Matriks Kesesuaian HTML Final — Eternal Production V3 (Fase 3)

**Diperbarui:** 2026-11-16 (Asia/Jakarta)
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**HEAD committed:** `5528bb291e573ce426ab89bd02e394cab9a1f72f`
**WIP lokal (NO COMMIT):** sticky sheet Jadwal/Tugas/Inbox + inventaris F3-001…039
**Checkpoint:** Fase 3 **PARSIAL** (bukan COMPLETE); Production **legacy**; target Final = **enforced**
**PR #15:** OPEN · **PR #14:** HOLD
**Inventaris atomik:** `docs/fase3-inventaris-39-fitur.md`

Acuan: Handoff Final (`/tmp/epv3-fase3-handoff/`) + Backend V3 PostgreSQL. Sandbox V22 pelengkap interaksi. Klaim COMPLETE / 100% **dilarang**.

---

## Ringkasan kuantitatif

| Kategori | Baseline historis | Audit ber-ID (putaran ini) |
|----------|-------------------|----------------------------|
| SELESAI* | **25** | **29** |
| PARSIAL | **11** | **7** |
| BLOCKED | **3** | **3** |
| **Total** | **39** | **39** |

Baseline historis **tidak diubah** tanpa keputusan Owner. Selisih dijelaskan di inventaris (pemecahan ID + sticky Jadwal/Tugas).

| Modul | Status | Bukti |
|-------|--------|-------|
| Approval Payment Settings | SELESAI* | API+audit+tes |
| Monitoring Penerimaan | SELESAI* | sticky/sort + smoke |
| Jadwal Produksi API cetak-only | SELESAI* | schedule API + smoke |
| Jadwal sticky/resize/visibility | SELESAI* | `data-v3-sticky=id,name` + vitest |
| Jadwal multi-op / HOLD / parity kolom Final | PARSIAL | buckets HOLD ada; kolom Final penuh belum |
| Kontrol qty | SELESAI* | KPI + Status Kerja |
| Jadwal Pengiriman SJ-centric | PARSIAL→tinggi | FE+API; Accurate list-all BLOCKED; COVERAGE TERBATAS |
| Users/Grup/Grant/Audit + packs | SELESAI* | sandbox enforced + browser enforced |
| Master Pengaturan agregat | PARSIAL | Cabang writable lokal; Live apply BLOCKED |
| Master Cabang writable | SELESAI* (lokal) | migrasi 0017 + CRUD + UI + tes |
| Tugas Tim 6 role + sticky sheet | SELESAI* (disposable) | E2E + sticky so,customer |
| Inbox Accurate | PARSIAL | 403 tanpa gateway |
| Accurate SJ list-all | BLOCKED | gateway by-id only |
| Enforced Production | BLOCKED | approval + grant Live |
| Reskin HTML Final penuh | BLOCKED | aset di `/tmp`, belum di repo |
| Layout nav vs Final | PARSIAL | edge toggle OK; label nav beda |

---

## Sumber HTML

| Paket | Path | Peran |
|-------|------|-------|
| Handoff Final | `/tmp/epv3-fase3-handoff/` | Acuan visual + kontrak integrasi |
| Sandbox V22 | `/tmp/epv3-fase3-sandbox/` | Referensi spreadsheet/filter/Tugas |

Konflik desain dicatat di inventaris; Backend PG = SoT data; kontrak bisnis tidak diganti diam-diam.

## Accurate SJ

Kontrak resmi: `GET /delivery-notes/{id}` saja.
V3: Loading PG + SO-link · **COVERAGE TERBATAS** · `accurate_sj_list_endpoint=null`.

## Enforced

Fondasi + browser disposable PASS. Production **legacy**. Auto-import OFF.

## Putaran implementasi (lokal)

1. `production.html`: `data-v3-sticky` + `data-v3-colw` pada Jadwal (`id,name`), Tugas (`so,customer`), Inbox (`id,name`).
2. CSS sticky Tugas Tim untuk kolom `so` + `customer`.
3. `v161StickyKeys` mengenali `task-sheet` / `v3-schedule-sheet`.
4. Smoke sticky Jadwal diperjelas; vitest `scheduleStickyParity.test.ts`.
5. Dokumen inventaris F3-001…039.

## Keputusan masih diperlukan

1. Apply migrasi Master Cabang ke staging/Live?
2. Accurate list SJ?
3. Cutover enforced Production?
4. Grant manual Live per role pack?
5. Salin aset HTML Final ke repo + prioritas reskin?
6. Ganti angka laporan baseline 25/11/3 → audit 29/7/3?
