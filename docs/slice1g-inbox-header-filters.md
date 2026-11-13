# Slice 1G — Inbox Accurate header filters

## Root cause

Inbox (`v36InboxView`) used a plain `v36-table` with static headers. Jadwal Produksi already used Excel-style `sheet-filter-trigger` + `openSheetFilter`. Filters were inconsistent.

## Policy

**Mode A only (default):** filter/sort the currently loaded Accurate page. Label: *Filter halaman ini*. Never rewrite Accurate grand-total metadata.

**Mode B:** not available — Backend/Gateway has no cross-page filter query. UI states the limitation explicitly. No automatic multi-page scan.

## Reuse

Dropdown UX mirrors Jadwal Produksi (`sheet-filter-menu` on `document.body` so overflow is not clipped). Inbox keeps its own `inboxColFilters` / `inboxSort` state so schedule filters are not mixed.

## Multi-item

Line fields match if **any** line token matches. One PO remains one row. KPI counts unique loaded POs only.
