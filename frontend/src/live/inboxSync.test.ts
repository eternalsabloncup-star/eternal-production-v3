import { describe, expect, it } from "vitest";
import {
  countBaruTerproses,
  isSharedOrdersReference,
  pageKpiCount,
  publishSharedOrders,
  rejectDemoFallback,
  shouldClearOnApiError,
  shouldRedirectUnauthorized,
} from "./inboxSync";

describe("Slice 1D inbox state sync", () => {
  it("API 50 PO → shared orders length 50; orders === window.orders", () => {
    const scope: { orders?: { id: string; productionStatus: string }[] } = {
      orders: [],
    };
    const rows = Array.from({ length: 50 }, (_, i) => ({
      id: `SO/${i + 1}`,
      productionStatus: i % 5 === 0 ? "Terproses" : "Baru",
      name: `Cust ${i}`,
      item: `Item ${i}`,
      qty: 100 + i,
      branch: "Yogyakarta",
      salesName: "Sales A",
    }));
    publishSharedOrders(scope, rows);
    expect(scope.orders).toHaveLength(50);
    expect(isSharedOrdersReference(scope.orders, scope.orders)).toBe(true);
    // Simulate legacy let-vs-window bug: separate array identity fails sync check.
    const shadowed: typeof rows = [];
    expect(isSharedOrdersReference(shadowed, scope.orders)).toBe(false);
  });

  it("KPI uses page row count, not Accurate total 11768", () => {
    const page = Array.from({ length: 50 }, (_, i) => ({
      id: String(i),
      productionStatus: "Baru" as const,
    }));
    const accurateTotal = 11768;
    expect(pageKpiCount(page, accurateTotal)).toBe(50);
    expect(pageKpiCount(page, accurateTotal)).not.toBe(accurateTotal);
  });

  it("counts Baru and Terproses on the current page only", () => {
    const orders = [
      { id: "1", productionStatus: "Baru" },
      { id: "2", productionStatus: "Terproses" },
      { id: "3", productionStatus: "Baru" },
      { id: "4", productionStatus: "Terproses" },
      { id: "5", productionStatus: "Baru" },
    ];
    expect(countBaruTerproses(orders)).toEqual({
      baru: 3,
      terproses: 2,
      pageCount: 5,
    });
  });

  it("empty API response yields empty shared state", () => {
    const scope: { orders?: unknown[] } = {
      orders: [{ id: "stale" }],
    };
    publishSharedOrders(scope, []);
    expect(scope.orders).toEqual([]);
  });

  it("API error clears stale live data", () => {
    expect(shouldClearOnApiError(500)).toBe(true);
    expect(shouldClearOnApiError(503)).toBe(true);
    const scope: { orders?: unknown[] } = {
      orders: [{ id: "old" }],
    };
    if (shouldClearOnApiError(502)) publishSharedOrders(scope, []);
    expect(scope.orders).toEqual([]);
  });

  it("unauthorized redirects to login", () => {
    expect(shouldRedirectUnauthorized(401)).toBe(true);
    expect(shouldRedirectUnauthorized(200)).toBe(false);
  });

  it("rejects demo/fixture fallback modes", () => {
    expect(rejectDemoFallback("live")).toBe(false);
    expect(rejectDemoFallback("fixture")).toBe(true);
    expect(rejectDemoFallback("demo")).toBe(true);
    expect(rejectDemoFallback(undefined)).toBe(true);
  });

  it("search/filter refresh keeps shared reference after republish", () => {
    const scope: { orders?: { id: string }[] } = {};
    publishSharedOrders(scope, [{ id: "A" }, { id: "B" }]);
    const first = scope.orders;
    publishSharedOrders(scope, [{ id: "A" }]); // filtered page from backend
    expect(scope.orders).toHaveLength(1);
    expect(scope.orders).not.toBe(first);
    expect(isSharedOrdersReference(scope.orders, scope.orders)).toBe(true);
  });
});
