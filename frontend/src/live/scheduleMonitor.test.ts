import { describe, expect, it } from "vitest";
import {
  bothGatesSatisfied,
  buildScheduleMonitorRows,
  effectiveLineProcess,
  printPhysicalQty,
  processSnapshotFromAccurate,
  scheduleKpiFromOrders,
  scheduleMonitorStatus,
  unknownPhysicalQty,
} from "./scheduleMonitor";

describe("Slice 1H schedule monitor classification", () => {
  it("maps Accurate production_process without inventing print", () => {
    expect(processSnapshotFromAccurate("print")).toBe("PRINT");
    expect(processSnapshotFromAccurate("non_print")).toBe("NON_PRINT");
    expect(processSnapshotFromAccurate("unknown")).toBe("UNKNOWN");
    expect(processSnapshotFromAccurate(null)).toBe("UNKNOWN");
  });

  it("never treats blank processSnapshot as print via item catalog fallback", () => {
    expect(
      effectiveLineProcess({
        production_process: "unknown",
        processSnapshot: "UNKNOWN",
      }),
    ).toBe("UNKNOWN");
    expect(
      effectiveLineProcess({
        production_process: "print",
        processSnapshot: "PRINT",
      }),
    ).toBe("PRINT");
  });

  it("shows print lines before ACC with blocked scheduling", () => {
    const order = {
      id: "SO/1",
      design_status: "pending",
      payment_status: "pending",
      scheduledQty: 0,
      done: 0,
      sourceLines: [
        {
          id: "L1",
          name: "Cup PET",
          qty: 5000,
          production_process: "print",
          processSnapshot: "PRINT",
        },
        {
          id: "L2",
          name: "Lid",
          qty: 5000,
          production_process: "non_print",
          processSnapshot: "NON_PRINT",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows).toHaveLength(1);
    expect(rows[0].process).toBe("PRINT");
    expect(rows[0].status).toBe("Belum ACC Design");
    expect(rows[0].schedulingAllowed).toBe(false);
    expect(bothGatesSatisfied(order)).toBe(false);
  });

  it("keeps unpaid print lines visible and payment gate independent", () => {
    const order = {
      id: "SO/2",
      design_status: "approved",
      payment_status: "pending",
      sourceLines: [
        {
          id: "L1",
          qty: 1000,
          production_process: "print",
          processSnapshot: "PRINT",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows[0].status).toBe("Belum ACC Payment");
    expect(rows[0].designGate).toBe("APPROVED");
    expect(rows[0].paymentGate).toBe("PENDING");
  });

  it("excludes unknown from Jadwal rows and does not count as print qty", () => {
    const order = {
      id: "SO/3",
      design_status: "pending",
      payment_status: "pending",
      sourceLines: [
        {
          id: "U1",
          qty: 200,
          production_process: "unknown",
          processSnapshot: "UNKNOWN",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows).toHaveLength(0);
    expect(printPhysicalQty(order)).toBe(0);
    expect(unknownPhysicalQty(order)).toBe(200);
  });

  it("mixed print+non_print shows only print on Jadwal; KPI uses print qty only", () => {
    const order = {
      id: "SO/MIX",
      design_status: "approved",
      payment_status: "approved",
      scheduledQty: 3000,
      done: 500,
      sourceLines: [
        {
          id: "P1",
          name: "Cup Cetak",
          qty: 3000,
          production_process: "print",
          processSnapshot: "PRINT",
        },
        {
          id: "N1",
          name: "Lid",
          qty: 3000,
          production_process: "non_print",
          processSnapshot: "NON_PRINT",
        },
        {
          id: "U1",
          name: "Misc",
          qty: 100,
          production_process: "unknown",
          processSnapshot: "UNKNOWN",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows).toHaveLength(1);
    expect(rows[0].process).toBe("PRINT");
    expect(rows[0].lineQty).toBe(3000);
    expect(printPhysicalQty(order)).toBe(3000);
    expect(unknownPhysicalQty(order)).toBe(100);
    const kpi = scheduleKpiFromOrders([order]);
    expect(kpi.printQty).toBe(3000);
    expect(kpi.scheduled).toBe(3000);
    expect(kpi.done).toBe(500);
    expect(kpi.remainingTotal).toBe(2500);
    expect(kpi.remainingScheduled).toBe(2500);
    expect(kpi.unassigned).toBe(0);
    expect(kpi.unknownQty).toBe(100);
  });

  it("allows scheduling only when both gates satisfied", () => {
    const order = {
      id: "SO/4",
      design_status: "approved",
      payment_status: "bypassed",
      sourceLines: [
        {
          id: "L1",
          qty: 100,
          production_process: "print",
          processSnapshot: "PRINT",
        },
      ],
    };
    expect(bothGatesSatisfied(order)).toBe(true);
    expect(scheduleMonitorStatus(order, { process: "PRINT", hasAssignment: false })).toBe(
      "Siap Dijadwalkan",
    );
  });

  it("does not double-count multi-colour assignment qty in KPI base", () => {
    const order = {
      id: "SO/5",
      design_status: "approved",
      payment_status: "approved",
      scheduledQty: 5000,
      done: 1000,
      productionAssignments: [
        {
          id: "a1",
          soLineId: "L1",
          colorIndex: 1,
          targetQty: 5000,
          operator: "A",
          machine: "M1",
        },
        {
          id: "a2",
          soLineId: "L1",
          colorIndex: 2,
          targetQty: 5000,
          operator: "B",
          machine: "M2",
        },
      ],
      sourceLines: [
        {
          id: "L1",
          qty: 5000,
          production_process: "print",
          processSnapshot: "PRINT",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows).toHaveLength(2);
    const kpi = scheduleKpiFromOrders([order]);
    expect(kpi.printQty).toBe(5000);
    expect(kpi.scheduled).toBe(5000);
    expect(kpi.done).toBe(1000);
    expect(kpi.unassigned).toBe(0);
  });
});
