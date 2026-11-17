# G4 Live Evidence Finalization

**WIB / Asia/Jakarta:** 2026-11-17  
**NO COMMIT · NO DEPLOY · NO VPS MOD · NO LIVE WRITES**  
**Tahap H:** HOLD sampai persetujuan Direktur

## Bukti Direktur (VPS) — diterima

### G4A
- Invoice list/detail Live PASS; `primeOwing` tersedia
- Sampel 20: 7 ZERO/Lunas · 12 FULL/Belum Bayar · 1 PARTIAL/Sebagian · tanpa anomali

### G4B
- delivery-order list/detail Live PASS
- rowCount 16871 · unique 16871 · dup 0 · missing 0 · failed_pages 0 · `census_scan_pass true`
- Snapshot atomik **tidak dijamin**

## Finalisasi lokal

| Area | Perubahan |
|---|---|
| Outstanding | `primeOwing` otoritatif; `totalAmount` ≠ sisa; label Lunas/Belum Bayar/Sebagian; invalid → UNKNOWN |
| Payment gate | Wajib `verified` + source + owing numerik; tolak `owing_source_key=totalAmount` |
| SJ discovery | list.do → internal id → detail.do |
| Reconcile | pagination/dedup/metadata/`census_scan_pass`; `full_universe_verified=false`; `atomic_snapshot_guaranteed=false` |
| Coverage UI | `coverage_label` + flags atomic/universe |

## Hasil tes
Gateway finalize/G4AB/coverage/fail-closed **14 PASS** · Backend coverage/payment **4 PASS** · FE delivery **4 PASS**

## Verdict

| Gate | Verdict |
|---|---|
| **G4A Outstanding** | **READY (mapping)** — Live evidence Director; fail-closed UNKNOWN tetap |
| **G4B SJ list** | **READY (discovery + census_scan)** — bukan atomic full universe |
| **Tahap H** | **HOLD** — menunggu persetujuan Direktur (deploy gateway routes staging masih terpisah) |
