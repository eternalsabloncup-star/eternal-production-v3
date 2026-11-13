import { describe, expect, it } from "vitest";
import {
  COLUMN_CATEGORY,
  V1_COLUMN_GAPS,
  V1_DEFAULT_ORDER,
  V1_DEFAULT_VISIBLE,
  contiguousCategorySpans,
  defaultOrderWithRemainder,
  defaultVisibleSet,
  filterColumnsByQuery,
  mergeColumnOrder,
} from "./scheduleColumnLayout";

const ALL = [
  ...V1_DEFAULT_ORDER,
  "orderDate",
  "salesName",
  "done",
  "action",
];

describe("Jadwal Produksi V1 default column layout", () => {
  it("default order starts with No PO + Customer and ends Status before extras", () => {
    expect(V1_DEFAULT_ORDER[0]).toBe("id");
    expect(V1_DEFAULT_ORDER[1]).toBe("name");
    expect(V1_DEFAULT_ORDER[V1_DEFAULT_ORDER.length - 1]).toBe("status");
    expect(V1_DEFAULT_ORDER).not.toContain("action");
  });

  it("default visible includes V1 keys + action and excludes Sumber Jadwal gap", () => {
    const vis = defaultVisibleSet(ALL);
    expect(vis.has("id")).toBe(true);
    expect(vis.has("name")).toBe(true);
    expect(vis.has("action")).toBe(true);
    expect(vis.has("designGate")).toBe(true);
    expect(V1_COLUMN_GAPS.some((g) => g.v1Label === "Sumber Jadwal")).toBe(true);
  });

  it("mergeColumnOrder preserves user order and appends new keys without wiping prefs", () => {
    const saved = ["id", "name", "qty", "action"];
    const merged = mergeColumnOrder(saved, ALL);
    expect(merged.slice(0, 3)).toEqual(["id", "name", "qty"]);
    expect(merged[merged.length - 1]).toBe("action");
    expect(merged).toContain("designGate");
    expect(new Set(merged).size).toBe(merged.length);
  });

  it("defaultOrderWithRemainder places V1 head then remainder then action", () => {
    const order = defaultOrderWithRemainder(ALL);
    expect(order.slice(0, 2)).toEqual(["id", "name"]);
    expect(order[order.length - 1]).toBe("action");
    expect(order.indexOf("orderDate")).toBeGreaterThan(order.indexOf("status"));
  });

  it("contiguousCategorySpans only groups neighbors", () => {
    const spans = contiguousCategorySpans([
      "id",
      "name",
      "assignmentDate",
      "operator",
      "item",
      "status",
    ]);
    expect(spans[0]).toEqual({ category: "IDENTITAS PO", span: 2 });
    expect(spans.some((s) => s.category === "PENJADWALAN" && s.span === 2)).toBe(
      true,
    );
  });

  it("filterColumnsByQuery matches label or key", () => {
    const labels = { id: "No PO", name: "Customer", qty: "Total Qty" };
    expect(filterColumnsByQuery(["id", "name", "qty"], labels, "cust")).toEqual([
      "name",
    ]);
    expect(filterColumnsByQuery(["id", "name"], labels, "id")).toEqual(["id"]);
  });

  it("every V1 default key has a category", () => {
    for (const k of V1_DEFAULT_VISIBLE) {
      if (k === "action") continue;
      expect(COLUMN_CATEGORY[k]).toBeTruthy();
    }
  });
});
