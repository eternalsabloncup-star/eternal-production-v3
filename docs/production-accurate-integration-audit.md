# Production Accurate Integration Audit — Function First Iterasi 3

**Tanggal (WIB / Asia/Jakarta):** 2026-11-16
**Repository:** `eternalsabloncup-star/eternal-production-v3`
**Branch:** `cursor/epv3-production-schedule-83bf`
**BASE HEAD:** `e0e4bd58228b959decde5628e51216bedd3707cc`
**Worktree:** `/tmp/epv3-fase1b-wt`
**Authz Production:** `legacy`
**PR #15:** OPEN · **PR #14:** HOLD
**Git putaran ini:** checkpoint commit Function First Iterasi 3 (Accurate Integration)

---

## 1. Endpoint Accurate terverifikasi (Gateway)

| Method | Path Gateway | Upstream Accurate | Mode |
|---|---|---|---|
| GET | `/sales-orders` | `sales-order/list.do` | fixture + live client |
| GET | `/sales-orders/{key}` | `sales-order/detail.do` | fixture + live client |
| GET | `/receipts/{id}` | `sales-receipt/detail.do` | fixture + live client |
| GET | `/delivery-notes/{id}` | `delivery-order/detail.do` | fixture + live client |
| — | **Tidak ada** `GET /delivery-notes` list | — | **TIDAK ADA** — jangan dikarang |

Sumber: `accurate-gateway/README.md`, `routes.py`, `accurate_client.py`.

---

## 2. Matriks kontrak A–J

| Area | Endpoint nyata | Gateway | V3 | Sumber kebenaran | Mapping | Auth | Bukti | Risiko |
|---|---|---|---|---|---|---|---|---|
| A. Daftar SO | `/sales-orders` | YA | Inbox `GET /production/inbox` | Accurate SO list | `normalize_summary` | M2M Bearer | Fixture PASS; Live VM **BLOCKED** | Pagination/filter_incomplete |
| B. Detail SO | `/sales-orders/{n}` | YA | `GET /production/orders/{n}` + job create sync | Accurate detail | line qty + process | M2M | Fixture + unit | Qty unverified → null |
| C. Pelanggan | pada SO | YA | field customer | Accurate | name/id | M2M | Fixture | — |
| D. Item/qty/uom | detail lines | YA | `JobLineQty` via sync | Accurate detail | process print/non_print/unknown | M2M | Prep/sync tests | UNKNOWN tidak invent PRINT |
| E. Penerimaan | `/receipts/{id}` | YA | `require_valid_receipt` | Receipt posted+verifiable | SO/branch match | M2M; fail-closed | phase32 | Invoice outstanding **UNKNOWN** |
| F. Identitas SJ | `/delivery-notes/{id}` | YA | Loading/POD evidence | SJ by id | id/number/SO/branch | M2M | multi_sj + evidence | Butuh id diketahui |
| G. SJ multi-item | detail lines | YA | loading line PCS | SJ lines | uom PCS | M2M | multi_sj | — |
| H. SO→SJ | `links.delivery_note_ids` pada SO detail | hint saja | `include_accurate_links` | SO links + Loading PG | by id fetch | M2M | `test_delivery_accurate_links_fase3` | Bukan inventaris penuh |
| I. Pagination | page/limit | YA | scoped scan cabang | Accurate total | scan_incomplete | M2M | inbox scoped tests | Empty page ≠ done (diperbaiki) |
| J. Error | 401/403/404/429/5xx | fail-closed; no fixture fallback in live | HTTP 502/503/404 | — | retry transport 408/429/5xx | M2M | gateway live_fail_closed + ReadGateway | Cred kosong → 503 |

---

## 3. Akses di lingkungan agent ini

| Item | Status |
|---|---|
| Secret names terikat app (Cursor) | Ada (ACCURATE_*, GATEWAY_M2M_TOKEN, V3_ACCURATE_READ_GATEWAY_*) |
| Env VM agent (`ACCURATE_*`, gateway URL/token) | **MISSING / EMPTY** — nilai tidak diinjeksi ke shell |
| Real read-only Accurate | **BLOCKED** |
| Sandbox Accurate non-Live | **BLOCKED** (tidak dikonfigurasi di VM) |
| Fixture Gateway | **PASS** (159 tests) |

Tidak ada credential dicetak. Tidak ada write Live.

---

## 4. PO → ProductionJob

- Inbox **read-only** — melihat SO tidak membuat job.
- Job hanya `POST /production/jobs` (aksi sah).
- Duplikat SO aktif dicegah lifecycle.
- Sync line dari detail Accurate; UNKNOWN tetap unknown.
- Cancel/revisi: soft-cancel + re-input; histori utuh (Iterasi 1B/2).

---

## 5. Payment gate

- Receipt wajib `posted` + `verifiable`; mismatch SO/cabang → 409.
- Gateway error/unconfigured → **503** (bukan PAID).
- `financial_payment_status` tetap **UNKNOWN** (bukan Lunas palsu).
- Bypass Direktur audited; tidak mengubah Accurate.

---

## 6. Surat Jalan — keputusan coverage

**Fakta:** Gateway **tidak** menyediakan list-all SJ.

**Jalur operasional terbatas yang sah:**
1. Loading V3 (event PostgreSQL) sebagai inventaris SJ yang sudah dikonfirmasi.
2. Opsional: SO `links.delivery_note_ids` → GET by-id (bukan census Accurate).

Label **COVERAGE TERBATAS** tetap. Loading PG **bukan** inventaris seluruh SJ Accurate.

Apakah menghalangi operasional awal? **Menghalangi inventaris SJ global / jadwal pengiriman lengkap dari Accurate.**
**Tidak menghalangi** Loading+POD untuk SJ yang id-nya sudah diketahui operator (scan/entry) dan tervalidasi by-id. Keputusan pengecualian risiko = **Direktur**, bukan agent.

---

## 7. Perbaikan lokal Iterasi 3 (WIP)

| ID | Severity | Root cause | Fix |
|---|---|---|---|
| ACC-01 | P1 | Inbox/`list_sales_orders` selalu `mode=live` | Provenance jujur: `live` / `fixture` / `unverified` + `live_verified` |
| ACC-02 | P1 | Empty upstream page + total sisa dianggap exhausted | Stop tanpa klaim inventory lengkap (`scan_incomplete`) |
| ACC-03 | P0 | Legacy tanpa workflow context: non-Direktur memakai total lintas cabang | Scoped scan untuk non-Direktur (role fallback) |
| ACC-04 | BLOCKED P0 | SJ list-all | Tidak dikarang |
| ACC-05 | BLOCKED P0 | Real/sandbox read-only di VM | Credential env kosong |

File: `accurate_read_gateway.py`, `production_inbox.py`, tests inbox + `test_accurate_integration_iter3.py`.

---

## 8. Bukti pengujian (pisah kategori)

| Kategori | Hasil |
|---|---|
| Fixture Gateway | **159 PASS** |
| Fixture/integration V3 Accurate + inbox + production + authz | **529 PASS** (subset run) |
| Frontend Vitest / build | **225 PASS** / **PASS** |
| Sandbox Accurate | **BLOCKED** |
| Real read-only | **BLOCKED** |
| Browser Inbox/Payment vs Accurate Live | **BLOCKED** (no gateway env); Delivery fixture browser ada di Iterasi 2 |

---

## 9. Keputusan Direktur yang diperlukan

1. Apakah operasional awal boleh jalan dengan **COVERAGE TERBATAS** (Loading + SO-link + SJ by-id) tanpa list-all?
2. Kapan mengaktifkan Gateway live + injeksi secret ke environment staging?
3. Apakah kontrak receivable/invoice Accurate akan dibuat (saat ini financial=UNKNOWN)?
4. Enforced authz (PR #14) tetap HOLD hingga staging Accurate stabil?

---

## 10. Verdict

**READY FOR STAGING** hanya untuk jalur fixture / Gateway terkonfigurasi + smoke Owner.
**NOT READY FOR LIVE APPROVAL** — real read-only belum terbukti; SJ list-all BLOCKED; enforced HOLD.
