# Slice 1F — Full Accurate PO fields in inbox + sales mapping

**ERP V1 repo** `prasnda21-tech/eternal-packaging`: **not readable** (GitHub 404).  
No V1 code was inspected or modified. Mapping uses Accurate Online fields + prior V3 Slice 0/1E notes.

## Sales rule

- Prefer `salesmanList` / nested sales person fields.
- Expose `sales` + `sales_source`.
- Never fall back to document creator, branch name, or login user when sales is absent.

## UI

- One table row per PO; multi-item fields use newline-joined summaries (not duplicate PO rows).
- Sheet pref key bumped to `eternal_v2_production_sheet_columns_v6`.
- Column presets: Operasional / Administrasi / Barang / Semua.
- Sticky No PO + Pelanggan.
- Null Buffer/Urgent → `Belum terverifikasi` (not false Ya/Tidak).
- Bounded detail enrich concurrency remains **3** (Slice 1E).
