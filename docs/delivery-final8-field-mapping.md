# Delivery Final-8 ↔ Accurate SJ (Live-verified gate)

**Live bukti VPS:** `GET /delivery-notes/120055` → HTTP 200, `source=accurate_live`, `live_verified=true`, `status=DIFAKTUR`, `line_count=1`  
**Lookup:** prefer Accurate **internal id** (`detail.do?id=`); nomor SJ = identitas bisnis.  
**DIFAKTUR ≠ POD / terkirim.**

## Mapping selesai (normalize lokal)

| Output V3 | Sumber Accurate | Catatan |
|---|---|---|
| `accurate_id` / path id | `id` (mis. 120055) | Parameter detail.do |
| `number` | `number` | Identitas bisnis SJ |
| `sj_printed_at` | `printedTime` → `deliveryPrintedTime` → `printDate`… | ≠ `shipDate`/`shipped_at` |
| `print_user_name` | `printUserName` | Identitas pencetak |
| `expedition` | `shipment.name` (+ kunci expedition) | Cetakan Ekspedisi (mis. OUTLET) |
| `customer_phone` | field kontak customer terbukti | Else Belum terhubung |
| `outlet` | `outlet` / `outletName` header saja | ≠ branch, ≠ expedition |
| `item_outlets` | `detailItem[].outlet` | Agregasi; kosong → Belum terhubung |
| signers ×4 | kunci signer eksplisit saja | Ruang tanda tangan kosong ≠ paraf |
| `pod_evidence` | selalu `false` dari DN normalize | POD hanya dari alur V3 |
| SO `links.delivery_note_ids` | prefer `id`, fallback `number` | + `delivery_note_numbers` |

## Field belum tersedia / Belum terhubung sampai API mengisi

- Header **Outlet** (jika Accurate tidak kirim `outlet`)
- **Outlet per item** jika `detailItem.outlet` kosong
- **Gudang / Cek Barang / Kurir / Penerima** tanpa kunci signer
- Telepon jika objek customer tanpa field kontak

## Blocker tersisa

1. Konfirmasi payload Live penuh untuk 120055 memuat `printedTime`/`printUserName`/`customer.mobilePhone` (tanpa paste PII).  
2. Wiring V3 API → gateway Live di environment dengan secrets (di luar scope perubahan VPS gateway).
