/** Slice 1I–1K — auditable Gap ERP V1 capability registry (not editable settings). */

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
    v3Source: "physical_cup_qty_from_events (pass1 ledger)",
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
    v1Behavior: "Packing hanya setelah seluruh warna/pass selesai",
    v3Source: "eligible_finished_qty_from_events + record_packing",
    frontend: "Official packing task blocked until finished",
    tests: "test_slice1j_multicolor_eligibility.py",
    status: "SELESAI",
    remainingGap: "Live multi-color PO verification",
    validation: "code_test",
    nextAction: "Staging: pass1 done / pass2 open → packing blocked",
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
    v1Behavior: "Screen setelah jadwal; Screen Kecil/Besar",
    v3Source: "prep screener + screen_size kecil|besar + history",
    frontend: "Panel V3 screen size select",
    tests: "test_slice1k_pod_screen.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified; migration not on VPS",
    validation: "code_test",
    nextAction: "Owner approve Alembic 0007 on staging; smoke screen size",
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
    id: "delivery.pod_schema",
    roleModule: "Driver / Logistik",
    v1Behavior: "Schema attachment POD (4 purpose)",
    v3Source: "production_attachments + Alembic 20261112_0007",
    frontend: "—",
    tests: "test_slice1k_pod_screen.py alembic",
    status: "SELESAI",
    remainingGap: "Staging migration BLOCKED until Owner approval",
    validation: "code_test",
    nextAction: "Owner approve migration on private staging",
  },
  {
    id: "delivery.pod_storage",
    roleModule: "Driver / Logistik",
    v1Behavior: "Private local attachment storage + SHA-256",
    v3Source: "V3_ATTACHMENT_ROOT local FS; authz upload/download",
    frontend: "multipart upload Panel V3",
    tests: "test_slice1k_pod_screen.py",
    status: "SELESAI",
    remainingGap: "Live staging path/permissions not verified",
    validation: "code_test",
    nextAction: "Staging storage path config + smoke",
  },
  {
    id: "delivery.pod_multi_evidence",
    roleModule: "Driver / Logistik",
    v1Behavior: "2 foto + TTD pengirim/penerima + nama penerima",
    v3Source: "record_pod binds 4 attachments atomically",
    frontend: "Panel V3 POD 4 file inputs",
    tests: "test_slice1k_pod_screen.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified; staging migration pending",
    validation: "code_test",
    nextAction: "Private Staging acceptance with real SJ",
  },
  {
    id: "delivery.loading_task",
    roleModule: "Driver / Tugas Tim",
    v1Behavior: "Loading task after packing + SJ",
    v3Source: "derive loading from packing + loading events",
    frontend: "Official Tugas Tim",
    tests: "test_slice1k_pod_screen.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified",
    validation: "code_test",
    nextAction: "Staging Tugas Tim loading smoke",
  },
  {
    id: "delivery.pengiriman_task",
    roleModule: "Driver / Tugas Tim",
    v1Behavior: "Pengiriman done only with compliant POD attachments",
    v3Source: "derive delivery; legacy POD without attachments ≠ done",
    frontend: "Official Tugas Tim",
    tests: "test_slice1k_pod_screen.py",
    status: "SELESAI",
    remainingGap: "Live staging not verified",
    validation: "code_test",
    nextAction: "Staging Tugas Tim delivery smoke",
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
