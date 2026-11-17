# Feature Preservation & Regression Checklist — Tahap H

**Policy:** Zero silent feature removal · bandingkan **sebelum vs sesudah** setiap perubahan material.

## Cara pakai

1. Isi kolom **Sebelum** dari baseline (`h-feature-inventory-baseline.md`).
2. Isi **Sesudah** setelah perubahan lokal.
3. Status: `PASS` | `FAIL` | `N/A (Direktur approved change)`.
4. Satu `FAIL` kritis → **STOP** (jangan commit/deploy).

## 1. Navigasi & shell

| # | Item | Sebelum | Sesudah | Status |
|---|---|---|---|---|
| N1 | 11 item sidebar Live | ada | ? | |
| N2 | Master Mesin tidak di sidebar; tetap via Settings | approved | ? | |
| N3 | `go('machineMaster')` masih berfungsi | ada | ? | |
| N4 | Collapse/handle sidebar | ada | ? | |
| N5 | Tidak ada nav baru yang menyembunyikan modul lama tanpa approval | — | ? | |

## 2. Modul operasional

| # | Item | Sebelum | Sesudah | Status |
|---|---|---|---|---|
| M1 | Inbox list + no auto job on view | ada | ? | |
| M2 | Monitoring Penerimaan + UNKNOWN finansial | ada | ? | |
| M3 | Jadwal Produksi sheet + HOLD | ada | ? | |
| M4 | Tugas Tim semua role verbs | ada | ? | |
| M5 | Jadwal Pengiriman 1 baris/SJ + detail | ada | ? | |
| M6 | Final-8 Belum terhubung | ada | ? | |
| M7 | Coverage banner jujur (bukan hide modul) | ada | ? | |
| M8 | Buffer / Laporan / Slip / History entry | ada | ? | |
| M9 | Settings payment/cabang/mesin/users | ada | ? | |

## 3. API & permission

| # | Item | Sebelum | Sesudah | Status |
|---|---|---|---|---|
| A1 | Route ops/workflow/inbox tetap terdaftar | 80+ | ? | |
| A2 | Authz mode Production tetap legacy | legacy | ? | |
| A3 | Branch isolation non-Direktur | scoped | ? | |
| A4 | Tidak ada permission gate baru yang silent-hide UI | — | ? | |
| A5 | Gateway Accurate tetap read-only | RO | ? | |

## 4. Larangan teknik silent removal

| # | Pemeriksaan | Status |
|---|---|---|
| T1 | Tidak ada `display:none` baru pada fitur aktif tanpa approval | |
| T2 | Tidak ada feature flag hide tanpa approval | |
| T3 | Integrasi gagal → error jujur / Belum terhubung / UNKNOWN — bukan hilangkan menu | |
| T4 | Tidak mengubah V1 | |

## 5. Role × cabang (wajib sampel)

| Role | Cabang | Views kritis | Mutasi kritis | Status |
|---|---|---|---|---|
| Direktur | lintas | semua sidebar | bypass/settings | |
| Kepala Produksi | cabang A | schedule/tasks | assign/HOLD | |
| Operator | cabang A | tasks | output | |
| Driver | cabang A | tasks/shipping | loading/POD | |
| Admin cabang B | cabang B | inbox/payment | tidak lintas A | |

## Sign-off

| Gate | Owner | Hasil |
|---|---|---|
| Feature preservation | Agent (lokal) / Direktur | |
| Workflow regression | Agent (lokal) | |
| Approval deploy Live | **Direktur** | HOLD sampai perintah eksplisit |
