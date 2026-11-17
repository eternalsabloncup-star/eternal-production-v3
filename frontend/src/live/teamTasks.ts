/** Slice 1H — map official V3 team-task API → Tugas Tim UI rows. */

export type OfficialTaskState =
  | "pending"
  | "blocked"
  | "actionable"
  | "done"
  | "partial";

export type OfficialTask = {
  id: string;
  kind: string;
  group: string;
  role: string;
  label: string;
  verb: string;
  state: OfficialTaskState;
  visible?: boolean;
  reason?: string | null;
  job_id: number;
  accurate_so_number: string;
  customer_name?: string | null;
  branch_id?: string;
  design_status?: string;
  payment_status?: string;
  processing_status?: string;
};

export type UiTaskStatus = "Siap" | "Menunggu" | "Selesai" | "Loading Parsial";

export function officialStateToUi(state: OfficialTaskState): UiTaskStatus {
  if (state === "done") return "Selesai";
  if (state === "actionable") return "Siap";
  if (state === "partial") return "Loading Parsial";
  return "Menunggu";
}

export const OFFICIAL_TASK_CARD_DEFS = [
  {
    id: "design_upload",
    role: "Designer",
    label: "Upload Design",
    verb: "Upload desain",
  },
  {
    id: "design_approve",
    role: "Designer",
    label: "Approval Design",
    verb: "Sahkan desain",
  },
  {
    id: "schedule",
    role: "Kepala Produksi",
    label: "Penjadwalan",
    verb: "Atur jadwal",
  },
  { id: "screen", role: "Screener", label: "Screen", verb: "Input screen" },
  {
    id: "prepare",
    role: "Helper",
    label: "Prepare Cup",
    verb: "Input cup siap",
  },
  {
    id: "sample",
    role: "Operator",
    label: "Upload Sampel Cetak",
    verb: "Upload sampel",
  },
  {
    id: "sample_approve",
    role: "Operator",
    label: "Approval Sampel Cetak",
    verb: "Approve sampel",
  },
  {
    id: "print",
    role: "Operator",
    label: "Konfirmasi Qty Cetak",
    verb: "Konfirmasi cetak",
  },
  { id: "packing", role: "Helper", label: "Packing", verb: "Input packing" },
  {
    id: "stockprep",
    role: "Helper",
    label: "Persiapan Barang Non-Cetak",
    verb: "Siapkan barang",
  },
  {
    id: "stockpack",
    role: "Helper",
    label: "Packing Barang Non-Cetak",
    verb: "Konfirmasi packing",
  },
  {
    id: "loading",
    role: "Driver",
    label: "Loading / Muat Barang",
    verb: "Kerjakan loading",
  },
  {
    id: "delivery",
    role: "Driver",
    label: "Pengiriman / POD",
    verb: "Kerjakan pengiriman",
  },
] as const;

export function mapOfficialTasksToRows(
  tasks: OfficialTask[],
  ordersById: Map<string, { id: string; name?: string; branch?: string; item?: string; ship?: string }>,
): Array<{
  o: { id: string; name?: string; branch?: string; item?: string; ship?: string };
  t: { id: string; role: string; label: string; verb: string };
  e: { status: UiTaskStatus; note: string; updated: string };
  status: UiTaskStatus;
  lineItem: string;
  official: OfficialTask;
}> {
  return (tasks || [])
    .filter((t) => t && t.visible !== false)
    .map((task) => {
      const order =
        ordersById.get(task.accurate_so_number) || {
          id: task.accurate_so_number,
          name: task.customer_name || task.accurate_so_number,
          branch: task.branch_id || "",
          item: "",
          ship: "",
        };
      const status = officialStateToUi(task.state);
      return {
        o: order,
        t: {
          id: task.kind,
          role: task.role,
          label: task.label,
          verb: task.verb,
        },
        e: {
          status,
          note: task.reason || "",
          updated: "V3 official",
        },
        status,
        lineItem: order.item || "",
        official: task,
      };
    });
}

export function syncGateFromJobStatuses(job: {
  design_status?: string | null;
  payment_status?: string | null;
}): { design: string; payment: string } {
  const map = (v: string | null | undefined) => {
    if (v === "approved") return "APPROVED";
    if (v === "bypassed") return "BYPASSED";
    if (v === "rejected") return "REJECTED";
    return "PENDING";
  };
  return {
    design: map(job.design_status),
    payment: map(job.payment_status),
  };
}
