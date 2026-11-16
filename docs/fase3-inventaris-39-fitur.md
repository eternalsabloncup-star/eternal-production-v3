# Inventaris 39 Fitur — Eternal Production V3 (Fase 3)

**Diperbarui:** 2026-11-16 (Asia/Jakarta)
**HEAD committed:** `5528bb291e573ce426ab89bd02e394cab9a1f72f`
**WIP lokal (NO COMMIT):** Reskin Iter1 Jadwal+Kontrol (token Handoff Final); sticky/smoke checkpoint sebelumnya sudah di-push `ac6be39`
**PR #15:** OPEN · **PR #14:** HOLD · Production authz: **legacy**
**Checkpoint smoke (committed):** empty/populated/sticky PASS · **Reskin Iter1 browser:** Jadwal KPI Final cards PASS (1440 + 1366) — F3-039 tetap BLOCKED

## Cara baca

- Status hanya: `SELESAI*` | `PARSIAL` | `BLOCKED`.
- `SELESAI*` = ada bukti implementasi + bukti uji (unit/API/browser). Bukan Live apply.
- Baseline historis **25 / 11 / 3** tetap tercatat; kolom *Audit baru* boleh berbeda jika bukti berubah.
- Sumber: Handoff Final (`/tmp/epv3-fase3-handoff/`) utama; Sandbox V22 pelengkap; Backend PostgreSQL V3 SoT data.

## Baseline historis vs audit baru

| | Baseline historis (dokumen tanpa ID) | Audit baru ber-ID F3-001…039 |
|--|--|--|
| SELESAI* | **25** | **29** |
| PARSIAL | **11** | **7** |
| BLOCKED | **3** | **3** |
| Total | **39** | **39** |

**Selisih:** angka baseline **tidak diganti**. Audit ber-ID memecah modul kasar dan mempromosikan sticky Jadwal/Tugas (F3-012, F3-021) setelah atribut `data-v3-sticky` + CSS + vitest. BLOCKED tetap: SJ list-all, enforced Live, reskin penuh.

## Matriks F3-001 … F3-039

| ID | Nama | Modul | Sumber | UI | Aksi | Endpoint / store | Perm | Status historis | Status audit | Bukti impl | Bukti uji | Gap | Dep | Prio |
|----|------|-------|--------|----|------|------------------|------|-----------------|--------------|------------|-----------|-----|-----|------|
| F3-001 | Inbox daftar PO | Inbox | Handoff | sheet Inbox | baca daftar | `GET …/inbox` · Accurate RO | inbox/job read | PARSIAL | PARSIAL | live-runtime + production.html | smoke inbox 403 tanpa gateway | Gateway/session | Accurate | P1 |
| F3-002 | Inbox search/filter/sort/pagination | Inbox | Handoff+V22 | header filter | filter halaman | client + inbox API | read | PARSIAL | PARSIAL | inboxSheetFilter | vitest filter | 403 tanpa gateway | F3-001 | P1 |
| F3-003 | Inbox detail qty/item | Inbox | Handoff | drawer | buka detail | order detail | read | PARSIAL | PARSIAL | inboxDetailState | unit | butuh data Accurate | F3-001 | P1 |
| F3-004 | Tidak auto-create job on view | Inbox | Kontrak | guard | ensure_job eksplisit | ensure_job | job.create | SELESAI* | SELESAI* | live-runtime | smoke `v3EnsureJob` | — | — | P1 |
| F3-005 | Monitoring daftar + filter | Penerimaan | Handoff | payment sheet | daftar PO | `…/payment/receipts` | payment read | SELESAI* | SELESAI* | live-runtime payment | smoke 200 + sheet | — | PG | P1 |
| F3-006 | Gate vs status finansial / UNKNOWN | Penerimaan | Kontrak | kolom gate | tampilkan UNKNOWN jujur | payment monitor | read | SELESAI* | SELESAI* | monitor fields | unit + FE | — | — | P1 |
| F3-007 | Pembayaran sebagian → approve gate | Penerimaan | Kontrak | status | server gate | receipts settlement | — | SELESAI* | SELESAI* | backend payment | pytest | — | — | P1 |
| F3-008 | Bypass Direktur + audit | Penerimaan | Handoff | tombol Bypass | POST bypass | `…/bypass` | payment.bypass | SELESAI* | SELESAI* | API + FE | Fase 2/3 | bypass default off | settings | P1 |
| F3-009 | Sticky/sort/col/scroll Monitoring | Penerimaan | V22/Handoff | v3-payment-sheet | spreadsheet | FE | — | SELESAI* | SELESAI* | `data-v3-sticky=so,customer` (+ empty tetap render sheet) | smoke sticky + geometry | — | — | P1 |
| F3-010 | Jadwal cetak-only API | Jadwal | Kontrak | schedule | list print lines | `…/ops/schedule` | schedule read | SELESAI* | SELESAI* | schedule API | pytest + smoke 200 | — | PG | P1 |
| F3-011 | Multi-operator / HOLD / filter header | Jadwal | Handoff+V22 | sheet + buckets | HOLD filter | schedule + FE | — | PARSIAL | PARSIAL | buckets HOLD + holdStatus | smoke buckets | parity kolom Final penuh | F3-010 | P1 |
| F3-012 | Sticky / resize / visibility / pagination Jadwal | Jadwal | Handoff | v3-schedule-sheet | spreadsheet | FE | — | PARSIAL | SELESAI* | `data-v3-sticky=id,name` + CSS | vitest + geometry smoke (scroll hold + align) | — | — | P1 |
| F3-013 | KPI Kontrol qty + Status Kerja | Kontrol | Sandbox/Handoff | `#v3-kontrol-qty` | ringkasan | schedule summary | read | SELESAI* | SELESAI* | scheduleOverview live + kartu Final Iter1 | smoke + reskin browser 1440/1366 | visual shell sidebar Final belum | F3-010 | P1 |
| F3-014 | Tugas Kepala Produksi | Tugas | Kontrak | role filter | Atur jadwal | `/tasks` | schedule | SELESAI* | SELESAI* | teamTasks + workflow | E2E + gap populated smoke | enforced Live HOLD; Inbox Accurate tetap PARSIAL | PR14 | P1 |
| F3-015 | Tugas Designer | Tugas | Kontrak | Kerjakan | upload/approve | tasks API | design | SELESAI* | SELESAI* | sama | E2E + gap populated | sama | PR14 | P1 |
| F3-016 | Tugas Screener | Tugas | Kontrak | Kerjakan | prep screen | prep API | prep | SELESAI* | SELESAI* | sama | E2E + gap populated | sama | — | P1 |
| F3-017 | Tugas Helper | Tugas | Kontrak | Kerjakan | helper/packing | prep/packing | — | SELESAI* | SELESAI* | sama | E2E + gap populated | sama | — | P1 |
| F3-018 | Tugas Operator + sample | Tugas | Kontrak | Kerjakan | output + sample | output API | output | SELESAI* | SELESAI* | sticky idempotency | E2E + gap populated | — | — | P1 |
| F3-019 | Tugas Driver loading/POD | Tugas | Kontrak | Kerjakan | loading/POD | delivery API | delivery | SELESAI* | SELESAI* | verbs resmi | E2E + gap populated | SJ list BLOCKED | Accurate | P1 |
| F3-020 | Tidak ada tugas fiktif/duplikat | Tugas | Kontrak | filter visible | derive dari job | mapOfficialTasks | — | SELESAI* | SELESAI* | teamTasks | empty+populated smoke (dup=0) | — | job | P1 |
| F3-021 | Filter/sort/resize/sticky Tugas | Tugas | V22 | task-sheet | spreadsheet | FE | — | PARSIAL | SELESAI* | sticky so,customer + CSS | vitest + geometry smoke | — | — | P1 |
| F3-022 | Tombol Kerjakan + Approval Sampel | Tugas | Kontrak | action cell | mutate + lock | submit/sample | role | SELESAI* | SELESAI* | taskActionLabel | E2E mutation | — | — | P1 |
| F3-023 | Pengiriman 1 baris / SJ | Pengiriman | Handoff | delivery sheet | list SJ | `…/ops/deliveries` | delivery read | SELESAI* | SELESAI* | dedupe accurate_sj_id | pytest SJ-centric | — | Loading PG | P1 |
| F3-024 | Multi-item detail SJ | Pengiriman | Handoff | detail modal | items[] | `…/deliveries/{id}` | read | SELESAI* | SELESAI* | detail API | pytest + smoke | — | gateway by-id | P1 |
| F3-025 | Enrich SO-link tanpa duplikat | Pengiriman | Kontrak | list | include_accurate_links | SO links | read | SELESAI* | SELESAI* | append links | pytest links | — | Accurate RO | P1 |
| F3-026 | Alamat/zona/ekspedisi passthrough | Pengiriman | PDF/Handoff | kolom | null jujur | normalize DN | — | SELESAI* | SELESAI* | field_availability | gateway normalize | — | Accurate | P2 |
| F3-027 | Loading + POD V3 | Pengiriman | Kontrak | aksi | loading/POD | loading API | delivery | SELESAI* | SELESAI* | loading ledger | E2E driver | — | — | P1 |
| F3-028 | Spreadsheet sticky/sort/col/page | Pengiriman | Handoff | v3-delivery-sheet | UI | FE | — | SELESAI* | SELESAI* | sticky sj,so | smoke interaktif | — | — | P1 |
| F3-029 | Accurate SJ list-all | Pengiriman | Kontrak | — | inventaris penuh | **tidak ada** | — | BLOCKED | BLOCKED | coverage null | API `accurate_sj_list_endpoint=null` | butuh kontrak Gateway | Accurate | P0 |
| F3-030 | Label COVERAGE TERBATAS | Pengiriman | Owner | banner | jujur | FE + API coverage | — | SELESAI* | SELESAI* | `#v3-del-coverage` | smoke | — | F3-029 | P1 |
| F3-031 | Approval Payment settings | Pengaturan | Handoff | form | GET/PUT + audit | payment-approval | settings.manage | SELESAI* | SELESAI* | SettingsPanel + API | vitest + smoke | — | PG | P1 |
| F3-032 | Master Cabang writable lokal | Pengaturan | Rancangan | UI cabang | CRUD + audit | branches API | manage | SELESAI* | SELESAI* | migrasi 0017 + UI | pytest + smoke | Live apply BLOCKED | keputusan Direktur | P1 |
| F3-033 | Master Mesin | Pengaturan | V3 | mesin | CRUD/list | `/ops/machines` | — | SELESAI* | SELESAI* | machines API | smoke | — | PG | P2 |
| F3-034 | Users / Grup / ScopedGrant / AccessAudit | Pengaturan | PR14 | Settings | grant manual | authz API | director | SELESAI* | SELESAI* | packs + panel | browser enforced disposable | Live cutover HOLD | PR14 | P2 |
| F3-035 | Workflow config + label browser-only | Pengaturan | Owner | prefs | label jujur demo | localStorage vs PG | — | PARSIAL | PARSIAL | guard demo views | connectionStatus tests | Urgent/Buffer demo non-SoT | — | P2 |
| F3-036 | Master Pengaturan agregat Live apply | Pengaturan | Owner | — | apply staging/Live | migrasi Live | — | PARSIAL | PARSIAL | lokal OK | — | Live BLOCKED | Direktur | P2 |
| F3-037 | Enforced Production Live | Authz | Owner | — | cutover | mode enforced | approval | BLOCKED | BLOCKED | fondasi + disposable | E2E enforced test | tidak aktifkan Live | PR14 | P0 |
| F3-038 | Layout sidebar/header/nav/scroll | Layout | Handoff+V22 | app shell | navigasi | FE | — | PARSIAL | PARSIAL | edge toggle + nav | smoke nav labels | nama nav ≠ Final; reskin penuh | F3-039 | P2 |
| F3-039 | Reskin HTML Final penuh | Layout | Handoff | seluruh UI | visual parity | aset handoff | — | BLOCKED | BLOCKED | aset di `/tmp` bukan di git | — | serahkan aset ke repo + prioritas modul | Owner | P0 |

## Daftar ringkas per status (audit baru)

### SELESAI* (29) — audit ber-ID

F3-004, F3-005, F3-006, F3-007, F3-008, F3-009, F3-010, F3-012, F3-013, F3-014, F3-015, F3-016, F3-017, F3-018, F3-019, F3-020, F3-021, F3-022, F3-023, F3-024, F3-025, F3-026, F3-027, F3-028, F3-030, F3-031, F3-032, F3-033, F3-034

### PARSIAL (7)

F3-001, F3-002, F3-003, F3-011, F3-035, F3-036, F3-038

### BLOCKED (3)

F3-029 (Accurate SJ list-all), F3-037 (enforced Live), F3-039 (reskin HTML Final penuh)

Baseline historis **25/11/3 tetap** sampai Owner memutuskan mengganti denominator laporan dengan angka audit ber-ID (**29/7/3**).

## Konflik Handoff vs Sandbox

| Topik | Handoff | Sandbox V22 | Keputusan |
|-------|---------|-------------|-----------|
| Nav | Inbox, Payments, Schedule, Tasks, Delivery, Buffer, Settings | + Dashboard, Flow, Kontrol terpisah | V3: Kontrol di KPI Jadwal; Buffer/Laporan tetap ada |
| Delivery SoT | SJ Accurate canonical | packing-based demo | **Backend Loading PG + SO-link**; bukan demo packing |
| Data | larangan fixture production | data simulasi | Jangan seed demo ke Production |
| Endpoint path | `/api/v3/...` | sandbox lokal | Map ke `/api/v1/production/...` |

## Keputusan Direktur yang masih diperlukan

1. Apply migrasi Master Cabang ke staging/Live?
2. Kontrak Accurate list-all SJ?
3. Cutover enforced Production + grant packs manual?
4. Salin aset HTML Final ke repo untuk reskin penuh?
5. Apakah baseline 25/11/3 diganti angka audit ber-ID (29/7/3)?
