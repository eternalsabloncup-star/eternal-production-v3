# Rancangan Teknis — Master Cabang (belum writable)

**Status:** DRAFT diperbarui — keputusan Direktur masih diperlukan untuk skema/migrasi
**Tanggal:** 2026-11-16 03:15 WIB (Asia/Jakarta)
**Kebijakan sesi:** **tidak** menambah tabel/API writable sekarang. Live memakai cabang efektif read-only.
**Implementasi aman lokal tanpa skema baru:** capability `settings.branch.read` terpetakan enforced; UI RO jujur `can_manage=false`.

## Relasi cabang existing (audit)

| Sumber | Bentuk | Modul terdampak |
|--------|--------|-----------------|
| `users.branch_ids` (JSONB) | daftar kode string | akses legacy Inbox/ops |
| `ProductionJob.branch_id` | string(64) | Inbox ensure, jadwal, kontrol qty, tasks, payment monitor |
| ScopedGrant.branches | list string per capability | enforced grant scope |
| `GET /production/settings/branches` | union grants ∪ job | Pengaturan RO |
| `production_machines.branch_id` | string | Master Mesin |
| Delivery / Loading / POD | via job.branch_id | Jadwal Pengiriman |
| Laporan / payroll runs | branch_id | laporan & slip |
| Accurate gateway | branch id/name upstream | referensi, bukan master V3 |

Tidak ada tabel `branches` PostgreSQL master editable di V3 saat ini.

## Identitas cabang (usulan setelah keputusan)

- `code` PK/unique — **immutable** setelah publish; 1:1 dengan `ProductionJob.branch_id` / grant / `users.branch_ids`
- `name`, `active`, `sort_order`
- opsional: `accurate_branch_id`, alamat, zona
- audit: reason + before/after + actor

## Dampak bila code diubah (dilarang tanpa migrasi data)

Job, grant, mesin, laporan histori putus. Mitigasi: hanya rename `name`; soft-deactivate `active=false`.

## Authz

- Enforced: daftar cabang UI grant dari master aktif ∪ histori job (bukan free-text liar).
- Capability usulan manage: `settings.branch.manage` (belum di katalog sampai keputusan).
- Legacy JSONB `branch_ids`: mapping eksplisit, **bukan** auto-import.

## Yang boleh tanpa keputusan baru (sudah/aman)

- Endpoint RO + `settings.branch.read` di SETTINGS_PROD map
- Transparansi di authorization-status (`branch_management`)
- Dokumentasi relasi + risiko

## Yang BLOCKED sampai keputusan Direktur

1. Tabel + migrasi Alembic writable
2. CRUD API + UI Simpan
3. Capability `settings.branch.manage`
4. Seed dari job/user ke master
5. Apply staging/Live

## Keputusan yang diminta

1. Setujui skema master cabang?
2. `code` immutable?
3. Siapa manage sebelum/ sesudah enforced?
4. Jadwal relatif cutover enforced?
