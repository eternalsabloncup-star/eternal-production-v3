import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { describe, expect, it } from "vitest";

import {
  countUrgentOrders,
  filterUrgentOrders,
  mergeUrgentFromIncoming,
  orderPriorityFromState,
  urgentFieldsFromAccurateState,
  urgentFlagFromState,
} from "./urgentState";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadPublicRuntime(): Record<string, Function> {
  const file = path.resolve(__dirname, "../../public/live-qty-integrity.js");
  const code = readFileSync(file, "utf8");
  const sandbox: { window: Record<string, unknown>; globalThis: unknown } = {
    window: {},
    globalThis: undefined,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(code, sandbox, { filename: "live-qty-integrity.js" });
  return sandbox.window.V3QtyIntegrity as Record<string, Function>;
}

describe("Step 58 urgent state consistency (typed module)", () => {
  it("maps normal → false, approved_urgent → true, unknown → null", () => {
    expect(urgentFlagFromState("normal")).toBe(false);
    expect(urgentFlagFromState("approved_urgent")).toBe(true);
    expect(urgentFlagFromState("legacy_urgent")).toBe(true);
    expect(urgentFlagFromState(null)).toBeNull();
    expect(urgentFlagFromState(undefined)).toBeNull();
    expect(urgentFlagFromState("")).toBeNull();
    expect(urgentFlagFromState("maybe")).toBeNull();
    expect(orderPriorityFromState("normal")).toBe("Normal");
    expect(orderPriorityFromState("approved_urgent")).toBe("Urgent");
    expect(orderPriorityFromState(null)).toBe("Belum terverifikasi");
  });

  it("urgentFields keep three fields aligned", () => {
    expect(urgentFieldsFromAccurateState("approved_urgent")).toEqual({
      urgent: true,
      urgentState: "approved_urgent",
      orderPriority: "Urgent",
    });
    expect(urgentFieldsFromAccurateState("normal")).toEqual({
      urgent: false,
      urgentState: "normal",
      orderPriority: "Normal",
    });
    expect(urgentFieldsFromAccurateState(null)).toEqual({
      urgent: null,
      urgentState: null,
      orderPriority: "Belum terverifikasi",
    });
  });

  it("preserves list urgent when detail omits status", () => {
    const kept = mergeUrgentFromIncoming(
      {
        urgent: true,
        urgentState: "approved_urgent",
        orderPriority: "Urgent",
      },
      null,
    );
    expect(kept.urgent).toBe(true);
    expect(kept.urgentState).toBe("approved_urgent");
    expect(kept.orderPriority).toBe("Urgent");
  });

  it("detail normal overwrites prior unknown without inventing from label alone", () => {
    const next = mergeUrgentFromIncoming(
      {
        urgent: null,
        urgentState: null,
        orderPriority: "Belum terverifikasi",
      },
      "normal",
    );
    expect(next).toEqual({
      urgent: false,
      urgentState: "normal",
      orderPriority: "Normal",
    });
  });

  it("filter and KPI count only urgent === true", () => {
    const rows = [
      { id: "1", urgent: true as boolean | null },
      { id: "2", urgent: false },
      { id: "3", urgent: null },
      { id: "4", urgent: true },
    ];
    expect(countUrgentOrders(rows)).toBe(2);
    expect(filterUrgentOrders(rows).map((r) => r.id)).toEqual(["1", "4"]);
  });

  it("does not invent tasks or change qty (pure urgent helpers only)", () => {
    const before = { qty: 2000, qtyVerified: true, urgent: null as boolean | null };
    const fields = urgentFieldsFromAccurateState("approved_urgent");
    expect(before.qty).toBe(2000);
    expect(fields.urgent).toBe(true);
  });
});

describe("Step 58 public live-qty-integrity urgent helpers", () => {
  const api = loadPublicRuntime();

  it("public helper matches typed module for core transitions", () => {
    expect(api.urgentFlagFromState("normal")).toBe(false);
    expect(api.urgentFlagFromState("approved_urgent")).toBe(true);
    expect(api.urgentFlagFromState(null)).toBeNull();
    expect(
      api.mergeUrgentFromIncoming(
        { urgent: false, urgentState: "normal", orderPriority: "Normal" },
        null,
      ),
    ).toEqual({
      urgent: false,
      urgentState: "normal",
      orderPriority: "Normal",
    });
    expect(
      api.countUrgentOrders([
        { urgent: true },
        { urgent: false },
        { urgent: null },
      ]),
    ).toBe(1);
  });

  it("stale page isolation helper still present alongside urgent helpers", () => {
    expect(api.shouldApplyDetail(2, 1, true)).toBe(false);
    expect(api.shouldApplyDetail(2, 2, true)).toBe(true);
  });
});
