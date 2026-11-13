# Slice 1H — Jadwal gates + Tugas Tim (canonical)

## Canonical source

One read path for cards / sheet / schedule:

1. **Official** `GET|POST /api/v1/production/jobs/tasks` derived from existing `ProductionJob` tables (no migration).
2. **Live fallback** when sync belum siap: `flow31Tasks` + order/job gates (`design_status` / `payment_status` / `productionAssignments`) — never demo catalog invent.

## Jadwal Produksi

- Print lines visible from PO entry **before ACC**.
- Unknown classification is separate (status *Proses Belum Terverifikasi*); qty unknown tidak masuk Total Qty Cetak.
- Schedule **save** blocked until Design + Payment gates satisfied (`gates_open_for_schedule` + UI `bothOfficialGatesOk` / `validateScheduleDraft`).
- Live: empty `productionAssignments` until V3 board evidence; no Terproses→fake run invent.

## Tugas Tim

| Process | Tasks |
|---|---|
| PRINT | Upload Design (tanpa payment) → Approval Design; Schedule Siap when payment OK (save masih butuh design); Screen/Prepare only after assignment |
| NON_PRINT | stockprep/stockpack only — no fake screen/sample/print |
| UNKNOWN | skip fake task chain (klasifikasi di Jadwal/Inbox) |

Cards/`allTasks` keep only **Siap | Selesai | Sedang** — blocks Prepare Cup inflation from Menunggu stockprep.

## Root cause fixed

`processSnapshot` null + filter `=== PRINT` → empty schedule/KPI 0; live itemIds miss demo catalog → NON_PRINT/stockprep mapped to Prepare Cup; Terproses invented run. Fixed via Accurate `production_process` → PRINT/NON_PRINT/UNKNOWN, inbox stage stay, official/live-derived tasks.
