# Eternal Production V3 — Deploy Runner

Satu CLI Python (stdlib saja), dijalankan manual (bukan daemon, bukan GitHub self-hosted runner).
Deploy satu **exact SHA 40-hex** yang CI-hijau dan merupakan ancestor `main`.

Status: DESAIN + SKRIP + TES SIMULASI. **Belum terpasang di VPS. Tidak ada Live activation.**

## Perintah

```bash
epv3-deploy validate-config                             # config live valid? (fail-closed)
epv3-deploy init-baseline --sha <sha-terpasang> --yes   # sekali: verifikasi runtime == SHA, DB == head, catat baseline (299a921...)
epv3-deploy plan   --sha <sha>                          # tanpa mutasi aplikasi (hanya memperbarui mirror git terisolasi)
epv3-deploy deploy --sha <sha>                          # dry-run (default)
epv3-deploy deploy --sha <sha> --yes                    # eksekusi setelah persetujuan Owner
epv3-deploy recover [--yes]                             # rollback jurnal yang terputus
epv3-deploy status
epv3-deploy migrate --sha <sha> --approval-file F --yes # TERPISAH, default nonaktif
```

Exit code: 0 ok/dry-run, 2 ditolak (tanpa mutasi), 3 gagal+rollback sukses, 4 rollback gagal, 5 jurnal belum selesai.
Tidak ada opsi menimpa drift. `SIGTERM`/Ctrl-C memicu rollback; `kill -9`/reboot ditangani `recover`.

## Alur `deploy`

1. Lock (`flock` non-blocking) -> tolak jika jurnal `in_progress`/`rollback_failed`.
2. `git remote update` pada mirror terisolasi `/opt/epv3/deploy/source/mirror.git` (deploy key read-only).
3. Validasi: SHA penuh, ada di mirror, ancestor `main`, CI check-runs wajib (3 job `ci.yml`) `success` pada SHA tsb,
   dan **revision DB live (`SELECT version_num FROM alembic_version`, read-only via psql) harus tepat satu baris
   sama dengan head Alembic SHA target**. Tidak butuh wrapper Alembic. Gagal baca/ambigu = ditolak.
4. Klasifikasi diff baseline->SHA per komponen (blob git): `gateway`, `backend`, `frontend`.
   Perubahan hanya `tests/`/`README`/`docs/` disinkron tanpa restart. Hanya-docs: baseline maju, tanpa efek.
5. Blokir otomatis (exit 2): perubahan `requirements*.txt` (butuh langkah venv disetujui), `staging-proxy/`
   (tak dikelola runner), perubahan Alembic (kecuali DB sudah di head target lewat `migrate` terpisah),
   **drift: STOP tanpa override** — file live (kode, dan file frontend terhadap manifest baseline) harus sama dengan
   baseline. Rekonsiliasi perubahan lokal bersama Owner, lalu `init-baseline` ulang.
6. Source terisolasi: `git archive <sha>` ke `source/releases/<sha>` (tanpa `.git`, tak menyentuh checkout legacy).
7. Build sekali: `compileall` untuk backend/gateway; frontend `npm ci && npm run build` -> artefak
   `artifacts/frontend/<git-tree-id-frontend>/` + MANIFEST sha256. Dipakai ulang bila tree frontend sama
   dan manifest masih valid.
8. Backup `/opt/epv3/backups/deploy-<ts>-<sha12>/`: `db.dump` (pg_dump -Fc, diverifikasi `pg_restore -l`),
   tar file kode yang akan ditimpa per komponen + rencana (restore/created), `SHA256SUMS` diverifikasi.
   Gagal backup = abort sebelum mutasi. Retensi `keep_backups` (hanya `deploy-*`).
9. Apply: hanya file tracked yang berubah disalin atomik (`os.replace`); file untracked (`.env`, `.venv`,
   upload) tidak disentuh/dihapus. Frontend **in-place** di `/opt/epv3/frontend-staging` (dist langsung): path/inode
   yang di-mount proxy tidak pernah diganti (tanpa rename/symlink); aset ber-hash dulu, `index.html` terakhir,
   lalu file usang dari manifest deploy sebelumnya dihapus.
10. Restart hanya unit terdampak (`epv3-accurate-gateway`, `epv3-api`) + health check retry.
11. Verifikasi frontend lewat proxy `:8180` yang sedang berjalan: SETIAP file artefak harus disajikan byte-identik
    (sha256) dan semua aset yang dirujuk `index.html` ada. Mount basi = gagal = rollback. Health proxy bila
    backend/gateway berubah.
12. Sukses: `deployed.json` maju, jurnal `success`, prune backup.

## Rollback & recovery

- Kegagalan pada fase apply/restart/verify (atau exception/SIGINT/SIGTERM) -> rollback otomatis: checksum backup
  diverifikasi, file dikembalikan dari tar, file baru dan sisa temp `.epv3new` dihapus (kode dan frontend sama),
  lalu **hanya unit yang benar-benar sempat di-restart** (dicatat jurnal sebelum restart) di-restart ulang + health check.
  Semua unit dicoba walau satu gagal; kegagalan dilaporkan sebagai `rollback_failed`.
- Jurnal atomik `state/current.json` + `journal.log` per fase. Bila proses mati (kill/reboot), deploy berikutnya
  ditolak (exit 5) sampai `recover --yes` menjalankan rollback yang sama (idempoten).
- Rollback gagal -> status `rollback_failed`, exit 4, semua deploy diblokir sampai ditangani manual
  (backup path tertera di jurnal).
- **DB tidak pernah di-rollback otomatis.** Restore DB hanya manual dengan persetujuan Owner.

## Migrasi PostgreSQL

`deploy` tidak pernah menjalankan Alembic. `migrate` hanya jalan bila `migrations.enabled=true` di config,
`commands.alembic_upgrade` diisi (tidak ada di config contoh), **dan** ada file approval JSON `{"sha","action":"alembic_upgrade","approved_by","expires"}` yang cocok SHA,
belum kedaluwarsa, plus `--yes`; membuat dump+checksum baru dulu. Urutan: `migrate` (migrasi harus backward
compatible) -> `deploy`.

## Instalasi (BELUM DILAKUKAN — perlu persetujuan Owner)

Lokasi: `/opt/epv3/deploy` (di luar `backend/`, `accurate-gateway/`, `frontend-staging/`, checkout legacy, V1/V2).
Installer **fail-closed**: butuh config live yang sudah disiapkan (`--config FILE` atau
`$PREFIX/deploy.conf.json` yang sudah ada) dan lolos `validate-config` (tanpa placeholder `REPLACE_ME`, deploy key
dan token ada, dest berupa direktori nyata, backup_dir ada, perintah lengkap). Config contoh tidak pernah
dipakai sebagai config live. Tidak ada `keys/`: deploy key yang sudah ada
(`/home/eternaladmin/.ssh/epv3_github`) dipakai apa adanya, tidak diduplikasi.

```bash
cp ops/deploy/deploy.conf.example.json /tmp/epv3-live.json   # edit REPLACE_ME (token checks read-only)
bash ops/deploy/install.sh --config /tmp/epv3-live.json            # dry-run
bash ops/deploy/install.sh --config /tmp/epv3-live.json --apply    # hanya setelah persetujuan
```

Hanya membuat dir + menyalin script + config (tidak menimpa config yang ada). Tidak menyentuh
systemd/nginx/sudoers/secrets/service dan tidak mencatat baseline.

Prasyarat persetujuan terpisah (tidak dilakukan skrip):
1. User runner (mis. `eternaladmin`) bisa menulis ke dest komponen dan `/opt/epv3/backups`.
2. Sudoers sempit: `systemctl restart epv3-api epv3-accurate-gateway`, `pg_dump` dan `psql -c 'SELECT version_num ...'`
   sebagai postgres (read-only).
3. Token GitHub read-only untuk membaca check-runs (`ci.token_file`).
4. Eksekusi `init-baseline` (read-only terhadap live; menolak bila runtime != 299a921... atau DB != head).

Rollback pemasangan: hapus `/opt/epv3/deploy` (tidak ada efek pada layanan).

## Tes

```bash
cd ops/deploy && python3 -m pytest -q tests
```
40 tes simulasi (hasil nyata: 40 passed), semua lokal (git origin sementara, stub systemctl/pg_dump/health), tanpa jaringan/DB/service.

Cakupan tambahan: config fail-closed, DB revision exact (tanpa wrapper), cutover frontend in-place + mount basi,
drift tanpa override, SIGTERM, recover hanya restart unit yang sempat di-restart, apply parsial + temp stray,
rollback gagal memblokir, installer fail-closed. Tidak ada tes yang menyentuh VPS/DB/service nyata.
Batas tes: mount proxy dan sudo/psql disimulasikan dengan stub; perilaku nyata baru terbukti saat `init-baseline`
dan deploy pertama yang disetujui.
