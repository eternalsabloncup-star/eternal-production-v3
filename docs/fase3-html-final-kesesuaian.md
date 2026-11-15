# Matriks Kesesuaian HTML Final — Eternal Production V3 (Fase 3)

**Diperbarui:** 2026-11-16 02:20 WIB (Asia/Jakarta)  
**Repository:** `eternalsabloncup-star/eternal-production-v3`  
**Branch:** `cursor/epv3-production-schedule-83bf`  
**Checkpoint:** Fase 3 **PARSIAL** (bukan COMPLETE)  
**Worktree:** `/tmp/epv3-fase1b-wt`  
**PR #15:** OPEN · **PR #14:** HOLD · **Otorisasi:** `legacy` (enforced tidak aktif)  
**Dokumen terkait:** `fase3-master-cabang-rancangan.md`, `fase3-pr14-authz-dependensi.md`

Acuan produk: Handoff Final + sandbox spreadsheet. Acuan teknis: Backend V3 + PostgreSQL.  
Status `SELESAI*` = terbukti uji (bukan Live apply). Klaim Fase 3 COMPLETE / 100% **dilarang**.

---

## Ringkasan kuantitatif

| Kategori | Jumlah fitur matriks | Keterangan |
|----------|---------------------|------------|
| SELESAI* (terverifikasi lokal) | **18** | API/FE/tes/smoke fokus |
| PARSIAL | **16** | Ada kode + bukti terbatas; belum Full Final |
| BLOCKED / BELUM ADA | **5** | Kontrak/keputusan/HOLD |
| **Total fitur dilacak** | **39** | |
| **% kesesuaian terverifikasi** | **≈ 46%** (18/39) | SELESAI* saja |
| **% SELESAI* + PARSIAL bermanfaat** | **≈ 87%** (34/39) | belum 100% |

Jangan dibaca sebagai “46% produk selesai” semata — banyak PARSIAL sudah usable Live-path, tetapi belum setara HTML Final penuh.

| Modul | Status | Bukti utama |
|-------|--------|-------------|
| Approval Payment Settings | SELESAI* | API+audit+tes; migrasi 0016 disposable PASS |
| Monitoring Penerimaan | SELESAI*→tinggi | Fase 2 + UNKNOWN/`approval_source`/`can_bypass` |
| Jadwal Pengiriman SJ-centric | PARSIAL→tinggi | 1 baris/SJ + SO-link enrich; list-all Accurate **BLOCKED** |
| Master Pengaturan | PARSIAL | Payment SoT + Cabang RO jujur + Mesin PG; Users/Grup HOLD #14 |
| Tugas Tim 6 role | PARSIAL→tinggi | Derive + FE defs; smoke roles=6; spreadsheet Final browser belum penuh |
| Inbox / Jadwal Produksi / Kontrol | PARSIAL | Regresi ada; parity Final penuh belum |
| Browser smoke gap-closure | SELESAI* (terbatas) | `scripts/fase3_gap_browser_smoke.mjs` PASS pada test DB |
| Accurate SJ inventaris lengkap | BLOCKED | Gateway **tidak** punya list-all |
| Mode Live dummy | SELESAI* (guard) | Preview terpisah |

---

## 1. Inbox Accurate

| Fitur Final | FE V3 | Endpoint | Store | Perm | Status | Bukti |
|-------------|-------|----------|-------|------|--------|-------|
| Daftar/cari/filter/pagination | live-runtime inbox | `GET /production/inbox` | Accurate RO | inbox/job read | PARSIAL | smoke inbox 403 tanpa gateway; tes inbox sebelumnya |
| Detail + qty/item | drawer | order detail | Accurate | read | PARSIAL | — |
| Tidak auto-create job on view | guard | ensure_job eksplisit | PG | job.create | SELESAI* | live-runtime + smoke `v3EnsureJob` |
| PO tanpa job | unsynced notice | ops unsynced | Accurate | read | PARSIAL | payment monitor |

## 2. Monitoring Penerimaan

| Fitur | Status | Endpoint | Bukti |
|-------|--------|----------|-------|
| Daftar per PO + filter + page | SELESAI* | `GET .../payment/receipts` | Fase 2 + smoke 200 |
| Gate vs finansial UNKNOWN | SELESAI* | monitor fields | unit + FE |
| Bypass + settings flag | SELESAI* | POST bypass + settings | Fase 2/3 + marker bypass |
| Invoice Lunas palsu | SELESAI* (dicegah) | null/UNKNOWN | unit |

## 3. Jadwal Produksi & Kontrol Qty

| Fitur | Status | Catatan |
|-------|--------|---------|
| Cetak-only schedule API | PARSIAL | `/production/ops/schedule` smoke 200 |
| Multi-op / HOLD / filter / kolom | PARSIAL | sheet + resize di production.html |
| KPI qty horizontal | PARSIAL | schedule overview strip |
| Browser Final parity penuh | PARSIAL | nav terlihat di smoke; interaksi Final belum |

## 4. Tugas Tim (6 role)

| Role | Backend | FE card/action | Status | Bukti |
|------|---------|----------------|--------|-------|
| Kepala Produksi | schedule tasks | Atur jadwal | PARSIAL→tinggi | derive + smoke roles |
| Designer | design upload/approve | panel + API | PARSIAL→tinggi | sama |
| Screener | prep screener | prep API | PARSIAL→tinggi | sama |
| Helper | prep/packing | prep/packing | PARSIAL→tinggi | sama |
| Operator | output/sample | sample approve API | PARSIAL→tinggi | sama |
| Driver | loading/delivery | FE defs + Kerjakan | PARSIAL→tinggi | teamTasks.ts + smoke |
| No fiktif / no duplikat | derived from job | filter visible | PARSIAL→tinggi | mapOfficialTasks + engine |
| Filter header / resize / sticky / kolom | sheet UI production.html | — | PARSIAL | kode ada; browser Final per-kolom belum |
| Tombol Kerjakan + Approval Sampel | verbs + sample_approve | API | PARSIAL→tinggi | FE defs + endpoints |

## 5. Jadwal Pengiriman (SJ) — Accurate inventory

### Audit kontrak Gateway

| Data yang diminta | Tersedia? | Sumber |
|-------------------|-----------|--------|
| Daftar seluruh Surat Jalan | **TIDAK** | Hanya `GET /delivery-notes/{id}` — **tidak ada list-all** |
| ID & nomor SJ | Ya (by id) | GET delivery-note |
| Nomor PO/SO | Ya (via job / note) | Loading V3 + note fields |
| Pelanggan | Ya | note.customer / job |
| Tanggal pengiriman | Parsial | plan/POD V3; bukan inventaris Accurate penuh |
| Alamat / Zona / Ekspedisi / Catatan | Opsional passthrough | normalize DN — **null jika Accurate kosong** (tidak dikarang) |
| Item & qty | Ya (by id) | `line_items` |
| Multi-item 1 baris/SJ | Ya | `list_deliveries` dedupe `accurate_sj_id` |

**Inventaris V3 saat ini — COVERAGE TERBATAS:** baris Loading PostgreSQL **plus** opsional `include_accurate_links=true` (SO `links.delivery_note_ids`, read-only, dedupe). **Bukan** inventaris SJ lengkap Accurate. Jangan klaim list-all.

| Fitur Final | Implementasi V3 | Status | Bukti |
|-------------|-----------------|--------|-------|
| 1 baris / SJ canonical | dedupe `accurate_sj_id` | SELESAI* | `test_delivery_sj_centric_fase3` |
| Multi-item detail | `items[]` + `GET /ops/deliveries/{sj_id}` | SELESAI* | sama + gateway pada detail |
| Enrich SO-link tanpa duplikat | `_append_sj_from_accurate_so_links` | SELESAI* | `test_delivery_accurate_links_fase3` |
| Alamat/zona/ekspedisi jika Accurate isi | normalize passthrough | SELESAI* | gateway normalize + link test |
| Field kosong = BELUM TERSEDIA | `field_availability` | SELESAI* | jujur |
| Accurate SJ list-all | **tidak ada endpoint** | **BLOCKED** | `coverage.accurate_sj_list_endpoint=null` |
| Column resize/sticky Final penuh | scroll + resize shared | PARSIAL | belum Final spreadsheet shipping |

## 6. Pengaturan

| Menu | SoT | SIMPAN→BACA→PERM→AUDIT | Status |
|------|-----|------------------------|--------|
| Approval Payment | PG `payment_approval_settings` (+audit) | Ya | SELESAI* |
| Inventaris transparan | UI katalog | N/A (read-only status) | SELESAI* |
| Cabang efektif | user grants + job branches | **Read-only** (`can_manage=false`) | SELESAI* (jujur, bukan fake save) |
| Master Cabang editable | — | Butuh skema baru + keputusan Direktur | **BLOCKED / BELUM ADA** |
| Master Mesin | PG `production_machines` | Ya via `/ops/machines` + summary settings | SELESAI*→tinggi |
| Pengguna/Grup/Grant/Workflow enforced | Settings API / PR #14 | AccessAudit | **PARSIAL (HOLD #14)** |
| Urgent/Buffer/Payroll demo | localStorage | Label demo non-SoT | PARSIAL (eksplisit) |
| Bypass default instalasi baru | `bypass_enabled=false` | Ber-audit | SELESAI* |

**Integrasi aman tanpa merge PR #14:** tetap `legacy`; panel Users/Grup/Grant penuh dari #14 jangan di-merge; Payment/Cabang RO/Mesin jalan independen. Enforced **tidak** diaktifkan.

## 7. Navigasi / UX

| Aspek | Status | Bukti |
|-------|--------|-------|
| Sidebar menu set | PARSIAL | smoke: 12 label nav (nama beda vs Final) |
| Preview vs Live | SELESAI* | guard |
| Reskin HTML Final penuh | BELUM ADA | disengaja |

## Mapping Handoff → V3

| Handoff | V3 |
|---------|-----|
| `/api/v3/delivery-schedule` | `GET /api/v1/production/ops/deliveries?include_accurate_links=true` (+ `/{sj_id}`) |
| `/api/v3/settings/payment-approval` | `GET/PUT /api/v1/production/settings/payment-approval` |
| Cabang sandbox | `GET /api/v1/production/settings/branches` (RO) |
| Mesin | `GET .../settings/machines-summary` + `/ops/machines` |
| `/api/v3/payment-monitor` | `GET /api/v1/production/jobs/payment/receipts` |
| `/api/v3/tasks` | `GET/POST .../production/jobs/tasks` |

## Dependensi PR #14

ScopedGrant enforced, panel grant penuh, capability catalog cutover → **HOLD**. Legacy Direktur/JSONB tetap. Jangan merge #14 / jangan `enforced`.

## Bukti tes (sesi gap closure)

| Lapisan | Hasil |
|---------|-------|
| Backend focused (settings+delivery+links) | **PASS** (9) |
| Migrasi 0016 disposable | **PASS** |
| Authz regression | **PASS** (33) |
| Frontend vitest (payment/delivery/teamRoles) | **PASS** |
| Browser+API smoke `fase3_gap_browser_smoke.mjs` | **PASS** (`ok=true`; 6 roles; bypass=false; sj_list=null; cabang can_manage=false) |
| Inbox Accurate live tanpa gateway | **403** (diharapkan di env smoke tanpa gateway token) |

## Inventaris 39 fitur (ringkas)

Lihat tabel per-modul di atas. Agregat: **18 SELESAI\* · 16 PARSIAL · 5 BLOCKED/BELUM**.  
Rincian BLOCKED/BELUM: (1) Accurate SJ list-all, (2) Master Cabang writable, (3) Users/Grup/Grant #14, (4) Enforced workflow cutover, (5) Reskin HTML Final penuh.

## Keputusan Direktur (tersisa)

1. Apply migrasi `0016` ke staging disposable / Live? (**belum**)
2. Kontrak Accurate: endpoint **list SJ**?
3. Setujui rancangan Master Cabang (`fase3-master-cabang-rancangan.md`)?
4. Urutan integrasi PR #14 setelah checkpoint #15?
5. Loading+SO-link cukup operasional sampai list-all ada?

## Lampiran

Handoff Final + sandbox. Backend V3 SoT; `server.py` Handoff tidak digabung. Smoke hanya DB `eternal_production_v3_test`.
