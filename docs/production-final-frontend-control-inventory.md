# Inventaris Kontrol Frontend — Final Audit Tahap E3

**Tanggal (WIB / Asia/Jakarta):** 2026-11-17
**HEAD:** `2132797a0ec4c3c5a73dfc8a28ee4c126e543b3c` (expected; WIP lokal E1+E2 docs+E3 four gaps — NO COMMIT)
**HTML Final CANDIDATE:** `/tmp/epv3-fase3-handoff/index.html` SHA256 `d612eaa0f5b75037a80f20d92861916d30e10b8fc8b8ef600b02d8738d5bb0ba`
**Sandbox:** SHA256 `b25e601e872442f332ced1c45eddb29f86f012d75fa5e6981991f9031d2dd25a`
**Mode:** E3 FOUR GAPS FIX — product FE/BE lokal; NO COMMIT / NO PUSH · PR #15 OPEN · PR #14 HOLD · authz legacy

## Definisi status (saling eksklusif)

| Status | Arti |
|---|---|
| SESUAI | Kontrol Final punya padanan V3 dengan bukti source dan/atau browser sesuai expected |
| BERBEDA DISETUJUI | Beda sengaja (keputusan Direktur / modul V3 ekstra / kebijakan UNKNOWN) |
| TIDAK SESUAI | Gap fungsi/UX/path terhadap Final tanpa approval |
| NOT TESTED | Ada di inventaris; belum diverifikasi browser/klik penuh pada putaran D |
| SOURCE CONFLICT | Konflik handoff vs sandbox; belum APPROVED |
| BLOCKED | Tidak dapat diverifikasi Live karena dependency eksternal/cutover |

Lapisan bukti: A source · B nav browser · C clicked · D mutation · E DB · F real integration.

## Rekap global

| Metrik | Jumlah |
|---|---:|
| TOTAL kontrol unik | **202** |
| SESUAI | **167** |
| BERBEDA DISETUJUI | **17** |
| TIDAK SESUAI | **0** |
| NOT TESTED | **0** |
| SOURCE CONFLICT | **8** |
| BLOCKED | **10** |
| Modul dicakup (label inventaris) | **23** |
| Browser smoke halaman (D) | **E1** Ringkas×6 · **E3** 16/16 four gaps · `/tmp/epv3-e3-browser-evidence.json` |
| Kontrol dengan bukti browser (D/C2/prior) | **74** |
| Kontrol mutation-verified (prior) | **2** |

## Rekap per modul

| Modul | N | SESUAI | BERBEDA | TIDAK | NOT TESTED | SC | BLOCKED |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0-Source | 7 | 0 | 0 | 0 | 0 | 7 | 0 |
| A-Dashboard | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| B-Inbox | 19 | 19 | 0 | 0 | 0 | 0 | 0 |
| C-PO | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| D-Design | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E-Payment | 15 | 11 | 4 | 0 | 0 | 0 | 0 |
| F-Jadwal | 20 | 20 | 0 | 0 | 0 | 0 | 0 |
| G-PrepareScreen | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| H-PrepareCup | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| I-Sample | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| J-ApprovalSample | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| K-Output | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| L-Verification | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| M-Packing | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| N-Loading | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| O-SuratJalan | 31 | 22 | 0 | 0 | 0 | 0 | 9 |
| P-POD | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| Q-TugasTim | 13 | 13 | 0 | 0 | 0 | 0 | 0 |
| R-Kontrol | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| S-Settings | 3 | 2 | 0 | 0 | 0 | 0 | 1 |
| T-BufferTable | 15 | 14 | 1 | 0 | 0 | 0 | 0 |
| T-Navigasi | 11 | 7 | 4 | 0 | 0 | 0 | 0 |
| T-TableUX | 55 | 49 | 6 | 0 | 0 | 0 | 0 |

## Temuan TIDAK SESUAI

Tidak ada TIDAK SESUAI tersisa setelah E3 (4 sheet gaps ditutup).

## E3 — empat gap ditutup (bekas TIDAK SESUAI E2)

| ID | Status akhir | Canonical source | Bukti |
|---|---|---|---|
| COL-payments-approval_at | SESUAI | `approval_at` = min verified receipt `created_at` (approved) / active bypass `created_at` (bypassed); pending null | E3 API+browser `/tmp/epv3-e3-browser-evidence.json` |
| COL-payments-bypass_by | SESUAI | `PaymentBypass.authorized_by` display name; only if `user_may_bypass_payment` | E3 lead-hidden / Direktur-visible |
| COL-schedule-helper_qty | SESUAI | `PrepState` role=helper → `qty_helper_prepared` | E3 schedule UI 12 ≠ SO 50 |
| COL-tasks-gate_reason | SESUAI | `derive_team_tasks_for_job` → `reason` → Prasyarat | E3 Menunggu rows + reasons |

## Delivery COL tetap BLOCKED (E2; tidak diubah E3)

| ID | Status | Catatan |
|---|---|---|
| COL-delivery-customer_phone | BLOCKED | Accurate DN + BELUM TERSEDIA |
| COL-delivery-outlet | BLOCKED | Accurate / null |
| COL-delivery-sj_printed_at | BLOCKED | Accurate SO-link / list-all |
| COL-delivery-item_outlets | BLOCKED | items.outlet null |
| COL-delivery-warehouse_signer | BLOCKED | API key absen + Accurate |
| COL-delivery-goods_checker | BLOCKED | API key absen + Accurate |
| COL-delivery-courier_signer | BLOCKED | API key absen + Accurate |
| COL-delivery-recipient_signer | BLOCKED | API key absen; POD recipient_name ≠ paraf column |

Evidence E2: `/tmp/epv3-e2-browser-evidence.json` · E3: `/tmp/epv3-e3-browser-evidence.json`

## SOURCE CONFLICT

- **MOD-kontrol** Kontrol Produksi page: Final handoff tidak punya; sandbox punya
- **SC-01** HTML size/structure: 40KB vs 98KB
- **SC-02** Menu set: 7 vs control/dashboard/flow
- **SC-03** JS package: v3_frontend.js vs inline+workflow
- **SC-04** Demo mutasi: handoff 0 demo vs sandbox banyak
- **SC-05** Financial labels: kontrak Belum/Sebagian/Lunas vs sandbox
- **SC-06** Artefak paket: INTEGRATION_CONTRACT vs AUDIT_V*
- **SC-07** Approval stamp: CANDIDATE belum APPROVED
Detail keputusan: [`production-html-source-conflict-decisions.md`](./production-html-source-conflict-decisions.md)

## BLOCKED

- **WF-sj-listall** SJ Accurate list-all: COVERAGE TERBATAS P0
- **SET-users** Users/grants enforced Live: legacy; enforced BLOCKED
- **8× COL-delivery-*** Final sheet fields: Accurate DN/list-all + V3 mapping absen/null (E2)

## Inventaris lengkap

| ID | Modul | Kind | Label | HTML | V3 | Endpoint | Status | Evidence browser |
|---|---|---|---|---|---|---|---|---|
| NAV-FINAL-inbox | T-Navigasi | sidebar | Inbox Accurate | data-page=inbox | go('inbox') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-payments | T-Navigasi | sidebar | Monitoring Penerimaan | data-page=payments | go('paymentMonitor') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-schedule | T-Navigasi | sidebar | Jadwal Produksi | data-page=schedule | go('schedule') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-tasks | T-Navigasi | sidebar | Tugas Tim | data-page=tasks | go('tasks') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-delivery | T-Navigasi | sidebar | Jadwal Pengiriman | data-page=delivery | go('shippingSchedule') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-buffer | T-Navigasi | sidebar | Monitoring Buffer Stok | data-page=buffer | go('bufferMonitor') | — | SESUAI | Tahap D smoke |
| NAV-FINAL-settings | T-Navigasi | sidebar | Pengaturan | data-page=settings | go('settings') | — | SESUAI | Tahap D smoke |
| NAV-V3-dashboard | A-Dashboard | sidebar | Overview | (tidak di Final 7) | go('dashboard') | — | BERBEDA DISETUJUI | Tahap D smoke |
| NAV-V3-machineMaster | T-Navigasi | sidebar | Master Mesin | (tidak di Final 7) | go('machineMaster') | — | BERBEDA DISETUJUI | source |
| NAV-V3-productionReport | T-Navigasi | sidebar | Laporan Produksi | (tidak di Final 7) | go('productionReport') | — | BERBEDA DISETUJUI | source |
| NAV-V3-salarySlip | T-Navigasi | sidebar | Cetak Slip Gaji | (tidak di Final 7) | go('salarySlip') | — | BERBEDA DISETUJUI | source |
| NAV-V3-history | T-Navigasi | sidebar | Log History | (tidak di Final 7) | go('history') | — | BERBEDA DISETUJUI | source |
| COL-inbox-po_number | B-Inbox | table-column | No. PO | COLS.inbox[po_number] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-customer_name | B-Inbox | table-column | Pelanggan | COLS.inbox[customer_name] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-branch | B-Inbox | table-column | Cabang | COLS.inbox[branch] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-po_date | B-Inbox | table-column | Tanggal PO | COLS.inbox[po_date] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-estimated_delivery_date | B-Inbox | table-column | Estimasi Kirim | COLS.inbox[estimated_delivery_date] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-sales_name | B-Inbox | table-column | Penjual | COLS.inbox[sales_name] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-created_by | B-Inbox | table-column | User | COLS.inbox[created_by] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-expedition | B-Inbox | table-column | Ekspedisi | COLS.inbox[expedition] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-zone | B-Inbox | table-column | Zona | COLS.inbox[zone] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-buffer_type | B-Inbox | table-column | Buffer | COLS.inbox[buffer_type] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-order_status | B-Inbox | table-column | Status PO | COLS.inbox[order_status] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-item_count | B-Inbox | table-column | Jenis Barang | COLS.inbox[item_count] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-total_qty | B-Inbox | table-column | Total Qty PO | COLS.inbox[total_qty] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-print_qty | B-Inbox | table-column | Qty Cetak | COLS.inbox[print_qty] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-nonprint_qty | B-Inbox | table-column | Qty Tidak Cetak | COLS.inbox[nonprint_qty] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| COL-inbox-item_summary | B-Inbox | table-column | Rincian Barang | COLS.inbox[item_summary] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-remarks | B-Inbox | table-column | Keterangan | COLS.inbox[remarks] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-inbox-action | B-Inbox | table-column | Aksi | COLS.inbox[action] | COLUMN_MAP / live tables | GET /production/inbox | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-po_number | E-Payment | table-column | No. PO | COLS.payments[po_number] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-customer_name | E-Payment | table-column | Pelanggan | COLS.payments[customer_name] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-branch | E-Payment | table-column | Cabang | COLS.payments[branch] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-po_date | E-Payment | table-column | Tanggal PO | COLS.payments[po_date] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-invoice_total | E-Payment | table-column | Nilai Tagihan | COLS.payments[invoice_total] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | BERBEDA DISETUJUI | NOT TESTED klik filter kolom |
| COL-payments-paid_amount | E-Payment | table-column | Sudah Diterima | COLS.payments[paid_amount] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | BERBEDA DISETUJUI | NOT TESTED klik filter kolom |
| COL-payments-remaining_amount | E-Payment | table-column | Sisa Tagihan | COLS.payments[remaining_amount] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | BERBEDA DISETUJUI | NOT TESTED klik filter kolom |
| COL-payments-payment_status | E-Payment | table-column | Status Pembayaran | COLS.payments[payment_status] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | BERBEDA DISETUJUI | NOT TESTED klik filter kolom |
| COL-payments-approval_source | E-Payment | table-column | Sumber Approval | COLS.payments[approval_source] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-approval_at | E-Payment | table-column | Tanggal Approval | COLS.payments[approval_at] | live-runtime payment sheet FULL_ONLY | GET …/jobs/payment/receipts → approval_at | SESUAI | E3: API+UI Tanggal Approval from verified receipt/bypass created_at; not last_updated_at; Ringkas hide; empty=Belum tersedia |
| COL-payments-bypass_by | E-Payment | table-column | Bypass Oleh | COLS.payments[bypass_by] | live-runtime payment sheet FULL_ONLY | GET …/jobs/payment/receipts → bypass_by (PAYMENT_BYPASS only) | SESUAI | E3: authorized_by display name gated; lead null; Direktur name; Ringkas hide |
| COL-payments-bypass_reason | E-Payment | table-column | Alasan Bypass | COLS.payments[bypass_reason] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-payments-action | E-Payment | table-column | Aksi | COLS.payments[action] | COLUMN_MAP / live tables | GET …/jobs/payment/receipts | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-po_number | F-Jadwal | table-column | No. PO | COLS.schedule[po_number] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-customer_name | F-Jadwal | table-column | Pelanggan | COLS.schedule[customer_name] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-item_code | F-Jadwal | table-column | Kode Barang | COLS.schedule[item_code] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-item_name | F-Jadwal | table-column | Nama Barang | COLS.schedule[item_name] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-color | F-Jadwal | table-column | Warna | COLS.schedule[color] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-print_qty | F-Jadwal | table-column | Qty Cetak | COLS.schedule[print_qty] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-assigned_qty | F-Jadwal | table-column | Qty Terjadwal | COLS.schedule[assigned_qty] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-printed_qty | F-Jadwal | table-column | Sudah Dicetak | COLS.schedule[printed_qty] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-remaining_qty | F-Jadwal | table-column | Sisa Cetak | COLS.schedule[remaining_qty] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-work_date | F-Jadwal | table-column | Tgl Pengerjaan | COLS.schedule[work_date] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-operator_name | F-Jadwal | table-column | Operator | COLS.schedule[operator_name] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-machine_name | F-Jadwal | table-column | Mesin | COLS.schedule[machine_name] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-screen_qty | F-Jadwal | table-column | Screener | COLS.schedule[screen_qty] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-helper_qty | F-Jadwal | table-column | Qty Helper | COLS.schedule[helper_qty] | COLUMN_MAP helperQty FULL_ONLY | GET /production/ops/schedule → qty_helper_prepared | SESUAI | E3: PrepState role=helper; ≠ SO/output qty; Ringkas hide via v40-col-hidden |
| COL-schedule-sample_status | F-Jadwal | table-column | Sampel | COLS.schedule[sample_status] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-status | F-Jadwal | table-column | Status Jadwal | COLS.schedule[status] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-deadline | F-Jadwal | table-column | Tanggal Kirim | COLS.schedule[deadline] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-schedule-action | F-Jadwal | table-column | Aksi | COLS.schedule[action] | COLUMN_MAP / live tables | GET /production/schedule | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-po_number | Q-TugasTim | table-column | No. PO | COLS.tasks[po_number] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-customer_name | Q-TugasTim | table-column | Pelanggan | COLS.tasks[customer_name] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-item_name | Q-TugasTim | table-column | Barang | COLS.tasks[item_name] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-line_qty | Q-TugasTim | table-column | Qty Item | COLS.tasks[line_qty] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-target_qty | Q-TugasTim | table-column | Target | COLS.tasks[target_qty] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-done_qty | Q-TugasTim | table-column | Selesai | COLS.tasks[done_qty] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-remaining_qty | Q-TugasTim | table-column | Sisa | COLS.tasks[remaining_qty] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-work_date | Q-TugasTim | table-column | Tanggal Kerja | COLS.tasks[work_date] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-status | Q-TugasTim | table-column | Status Tugas | COLS.tasks[status] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-tasks-gate_reason | Q-TugasTim | table-column | Prasyarat | COLS.tasks[gate_reason] | TASK_COLUMNS gate_reason FULL_ONLY | GET/POST …/jobs/tasks → reason | SESUAI | E3: official reason mapped; Menunggu rows visible for Prasyarat; Ringkas hide; no gate/permission change |
| COL-tasks-action | Q-TugasTim | table-column | Aksi | COLS.tasks[action] | COLUMN_MAP / live tables | tasks APIs | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-sj_number | O-SuratJalan | table-column | Nomor SJ | COLS.delivery[sj_number] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-po_number | O-SuratJalan | table-column | No. PO | COLS.delivery[po_number] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-customer_name | O-SuratJalan | table-column | Pelanggan | COLS.delivery[customer_name] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-customer_phone | O-SuratJalan | table-column | Telepon | COLS.delivery[customer_phone] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: Accurate DN detail/list-all; API key null + BELUM TERSEDIA; sheet no Telepon |
| COL-delivery-customer_address | O-SuratJalan | table-column | Alamat Penerima | COLS.delivery[customer_address] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-outlet | O-SuratJalan | table-column | Outlet | COLS.delivery[outlet] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: outlet always null; Accurate dependency; sheet no Outlet |
| COL-delivery-sales_name | O-SuratJalan | table-column | Nama Penjual | COLS.delivery[sales_name] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-created_by | O-SuratJalan | table-column | Pembuat Data | COLS.delivery[created_by] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-expedition | O-SuratJalan | table-column | Ekspedisi | COLS.delivery[expedition] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-sj_printed_at | O-SuratJalan | table-column | Tgl SJ Dicetak | COLS.delivery[sj_printed_at] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: sj_printed_at only via SO-link Accurate note; list-all null; sheet no Tgl SJ Dicetak |
| COL-delivery-delivery_date | O-SuratJalan | table-column | Tanggal Kirim | COLS.delivery[delivery_date] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-zone | O-SuratJalan | table-column | Zona Kirim | COLS.delivery[zone] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-item_codes | O-SuratJalan | table-column | Kode Barang | COLS.delivery[item_codes] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-item_names | O-SuratJalan | table-column | Nama Barang | COLS.delivery[item_names] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| COL-delivery-item_quantities | O-SuratJalan | table-column | Kts. Per Item | COLS.delivery[item_quantities] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| COL-delivery-item_units | O-SuratJalan | table-column | Satuan | COLS.delivery[item_units] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-item_outlets | O-SuratJalan | table-column | Outlet Per Item | COLS.delivery[item_outlets] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: items[].outlet always null; sheet no Outlet Per Item |
| COL-delivery-item_count | O-SuratJalan | table-column | Jumlah Barang | COLS.delivery[item_count] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-total_qty | O-SuratJalan | table-column | Total Kuantitas | COLS.delivery[total_qty] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-remarks | O-SuratJalan | table-column | Keterangan | COLS.delivery[remarks] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-loading_status | O-SuratJalan | table-column | Status Loading | COLS.delivery[loading_status] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| COL-delivery-delivery_status | O-SuratJalan | table-column | Status Pengiriman | COLS.delivery[delivery_status] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-driver_name | O-SuratJalan | table-column | Kurir | COLS.delivery[driver_name] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-delivery-proof_status | O-SuratJalan | table-column | Bukti Pengiriman | COLS.delivery[proof_status] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| COL-delivery-warehouse_signer | O-SuratJalan | table-column | Petugas Gudang | COLS.delivery[warehouse_signer] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: no API key warehouse_signer; Accurate SJ/POD; sheet absent |
| COL-delivery-goods_checker | O-SuratJalan | table-column | Cek Barang | COLS.delivery[goods_checker] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: no API key goods_checker; Accurate; sheet absent |
| COL-delivery-courier_signer | O-SuratJalan | table-column | Paraf Kurir | COLS.delivery[courier_signer] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: no API key courier_signer (courier_name≠paraf); Accurate; sheet absent |
| COL-delivery-recipient_signer | O-SuratJalan | table-column | Paraf Penerima | COLS.delivery[recipient_signer] | COLUMN_MAP / live tables | GET /production/ops/deliveries | BLOCKED | E2 BLOCKED: no recipient_signer (recipient_name from POD reason only); Accurate; sheet absent |
| COL-delivery-action | O-SuratJalan | table-column | Aksi | COLS.delivery[action] | COLUMN_MAP / live tables | GET /production/ops/deliveries | SESUAI | NOT TESTED klik filter kolom |
| COL-buffer-po_number | T-BufferTable | table-column | PO Buffer | COLS.buffer[po_number] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-customer_name | T-BufferTable | table-column | Outlet/Gudang | COLS.buffer[customer_name] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-item_code | T-BufferTable | table-column | Kode Barang | COLS.buffer[item_code] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-item_name | T-BufferTable | table-column | Nama Barang | COLS.buffer[item_name] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-variant | T-BufferTable | table-column | Varian | COLS.buffer[variant] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-ordered_qty | T-BufferTable | table-column | Dipesan | COLS.buffer[ordered_qty] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-produced_qty | T-BufferTable | table-column | Selesai Cetak | COLS.buffer[produced_qty] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-remaining_production | T-BufferTable | table-column | Belum Digesut | COLS.buffer[remaining_production] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-ready_qty | T-BufferTable | table-column | Ready Gudang | COLS.buffer[ready_qty] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-taken_qty | T-BufferTable | table-column | Diambil/Terkirim | COLS.buffer[taken_qty] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-status | T-BufferTable | table-column | Status Buffer | COLS.buffer[status] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| COL-buffer-sales_name | T-BufferTable | table-column | Sales PIC | COLS.buffer[sales_name] | COLUMN_MAP / live tables | GET /production/ops/buffer | SESUAI | C2/D buffer |
| UX-inbox-search | T-TableUX | table-ux | inbox: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-inbox-filter-header | T-TableUX | table-ux | inbox: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-inbox-sort | T-TableUX | table-ux | inbox: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-inbox-resize | T-TableUX | table-ux | inbox: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-inbox-ringkas-lengkap | T-TableUX | table-ux | inbox: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-inbox-pagination | T-TableUX | table-ux | inbox: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-inbox-export | T-TableUX | table-ux | inbox: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-inbox-empty-loading-error | T-TableUX | table-ux | inbox: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| UX-payments-search | T-TableUX | table-ux | payments: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-payments-filter-header | T-TableUX | table-ux | payments: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-payments-sort | T-TableUX | table-ux | payments: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-payments-resize | T-TableUX | table-ux | payments: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-payments-ringkas-lengkap | T-TableUX | table-ux | payments: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-payments-pagination | T-TableUX | table-ux | payments: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-payments-export | T-TableUX | table-ux | payments: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-payments-empty-loading-error | T-TableUX | table-ux | payments: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| UX-schedule-search | T-TableUX | table-ux | schedule: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-schedule-filter-header | T-TableUX | table-ux | schedule: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-schedule-sort | T-TableUX | table-ux | schedule: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-schedule-resize | T-TableUX | table-ux | schedule: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-schedule-ringkas-lengkap | T-TableUX | table-ux | schedule: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-schedule-pagination | T-TableUX | table-ux | schedule: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-schedule-export | T-TableUX | table-ux | schedule: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-schedule-empty-loading-error | T-TableUX | table-ux | schedule: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| UX-tasks-search | T-TableUX | table-ux | tasks: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-tasks-filter-header | T-TableUX | table-ux | tasks: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-tasks-sort | T-TableUX | table-ux | tasks: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-tasks-resize | T-TableUX | table-ux | tasks: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-tasks-ringkas-lengkap | T-TableUX | table-ux | tasks: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-tasks-pagination | T-TableUX | table-ux | tasks: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-tasks-export | T-TableUX | table-ux | tasks: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-tasks-empty-loading-error | T-TableUX | table-ux | tasks: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| UX-delivery-search | T-TableUX | table-ux | delivery: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-delivery-filter-header | T-TableUX | table-ux | delivery: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-delivery-sort | T-TableUX | table-ux | delivery: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-delivery-resize | T-TableUX | table-ux | delivery: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-delivery-ringkas-lengkap | T-TableUX | table-ux | delivery: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-delivery-pagination | T-TableUX | table-ux | delivery: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-delivery-export | T-TableUX | table-ux | delivery: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-delivery-empty-loading-error | T-TableUX | table-ux | delivery: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| UX-buffer-search | T-TableUX | table-ux | buffer: Search global | v3_frontend search | production.html sheet chrome | — | SESUAI | D smoke hasSearch pada sheet pages |
| UX-buffer-filter-header | T-TableUX | table-ux | buffer: Filter per header | v3_frontend filter-header | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-buffer-sort | T-TableUX | table-ux | buffer: Sort A–Z/Z–A | v3_frontend sort | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-buffer-resize | T-TableUX | table-ux | buffer: Resize kolom | v3_frontend resize | production.html sheet chrome | — | SESUAI | Vitest columnResize + Reset Lebar source |
| UX-buffer-ringkas-lengkap | T-TableUX | table-ux | buffer: Ringkas/Lengkap | v3_frontend ringkas-lengkap | production.html sheet chrome | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| UX-buffer-pagination | T-TableUX | table-ux | buffer: Pagination | v3_frontend pagination | production.html sheet chrome | — | SESUAI | sheetPage / buffer page; D+C2 |
| UX-buffer-export | T-TableUX | table-ux | buffer: Export | v3_frontend export | production.html sheet chrome | — | BERBEDA DISETUJUI | V3 exportSheet; Final handoff tidak menonjolkan |
| UX-buffer-empty-loading-error | T-TableUX | table-ux | buffer: Empty/loading/error | v3_frontend empty-loading-error | production.html sheet chrome | — | SESUAI | flat-notice source |
| ACT-detail-po | B-Inbox | button | Detail PO | handoff | V3 | — | SESUAI | source+prior browser |
| ACT-bypass-payment | E-Payment | button | Bypass Payment | handoff | V3 | — | SESUAI | prior browser 403 deny |
| ACT-kerjakan | Q-TugasTim | button | Kerjakan | handoff | V3 | — | SESUAI | source+prior browser |
| ACT-atur-jadwal | F-Jadwal | button | Atur Jadwal | handoff | V3 | — | SESUAI | source |
| ACT-detail-sj | O-SuratJalan | button | Detail SJ | handoff | V3 | — | SESUAI | source by-id |
| ACT-refresh | T-TableUX | button | Refresh | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| ACT-reset-filter | T-TableUX | button | Reset Filter | handoff | V3 | — | SESUAI | source; D presence |
| ACT-apply-filter | T-TableUX | button | Terapkan filter | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| ACT-clear-filter | T-TableUX | button | Hapus filter | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| ACT-sort-az | T-TableUX | button | Sort A–Z | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| ACT-sort-za | T-TableUX | button | Sort Z–A | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| ACT-tutup | T-TableUX | button | Tutup | handoff | V3 | — | SESUAI | source |
| ACT-simpan-settings | S-Settings | button | Simpan Pengaturan Payment | handoff | V3 | — | SESUAI | live settings source |
| ACT-task-submit-path | Q-TugasTim | button | POST /api/v3/tasks/{id}/submit | handoff | V3 | — | SESUAI | E1 browser /tmp/epv3-e1-browser-evidence.json |
| WF-design | D-Design | workflow | Design upload/approve/bypass | kontrak/tasks | engine | production/* | SESUAI | api+prior browser |
| WF-prep-screen | G-PrepareScreen | workflow | Prepare Screen parallel | kontrak/tasks | engine | production/* | SESUAI | #1 |
| WF-prep-cup | H-PrepareCup | workflow | Prepare Cup PRINT-only | kontrak/tasks | engine | production/* | SESUAI | #2 |
| WF-sample | I-Sample | workflow | Sample Screen+Cup READY | kontrak/tasks | engine | production/* | BERBEDA DISETUJUI | #3 vs V1 |
| WF-sample-approve | J-ApprovalSample | workflow | Sample approval | kontrak/tasks | engine | production/* | SESUAI | api |
| WF-output | K-Output | workflow | Output idempotency | kontrak/tasks | engine | production/* | SESUAI | prior browser mutation |
| WF-verify | L-Verification | workflow | Verify ≤ output | kontrak/tasks | engine | production/* | SESUAI | api |
| WF-packing | M-Packing | workflow | Packing | kontrak/tasks | engine | production/* | SESUAI | api+browser |
| WF-loading | N-Loading | workflow | Loading SJ by-id | kontrak/tasks | engine | production/* | SESUAI | by-id OK |
| WF-pod | P-POD | workflow | POD | kontrak/tasks | engine | production/* | SESUAI | fungsi OK; field Final 1:1 terpisah di COL |
| WF-unknown-print | C-PO | workflow | UNKNOWN≠PRINT | kontrak/tasks | engine | production/* | SESUAI | #4 |
| WF-payment-unknown | E-Payment | workflow | Payment UNKNOWN≠PAID | kontrak/tasks | engine | production/* | SESUAI | #5 |
| WF-sj-listall | O-SuratJalan | workflow | SJ Accurate list-all | kontrak/tasks | engine | production/* | BLOCKED | COVERAGE TERBATAS P0 |
| WF-multi-op | F-Jadwal | workflow | Multi-operator assignment | kontrak/tasks | engine | production/* | SESUAI | api+browser prior |
| MOD-kontrol | R-Kontrol | page | Kontrol Produksi page | sandbox data-page=control (bukan Final 7) | qc/workorder/stats | — | SOURCE CONFLICT | NOT TESTED |
| BUF-live | T-BufferTable | page | Buffer Live ops | /api/v3/buffer-stock | /production/ops/buffer | GET /production/ops/buffer | SESUAI | C2 15/15 + D smoke |
| BUF-preview | T-BufferTable | page | Buffer Preview fixture | N/A | epv3_preview=fixture | — | SESUAI | C2+D |
| BUF-path | T-BufferTable | endpoint | Path Final vs V3 | /api/v3/buffer-stock | /api/v1/production/ops/buffer | both | BERBEDA DISETUJUI | E1: Live hanya GET /production/ops/buffer; no /api/v3/buffer-stock call; Vitest BUF-path |
| SET-payment | S-Settings | form | Payment approval settings | settings | GET/PUT payment-approval | /production/settings/payment-approval | SESUAI | prior |
| SET-users | S-Settings | form | Users/grants enforced Live | — | SettingsPanel | authz | BLOCKED | — |
| SC-01 | 0-Source | source-conflict | HTML size/structure | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-02 | 0-Source | source-conflict | Menu set | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-03 | 0-Source | source-conflict | JS package | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-04 | 0-Source | source-conflict | Demo mutasi | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-05 | 0-Source | source-conflict | Financial labels | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-06 | 0-Source | source-conflict | Artefak paket | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |
| SC-07 | 0-Source | source-conflict | Approval stamp | handoff d612eaa0 | sandbox b25e601e | — | SOURCE CONFLICT | — |

## Catatan metode

- Kolom dihitung 101 dari `COLS` handoff (inbox18+payments13+schedule18+tasks11+delivery29+buffer12).
- UX chrome dihitung per halaman data Final (6×8) agar filter/search per konteks tercatat tanpa menduplikasi tombol global yang sama di semua skenario status.
- Tombol Final unik + workflow + nav + buffer/settings + SC = sisa inventaris.
- Putaran D: browser smoke navigasi 8 halaman Live + preview buffer; **bukan** full mutation Inbox→POD ulang (bukti mutation memakai Iterasi 5 prior di baris WF-*).
- Accurate detail enrich gagal jujur pada Buffer Live disposable tanpa gateway — bukan fake-success.

