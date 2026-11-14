# epv3-ci

CLI CI terisolasi untuk SHA `05befb16cd7081751bc9e97f57b239d6da98e8e6`. Tiga perintah, sebagai root di VPS:

```bash
sudo bash ops/ci/epv3-ci/install.sh
epv3-ci check
epv3-ci prepare
epv3-ci run
```

`check` hanya membaca. `prepare` dan `run` mengulang pemeriksaan itu dan berhenti bila gagal.

Laporan setelah `run`:

`/var/lib/epv3-ci-test/reports/05befb16cd7081751bc9e97f57b239d6da98e8e6/REPORT.txt`

Manifest setelah `prepare`:

`/var/lib/epv3-ci-test/manifests/05befb16cd7081751bc9e97f57b239d6da98e8e6/prepare.manifest`

Node 24 tidak dianggap setara dengan GitHub CI Node 22. E2E yang tidak dijalankan atau di-skip bukan PASS. CLI ini tidak mengubah `/opt/epv3`, database Live, atau service Live.

Belum dipasang di VPS dan belum menghasilkan CI PASS.
