import { describe, expect, it } from "vitest";
import {
  INBOX_COLUMN_ORDER_KEY,
  INBOX_LOCKED_COLUMNS,
  defaultInboxColumnOrder,
  isInboxColumnLocked,
  moveInboxColumn,
  normalizeInboxColumnOrder,
  nudgeInboxColumn,
  readInboxColumnOrder,
  writeInboxColumnOrder,
} from "./inboxColumnOrder";

const ALL = [
  "id",
  "name",
  "orderDate",
  "salesName",
  "branch",
  "ship",
  "item",
  "qty",
  "detailPo",
  "liveTracking",
  "action",
] as const;

describe("Slice 1H inbox column order", () => {
  it("defaults with No PO + Pelanggan locked first", () => {
    const order = defaultInboxColumnOrder(ALL);
    expect(order.slice(0, 2)).toEqual(["id", "name"]);
    expect(order).toHaveLength(ALL.length);
  });

  it("moves Sales beside Cabang without swapping cell bindings", () => {
    const order = defaultInboxColumnOrder(ALL);
    const next = moveInboxColumn(order, "salesName", "branch", "before");
    expect(next.indexOf("salesName")).toBe(next.indexOf("branch") - 1);
    expect(next.slice(0, 2)).toEqual(["id", "name"]);
    expect(new Set(next).size).toBe(ALL.length);
  });

  it("moves Estimasi Kirim beside Tanggal PO", () => {
    const order = defaultInboxColumnOrder(ALL);
    const next = moveInboxColumn(order, "ship", "orderDate", "after");
    expect(next.indexOf("ship")).toBe(next.indexOf("orderDate") + 1);
  });

  it("moves Total Qty beside Nama Barang", () => {
    const order = defaultInboxColumnOrder(ALL);
    const next = moveInboxColumn(order, "qty", "item", "after");
    expect(next.indexOf("qty")).toBe(next.indexOf("item") + 1);
  });

  it("refuses dragging locked sticky columns", () => {
    const order = defaultInboxColumnOrder(ALL);
    expect(moveInboxColumn(order, "id", "branch")).toEqual(order);
    expect(moveInboxColumn(order, "salesName", "name")).toEqual(order);
    expect(isInboxColumnLocked("id")).toBe(true);
    expect(INBOX_LOCKED_COLUMNS).toEqual(["id", "name"]);
  });

  it("keyboard nudge skips locked columns", () => {
    const order = defaultInboxColumnOrder(ALL);
    const right = nudgeInboxColumn(order, "orderDate", 1);
    expect(right.indexOf("orderDate")).toBeGreaterThan(order.indexOf("orderDate"));
    expect(nudgeInboxColumn(order, "id", 1)).toEqual(order);
  });

  it("persists order in localStorage and reset restores default", () => {
    const mem: Record<string, string> = {};
    const storage = {
      getItem: (k: string) => mem[k] ?? null,
      setItem: (k: string, v: string) => {
        mem[k] = v;
      },
    };
    const moved = moveInboxColumn(defaultInboxColumnOrder(ALL), "qty", "item", "before");
    writeInboxColumnOrder(storage, moved);
    expect(mem[INBOX_COLUMN_ORDER_KEY]).toBeTruthy();
    const loaded = readInboxColumnOrder(storage, ALL);
    expect(loaded.indexOf("qty")).toBe(loaded.indexOf("item") - 1);
    const reset = normalizeInboxColumnOrder(null, ALL);
    expect(reset).toEqual(defaultInboxColumnOrder(ALL));
  });

  it("hidden/missing keys are appended without dropping saved positions", () => {
    const saved = ["id", "name", "salesName", "qty", "ghost"];
    const next = normalizeInboxColumnOrder(saved, ALL);
    expect(next[0]).toBe("id");
    expect(next).toContain("branch");
    expect(next).not.toContain("ghost");
    expect(next.indexOf("salesName")).toBeLessThan(next.indexOf("qty"));
  });
});
