/** Slice 1I — auditable Gap ERP V1 capability registry (not editable settings). */

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
  },
  {
    id: "qty.physical_multicolor",
    roleModule: "Operator / Packing",
    v1Behavior: "Multiwarna tidak menggandakan qty fisik cup",
    v3Source: "physical_cup_qty_from_events + record_packing color_pass=1",
    frontend: "KPI Jadwal printPhysicalQty",
    tests: "test_slice1i_quantity_integrity.py",
    status: "SELESAI",
    remainingGap: "Live multi-color PO verification",
    validation: "code_test",
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
  },
  {
    id: "screener.after_schedule",
    roleModule: "Screener",
    v1Behavior: "Screen actionable setelah jadwal",
    v3Source: "prep screener + derive screen",
    frontend: "Panel V3",
    tests: "test_slice1h_team_tasks.py",
    status: "PARSIAL",
    remainingGap: "Screen Kecil/Besar metadata tidak ada di schema → BLOCKED field",
    validation: "code_test",
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
  },
  {
    id: "delivery.pod_multi_evidence",
    roleModule: "Driver / Logistik",
    v1Behavior: "2 foto + TTD pengirim/penerima + nama penerima",
    v3Source: "record_pod single evidence_ref",
    frontend: "Panel V3 POD",
    tests: "phase4 POD qty tests (single evidence)",
    status: "BLOCKED",
    remainingGap:
      "Schema/attachment storage untuk multi-bukti POD belum ada — butuh kontrak Owner",
    validation: "code_test",
  },
  {
    id: "payment.accurate_receipt",
    roleModule: "Finance",
    v1Behavior: "Payment gate dari receipt Accurate efektif",
    v3Source: "require_valid_receipt / bypass",
    frontend: "Panel V3 payment",
    tests: "accurate_evidence + workflow",
    status: "PARSIAL",
    remainingGap: "Live gateway credentials required for staging verify",
    validation: "live_staging_not_verified",
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
  },
  {
    id: "payroll.official_posting",
    roleModule: "Payroll",
    v1Behavior: "Posting slip gaji resmi",
    v3Source: "payroll APIs exist; posting financial not approved",
    frontend: "demo rates localStorage",
    tests: "payroll unit",
    status: "BLOCKED",
    remainingGap: "No approved financial posting contract",
    validation: "code_test",
  },
];

export function capabilityStatusClass(status: CapabilityStatus): string {
  if (status === "SELESAI") return "ok";
  if (status === "PARSIAL") return "partial";
  if (status === "BLOCKED") return "blocked";
  return "missing";
}
