# Phase 2 — V49 contextual button → API mapping

Source UI: `frontend/public/production.html` (V49).  
API prefix: `/api/v1/production/jobs`.

No global transaction buttons. Each action is SO/job-contextual.

| V49 UI action | UI function / control | Backend endpoint | Notes |
|---|---|---|---|
| Ensure / open production job | inbox → Terproses / PO detail | `POST /` | Creates or returns `production_jobs` + WO mirror |
| Job gate status | PO detail / tracking | `GET /{job_id}` | design/payment/sample/processing mirrors |
| Upload design file | `v26Action('designFile')`, intake design | `POST /{job_id}/design/versions` | Version history; prior approved → superseded |
| Approve design | `v26SourceGate('design',true)`, `intakeAction('design')` | `POST /design/versions/{id}/decision` | `decision=approved` |
| Design bypass | `v28Action('bypass')` (design path) | same decision endpoint with `bypass=true` + reason | Requires `production.design.bypass` |
| Customer approval alt | intake / design drawer | decision with `customer_approval=true` | Audited on version row |
| Reject / revise design | design reject controls | decision `rejected`; re-upload new version | History retained |
| Record Accurate receipt | `intakeAction('payment')`, payment detail | `POST /{job_id}/payment/receipts` | Opens payment gate; no bare manual approve |
| Payment bypass | `v28Action('bypass')` | `POST /{job_id}/payment/bypass` | Reason + actor required |
| Revoke payment bypass | `v28Action('revokeBypass')` | `POST /payment/bypass/{id}/revoke` | Re-evaluates gate |
| Invalidate / reverse receipt | Accurate reverse simulation | `POST /payment/receipts/{id}/invalidate` | Closes gate if no other evidence |
| Create schedule assignment | `v26Action('assign')`, schedule editor | `POST /{job_id}/schedule/assignments` | Operator/machine/date/pass/qty; gates required |
| Cancel remaining qty | `cancelRemaining` | `POST /schedule/assignments/{id}/cancel-remaining` | Never cancels confirmed output |
| Transfer remaining | `v23TransferRemaining`, `v26MoveAction` | `POST /schedule/assignments/{id}/transfer-remaining` | New assignment + provenance |
| Screener prepare | workflow Screen / `v26Action('prepare')` | `POST /{job_id}/prep/screener` | Evidence + idempotency; parallel after gates |
| Helper prepare cups | Prepare Cup / `v26Action('prepare')` | `POST /{job_id}/prep/helper` | PO ceiling + cannot reduce below confirmed output |
| Upload sample | sample drawer / Renea sample | `POST /{job_id}/samples` | Version + optional assignment |
| Approve / reject sample | `approveSample`, sample decision UI | `POST /samples/{id}/decision` | Blocks print output while pending |
| Confirm operator output | print-on / output modal | `POST /{job_id}/outputs` | Idempotency key; physical vs pass ops |
| Correct output | integrity / revision controls | `POST /{job_id}/outputs/corrections` | Compensating event only |
| Record reject | `v28Action('reject')` | `POST /{job_id}/rejects` | Assignment/pass/lot/reason |
| Verify reject | `v28Action('approveReject')` | `POST /rejects/{event_id}/verify` | Authorized verification |
| Replacement schedule | `v28Action('scheduleReplacement')` | create assignment after cancel/transfer | No PO physical qty duplication |
| Packing batch | packing stage / pack helpers | `POST /{job_id}/packing` | Overpack guard from ledger |
| Loading against SJ | `v26ShipAction(...,'loading')`, `loadSJ` | `POST /{job_id}/loading` | Accurate SJ identity required |
| Proof of delivery | `confirmDriverDelivery`, `v26ShipAction(...,'pod')` | `POST /{job_id}/pod` | Evidence + receiver; cannot bypass Loading |
| Cancel / supersede SJ | `v26ShipAction(...,'delete')` | `POST /{job_id}/sj/cancel` | History preserved as `sj_cancelled` |
| Live tracking timeline | tracking drawer / monitor | `GET /{job_id}/tracking` | Authoritative event ledger |
| Operator payroll rates | salary slip tarif inputs | `POST/GET /production/payroll/rates` | Effective-dated + historical close |
| Operator payroll period | `payCalc` / `showSalarySlip` | `POST/GET /production/payroll/runs` | Confirmed events only; idempotent run |

## Explicitly out of scope for Phase 2 wiring

- Mapping Proses Barang management UI
- Production Approval stage buttons
- Global “transaction” toolbar actions
