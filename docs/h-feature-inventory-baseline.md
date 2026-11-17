# Feature Inventory Baseline — Eternal Production V3 (Tahap H)

**WIB:** 2026-11-17 · Branch kerja: `cursor/epv3-production-schedule-83bf` · Authz Production: **legacy**  
**Sumber:** `production.html` nav + `live-runtime.js` + `backend/app/api` + inventaris F3  
**Tujuan:** baseline sebelum Direct Live — untuk audit zero silent removal

## A. Sidebar Live (11 item — harus tetap terlihat)

| View id | Label sidebar | Catatan |
|---|---|---|
| dashboard | Overview | |
| inbox | Inbox Accurate | |
| schedule | Jadwal Produksi | |
| tasks | Tugas Tim | |
| shippingSchedule | Jadwal Pengiriman | coverage label dinamis; list Accurate proven Director |
| paymentMonitor | Monitoring Penerimaan | UNKNOWN finansial fail-closed |
| bufferMonitor | Monitoring Buffer | |
| productionReport | Laporan Produksi | |
| salarySlip | Cetak Slip Gaji | |
| history | Log History | |
| settings | Pengaturan | |

**Bukan sidebar (disetujui Direktur / Settings):** `machineMaster` (Master Mesin) — tetap di Settings + `go('machineMaster')`, **bukan** dihapus.

**View sekunder (bukan nav utama):** `mapping`, `integrityLab` — jangan silent-remove.

## B. Modul UI kritis (harus ada)

| Modul | Kontrol wajib |
|---|---|
| Inbox | list/search/filter/sort/page, detail, **no auto-create job on view** |
| Monitoring Penerimaan | sheet sticky, gate vs finansial UNKNOWN, bypass berwenang |
| Jadwal | schedule sheet, HOLD, sticky, assignment actions |
| Tugas Tim | role filters, Kerjakan, sample/design/prep/output/loading/POD verbs |
| Jadwal Pengiriman | 1 baris/SJ, detail multi-item, Final-8 + Belum terhubung, coverage banner |
| Settings | Payment approval, Cabang, Mesin (link), Users/grants (Direktur) |
| Buffer / Laporan / Slip / History | entry + API read paths |

## C. API surface (prefix `/api/v1` kecuali noted)

Ringkas (80 route decorator terdaftar di `backend/app/api`):

| Area | Contoh path | Mutasi? |
|---|---|---|
| Health | `/health`, `/ready` | no |
| Auth | `/auth/login`, `/auth/me` | login |
| Inbox | `/production/inbox`, `/production/orders/{so}` | read |
| Ops | `/production/ops/schedule`, `/deliveries`, `/buffer`, `/machines`, `/branches*` | mix |
| Workflow jobs | `/production/jobs/...` payment/design/loading/POD/outputs/… | mix |
| Settings | `/production/settings/payment-approval` | PUT berizin |
| Payroll | `/production/payroll/...` | mix |
| Portal | `/t/{slug}/...` | customer decision |

**Accurate Gateway (read-only, terpisah):**  
`/sales-orders`, `/receipts/{id}`, `/delivery-notes`, `/delivery-notes/{id}`, `/sales-invoices`, `/sales-invoices/{id}`, `/integration-coverage`  
*(route list invoice/SJ = kode lokal siap; deploy Live terpisah menunggu approval)*

## D. Permission / role packs

- Production default: **legacy** (jangan silent-switch ke enforced).
- Enforced cutover: fondasi ada, **Live HOLD** (F3-037) sampai Owner approval ref.
- Branch isolation: non-Direktur scoped cabang — jangan longgarkan.

## E. Keputusan Direktur yang sudah mengikat (bukan regresi)

| Keputusan | Status |
|---|---|
| Master Mesin keluar sidebar Live | APPROVED |
| financial_payment_status UNKNOWN tanpa outstanding terverifikasi | APPROVED |
| Delivery 8 kolom → Belum terhubung jika kosong | APPROVED |
| Outstanding = `primeOwing` (bukan totalAmount) | APPROVED (G4A Live) |
| SJ discovery list.do→id→detail; census_scan ≠ atomic universe | APPROVED (G4B Live) |
| Authz enforced Production Live | HOLD |
| Direct Live workflow (staging optional) | APPROVED (kebijakan ini) |

## F. Inventaris F3 (ringkas)

Lihat `docs/fase3-inventaris-39-fitur.md` (29 SELESAI* / 7 PARSIAL / 3 BLOCKED historis).  
Update H: F3-029 (SJ list-all) naik ke **PARSIAL/READY mapping** berdasarkan Director Live census — `full_universe_verified` tetap false (atomic tidak dijamin). F3-037 enforced Live tetap **BLOCKED/HOLD**.
