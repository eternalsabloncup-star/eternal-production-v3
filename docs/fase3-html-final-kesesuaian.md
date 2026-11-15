# Matriks Kesesuaian HTML Final — Eternal Production V3 (Fase 3)

**Diperbarui:** 2026-11-16 03:20 WIB (Asia/Jakarta)
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**HEAD baseline (committed):** `b58d00017a9bbd7cc688621fb752fd4c36e9ddf8`
**Worktree lokal (belum commit):** `/tmp/epv3-fase1b-wt` — UI Fase 3 + authz #14 + finalisasi privilege/role packs
**Checkpoint:** Fase 3 authorization completion **PARSIAL→tinggi** (bukan COMPLETE); Production tetap **legacy**
**PR #15:** OPEN · **PR #14:** HOLD · **Otorisasi Production:** `legacy`
**Dokumen terkait:** `fase3-master-cabang-rancangan.md`, `fase3-permission-role-matrix.md`, `fase3-pr14-authz-dependensi.md`, `authorization-enforced-cutover.md`

Acuan produk: Handoff Final + sandbox spreadsheet. Acuan teknis: Backend V3 + PostgreSQL.
Status `SELESAI*` = terbukti uji (bukan Live apply). Klaim Fase 3 COMPLETE / 100% **dilarang**.

---

## Ringkasan kuantitatif

| Kategori | Jumlah fitur matriks | Keterangan |
|----------|---------------------|------------|
| SELESAI* (terverifikasi lokal) | **22** | +1 paket grant 6 role + matriks privilege (sandbox enforced) |
| PARSIAL | **13** | −1 (Tugas Tim authz packs naik; FE E2E mutasi tetap parsial di modul lain) |
| BLOCKED / BELUM ADA | **4** | Master Cabang writable, SJ list-all, enforced Live, reskin |
| **Total fitur dilacak** | **39** | Denominator tetap |
| **% kesesuaian terverifikasi** | **≈ 56%** (22/39) | SELESAI* saja |
| **% SELESAI* + PARSIAL bermanfaat** | **≈ 90%** (35/39) | belum 100% |

Promosi SELESAI* hanya dengan bukti tes (bukan aktivasi Production).

| Modul | Status | Bukti utama |
|-------|--------|-------------|
| Approval Payment Settings | SELESAI* | API+audit+tes; mapped `settings.payment_approval.*` |
| Monitoring Penerimaan | SELESAI* | sticky/sort/col + smoke |
| Jadwal Pengiriman SJ-centric | PARSIAL→tinggi | FE parity SELESAI*; Accurate list-all **BLOCKED** |
| Users / Grup / ScopedGrant / Audit | SELESAI* | Settings API + panel + AccessAudit; auto-import NONAKTIF |
| Authorization status / startup gate | SELESAI* (sandbox) | `mode.py` + role packs + privilege_options; Production legacy |
| Paket grant 6 role + 3 privilege | SELESAI* (sandbox) | `role_packs.py` + `test_fase3_enforced_role_packs` HTTP 200/403 |
| Master Pengaturan (agregat) | PARSIAL→tinggi | Users SELESAI*; Cabang writable / enforced Live masih BLOCKED |
| Tugas Tim 6 role | PARSIAL→tinggi | Verb Kerjakan + packs backend; mutasi E2E FE terbatas |
| Inbox / Jadwal Produksi | PARSIAL | Inbox 403 tanpa gateway; KPI strip SELESAI* |
| Kontrol qty horizontal | SELESAI* | Summary + Status Kerja |
| Browser smoke gap-closure | SELESAI* | interaktif `ok=true` |
| Accurate SJ inventaris lengkap | BLOCKED | tidak ada list-all |
| Enforced cutover Production | BLOCKED | butuh approval ref + keputusan Direktur |
| Mode Live dummy | SELESAI* (guard) | Preview terpisah |

---

## 1. Inbox Accurate

| Fitur Final | FE V3 | Endpoint | Store | Perm | Status | Bukti |
|-------------|-------|----------|-------|------|--------|-------|
| Daftar/cari/filter/pagination | live-runtime inbox | `GET /production/inbox` | Accurate RO | inbox/job read | PARSIAL | smoke inbox 403 tanpa gateway |
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
| Sticky/sort/col/scroll tabel | SELESAI* | `v3-payment-sheet` | smoke: sticky `so,customer`, sort, scroll |

## 3. Jadwal Produksi & Kontrol Qty

| Fitur | Status | Catatan |
|-------|--------|---------|
| Cetak-only schedule API | PARSIAL | `/production/ops/schedule` smoke 200 |
| Multi-op / HOLD / filter / kolom | PARSIAL | sheet + resize di production.html |
| KPI qty horizontal + Status Kerja | SELESAI* | summary server anti double-count; smoke `v3-kontrol-qty` / labels |
| Browser Final parity penuh sheet | PARSIAL | overview+search OK; parity kolom Final penuh belum |

## 4. Tugas Tim (6 role)

| Role | Backend | FE card/action | Status | Bukti |
|------|---------|----------------|--------|-------|
| Kepala Produksi | schedule tasks | Atur jadwal | PARSIAL→tinggi | derive + role filter smoke |
| Designer | design upload/approve | panel + API | PARSIAL→tinggi | sama |
| Screener | prep screener | prep API | PARSIAL→tinggi | sama |
| Helper | prep/packing | prep/packing | PARSIAL→tinggi | roles API Helper+Driver |
| Operator | output/sample | sample approve API | PARSIAL→tinggi | focus map sample_approve |
| Driver | loading/delivery | Kerjakan loading/pengiriman | PARSIAL→tinggi | verb resmi + smoke role Driver |
| No fiktif / no duplikat | derived from job | filter visible | PARSIAL→tinggi | mapOfficialTasks; Live tanpa FLOW31 |
| Filter header / resize / sticky / kolom | sheet UI | — | PARSIAL→tinggi | smoke: filterMenu + search + 6 role |
| Tombol Kerjakan + Approval Sampel | verbs + sample_approve | API + inFlight lock | PARSIAL→tinggi | `taskActionLabel` + mutate lock; tombol tidak muncul tanpa job official |

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
| Sort / sticky / col toggle / pagination / empty / scroll internal | `v3-delivery-sheet` | SELESAI* | smoke interaktif: sort↑, colToggle, sticky sj,so, searchEmpty |

## 6. Pengaturan

| Menu | SoT | SIMPAN→BACA→PERM→AUDIT | Status |
|------|-----|------------------------|--------|
| Approval Payment | PG `payment_approval_settings` (+audit) | Ya | SELESAI* |
| Inventaris transparan | UI katalog | N/A (read-only status) | SELESAI* |
| Cabang efektif | user grants + job branches | **Read-only** (`can_manage=false`) | SELESAI* (jujur, bukan fake save) |
| Master Cabang editable | — | Butuh skema baru + keputusan Direktur | **BLOCKED / BELUM ADA** |
| Master Mesin | PG `production_machines` | Ya via `/ops/machines` + summary settings | SELESAI*→tinggi |
| Pengguna/Grup/ScopedGrant/AccessAudit | Settings API (integrasi selektif #14) | Ya (manual, no auto-import) | SELESAI* |
| Authorization-status + startup gate | `mode.py` / owner_policy / role_packs | Baca status + packs; tidak mengaktifkan | SELESAI* (sandbox) |
| Paket grant jabatan (6 role) | `role_packs.py` + Settings panel | Panduan saja; grant manual | SELESAI* (sandbox HTTP) |
| Tiga privilege review → packs | `PRIVILEGE_OPTIONS` | mapped_manual_packs; no auto-import | SELESAI* (mapping); Live apply BLOCKED |
| Workflow enforced Production | env + approval ref | — | **BLOCKED** (tidak diaktifkan) |
| Urgent/Buffer/Payroll demo | localStorage | Label demo non-SoT | PARSIAL (eksplisit) |
| Bypass default instalasi baru | `bypass_enabled=false` | Ber-audit | SELESAI* |

**Integrasi selektif tanpa merge PR #14:** Users/Grup/Grant + gate + status terpasang di worktree #15. Production tetap `legacy`. Enforced **tidak** diaktifkan di VPS.

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

Kode gate/status/panel diintegrasikan selektif (lihat `fase3-pr14-authz-dependensi.md`). Merge Git #14 **tidak** dilakukan. Manifest enforced: **70** endpoint (WORKFLOW+INBOX+PAYROLL+SETTINGS_PROD). Production tetap `legacy`.

## Bukti tes (sesi authorization completion — lokal, NO COMMIT)

| Lapisan | Hasil |
|---------|-------|
| Frontend Vitest lengkap | **PASS** 39 files / **218** tests (+1 status packs) |
| Frontend build | **PASS** |
| Backend enforced role packs | **PASS** 5/5 (`test_fase3_enforced_role_packs`) |
| Backend authz focused (gate+workflow+foundation+role) | **PASS** **137** |
| Backend payment/workflow business | **PASS** 9 |
| Browser smoke interaktif (sesi UI sebelumnya) | **PASS** (`ok=true`) — tidak diulang sesi ini |
| `git diff --check` | **PASS** |
| Default Production mode | **legacy** (approval ref kosong; enforced hanya APP_ENV=test) |

### Bukti browser per fitur (interaktif)

| Fitur | Bukti smoke |
|-------|-------------|
| Coverage SJ | `#v3-del-coverage` berisi COVERAGE TERBATAS |
| Sticky SJ/SO | `data-v3-sticky=sj,so` |
| Sort kolom | klik Pelanggan → `Pelanggan ↑` |
| Toggle kolom | checkbox Alamat mengubah state |
| Search + empty | query fiktif → empty state tabel |
| Scroll internal | `.v3-delivery-scroll`; page body tidak overflow-x |
| Tugas Tim 6 role | select berisi 6 role Final |
| Filter header tugas | `#task-filter-menu` terbuka |
| Payment sticky/sort | sticky `so,customer`; sort Pelanggan |
| Kontrol qty + Status Kerja | `#v3-kontrol-qty` / labels + status |
| Pagination SJ | pager `del-prev`/`del-next` di DOM |

## Inventaris 39 fitur (ringkas)

Agregat: **22 SELESAI\* · 13 PARSIAL · 4 BLOCKED/BELUM**.
Rincian BLOCKED/BELUM: (1) Accurate SJ list-all, (2) Master Cabang writable, (3) Enforced cutover Production, (4) Reskin HTML Final penuh.

## Keputusan Direktur (tersisa)

1. Apply migrasi `0016` ke staging disposable / Live? (**belum**)
2. Kontrak Accurate: endpoint **list SJ**?
3. Setujui rancangan Master Cabang (`fase3-master-cabang-rancangan.md`) + skema/migrasi?
4. Cutover enforced Production: inventory clear + grant manual + `V3_WORKFLOW_ENFORCED_APPROVAL_REF`?
5. Loading+SO-link cukup operasional sampai list-all ada?
6. Di Live: grup mana memakai paket mana (6 role packs sudah siap; **tidak** auto-apply)?
7. Apakah `settings.payment_approval.*` / `settings.branch.read` tetap Director-only, atau boleh grantable (perlu ubah evaluator modul settings)?

## Lampiran

Handoff Final + sandbox. Backend V3 SoT; `server.py` Handoff tidak digabung. Smoke hanya DB `eternal_production_v3_test`.
Perubahan sesi ini **belum di-commit / push** sesuai batasan Owner.
