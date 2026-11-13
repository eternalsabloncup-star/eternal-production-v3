import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { describe, expect, it } from "vitest";

import {
  inboxDetailDependentHtml,
  inboxFieldHasVerifiedDisplay,
} from "./inboxDetailState";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadPublicApi(): Record<string, Function> {
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

describe("Step 86 inbox detail field states", () => {
  it("list loaded / detail pending → Belum dimuat (no em dash)", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "not_loaded" },
      { value: null },
    );
    expect(html).toContain("Belum dimuat");
    expect(html).not.toContain("—");
  });

  it("detail loading → Memuat…", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loading" },
      { value: null },
    );
    expect(html).toContain("Memuat…");
    expect(html).not.toContain("—");
  });

  it("detail failed → Gagal dimuat + existing Retry hook", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO/1", detailLoadState: "failed" },
      { value: null },
    );
    expect(html).toContain("Gagal dimuat");
    expect(html).toContain("retryInboxDetail");
    expect(html).toContain("SO/1");
    expect(html).not.toContain("—");
  });

  it("preserves verified list value while detail loading", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loading" },
      { value: "ZONE-A" },
    );
    expect(html).toBe("ZONE-A");
  });

  it("detail success field missing → Belum tersedia", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loaded" },
      { value: null, absence: "unavailable" },
    );
    expect(html).toContain("Belum tersedia");
  });

  it("detail success verified value", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loaded" },
      { value: "JNE", absence: "unverified" },
    );
    expect(html).toBe("JNE");
  });

  it("Sales/Expedition UNKNOWN → Belum terverifikasi (not Normal/false)", () => {
    const sales = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loaded" },
      { value: null, absence: "unverified" },
    );
    const exp = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loaded" },
      { value: "Belum terverifikasi", absence: "unverified" },
    );
    expect(sales).toContain("Belum terverifikasi");
    expect(exp).toContain("Belum terverifikasi");
    expect(sales).not.toMatch(/Normal|false/i);
  });

  it("multi-line item rendering preserved via wrap", () => {
    const html = inboxDetailDependentHtml(
      { id: "SO-1", detailLoadState: "loaded" },
      {
        value: "Cetak\nTidak Cetak",
        wrap: (v) => `<div class="po-multiline">${v}</div>`,
      },
    );
    expect(html).toBe('<div class="po-multiline">Cetak\nTidak Cetak</div>');
  });

  it("placeholders are not treated as verified display", () => {
    expect(inboxFieldHasVerifiedDisplay("—")).toBe(false);
    expect(inboxFieldHasVerifiedDisplay("Belum terverifikasi")).toBe(false);
    expect(inboxFieldHasVerifiedDisplay("Detail barang belum dimuat")).toBe(
      false,
    );
    expect(inboxFieldHasVerifiedDisplay("Urgent")).toBe(true);
    expect(inboxFieldHasVerifiedDisplay(0)).toBe(true);
  });

  it("Urgent/Buffer verified labels preserved during loading", () => {
    expect(
      inboxDetailDependentHtml(
        { detailLoadState: "loading" },
        { value: "Urgent", absence: "unverified" },
      ),
    ).toBe("Urgent");
    expect(
      inboxDetailDependentHtml(
        { detailLoadState: "loading" },
        { value: "Non-Buffer", absence: "unverified" },
      ),
    ).toBe("Non-Buffer");
  });

  it("public runtime helper matches + qty states + dedupe/stale", async () => {
    const api = loadPublicApi();
    expect(
      api.inboxDetailDependentHtml(
        { id: "X", detailLoadState: "failed" },
        { value: null },
      ),
    ).toContain("Gagal dimuat");

    const qtyOk = api.inboxQtyCellHtml(
      { id: "X", qty: 0, qtyVerified: true, detailLoadState: "loaded" },
      (s: unknown) => String(s),
    );
    expect(qtyOk).toContain("0");

    const qtyUnverified = api.inboxQtyCellHtml(
      { id: "X", qty: null, qtyVerified: false, detailLoadState: "loaded" },
      (s: unknown) => String(s),
    );
    expect(qtyUnverified).toContain("Qty belum terverifikasi");

    // pagination stale
    expect(api.shouldApplyDetail(2, 1, true)).toBe(false);
    expect(api.shouldApplyDetail(2, 2, true)).toBe(true);

    // detail dedupe
    const stores: {
      cache: Record<string, unknown>;
      inflight: Record<string, Promise<unknown>>;
    } = { cache: {}, inflight: {} };
    let calls = 0;
    const fetcher = async () => {
      calls += 1;
      return { ok: true };
    };
    const a = api.fetchDetailDeduped("SO-1", stores, fetcher, {});
    const b = api.fetchDetailDeduped("SO-1", stores, fetcher, {});
    await Promise.all([a, b]);
    expect(calls).toBe(1);

    // retry success path: force bypasses cache
    stores.cache["SO-1"] = { stale: true };
    await api.fetchDetailDeduped("SO-1", stores, fetcher, { force: true });
    expect(calls).toBe(2);
  });
});
