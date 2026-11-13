# Eternal Production V3 — Deploy Runner

Satu CLI Python (stdlib saja), dijalankan manual (bukan daemon, bukan GitHub self-hosted runner).
Deploy satu **exact SHA 40-hex** yang CI-hijau dan merupakan ancestor `main`.

Status: DESAIN + SKRIP + TES SIMULASI. **Belum terpasang di VPS. Tidak ada Live activation.**

## Perintah

```bash
epv3-deploy init-baseline --sha <sha-terpasang> --yes   # sekali: catat baseline (runtime 299a921...)
epv3-deploy plan   --sha <sha>                          # tanpa efek: validasi + klasifikasi
epv3-deploy deploy --sha <sha>                          # dry-run (default)
epv3-deploy deploy --sha <sha> --yes                    # eksekusi setelah persetujuan Owner
epv3-deploy recover [--yes]                             # rollback jurnal yang terputus
epv3-deploy status
epv3-deploy migrate --sha <sha> --approval-file F --yes # TERPISAH, default nonaktif
```

Exit code: 0 ok/dry-run, 2 ditolak (tanpa mutasi), 3 gagal+rollback sukses, 4 rollback gagal, 5 jurnal belum selesai.

## Alur `deploy`

1. Lock (`flock` non-blocking) -> tolak jika jurnal `in_progress`/`rollback_failed`.
2. `git remote update` pada mirror terisolasi `/opt/epv3/deploy/source/mirror.git` (deploy key read-only).
3. Validasi: SHA penuh, ada di mirror, ancestor `main`, CI check-runs wajib (3 job `ci.yml`) `success` pada SHA tsb.
4. Klasifikasi diff baseline->SHA per komponen (blob git): `gateway`, `backend`, `frontend`.
   Perubahan hanya `tests/`/`README`/`docs/` disinkron tanpa restart. Hanya-docs: baseline maju, tanpa efek.
5. Blokir otomatis (exit 2): perubahan `requirements*.txt` (butuh langkah venv disetujui), `staging-proxy/`
   (tak dikelola runner), perubahan Alembic (kecuali DB sudah di head target lewat `migrate` terpisah),
   drift (file live berbeda dari baseline/target; override `--accept-drift` sadar).
6. Source terisolasi: `git archive <sha>` ke `source/releases/<sha>` (tanpa `.git`, tak menyentuh checkout legacy).
7. Build sekali: `compileall` untuk backend/gateway; frontend `npm ci && npm run build` -> artefak
   `artifacts/frontend/<git-tree-id-frontend>/` + MANIFEST sha256. Dipakai ulang bila tree frontend sama
   dan manifest masih valid.
8. Backup `/opt/epv3/backups/deploy-<ts>-<sha12>/`: `db.dump` (pg_dump -Fc, diverifikasi `pg_restore -l`),
   tar file kode yang akan ditimpa per komponen + rencana (restore/created), `SHA256SUMS` diverifikasi.
   Gagal backup = abort sebelum mutasi. Retensi `keep_backups` (hanya `deploy-*`).
9. Apply: hanya file tracked yang berubah disalin atomik (`os.replace`); file untracked (`.env`, `.venv`,
   upload) tidak disentuh/dihapus. Frontend: dir baru lalu `rename` swap (mode dir atau symlink).
10. Restart hanya unit terdampak (`epv3-accurate-gateway`, `epv3-api`) + health check retry.
11. Verifikasi frontend via proxy `:8180`: `index.html` sama dengan artefak (sha256) dan semua `/assets/*` 200;
    health proxy bila backend/gateway berubah.
12. Sukses: `deployed.json` maju, jurnal `success`, prune backup.

## Rollback & recovery

- Kegagalan pada fase apply/restart/verify (atau exception/SIGINT) -> rollback otomatis: kembalikan file dari
  tar backup (checksum diverifikasi dulu), hapus file baru, balikan frontend, restart unit terdampak, health check.
- Jurnal atomik `state/current.json` + `journal.log` per fase. Bila proses mati (kill/reboot), deploy berikutnya
  ditolak (exit 5) sampai `recover --yes` menjalankan rollback yang sama (idempoten).
- Rollback gagal -> status `rollback_failed`, exit 4, semua deploy diblokir sampai ditangani manual
  (backup path tertera di jurnal).
- **DB tidak pernah di-rollback otomatis.** Restore DB hanya manual dengan persetujuan Owner.

## Migrasi PostgreSQL

`deploy` tidak pernah menjalankan Alembic. `migrate` hanya jalan bila `migrations.enabled=true` di config
**dan** ada file approval JSON `{"sha","action":"alembic_upgrade","approved_by","expires"}` yang cocok SHA,
belum kedaluwarsa, plus `--yes`; membuat dump+checksum baru dulu. Urutan: `migrate` (migrasi harus backward
compatible) -> `deploy`.

## Instalasi (BELUM DILAKUKAN — perlu persetujuan Owner)

Lokasi aman: `/opt/epv3/deploy` (di luar `backend/`, `accurate-gateway/`, `frontend-staging/`, checkout legacy,
V1/V2). `bash ops/deploy/install.sh` = dry-run; `--apply` membuat dir + salin script + config contoh
(tidak menimpa config). Tidak menyentuh systemd/nginx/sudoers/secrets.

Prasyarat yang butuh persetujuan terpisah (tidak dilakukan skrip):
1. User `epv3deploy` (atau `epv3`) dengan tulis ke `dest` komponen + `/opt/epv3/backups`.
2. Sudoers sempit: `systemctl restart epv3-api epv3-accurate-gateway`, `pg_dump` sbg postgres (read-only).
3. Deploy key V3 read-only di `keys/` (0600) + `github_checks_token` (read-only checks). Wrapper
   `alembic-*-wrapper` hanya diperlukan untuk `migrate`/deteksi revisi DB.
4. Verifikasi VPS (belum bisa dilakukan agen): letak/izin `frontend-staging` (dir vs symlink), health path
   `:8100`/`:8091`, `EPV3_FRONTEND_ROOT` proxy menunjuk ke `frontend-staging`.

Rollback pemasangan: hapus `/opt/epv3/deploy` (tidak ada efek pada layanan).

## Tes

```bash
cd ops/deploy && python3 -m pytest -q tests
```
27 tes simulasi gagal, semua lokal (git origin sementara, stub systemctl/pg_dump/health), tanpa jaringan/DB/service.
