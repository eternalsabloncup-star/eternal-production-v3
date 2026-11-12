# Slice 1H — Accurate live field parity + inbox polish

## Root causes

| Field | Cause |
|---|---|
| Sales | Nested `salesmanList[].salesman.name` not read; enrich wiped list sales when detail omitted sales |
| Ekspedisi / Zona | Native keys often absent; Eternal uses **labeled** Accurate custom fields |
| Status Pesanan / Buffer | Hard-null without label-proven custom field |
| Proses / Warna | Only explicit `production_process` / `color`; unlabeled `charField*` ignored (correct) — labeled Proses/Warna now mapped |

## Mapping rule

Custom fields map **only when companion label matches** (e.g. `charField1Name: "Ekspedisi"`). Unlabeled noise stays null/unknown.

## Inbox UI

- Column drag/drop + keyboard ←→ (No PO / Pelanggan locked sticky)
- Pref key `eternal_v3_inbox_column_order_v1`
- PO number `title` for full value; denser row height; filter menu escapes overflow

## Live probe

This agent VM: gateway `live_credentials_present=false` — acceptance PO not queried here. Staging re-check required after deploy.