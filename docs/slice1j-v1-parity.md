# Slice 1J — Remaining V1 parity (finished passes, blockers)

## Baseline

`887ac2a` → this slice on `cursor/v49-live-phase1-3e4e` (Draft PR #2).

## Implemented (safe, no migration)

### Multicolor packing eligibility

- Required passes = distinct `color_pass` on non-cancelled `schedule_assignments` for the SO line (default `{1}`).
- Eligible finished = `min(net qty per required pass)` where net = outputs + corrections − reject_verified.
- Packing / Tugas Tim packing gate use this eligibility — **pass 1 alone is never finished proof** when pass 2+ is scheduled.
- Payroll continues to use work-pass qty (`qty_pass_ops`), independent of finished cups.

Acceptance:

| Pass1 | Pass2 | Eligible pack |
|------:|------:|--------------:|
| 5000 | 0 | 0 |
| 5000 | 3000 | 3000 |
| 5000 | 5000 | 5000 |

### Capability registry

- Added `qty.finished_all_passes`, `payroll.rate_read`, `nextAction` column.
- POD / screen size / SLA / payroll posting remain honestly BLOCKED or PARSIAL.

## BLOCKED (Owner approval — see slice1j-migration-proposals.md)

1. POD multi-attachment storage
2. Screener `screen_size` (Kecil/Besar)
3. Working-day / holiday calendar
4. Official payroll posting

## Payment

CODE TESTED via gateway fixtures (`test_phase32_accurate_gateway.py`). LIVE NOT VERIFIED without staging Accurate credentials. No Accurate writes from Cursor.

## Constraints

No merge / no VPS / no DB migration / no public deploy / ERP V1 read-only.
