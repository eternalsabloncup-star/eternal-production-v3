# epv3-ci

CLI CI terisolasi untuk SHA `05befb16cd7081751bc9e97f57b239d6da98e8e6`. Tiga perintah, sebagai root di VPS:

```bash
sudo bash ops/ci/epv3-ci/install.sh
epv3-ci check
epv3-ci prepare
epv3-ci run
```

`check` hanya membaca. `prepare` dan `run` mengulang pemeriksaan itu dan berhenti bila gagal.

Source di `/var/lib/epv3-ci-test/src` boleh berupa hasil `git archive` tanpa `.git`. SHA dibuktikan dengan tree `c6fa7a6ea34dd8397d956fd5fa765c7b6ab26e9f`, bukan dengan manifest yang ditulis `prepare`.

PostgreSQL CI ada di `/var/lib/epv3-ci/pgdata` port 5433. `data_directory` hanya dibaca lewat socket cluster oleh user pemilik proses, bukan oleh role `epv3_ci_runner`. Aturan firewall yang dihapus hanyalah aturan yang dipasang proses `run` itu sendiri.

Laporan setelah `run`:

`/var/lib/epv3-ci-test/reports/05befb16cd7081751bc9e97f57b239d6da98e8e6/REPORT.txt`

Manifest setelah `prepare`:

`/var/lib/epv3-ci-test/manifests/05befb16cd7081751bc9e97f57b239d6da98e8e6/prepare.manifest`

Node 24 tidak dianggap setara dengan GitHub CI Node 22. E2E yang tidak dijalankan atau di-skip bukan PASS. CLI ini tidak mengubah `/opt/epv3`, database Live, atau service Live.

Belum dipasang di VPS dan belum menghasilkan CI PASS.
