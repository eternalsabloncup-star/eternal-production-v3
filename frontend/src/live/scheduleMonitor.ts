/** Slice 1H — Jadwal Produksi early visibility + print classification (pure). */

export type ProcessKind = "PRINT" | "NON_PRINT" | "UNKNOWN";

export type ScheduleLineLike = {
  id?: string | null;
  name?: string | null;
  qty?: number | null;
  color?: string | null;
  production_process?: string | null;
  processSnapshot?: string | null;
};

export type ScheduleOrderLike = {
  id: string;
  name?: string;
  item?: string;
  qty?: number | null;
  qtyVerified?: boolean;
  done?: number | null;
  packed?: number | null;
  scheduledQty?: number | null;
  design_status?: string | null;
  payment_status?: string | null;
  approval?: boolean;
  productionAssignments?: Array<{
    id?: string;
    soLineId?: string;
    lineId?: string;
    colorIndex?: number;
    colorName?: string;
    operator?: string;
    machine?: string;
    targetQty?: number;
    workDate?: string;
  }> | null;
  sourceLines?: ScheduleLineLike[] | null;
};

export function processSnapshotFromAccurate(
  productionProcess: string | null | undefined,
): "PRINT" | "NON_PRINT" | "UNKNOWN" {
  if (productionProcess === "print") return "PRINT";
  if (productionProcess === "non_print") return "NON_PRINT";
  return "UNKNOWN";
}

export function effectiveLineProcess(line: ScheduleLineLike): ProcessKind {
  const snap = line.processSnapshot;
  if (snap === "PRINT" || snap === "NON_PRINT" || snap === "UNKNOWN") return snap;
  if (snap === "SERVICE") return "NON_PRINT";
  if (line.production_process === "print") return "PRINT";
  if (line.production_process === "non_print") return "NON_PRINT";
  return "UNKNOWN";
}

export function printLinesOf(order: ScheduleOrderLike): ScheduleLineLike[] {
  return (order.sourceLines || []).filter((l) => effectiveLineProcess(l) === "PRINT");
}

export function unknownLinesOf(order: ScheduleOrderLike): ScheduleLineLike[] {
  return (order.sourceLines || []).filter((l) => effectiveLineProcess(l) === "UNKNOWN");
}

export function printPhysicalQty(order: ScheduleOrderLike): number {
  return printLinesOf(order).reduce((sum, line) => {
    const n = Number(line.qty);
    return sum + (Number.isFinite(n) ? Math.max(0, n) : 0);
  }, 0);
}

export function unknownPhysicalQty(order: ScheduleOrderLike): number {
  return unknownLinesOf(order).reduce((sum, line) => {
    const n = Number(line.qty);
    return sum + (Number.isFinite(n) ? Math.max(0, n) : 0);
  }, 0);
}

export function gateLabelFromJob(
  status: string | null | undefined,
): "APPROVED" | "BYPASSED" | "PENDING" {
  const s = String(status || "").toLowerCase();
  if (s === "approved") return "APPROVED";
  if (s === "bypassed") return "BYPASSED";
  return "PENDING";
}

export function gateSatisfied(status: string | null | undefined): boolean {
  const label = gateLabelFromJob(status);
  return label === "APPROVED" || label === "BYPASSED";
}

export function bothGatesSatisfied(order: ScheduleOrderLike): boolean {
  if (order.design_status != null || order.payment_status != null) {
    return gateSatisfied(order.design_status) && gateSatisfied(order.payment_status);
  }
  return !!order.approval;
}

export type ScheduleMonitorStatus =
  | "Proses Belum Terverifikasi"
  | "Belum ACC Design"
  | "Belum ACC Payment"
  | "Siap Dijadwalkan"
  | "Sudah Dijadwalkan"
  | "Sedang Produksi"
  | "Selesai";

export function scheduleMonitorStatus(
  order: ScheduleOrderLike,
  opts: { process: ProcessKind; hasAssignment: boolean },
): ScheduleMonitorStatus {
  if (opts.process === "UNKNOWN") return "Proses Belum Terverifikasi";
  const qty = printPhysicalQty(order);
  const done = Math.max(0, Math.trunc(Number(order.done) || 0));
  const scheduled = Math.max(
    0,
    Math.trunc(Number(order.scheduledQty) || 0),
    opts.hasAssignment ? 1 : 0,
  );
  if (opts.hasAssignment || scheduled > 0) {
    if (qty > 0 && done >= qty) return "Selesai";
    if (done > 0) return "Sedang Produksi";
    return "Sudah Dijadwalkan";
  }
  const designOk = gateSatisfied(order.design_status) || !!order.approval;
  const paymentOk = gateSatisfied(order.payment_status) || !!order.approval;
  // Prefer independent gate labels when a job exists; approval alone is demo fallback.
  if (order.design_status != null || order.payment_status != null) {
    if (!gateSatisfied(order.design_status) && !gateSatisfied(order.payment_status)) {
      return "Belum ACC Design";
    }
    if (!gateSatisfied(order.design_status)) return "Belum ACC Design";
    if (!gateSatisfied(order.payment_status)) return "Belum ACC Payment";
    return "Siap Dijadwalkan";
  }
  if (!designOk) return "Belum ACC Design";
  if (!paymentOk) return "Belum ACC Payment";
  return "Siap Dijadwalkan";
}

export type MonitorRow = {
  orderId: string;
  lineId: string;
  process: ProcessKind;
  lineName: string;
  lineQty: number;
  colorName: string;
  colorIndex: number;
  assignmentId: string;
  assignmentQty: number;
  operator: string;
  machine: string;
  workDate: string;
  status: ScheduleMonitorStatus;
  designGate: "APPROVED" | "BYPASSED" | "PENDING";
  paymentGate: "APPROVED" | "BYPASSED" | "PENDING";
  schedulingAllowed: boolean;
  reason: string;
};

/** One row per print/unknown line (or per real assignment). Never duplicates physical qty across colours. */
export function buildScheduleMonitorRows(order: ScheduleOrderLike): MonitorRow[] {
  const designGate = gateLabelFromJob(order.design_status);
  const paymentGate = gateLabelFromJob(order.payment_status);
  const schedulingAllowed = bothGatesSatisfied(order);
  const rows: MonitorRow[] = [];
  const assignments = Array.isArray(order.productionAssignments)
    ? order.productionAssignments
    : [];

  for (const line of printLinesOf(order)) {
    const lineId = String(line.id || "");
    const lineName = String(line.name || order.item || "Item cetak");
    const lineQty = Number.isFinite(Number(line.qty)) ? Math.max(0, Number(line.qty)) : 0;
    const matching = assignments.filter(
      (a) => String(a.soLineId || a.lineId || "") === lineId,
    );
    if (matching.length) {
      matching.forEach((a, i) => {
        rows.push({
          orderId: order.id,
          lineId,
          process: "PRINT",
          lineName,
          lineQty,
          colorName: String(a.colorName || line.color || `Warna ${a.colorIndex || i + 1}`),
          colorIndex: Number(a.colorIndex) || i + 1,
          assignmentId: String(a.id || ""),
          assignmentQty: Math.max(0, Number(a.targetQty) || 0),
          operator: String(a.operator || ""),
          machine: String(a.machine || ""),
          workDate: String(a.workDate || ""),
          status: scheduleMonitorStatus(order, { process: "PRINT", hasAssignment: true }),
          designGate,
          paymentGate,
          schedulingAllowed,
          reason: "",
        });
      });
    } else {
      rows.push({
        orderId: order.id,
        lineId,
        process: "PRINT",
        lineName,
        lineQty,
        colorName: String(line.color || "Belum tercatat"),
        colorIndex: 1,
        assignmentId: "",
        assignmentQty: 0,
        operator: "",
        machine: "",
        workDate: "",
        status: scheduleMonitorStatus(order, { process: "PRINT", hasAssignment: false }),
        designGate,
        paymentGate,
        schedulingAllowed,
        reason: "",
      });
    }
  }

  for (const line of unknownLinesOf(order)) {
    rows.push({
      orderId: order.id,
      lineId: String(line.id || ""),
      process: "UNKNOWN",
      lineName: String(line.name || order.item || "Item"),
      lineQty: Number.isFinite(Number(line.qty)) ? Math.max(0, Number(line.qty)) : 0,
      colorName: String(line.color || "—"),
      colorIndex: 0,
      assignmentId: "",
      assignmentQty: 0,
      operator: "",
      machine: "",
      workDate: "",
      status: "Proses Belum Terverifikasi",
      designGate,
      paymentGate,
      schedulingAllowed: false,
      reason:
        "Klasifikasi proses Accurate belum terbukti (bukan Cetak / Tidak Cetak) — tidak masuk antrean operator cetak",
    });
  }

  return rows;
}

export function scheduleKpiFromOrders(orders: ScheduleOrderLike[]): {
  printQty: number;
  scheduled: number;
  done: number;
  remainingTotal: number;
  remainingScheduled: number;
  unassigned: number;
  unknownQty: number;
} {
  let printQty = 0;
  let scheduled = 0;
  let done = 0;
  let unknownQty = 0;
  for (const o of orders) {
    const pq = printPhysicalQty(o);
    printQty += pq;
    unknownQty += unknownPhysicalQty(o);
    const sch = Math.min(pq, Math.max(0, Math.trunc(Number(o.scheduledQty) || 0)));
    const dn = Math.min(pq, Math.max(0, Math.trunc(Number(o.done) || 0)));
    scheduled += sch;
    done += dn;
  }
  return {
    printQty,
    scheduled,
    done,
    remainingTotal: Math.max(0, printQty - done),
    remainingScheduled: Math.max(0, scheduled - done),
    unassigned: Math.max(0, printQty - scheduled),
    unknownQty,
  };
}
