# Phase 2.1 — Workflow completeness matrix

**ERP V1 source:** `prasnda21-tech/eternal-packaging` was **not readable** from this agent (GitHub 404).  
Behavioral parity uses **V49** (`frontend/public/production.html`) + Phase 2 engine rules. Intentional V3 differences are marked.

| V1 / V49 business rule | V3 API | DB model | Test | V49 contextual action |
|---|---|---|---|---|
| Design upload + version history | `POST .../design/versions` | `design_versions` | e2e | `v26Action('designFile')` |
| Design approve / bypass / customer alt | `POST .../design/versions/{id}/decision` | `design_versions` | e2e | `v26SourceGate` / intake design |
| New design revokes prior approval | same upload path supersedes | `design_versions.status` | e2e | design change |
| Payment via Accurate receipt only | `POST .../payment/receipts` | `payment_receipt_refs` | e2e | `intakeAction('payment')` |
| Payment bypass + revoke | bypass / revoke endpoints | `payment_bypasses` | e2e | `v28Action('bypass'/'revokeBypass')` |
| Invalidate receipt closes unfinished gate | `.../payment/receipts/{id}/invalidate` | `payment_receipt_refs` | e2e | Accurate reverse sim |
| Schedule multi-assignment | `POST .../schedule/assignments` | `schedule_assignments` | e2e | `v26Action('assign')` |
| Cancel remaining only | `.../cancel-remaining` | `schedule_assignments` | e2e | `cancelRemaining` |
| Transfer remaining + provenance | `.../transfer-remaining` | `schedule_assignments` | (engine) | `v23TransferRemaining` / `v26MoveAction` |
| Screener prep + evidence | `POST .../prep/screener` | `prep_states`, `prep_events` | prep test | `v26Action('prepare')` screen field / workflow Screen |
| Helper prep + evidence | `POST .../prep/helper` | `prep_states`, `prep_events` | prep test | `v26Action('prepare')` cup field / Prepare Cup |
| Prep ≤ PO qty; cannot reduce below confirmed output | helper validations | `job_line_qtys` | prep test | `v25Prepare` guards |
| Prep partial + remaining vs PO | response `remaining_vs_po` | `job_line_qtys`/`prep_states` | e2e | parallel prep strip |
| Sample upload/decide; blocks print | samples endpoints | `sample_versions` | e2e | sample drawer / `approveSample` |
| Sample approve needs screen+prepared > 0 | decide_sample gate | `prep_states` | e2e | `approveSample` |
| Output immutable + idempotency | `POST .../outputs` | `production_events` | e2e | print confirm |
| Output ≤ prepared helper qty | confirm_output gate | `prep_states` | prep test | `printOn` `OUTPUT_OVER_PREPARED` |
| Reject + authorized verify | rejects + verify | `production_events` | e2e | `v28Action('reject'/'approveReject')` |
| Output correction compensating event | `.../outputs/corrections` | `production_events` | (API) | integrity / revision |
| Packing overpack guard | `POST .../packing` | `production_events` | e2e | packing stage |
| Loading / POD / SJ cancel | loading/pod/sj/cancel | `production_events` | e2e | `v26ShipAction`, `confirmDriverDelivery` |
| Live tracking from events | `GET .../tracking` | `production_events` | e2e | tracking drawer |
| Effective-dated operator rates | `POST/GET .../payroll/rates` | `operator_rates` | payroll test | salary slip tarif inputs |
| Period payroll from confirmed output only | `POST .../payroll/runs` | `payroll_runs`/`payroll_lines` | payroll test | `payCalc` / `showSalarySlip` |
| No duplicate wages (idempotent run) | payroll run unique key | `payroll_runs.idempotency_key` | payroll test | — |
| Verified reject adjusts eligible qty | payroll compute | `production_events` | (engine) | reject verified |
| Role/branch permissions | permission constants | `users.permissions` | auth + tests | role gates |

## Intentional V3 differences (V1 unread)

1. **Color wage bucket:** V49 demo buckets by item text “N warna”; V3 buckets each confirmed event by `color_pass` (1→one … 4→four) for multioperator attribution.
2. **Screen wage units:** V49 demo `screens+=1` per order; V3 credits one screen unit per `prep_screener` event linked to an assignment.
3. **Daily/overtime:** Rate table exists; period run does **not** invent attendance/OT from frontend — those components stay 0 until a timesheet source is added.
4. **Accurate receipt/SJ live validation:** stores identity refs; live gateway verification remains Phase 1 gateway scope / future slice.

## Remaining gaps

- Frontend live wiring of V49 buttons to these APIs
- Attendance/OT timesheet source for payroll components
- Live Accurate receipt/SJ validity checks on every gate
- Dedicated concurrency stress suite beyond unique-constraint idempotency
- Transfer-remaining / output-correction focused HTTP tests (engine covered)
