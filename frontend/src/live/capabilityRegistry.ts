/** Slice 1I/1J — auditable Gap ERP V1 capability registry (not editable settings). */

export type CapabilityStatus = "SELESAI" | "PARSIAL" | "BELUM" | "BLOCKED";
export type ValidationLevel =
  | "code_test"
  | "live_staging_verified"
  | "live_staging_not_verified";

export type Capability = {
  id: string;
  roleModule: string;
  v1Behavior: string;
  v3Source: string;
  frontend: string;
  tests: string;
  status: CapabilityStatus;
  remainingGap: string;
  validation: ValidationLevel;
  nextAction: string;
};

export const CAPABILITY_REGISTRY: Capability[] = [
  {
    id: "design.upload_without_payment",
    roleModule: "Designer",
    v1Behavior: "Upload desain tanpa menunggu payment",
    v3Source: "POST /jobs/{id}/design/versions + derive design_upload",
    frontend: "Panel V3 / Tugas Tim official",
    tests: "test_slice1h_team_tasks.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified in agent VM",
    validation: "live_staging_not_verified",
    nextAction: "Owner smoke on private staging",
  },
  {
    id: "design.approval_separate",
    roleModule: "Designer",
    v1Behavior: "Approval terpisah dari upload; revisi supersede",
    v3Source: "design_versions pending/decision",
    frontend: "Panel V3",
    tests: "test_slice1h_team_tasks.py",
    status: "SELESAI",
    remainingGap: "Customer approval UX live unverified",
    validation: "live_staging_not_verified",
    nextAction: "Staging UX check for reject/revise cycle",
  },
  {
    id: "schedule.print_before_acc",
    roleModule: "Kepala Produksi",
    v1Behavior: "Item cetak terlihat sebelum ACC; simpan butuh gate",
    v3Source: "liveScheduleMonitorRows + gates_open_for_schedule",
    frontend: "Jadwal Produksi",
    tests: "scheduleMonitor.test.ts + workflow e2e",
    status: "SELESAI",
    remainingGap: "Live staging smoke required",
    validation: "live_staging_not_verified",
    nextAction: "Staging: print lines visible before ACC",
  },
  {
    id: "qty.physical_multicolor",
    roleModule: "Operator / Packing",
    v1Behavior: "Multiwarna tidak menggandakan qty fisik cup",
    v3Source: "physical_cup_qty_from_events (pass1 ledger) — never sum passes",
    frontend: "KPI Jadwal printPhysicalQty",
    tests: "test_slice1i_quantity_integrity.py",
    status: "SELESAI",
    remainingGap: "Live multi-color PO verification",
    validation: "code_test",
    nextAction: "Staging multi-color PO smoke",
  },
  {
    id: "qty.finished_all_passes",
    roleModule: "Packing / Tugas Tim",
    v1Behavior: "Packing hanya setelah seluruh warna/pass selesai (min across passes)",
    v3Source: "eligible_finished_qty_from_events + record_packing required passes",
    frontend: "Official packing task blocked until finished",
    tests: "test_slice1j_multicolor_eligibility.py",
    status: "SELESAI",
    remainingGap: "Live multi-color PO verification",
    validation: "code_test",
    nextAction: "Staging: pass1 complete / pass2 open → packing blocked",
  },
  {
    id: "packing.event_contract",
    roleModule: "Helper Packing",
    v1Behavior: "Packing evidence → tugas packing selesai",
    v3Source: "packing_batch (+ alias packing_recorded consumers)",
    frontend: "Official tasks packing",
    tests: "test_slice1i_quantity_integrity.py",
    status: "SELESAI",
    remainingGap: "",
    validation: "code_test",
    nextAction: "None — keep regression green",
  },
  {
    id: "screener.after_schedule",
    roleModule: "Screener",
    v1Behavior: "Screen actionable setelah jadwal; Screen Kecil/Besar",
    v3Source: "prep screener + derive screen",
    frontend: "Panel V3 (no size select — schema missing)",
    tests: "test_slice1h_team_tasks.py",
    status: "PARSIAL",
    remainingGap: "screen_size on prep/assignment requires migration",
    validation: "code_test",
    nextAction: "Owner approve screen_size migration proposal",
  },
  {
    id: "helper.prepare_parallel",
    roleModule: "Helper",
    v1Behavior: "Prepare Cup paralel dengan screen setelah jadwal",
    v3Source: "prep helper + derive prepare",
    frontend: "Panel V3",
    tests: "test_slice1h_team_tasks.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified",
    validation: "live_staging_not_verified",
    nextAction: "Staging parallel screener/helper smoke",
  },
  {
    id: "delivery.pod_multi_evidence",
    roleModule: "Driver / Logistik",
    v1Behavior: "2 foto + TTD pengirim/penerima + nama penerima",
    v3Source: "record_pod single evidence_ref; remaining=loaded−prior pod",
    frontend: "Panel V3 POD (no fake multi-upload)",
    tests: "phase4 POD qty tests (single evidence)",
    status: "BLOCKED",
    remainingGap:
      "No attachment table / file ownership integrity — see docs/slice1j-migration-proposals.md",
    validation: "code_test",
    nextAction: "Owner approve POD attachment schema + storage",
  },
  {
    id: "payment.accurate_receipt",
    roleModule: "Finance",
    v1Behavior: "Payment gate dari receipt Accurate efektif / void / partial",
    v3Source: "require_valid_receipt / bypass / revoke",
    frontend: "Panel V3 payment",
    tests: "test_phase32_accurate_gateway.py",
    status: "PARSIAL",
    remainingGap: "Live gateway credentials required for staging verify",
    validation: "live_staging_not_verified",
    nextAction: "Staging with read-only Accurate credentials",
  },
  {
    id: "sla.working_days",
    roleModule: "Kepala Produksi",
    v1Behavior: "Target 1/3/5 hari kerja + kalender libur",
    v3Source: "—",
    frontend: "demo scheduleLead only",
    tests: "—",
    status: "BLOCKED",
    remainingGap: "Holiday calendar contract missing",
    validation: "code_test",
    nextAction: "Owner approve working-day calendar contract",
  },
  {
    id: "payroll.rate_read",
    roleModule: "Payroll",
    v1Behavior: "Baca tarif efektif per tanggal (read-only)",
    v3Source: "GET /production/payroll/rates",
    frontend: "Panel V3 rates read; settings localStorage = demo only",
    tests: "test_prep_payroll.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified",
    validation: "live_staging_not_verified",
    nextAction: "Staging rate read smoke; keep posting blocked",
  },
  {
    id: "payroll.official_posting",
    roleModule: "Payroll",
    v1Behavior: "Posting slip gaji resmi",
    v3Source: "payroll APIs exist; posting financial not approved",
    frontend: "demo rates localStorage (not authoritative)",
    tests: "payroll unit",
    status: "BLOCKED",
    remainingGap: "No approved financial posting contract",
    validation: "code_test",
    nextAction: "Owner approve financial posting contract",
  },
];

export function capabilityStatusClass(status: CapabilityStatus): string {
  if (status === "SELESAI") return "ok";
  if (status === "PARSIAL") return "partial";
  if (status === "BLOCKED") return "blocked";
  return "missing";
}
