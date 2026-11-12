import { describe, expect, it } from "vitest";

/** Mirrors live-runtime applyDetailToOrder preserve rules (pure). */
function mergeDetailSales(
  existing: { salesName?: string | null; salesSource?: string | null },
  detail: { sales?: string | null; sales_source?: string | null },
) {
  const next = { ...existing };
  if (detail.sales != null && String(detail.sales).trim()) {
    next.salesName = String(detail.sales).trim();
    next.salesSource = detail.sales_source || next.salesSource || "detail";
  } else if (!next.salesName || next.salesName === "Belum terverifikasi") {
    next.salesName = "Belum terverifikasi";
    next.salesSource = detail.sales_source || next.salesSource || null;
  }
  return next;
}

function mergeOptional(
  existing: string | null | undefined,
  incoming: string | null | undefined,
) {
  return incoming ? incoming : existing ?? null;
}

describe("Slice 1H enrich preserve", () => {
  it("keeps verified list sales when detail omits sales", () => {
    const merged = mergeDetailSales(
      { salesName: "Dimas Aji Prasetya", salesSource: "salesmanList" },
      { sales: null, sales_source: null },
    );
    expect(merged.salesName).toBe("Dimas Aji Prasetya");
    expect(merged.salesSource).toBe("salesmanList");
  });

  it("never invents sales from creator", () => {
    const merged = mergeDetailSales(
      { salesName: "Belum terverifikasi" },
      { sales: null },
    );
    expect(merged.salesName).toBe("Belum terverifikasi");
  });

  it("preserves expedition/zone when detail omits them", () => {
    expect(mergeOptional("OUTLET", null)).toBe("OUTLET");
    expect(mergeOptional("JU", "")).toBe("JU");
    expect(mergeOptional(null, "OUTLET")).toBe("OUTLET");
  });
});
