# Authorization enforced cutover — prosedur, penghambat, rollback

**Status paket kode:** siap review. **Tidak** mengaktifkan `enforced` di VPS,
**tidak** merge, **tidak** deploy dari dokumen ini.

Persetujuan dipisah: (1) implementasi/PR → (2) merge → (3) deploy/cutover
Direktur. Masing-masing langkah memerlukan persetujuan eksplisit.

## Ringkasan audit (sebelum perubahan)

| Item | Temuan |
|------|--------|
| Endpoint produksi terpetakan | 61/61 (`workflow`+`operations`+`payroll`+`inbox`) fail-closed jika unmapped |
| Direktur | Grup sistem `director` via bootstrap; `evaluate()` Full Access lintas cabang |
| Mode default | `V3_WORKFLOW_AUTHORIZATION=legacy` |
| Gate lama | `enforced` hanya jika `APP_ENV=test` + Settings enabled |
| Import grant otomatis | **Dilarang** (`automatic_import_allowed=false`) |
| Mapping Owner terbuka | `production.job.read`, `production.delivery.manage`, `production.tracking.read` |
| Cabang | ID eksplisit pada grant; **bukan** master cabang terpisah |
| Password / staging_admin | Tidak diubah / tidak dinonaktifkan oleh paket ini |

## Setelah perubahan (transparansi)

| Perubahan | Efek | Masih nonaktif? |
|-----------|------|-----------------|
| Gate produksi `V3_WORKFLOW_ENFORCED_APPROVAL_REF` | Mengizinkan *process start* `enforced` di luar test **hanya** jika Settings on + ref Owner tercatat | Mode tetap `legacy` sampai env diganti + deploy |
| `GET /settings/authorization-status` | Direktur melihat mode, blockers, inventory summary | Tidak mengaktifkan apa pun |
| UI Pengaturan + panel Produksi | Menampilkan mode `legacy`/`enforced` apa adanya | Tidak menyembunyikan menu |
| Dokumen cutover ini | Prosedur backup/rollback/login | Deploy manual |

**Tidak diubah:** workflow bisnis, gate Payment/Desain/SoD, password hash, ERP V1/V2,
hak istimewa grup Direktur (tetap Full Access), tombol/menu yang sudah ada.

## Penghambat aktivasi (wajib clear sebelum cutover)

1. Inventory read-only belum `cutover_review_clear` (narrowing / unknown / unresolved).
2. Keputusan Owner untuk tiga privilege `MAPPING_REVIEW_REQUIRED`.
3. Grant manual untuk akun operasional (tanpa grant → 403 di `enforced`).
4. Bootstrap Direktur belum selesai.
5. `V3_WORKFLOW_ENFORCED_APPROVAL_REF` belum diisi (produksi).
6. Persetujuan Direktur terpisah untuk merge dan untuk deploy.

Selama penghambat ada: **jangan** paksa aktivasi. Tampilkan status ke Direktur
via Pengaturan → status otorisasi / `authorization-status`.

## Prosedur cutover (setelah persetujuan)

Runner resmi saja: `/opt/epv3/deploy/bin/epv3-deploy`.

### A. Backup

```bash
/opt/epv3/deploy/bin/epv3-deploy check
/opt/epv3/deploy/bin/epv3-deploy prepare --yes
```

`prepare` menulis release + backup tanpa mengubah Live. Simpan path backup dan SHA.

### B. Verifikasi pra-cutover (bukan Live write)

```bash
# dari host yang punya akses DB read-only yang disetujui Owner
cd /opt/epv3/releases/<sha>/backend
python -m app.authorization.inventory --preflight
python -m app.authorization.inventory --summary --owner-approval-ref '<ref Owner>'
```

Exit 0 = clear. Exit 2 = BLOCKED — stop.

Konfirmasi login Direktur (grup sistem), buka Pengaturan, baca
`/api/v1/settings/authorization-status` — `activation_recommended` harus true
hanya jika inventory clear + approval ref + bootstrap.

### C. Deploy kode (masih legacy)

```bash
/opt/epv3/deploy/bin/epv3-deploy deploy --yes
```

Pastikan env Live masih `V3_WORKFLOW_AUTHORIZATION=legacy` pada langkah ini.
Restart layanan. Verifikasi login legacy/settings tetap jalan.

### D. Aktifkan enforced (hanya setelah langkah C + persetujuan Direktur)

Set di unit/env Live (contoh):

- `V3_SETTINGS_ENABLED=true` (sudah sebelumnya)
- `V3_WORKFLOW_ENFORCED_APPROVAL_REF=<referensi persetujuan tertulis>`
- `V3_WORKFLOW_AUTHORIZATION=enforced`

Restart backend. **Jangan** ubah password. **Jangan** nonaktifkan `staging_admin`
tanpa persetujuan terpisah.

### E. Verifikasi login

1. Login Direktur → `/auth/me` → `system_director=true`, `workflow_authorization=enforced`.
2. Pengaturan menampilkan status **enforced AKTIF**; menu Pengguna/Grup/Audit tetap ada.
3. Akun operasional dengan grant cabang A: akses A OK, cabang B ditolak.
4. Akun tanpa grant: 403 pada endpoint produksi.
5. Gate bisnis (payment/design) tetap menolak bypass Direktur.

## Rollback

1. Set `V3_WORKFLOW_AUTHORIZATION=legacy`, restart.
2. Jika perlu kembalikan kode: `/opt/epv3/deploy/bin/epv3-deploy recover` sesuai jurnal,
   atau deploy ulang SHA sebelumnya lewat runner resmi.
3. Catatan: rollback mode **tidak** mengembalikan `User.permissions` lama dan **tidak**
   menghapus grant/revocation yang sudah ditulis. Sesi managed tetap memakai credential generation.

Menonaktifkan `V3_SETTINGS_ENABLED` setelah bootstrap **dilarang** (menolak login
legacy resurrection).

## Tes otomatis terkait

- `tests/authorization/test_enforced_activation_gate.py` — gate + status Direktur
- `tests/authorization/test_workflow_access.py` — Direktur lintas cabang, batasan cabang,
  karyawan, deny tanpa grant
- Frontend: `settingsMenu.test.ts` menampilkan mode aktual (bukan hardcoded legacy)
