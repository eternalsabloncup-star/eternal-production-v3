import { describe, expect, it } from "vitest";
import {
  buildScheduleGroupSpans,
  groupWidthMatchesChildren,
  sumWidths,
} from "./scheduleHeaderGeometry";

const CAT: Record<string, string> = {
  id: "IDENTITAS PO",
  name: "IDENTITAS PO",
  branch: "IDENTITAS PO",
  operator: "PENJADWALAN",
  assignmentDate: "PENJADWALAN",
  item: "PRODUKSI",
  qty: "PROGRESS PRODUKSI",
  action: "LAINNYA",
};

describe("scheduleHeaderGeometry", () => {
  it("builds colspan spans for consecutive visible categories", () => {
    const spans = buildScheduleGroupSpans(
      ["id", "name", "branch", "operator", "assignmentDate", "item", "qty", "action"],
      new Set(["id", "name", "branch", "operator", "assignmentDate", "item", "qty", "action"]),
      (k) => CAT[k] || "LAINNYA",
    );
    expect(spans.map((s) => [s.label || s.key, s.span])).toEqual([
      ["IDENTITAS PO", 3],
      ["PENJADWALAN", 2],
      ["PRODUKSI", 1],
      ["PROGRESS PRODUKSI", 1],
      ["action", 1],
    ]);
    expect(sumWidths(spans.map((s) => s.span))).toBe(8);
  });

  it("omits hidden columns from colspan runs", () => {
    const spans = buildScheduleGroupSpans(
      ["id", "name", "branch", "operator", "item", "action"],
      new Set(["id", "name", "operator", "item", "action"]), // branch hidden
      (k) => CAT[k] || "LAINNYA",
    );
    expect(spans[0]).toMatchObject({ label: "IDENTITAS PO", span: 2, keys: ["id", "name"] });
    expect(spans[1]).toMatchObject({ label: "PENJADWALAN", span: 1, keys: ["operator"] });
  });

  it("validates group X bounds equal union of children", () => {
    expect(
      groupWidthMatchesChildren(10, 110, [
        { left: 10, right: 40 },
        { left: 40, right: 110 },
      ]),
    ).toBe(true);
    expect(
      groupWidthMatchesChildren(10, 100, [
        { left: 10, right: 40 },
        { left: 40, right: 90 },
      ]),
    ).toBe(false);
  });
});
