# G4 — Accurate Integration (Outstanding + SJ Coverage)

**WIB:** 2026-11-17 · HEAD `36abda1` · NO COMMIT · NO VPS MOD · NO LIVE WRITES  
**Carry-forward G3:** Gateway/SJ Live id mapping lokal hijau.

## Outstanding: **BLOCKED**

| Item | Fakta |
|---|---|
| Gateway endpoint | **Tidak ada** |
| Upstream Accurate | Tidak dikontrak di V3 (bukan sales-receipt) |
| Bukti bayar yang ada | `GET /receipts/{id}` → gate produksi (bukan settlement invoice) |
| V3 default | `financial_payment_status=UNKNOWN` |
| Fail-closed | `accurate_financial` hanya diterima jika `verified=true` **dan** `source` ∈ `{accurate_receivable, accurate_sales_invoice, owner_verified_outstanding}` |

## SJ coverage: **BLOCKED** (COVERAGE TERBATAS — fail-closed)

| Item | Strategi terbukti |
|---|---|
| List-all | **Tidak ada** `GET /delivery-notes` / `delivery-order/list.do` di gateway |
| Detail | `GET /delivery-notes/{internal_id}` → `detail.do?id=` |
| Discovery | (1) V3 Loading events — termasuk SJ tanpa SO setelah load by id · (2) SO `links.delivery_note_ids` (prefer id) |
| Full universe | `false` |

## Keputusan Direktur (jika diperlukan)

```
KEPUTUSAN DIREKTUR DIBUTUHKAN

ID: G4-01
Modul: Accurate Outstanding / SJ census
Masalah: Outstanding invoice/AR dan list-all SJ belum punya endpoint resmi di gateway.
Aturan V1: (settlement Accurate / inventaris SJ penuh — perlu konfirmasi Owner)
Aturan V3: UNKNOWN finansial; SJ = Loading + SO-link by id (COVERAGE TERBATAS)
Pilihan A: Terima COVERAGE TERBATAS + UNKNOWN sampai Owner pin path Accurate (receivable + delivery-order/list)
Pilihan B: Owner sebutkan path Accurate resmi sekarang → agent menambah route gateway read-only
Rekomendasi: A untuk operasi awal; B hanya dengan path tertulis
Dampak: A = gap inventaris/settlement terlihat jujur; B prematur tanpa path = risiko invent endpoint
Pertanyaan kepada Direktur: Setujui A, atau berikan path Accurate resmi untuk outstanding dan/atau SJ list?
```

## Verdict G4

**PARTIAL READY** — kontrak fail-closed Outstanding + SJ coverage terkunci lokal; **Outstanding BLOCKED**, **SJ full coverage BLOCKED**; siap gate berikutnya hanya untuk jalur terbatas (receipt gate + SJ by id).
