import { describe, expect, it } from "vitest";
import {
  effectiveLineMode,
  normalizeProductionProcess,
  orderSourceLinesForLive,
  processSnapshotFromProcess,
} from "./processSnapshot";
import {
  mapOfficialTasksToRows,
  officialStateToUi,
  syncGateFromJobStatuses,
  type OfficialTask,
} from "./teamTasks";

describe("Slice 1H processSnapshot", () => {
  it("maps print/non_print only — never invents PRINT", () => {
    expect(processSnapshotFromProcess("print")).toBe("PRINT");
    expect(processSnapshotFromProcess("non_print")).toBe("NON_PRINT");
    expect(processSnapshotFromProcess("unknown")).toBeNull();
    expect(processSnapshotFromProcess(null)).toBeNull();
    expect(normalizeProductionProcess("Non-Print")).toBe("non_print");
  });

  it("effectiveLineMode prefers processSnapshot then production_process", () => {
    expect(
      effectiveLineMode({ processSnapshot: "PRINT", production_process: "non_print" }),
    ).toBe("PRINT");
    expect(effectiveLineMode({ production_process: "non_print" })).toBe("NON_PRINT");
    expect(
      effectiveLineMode({ production_process: "unknown", itemId: "x" }, () => "PRINT"),
    ).toBe("PRINT");
    expect(effectiveLineMode({ production_process: "unknown" })).toBe("UNKNOWN");
  });

  it("live empty sourceLines stay empty (no demo invent)", () => {
    expect(
      orderSourceLinesForLive({} as { sourceLines?: unknown }, () => [{ id: "demo" }], true),
    ).toEqual([]);
    expect(
      orderSourceLinesForLive(
        { sourceLines: [{ id: "L1" }] },
        () => [{ id: "demo" }],
        true,
      ),
    ).toEqual([{ id: "L1" }]);
    expect(
      orderSourceLinesForLive({} as { sourceLines?: unknown }, () => [{ id: "demo" }], false),
    ).toEqual([{ id: "demo" }]);
  });
});

describe("Slice 1H official team tasks mapping", () => {
  it("maps states and gates independently", () => {
    expect(officialStateToUi("actionable")).toBe("Siap");
    expect(officialStateToUi("blocked")).toBe("Menunggu");
    expect(officialStateToUi("done")).toBe("Selesai");
    expect(
      syncGateFromJobStatuses({
        design_status: "approved",
        payment_status: "pending",
      }),
    ).toEqual({ design: "APPROVED", payment: "PENDING" });
  });

  it("builds UI rows from API without inventing missing orders", () => {
    const tasks: OfficialTask[] = [
      {
        id: "SO/A::design_upload",
        kind: "design_upload",
        group: "design_upload",
        role: "Designer",
        label: "Upload Design",
        verb: "Upload desain",
        state: "actionable",
        job_id: 1,
        accurate_so_number: "SO/A",
        customer_name: "Acme",
      },
    ];
    const rows = mapOfficialTasksToRows(tasks, new Map());
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe("Siap");
    expect(rows[0].t.id).toBe("design_upload");
    expect(rows[0].o.id).toBe("SO/A");
  });
});
