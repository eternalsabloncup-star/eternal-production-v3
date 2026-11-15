# Rancangan Teknis — Master Cabang (belum diimplementasikan)

**Status:** DRAFT untuk keputusan Direktur  
**Tanggal:** 2026-11-16 (Asia/Jakarta)  
**Kebijakan sesi:** **tidak** menambah tabel/API writable sekarang. Live memakai cabang efektif read-only.

## Relasi cabang existing

| Sumber | Bentuk | Peran |
|--------|--------|-------|
| `users.branch_ids` (JSONB) | daftar kode string | Cakupan akses legacy |
| `ProductionJob.branch_id` | string(64), indexed | Cabang operasional job |
| Accurate SO/branch | id/name dari gateway | Referensi upstream, bukan master V3 |
| ScopedGrant (PR #14) | grant + branch scope | Cakupan enforced (HOLD; belum aktif) |
| `GET /production/settings/branches` | union grants ∪ job branches | **Read-only** efektif |

Tidak ada tabel `branches` PostgreSQL sebagai master editable di V3 Live saat ini.

## Identitas cabang (usulan)

Jika disetujui nanti:

- `code` (PK/unique, selaras Accurate/job, immutable setelah publish)
- `name`, `active`, `sort_order`
- opsional: `accurate_branch_id`, alamat, zona default
- `created_at` / `updated_at` / `updated_by_user_id`
- audit table terpisah (before/after JSONB + reason)

Kode harus 1:1 dengan nilai yang sudah dipakai di `ProductionJob.branch_id` dan `users.branch_ids`.

## Dampak ProductionJob

- Filter jadwal, delivery, monitor, laporan sudah by `branch_id` string.
- Rename code = migrasi data job + risiko histori; lebih aman: `code` immutable, hanya `name`/`active` yang diubah.
- Soft-deactivate: job lama tetap terbaca; create/schedule baru ditolak jika `active=false`.

## Dampak ScopedGrant / authz

- PR #14 memakai branch scope pada grant; master cabang harus menjadi sumber daftar cabang untuk UI grant (bukan free-text saja).
- Legacy `branch_ids` JSONB perlu mapping/migrasi eksplisit — **bukan** auto-import diam-diam (kebijakan Owner PR #14).
- Enforced tetap OFF sampai cutover terpisah.

## Dampak filter & laporan

- Dropdown cabang: dari master aktif ∪ cabang yang masih muncul di data historis.
- Laporan lintas cabang: Direktur / grant koleksi; operator tetap scoped.

## Kebijakan edit & audit (usulan)

- Hanya Direktur (legacy) atau grant `settings.branches.manage` (enforced nanti).
- Setiap ubah: reason wajib + baris audit.
- Tidak ada soft-save palsu di UI sebelum SoT PG siap.

## Rencana migrasi (setelah keputusan)

1. Tambah tabel + audit (revisi Alembic baru, DB disposable dulu).
2. Seed dari distinct `ProductionJob.branch_id` ∪ `users.branch_ids` (read-only seed).
3. API CRUD + ganti `settings/branches` dari RO → manage.
4. Uji filter job/delivery/monitor/tasks.
5. Integrasi UI grant PR #14 tanpa merge prematur.
6. Apply staging disposable → keputusan Live apply terpisah.

## Keputusan yang diminta Direktur

1. Setujui skema master cabang?  
2. `code` immutable?  
3. Siapa boleh manage sebelum enforced?  
4. Jadwal relatif terhadap merge PR #14?
