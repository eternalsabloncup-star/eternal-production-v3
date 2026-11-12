import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { describe, expect, it } from "vitest";

import {
  fetchDetailDeduped,
  shouldApplyDetail,
} from "./detailEnrich";
import {
  inboxQtyCellHtml,
  isQtyUnverified,
  productionQtySnapshot,
  scheduleDetailProgress,
  scheduleLeadLabel,
  scheduleOverviewSum,
} from "./qtyIntegrity";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Load the exact public runtime helper used by production.html + live-runtime.js. */
function loadPublicRuntime(): Record<string, Function> {
  const file = path.resolve(__dirname, "../../public/live-qty-integrity.js");
  const code = readFileSync(file, "utf8");
  const sandbox: { window: Record<string, unknown>; globalThis: unknown } = {
    window: {},
    globalThis: undefined,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(code, sandbox, { filename: "live-qty-integrity.js" });
  const api = sandbox.window.V3QtyIntegrity as Record<string, Function>;
  if (!api || typeof api.scheduleLeadLabel !== "function") {
    throw new Error("public live-qty-integrity.js did not attach V3QtyIntegrity");
  }
  return api;
}

describe("Slice 1M.1 qty integrity (typed module)", () => {
  it("UNKNOWN qty never becomes Selesai", () => {
    const o = {
      id: "SO/A",
      qty: null,
      qtyVerified: false,
      ship: "15 Nov 2026",
    };
    const q = productionQtySnapshot(o, { live: true });
    expect(q.qtyUnverified).toBe(true);
    expect(q.qty).toBeNull();
    expect(q.remainingTotal).toBeNull();
    expect(scheduleLeadLabel(o, q)).toBe("Qty belum terverifikasi");
    expect(scheduleLeadLabel(o, q)).not.toBe("Selesai");
  });

  it("verified remainingTotal 0 may be Selesai", () => {
    const o = {
      id: "SO/B",
      qty: 100,
      qtyVerified: true,
      done: 100,
      ship: "15 Nov 2026",
    };
    const q = productionQtySnapshot(o, {
      live: true,
      printPhysicalQty: 100,
      unknownPhysicalQty: 0,
    });
    expect(q.qtyUnverified).toBe(false);
    expect(scheduleLeadLabel(o, q)).toBe("Selesai");
  });

  it("inbox failed shows Retry for the correct PO", () => {
    const html = inboxQtyCellHtml({
      id: "PO/11/X/1",
      qtyVerified: false,
      detailLoadState: "failed",
    });
    expect(html).toContain("Gagal dimuat");
    expect(html).toContain("Retry");
    expect(html).toContain("retryInboxDetail('PO/11/X/1')");
    expect(html).not.toContain("<script>");
  });

  it("inbox states: not_loaded / loading / loaded invalid / valid", () => {
    expect(
      inboxQtyCellHtml({ id: "A", detailLoadState: "not_loaded" }),
    ).toContain("Belum dimuat");
    expect(
      inboxQtyCellHtml({ id: "A", detailLoadState: "loading" }),
    ).toContain("Memuat");
    expect(
      inboxQtyCellHtml({
        id: "A",
        detailLoadState: "loaded",
        qtyVerified: false,
      }),
    ).toContain("Qty belum terverifikasi");
    expect(
      inboxQtyCellHtml({
        id: "A",
        detailLoadState: "loaded",
        qty: 2000,
        qtyVerified: true,
      }),
    ).toContain("2.000");
  });

  it("KPI excludes UNKNOWN from verified total and labels incomplete", () => {
    const rows = [
      { id: "1", qty: 1000, qtyVerified: true },
      { id: "2", qty: null, qtyVerified: false },
    ];
    const sum = scheduleOverviewSum(
      rows,
      (o) =>
        productionQtySnapshot(o, {
          live: true,
          printPhysicalQty: o.qtyVerified ? Number(o.qty) : 0,
        }),
      (o) => scheduleLeadLabel(o),
    );
    expect(sum.qty).toBe(1000);
    expect(sum.unverifiedPoCount).toBe(1);
    expect(sum.cells[0][0]).toContain("terverifikasi");
    expect(sum.cells.some((c) => String(c[0]).includes("belum terverifikasi"))).toBe(
      true,
    );
  });

  it("schedule detail progress is UNKNOWN when unverified", () => {
    expect(
      scheduleDetailProgress({ qty: null, qtyVerified: false, done: 5 }),
    ).toEqual({ label: "UNKNOWN", pct: 0, unknown: true });
    expect(
      scheduleDetailProgress({ qty: 100, qtyVerified: true, done: 50 }).pct,
    ).toBe(50);
  });

  it("two force retries share one inflight request", async () => {
    let calls = 0;
    const stores = { cache: {} as Record<string, { ok: number }>, inflight: {} as Record<string, Promise<{ ok: number }>> };
    const requestFn = () => {
      calls += 1;
      return new Promise<{ ok: number }>((resolve) => {
        setTimeout(() => resolve({ ok: 1 }), 20);
      });
    };
    const a = fetchDetailDeduped("SO/1", stores, requestFn, { force: true });
    const b = fetchDetailDeduped("SO/1", stores, requestFn, { force: true });
    const [ra, rb] = await Promise.all([a, b]);
    expect(calls).toBe(1);
    expect(ra).toBe(rb);
    expect(stores.cache["SO/1"]).toEqual({ ok: 1 });
  });

  it("stale generation isolation blocks overwrite", () => {
    expect(shouldApplyDetail(2, 1, true)).toBe(false);
    expect(shouldApplyDetail(2, 2, false)).toBe(false);
    expect(shouldApplyDetail(2, 2, true)).toBe(true);
  });

  it("valid qty is not regressively unverified", () => {
    expect(isQtyUnverified({ qty: 2000, qtyVerified: true })).toBe(false);
    const q = productionQtySnapshot(
      { qty: 2000, qtyVerified: true, done: 0 },
      { live: true, printPhysicalQty: 1000, unknownPhysicalQty: 0 },
    );
    expect(q.qty).toBe(1000);
    expect(q.qtyUnverified).toBe(false);
  });

  it("legacy/demo qty without flag is not forced UNKNOWN", () => {
    expect(isQtyUnverified({ qty: 5000 })).toBe(false);
    const q = productionQtySnapshot({ qty: 5000, done: 5000 });
    expect(q.qtyUnverified).toBe(false);
    expect(scheduleLeadLabel({ qty: 5000, done: 5000, ship: "15 Nov 2026" }, q)).toBe(
      "Selesai",
    );
  });
});

describe("Slice 1M.1 public runtime helper (live-qty-integrity.js)", () => {
  const api = loadPublicRuntime();

  it("public helper matches: UNKNOWN never Selesai", () => {
    const o = { id: "SO/P", qty: null, qtyVerified: false, ship: "12 Nov 2026" };
    const q = api.productionQtySnapshot(o, { live: true });
    expect(q.qtyUnverified).toBe(true);
    expect(api.scheduleLeadLabel(o, q)).toBe("Qty belum terverifikasi");
  });

  it("public helper inbox Retry escapes SO id", () => {
    const html = api.inboxQtyCellHtml({
      id: "SO/'\"X",
      detailLoadState: "failed",
      qtyVerified: false,
    });
    expect(html).toContain("Retry");
    expect(html).toContain("retryInboxDetail");
    expect(html).not.toMatch(/retryInboxDetail\('SO'"/);
  });

  it("public helper force retries dedupe inflight", async () => {
    let calls = 0;
    const stores = { cache: {}, inflight: {} };
    const req = () => {
      calls += 1;
      return Promise.resolve({ n: 1 });
    };
    const p1 = api.fetchDetailDeduped("Z", stores, req, { force: true });
    const p2 = api.fetchDetailDeduped("Z", stores, req, { force: true });
    await Promise.all([p1, p2]);
    expect(calls).toBe(1);
  });

  it("public helper KPI omits unverified from total", () => {
    const sum = api.scheduleOverviewSum(
      [
        { id: "1", qty: 500, qtyVerified: true },
        { id: "2", qtyVerified: false },
      ],
      (o: { qtyVerified?: boolean; qty?: number }) =>
        api.productionQtySnapshot(o, {
          live: true,
          printPhysicalQty: o.qtyVerified ? o.qty : 0,
        }),
      (o: object) => api.scheduleLeadLabel(o),
    );
    expect(sum.qty).toBe(500);
    expect(sum.unverifiedPoCount).toBe(1);
  });
});
