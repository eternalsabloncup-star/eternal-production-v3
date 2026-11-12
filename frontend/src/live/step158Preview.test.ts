import { describe, expect, it } from "vitest";
import {
  buildScheduleMonitorRows,
  printPhysicalQty,
  scheduleKpiFromOrders,
  unknownPhysicalQty,
} from "./scheduleMonitor";
import {
  clampColumnWidth,
  clearColumnWidths,
  loadColumnWidths,
  saveColumnWidths,
  stickyLeftOffsets,
} from "./columnResize";

describe("Step 158 preview acceptance", () => {
  it("mixed PO: Jadwal print-only; Inbox total qty still includes all verified lines conceptually", () => {
    const order = {
      id: "SO/PREVIEW-MIX",
      design_status: "approved",
      payment_status: "approved",
      scheduledQty: 2000,
      done: 200,
      qty: 5100,
      qtyVerified: true,
      sourceLines: [
        {
          id: "P1",
          name: "Cup Cetak",
          qty: 2000,
          production_process: "print",
          processSnapshot: "PRINT",
        },
        {
          id: "N1",
          name: "Lid NonCetak",
          qty: 3000,
          production_process: "non_print",
          processSnapshot: "NON_PRINT",
        },
        {
          id: "U1",
          name: "Unknown Item",
          qty: 100,
          production_process: "unknown",
          processSnapshot: "UNKNOWN",
        },
      ],
    };
    const rows = buildScheduleMonitorRows(order);
    expect(rows.every((r) => r.process === "PRINT")).toBe(true);
    expect(rows).toHaveLength(1);
    expect(printPhysicalQty(order)).toBe(2000);
    expect(unknownPhysicalQty(order)).toBe(100);
    // Inbox total qty remains full PO qty when verified (not print-only)
    expect(order.qty).toBe(5100);
    const kpi = scheduleKpiFromOrders([order]);
    expect(kpi.printQty).toBe(2000);
    expect(kpi.scheduled).toBe(2000);
    expect(kpi.done).toBe(200);
    expect(kpi.remainingTotal).toBe(1800);
    expect(kpi.unassigned).toBe(0);
    expect(kpi.unknownQty).toBe(100);
  });

  it("unknown never becomes print in schedule or KPI print base", () => {
    const order = {
      id: "SO/UNK",
      scheduledQty: 0,
      done: 0,
      sourceLines: [
        {
          id: "U1",
          qty: 999,
          production_process: "unknown",
          processSnapshot: "UNKNOWN",
        },
      ],
    };
    expect(buildScheduleMonitorRows(order)).toEqual([]);
    expect(printPhysicalQty(order)).toBe(0);
    expect(scheduleKpiFromOrders([order]).printQty).toBe(0);
  });

  it("column widths persist per table key and reset clears", () => {
    saveColumnWidths("epv3:colw:inbox", { id: 190, name: 210 });
    expect(loadColumnWidths("epv3:colw:inbox").id).toBe(190);
    expect(stickyLeftOffsets(["id", "name"], { id: 190 }).name).toBe(190);
    expect(clampColumnWidth("id", 40)).toBeGreaterThanOrEqual(120);
    clearColumnWidths("epv3:colw:inbox");
    expect(loadColumnWidths("epv3:colw:inbox")).toEqual({});
  });
});
