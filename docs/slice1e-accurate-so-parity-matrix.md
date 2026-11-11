# Slice 1E — Accurate SO detail parity matrix

**ERP V1 repo** `prasnda21-tech/eternal-packaging`: **not readable** from this agent (GitHub 404).  
Parity uses Owner Slice 0 live probe + prior V3/V49 notes. No V1 code was modified.

| Accurate raw (typical) | V1 normalized (documented) | V3 Gateway | V3 Backend | V3 UI | Status |
|---|---|---|---|---|---|
| `id` | accurate id | `accurate_id` | `accurate_id` | Accurate ID | **Supported** |
| `number` | SO number | `number` | `number`/`po_number` | Nomor PO | **Supported** |
| `transDate` | order date | `order_date` | `order_date` | Tanggal PO | **Supported** |
| `customer.name` | customer | `customer` | `customer` | Pelanggan | **Supported** |
| `toAddress` / address | address | `address` | `address` | Alamat | **Supported** (when Accurate returns) |
| payment term fields | payment terms | `payment_terms` | `payment_terms` | Syarat bayar | **Supported** (when present) |
| expedition fields | expedition | `expedition` | `expedition` | Ekspedisi | **Supported** (when present) |
| estimated delivery | deadline | `estimated_delivery` | `deadline` | Estimasi kirim | **Supported** (when present) |
| delivery zone fields | zone | `delivery_zone` | `delivery_zone` | Zona | **Supported** (when present) |
| `salesPersonName` / salesPerson | salesperson | `sales` | `sales` | Sales | **Supported** (when present) |
| created user fields | creator | `created_by_user` | `created_by_user` | Pembuat PO | **Supported** (when present; ≠ sales) |
| `branch` / `branchName` | branch | `branch`/`branch_name` | `branch_id`+`branch_name` | Cabang | **Supported** — never invent name from id `50`/`150` |
| Buffer | `orders.buffer_stock` | `buffer_stock` | passthrough | Buffer | **Unproven in live sample** → null |
| Urgent/priority | priority + workflow | `urgent_state` | passthrough | Urgent | **Unproven in live sample** → null |
| `detailItem.id` | accurate_line_id | `accurate_line_id` | same | line id | **Supported** |
| `itemId` / item.id | item id | `accurate_item_id` | same | item id | **Supported** |
| `itemNo` | sku | `item_code` | same | Kode | **Supported** |
| `detailName` | name | `name` | same | Nama | **Supported** |
| `quantity` | qty | `quantity` | same | Qty | **Supported** |
| `itemUnit` | uom | `unit` | same | Satuan | **Supported** (object or string) |
| explicit process | `production_process` print\|non_print | same | same | Cetak/Tidak Cetak | **Only if explicit** — else `unknown` (no blank→print) |
| color fields | color | `color` | same | Warna | **Supported** when field present |
| line notes | notes | `notes` | same | Catatan | **Supported** when present |
| charField*/numericField* | unverified mapping | not auto-mapped | — | — | **Unverified** — never auto Buffer/Urgent/print |

## List vs detail strategy

- Accurate `sales-order/list.do` is **summary-only** (no `detailItem`).
- Inbox keeps server-side pagination; produk/qty filled via **bounded** detail enrich (concurrency 3), plus on Detail PO open.
- No DB migration; V3 DB is not a second source of truth for Accurate lines.
