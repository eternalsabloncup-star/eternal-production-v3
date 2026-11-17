# Rancangan Teknis — Master Cabang (writable lokal)

**Status:** IMPLEMENTASI LOKAL — migrasi `20261120_0017` + API/UI (NO LIVE APPLY)
**Tanggal:** 2026-11-16 (Asia/Jakarta)
**HEAD acuan:** `8636b1f` + WIP lokal Master Cabang
**Kebijakan:** NO LIVE MIGRATION · Production authorization **legacy** · tidak ada auto-grant/auto-seed

## 1. Audit sumber existing (ID tidak diubah)

| Sumber | Bentuk | Integrasi |
|--------|--------|-----------|
| `users.branch_ids` JSONB | list string | akses legacy ops / Inbox |
| `ScopedGrant.branches` | list string per capability | enforced scope |
| `ProductionJob.branch_id` | string(64) | jadwal, tasks, payment, delivery |
| `production_machines.branch_id` | string | Master Mesin |
| Delivery / Loading / POD | via job.branch_id | Jadwal Pengiriman |
| `production_branches` | master PG (baru) | SoT nama/aktif/sort — **bukan** rewrite ID |
| Accurate gateway | branch id/name upstream | referensi, bukan master V3 |

## 2. Kontrak identitas (disetujui prinsip Direktur)

| Field | Aturan |
|-------|--------|
| `code` | PK, **immutable** setelah insert; 1:1 dengan job/grant/`users.branch_ids` |
| `name` | editable |
| `active` | soft-deactivate saja; **tidak ada hard-delete** endpoint |
| `sort_order` | int |
| opsional | `accurate_branch_id`, alamat, zona |
| audit | `production_branches_audit` (actor, reason, before/after) |

**Anti-duplikat:** unique(`code`).
**Cabang baru:** MANUAL Direktur saja; tidak seed otomatis dari job/user.

## 3. DDL (Alembic `20261120_0017`)

```sql
CREATE TABLE production_branches (
  code VARCHAR(64) PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  accurate_branch_id VARCHAR(64) NULL,
  address TEXT NULL,
  zone VARCHAR(64) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by_user_id INTEGER NULL
);
CREATE TABLE production_branches_audit (...);
```

Upgrade **tidak** menyisipkan baris. Downgrade menghapus hanya tabel master/audit.

## 4. API

| Method | Path | Cap / gate |
|--------|------|------------|
| GET | `/production/settings/branches` | `settings.branch.read` / legacy `job.read` |
| GET | `/production/settings/branches/{code}` | sama |
| POST | `/production/settings/branches` | Direktur + `settings.branch.manage` (enforced) |
| PATCH | `/production/settings/branches/{code}` | sama |
| GET | `/production/settings/branches/audit` | Direktur |

Orphan (kode job/grant belum di master) ditampilkan `source=effective_orphan`, `writable=false`.
Daftarkan dengan POST kode yang sama — **tidak** mengubah job/grant existing.

## 5. Permission

- Capability: `settings.branch.manage` (katalog admin / modul settings).
- Evaluator: modul `settings.*` = Director-only; grant ke karyawan **ditolak**.
- Tahap awal: grant manual capability ini **belum diizinkan** (`manual_grant_branch_manage_allowed=false`).
- Backend `user_may_manage_branches` mengabaikan grant non-Direktur.

## 6. UI Pengaturan

Tab Cabang: loading / sukses / error / validasi; SIMPAN→BACA→AUDIT via API.
Bukan localStorage SoT. Non-Direktur: banner baca-saja tanpa tombol Simpan.

## 7. Rencana rekonsiliasi kode cabang (keputusan Direktur)

Tidak ada rewrite ID otomatis. Inventaris sebelum apply Live:

| Kelas | Contoh | Tindakan usulan |
|-------|--------|-----------------|
| Cabang resmi | kode yang disepakati Direktur (mis. `BR-JKT`) | POST master dengan `code` sama + nama resmi |
| Referensi legacy | `branch-a` / string fixture lama | Tetap di job/grant sampai migrasi data eksplisit; tampil orphan |
| Orphan | kode di job/user/grant tanpa baris master | Daftarkan master (kode identik) **atau** biarkan orphan RO |
| ProductionJob | `jobs.branch_id` | Jangan diubah oleh Master Cabang |
| ScopedGrant | `access_grants.branches` | Jangan diubah oleh Master Cabang |
| Mesin / pengiriman | `production_machines` / delivery via job | Ikut `branch_id` job; tidak dipindah |

Urutan usulan Live (setelah approve):
1. Apply migrasi `20261120_0017` (DDL kosong).
2. Direktur POST daftar kode resmi (manual, beralasan, ter-audit).
3. Laporan orphan tersisa → keputusan alias/rename data terpisah (bukan endpoint rename `code`).
4. Soft-deactivate kode yang tidak dipakai (referensi tetap utuh).

## 8. Masih BLOCKED untuk Live

1. Apply migrasi staging/production
2. Seed manual daftar cabang Live (keputusan eksplisit)
3. Enforced Production activation
