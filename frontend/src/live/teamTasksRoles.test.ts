import { describe, expect, it } from "vitest";
import { OFFICIAL_TASK_CARD_DEFS, mapOfficialTasksToRows } from "./teamTasks";

describe("teamTasks Final role coverage", () => {
  it("covers six operational roles with Kerjakan verbs for Driver", () => {
    const roles = [...new Set(OFFICIAL_TASK_CARD_DEFS.map((d) => d.role))];
    expect(roles).toEqual(
      expect.arrayContaining([
        "Kepala Produksi",
        "Designer",
        "Screener",
        "Helper",
        "Operator",
        "Driver",
      ]),
    );
    expect(roles).toHaveLength(6);
    const driver = OFFICIAL_TASK_CARD_DEFS.filter((d) => d.role === "Driver");
    expect(driver.map((d) => d.id).sort()).toEqual(["delivery", "loading"]);
    expect(driver.every((d) => d.verb.startsWith("Kerjakan"))).toBe(true);
    expect(OFFICIAL_TASK_CARD_DEFS.some((d) => d.id === "sample_approve")).toBe(true);
  });

  it("maps official tasks without inventing duplicates", () => {
    const rows = mapOfficialTasksToRows(
      [
        {
          id: "1",
          kind: "loading",
          role: "Driver",
          label: "Loading",
          verb: "Kerjakan loading",
          state: "todo",
          accurate_so_number: "SO-1",
          customer_name: "A",
          branch_id: "BR",
          visible: true,
        },
        {
          id: "2",
          kind: "loading",
          role: "Driver",
          label: "Loading",
          verb: "Kerjakan loading",
          state: "todo",
          accurate_so_number: "SO-1",
          customer_name: "A",
          branch_id: "BR",
          visible: false,
        },
      ] as any,
      new Map(),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].t.role).toBe("Driver");
  });
});
