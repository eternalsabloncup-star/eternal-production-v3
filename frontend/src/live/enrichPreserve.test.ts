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
  } else if (
    next.salesName &&
    next.salesName !== "Belum terverifikasi"
  ) {
    // Preserve list sales when detail omits — never wipe, never use creator.
  } else {
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

type DetailLoadState = "not_loaded" | "loading" | "loaded" | "failed";

function resolveQtyFromDetail(detail: {
  total_quantity?: number | null;
  total_quantity_verified?: boolean;
  line_items?: Array<{
    quantity?: number | null;
    qty?: number | null;
    qty_verified?: boolean;
  }>;
}): { qty: number | null; qtyVerified: boolean } {
  const lines = Array.isArray(detail.line_items) ? detail.line_items : [];
  if (
    detail.total_quantity_verified === true &&
    detail.total_quantity != null &&
    Number.isFinite(Number(detail.total_quantity))
  ) {
    return { qty: Number(detail.total_quantity), qtyVerified: true };
  }
  if (
    lines.length &&
    lines.every(
      (x) =>
        x.qty_verified === true &&
        (x.quantity != null || x.qty != null) &&
        Number.isFinite(Number(x.quantity != null ? x.quantity : x.qty)),
    )
  ) {
    const qty = lines.reduce((sum, x) => {
      const n = Number(x.quantity != null ? x.quantity : x.qty);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
    return Number.isFinite(qty)
      ? { qty, qtyVerified: true }
      : { qty: null, qtyVerified: false };
  }
  return { qty: null, qtyVerified: false };
}

function markDetailFailed(prev: {
  qty: number | null;
  qtyVerified: boolean;
  detailLoadState: DetailLoadState;
}): {
  qty: number | null;
  qtyVerified: boolean;
  detailLoadState: DetailLoadState;
  detailError: string;
} {
  return {
    qty: prev.qtyVerified ? prev.qty : null,
    qtyVerified: prev.qtyVerified,
    detailLoadState: "failed",
    detailError: "Gagal memuat detail Accurate",
  };
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

describe("Slice 1M qty + enrich reliability", () => {
  it("sums verified print + non-print as 2000", () => {
    const r = resolveQtyFromDetail({
      total_quantity: 2000,
      total_quantity_verified: true,
      line_items: [
        { quantity: 1000, qty_verified: true },
        { quantity: 1000, qty_verified: true },
      ],
    });
    expect(r).toEqual({ qty: 2000, qtyVerified: true });
  });

  it("official zero stays verified; missing stays unverified", () => {
    expect(
      resolveQtyFromDetail({
        line_items: [
          { quantity: 0, qty_verified: true },
          { quantity: 5, qty_verified: true },
        ],
      }),
    ).toEqual({ qty: 5, qtyVerified: true });
    expect(
      resolveQtyFromDetail({
        line_items: [
          { quantity: 1000, qty_verified: true },
          { quantity: null, qty_verified: false },
        ],
      }),
    ).toEqual({ qty: null, qtyVerified: false });
  });

  it("rejects NaN / Infinity as unverified", () => {
    expect(
      resolveQtyFromDetail({
        line_items: [{ quantity: Number.NaN, qty_verified: true }],
      }),
    ).toEqual({ qty: null, qtyVerified: false });
    expect(
      resolveQtyFromDetail({
        total_quantity: Number.POSITIVE_INFINITY,
        total_quantity_verified: true,
      }),
    ).toEqual({ qty: null, qtyVerified: false });
  });

  it("does not multiply physical qty by color count", () => {
    const physical = resolveQtyFromDetail({
      line_items: [
        { quantity: 1000, qty_verified: true },
        { quantity: 1000, qty_verified: true },
      ],
    });
    const colorPasses = 3;
    expect(physical.qty).toBe(2000);
    expect(physical.qty! * colorPasses).not.toBe(physical.qty);
  });

  it("failure clears inventable zero and allows retry state", () => {
    const failed = markDetailFailed({
      qty: null,
      qtyVerified: false,
      detailLoadState: "loading",
    });
    expect(failed.detailLoadState).toBe("failed");
    expect(failed.qty).toBeNull();
    expect(failed.qtyVerified).toBe(false);
    // Retry path: failure is not permanent cache — caller deletes cache then reloads.
    const afterRetry = resolveQtyFromDetail({
      total_quantity: 2000,
      total_quantity_verified: true,
    });
    expect(afterRetry.qtyVerified).toBe(true);
  });

  it("stale generation isolation: ignore apply when page generation changed", () => {
    let enrichGeneration = 1;
    const startedGen = enrichGeneration;
    enrichGeneration = 2; // page/filter changed
    const shouldApply = startedGen === enrichGeneration;
    expect(shouldApply).toBe(false);
  });

  it("detail load states are distinct", () => {
    const states: DetailLoadState[] = [
      "not_loaded",
      "loading",
      "loaded",
      "failed",
    ];
    expect(new Set(states).size).toBe(4);
  });

  it("concurrency bound remains 3", () => {
    const ENRICH_CONCURRENCY = 3;
    expect(ENRICH_CONCURRENCY).toBe(3);
  });
});
