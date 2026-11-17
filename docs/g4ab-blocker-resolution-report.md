# G4 Blocker Resolution — Outstanding (G4A) + SJ List (G4B)

**WIB / Asia/Jakarta:** 2026-11-17 · NO COMMIT · NO VPS · NO LIVE WRITES  
**Direktur:** Opsi B — Staging Acceptance HOLD sampai Outstanding + daftar SJ terbukti.  
**Env agent:** `ACCURATE_*` **EMPTY** → live read-only **tidak dijalankan**.

## Endpoint resmi & referensi

| Area | Path resmi Accurate | Scope | Referensi |
|---|---|---|---|
| G4A Outstanding | `GET /api/sales-invoice/list.do` + `detail.do` | `sales_invoice_view` | Accurate OpenAPI mirror (`tickernelz/accurate-openapi` llms.txt); SwaggerHub `cpssoft/accurate-online-public-api`; filter `filter.outstanding` / `outstandingFilter` |
| G4A Owing field | `primeOwing` (detail authoritative); aliases `owingAmount`/`owing` | — | Practitioner evidence: list `totalAmount` = nilai faktur penuh, **bukan** sisa piutang |
| G4B SJ list | `GET /api/delivery-order/list.do` | `delivery_order_view` | OpenAPI: `sp.page`, `sp.pageSize`, `fields`, filters keywords/branch/customer/shipDate/transDate |
| G4B SJ detail | `GET /api/delivery-order/detail.do?id=` | `delivery_order_view` | Internal `id` dari list → detail |

V3 gateway memakai prefix API Token: `/accurate/api/...` (sama pola SO/receipt yang sudah terbukti).

## Kontrak request/response (V3 gateway)

### G4A — `GET /sales-invoices` / `GET /sales-invoices/{id}`
- Upstream: `sales-invoice/list.do|detail.do`
- Query list: `keywords`, `outstanding_only`, `page`, `limit` → `sp.page` / `sp.pageSize` / `filter.outstanding`
- Response fields: `accurate_id`, `number`, `invoice_total`, `outstanding_amount` (owing), `paid_amount`, `financial_payment_status` ∈ {Belum Bayar, Sebagian, Lunas} **hanya** jika owing field ada; else null → V3 tetap **UNKNOWN**
- `verified=true` hanya pada live detail dengan `owing_field_present`
- `reconciliation`: count/unique/dup; `full_universe_verified=false` selalu sampai census Live multi-page Owner-approved

### G4B — `GET /delivery-notes` / `GET /delivery-notes/{id}`
- Upstream: `delivery-order/list.do|detail.do`
- List summary: `accurate_id`, `number`, `status`, customer/branch, `detail_lookup` pakai internal id
- `full_accurate_sj_universe=false`; satu halaman **bukan** census
- Detail tetap prefer `id` numerik

## Bukti verifikasi read-only

| Bukti | Hasil |
|---|---|
| Dokumentasi OpenAPI path+filter | **PASS** (dokumen) |
| Implementasi lokal + fixture | **PASS** |
| Live Accurate list/detail/recon | **BLOCKED** — credential env kosong; tidak ada probe Live |
| Klaim coverage penuh dari sampel | **DITOLAK** (`full_universe_verified=false`) |

## Hasil tes (focused)

| Suite | Hasil |
|---|---|
| Gateway G4A/G4B + coverage + live_fail_closed + gateway | **20 PASS** |
| Backend coverage + payment UNKNOWN fail-closed | **3 PASS** |

## Blocker tersisa

1. **Live credentials** belum diinjeksikan ke environment → tidak ada HTTP 200 Live untuk invoice/SJ list.
2. **Scope token** (`sales_invoice_view`, `delivery_order_view`) belum dibuktikan di Live.
3. **Rekonsiliasi multi-page Live** (unique id vs `sp.rowCount`) belum dijalankan.
4. Staging Acceptance tetap **HOLD** per Direktur sampai (1)–(3) hijau.

## Verdict

| Gate | Verdict |
|---|---|
| **G4A Outstanding** | **BLOCKED (DOCUMENTED + CODE READY, LIVE UNVERIFIED)** — UNKNOWN tetap default |
| **G4B SJ list** | **BLOCKED (DOCUMENTED + CODE READY, LIVE UNVERIFIED)** — `COVERAGE_TERBATAS` tetap |

**STOP** — tidak lanjut Tahap H tanpa persetujuan Direktur.
