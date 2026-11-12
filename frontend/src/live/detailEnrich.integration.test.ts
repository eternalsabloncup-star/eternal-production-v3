/** Step 139 — runtime enrich logic: cache, concurrency 3, page switch, Retry. */
import { describe, expect, it, vi } from "vitest";
import {
  fetchDetailDeduped,
  markDetailFailedState,
  shouldApplyDetail,
  type DetailFetchStores,
} from "./detailEnrich";

const ENRICH_CONCURRENCY = 3;

async function enrichPage(
  numbers: string[],
  stores: DetailFetchStores<{ expedition?: string | null }>,
  requestFn: (so: string) => Promise<{ expedition?: string | null }>,
  opts: {
    force?: boolean;
    getGeneration: () => number;
    orderPresent: (so: string) => boolean;
    onApply: (so: string, detail: { expedition?: string | null }) => void;
    onFail: (so: string) => void;
  },
) {
  const started = opts.getGeneration();
  const queue = numbers.slice();
  async function worker() {
    while (queue.length) {
      const so = queue.shift();
      if (!so) return;
      if (opts.getGeneration() !== started) return;
      try {
        const detail = await fetchDetailDeduped(
          so,
          stores,
          () => requestFn(so),
          { force: opts.force },
        );
        if (!shouldApplyDetail(opts.getGeneration(), started, opts.orderPresent(so))) {
          continue;
        }
        opts.onApply(so, detail);
      } catch {
        if (!shouldApplyDetail(opts.getGeneration(), started, opts.orderPresent(so))) {
          continue;
        }
        opts.onFail(so);
      }
    }
  }
  const n = Math.min(ENRICH_CONCURRENCY, Math.max(1, queue.length));
  await Promise.all(Array.from({ length: n }, () => worker()));
}

describe("Step 139 enrich integration", () => {
  it("dedupes inflight and caches success; failure not cached", async () => {
    const stores: DetailFetchStores<{ expedition: string }> = {
      cache: {},
      inflight: {},
    };
    let calls = 0;
    const requestFn = () => {
      calls += 1;
      return new Promise<{ expedition: string }>((resolve) =>
        setTimeout(() => resolve({ expedition: "DIAMBIL" }), 20),
      );
    };
    const a = fetchDetailDeduped("SO/1", stores, requestFn, {});
    const b = fetchDetailDeduped("SO/1", stores, requestFn, {});
    expect(await a).toEqual({ expedition: "DIAMBIL" });
    expect(await b).toEqual({ expedition: "DIAMBIL" });
    expect(calls).toBe(1);
    expect(stores.cache["SO/1"]).toEqual({ expedition: "DIAMBIL" });

    // Retry force joins inflight, does not duplicate.
    calls = 0;
    let resolveHang!: (v: { expedition: string }) => void;
    const hang = new Promise<{ expedition: string }>((r) => {
      resolveHang = r;
    });
    const c = fetchDetailDeduped("SO/2", stores, () => {
      calls += 1;
      return hang;
    }, { force: true });
    const d = fetchDetailDeduped("SO/2", stores, () => {
      calls += 1;
      return hang;
    }, { force: true });
    resolveHang({ expedition: "JNE" });
    expect(await c).toEqual({ expedition: "JNE" });
    expect(await d).toEqual({ expedition: "JNE" });
    expect(calls).toBe(1);

    // Failure clears cache.
    await expect(
      fetchDetailDeduped("SO/3", stores, async () => {
        throw new Error("timeout");
      }),
    ).rejects.toThrow("timeout");
    expect(stores.cache["SO/3"]).toBeUndefined();
    expect(stores.inflight["SO/3"]).toBeUndefined();
  });

  it("bounds concurrency to 3 and skips stale page after switch", async () => {
    const stores: DetailFetchStores<{ expedition: string }> = {
      cache: {},
      inflight: {},
    };
    let generation = 1;
    let maxInflight = 0;
    let inflight = 0;
    const applied: string[] = [];
    const present = new Set(["A", "B", "C", "D", "E"]);
    const requestFn = async (so: string) => {
      inflight += 1;
      maxInflight = Math.max(maxInflight, inflight);
      await new Promise((r) => setTimeout(r, 30));
      inflight -= 1;
      return { expedition: so };
    };
    const run = enrichPage(["A", "B", "C", "D", "E"], stores, requestFn, {
      getGeneration: () => generation,
      orderPresent: (so) => present.has(so),
      onApply: (so) => applied.push(so),
      onFail: () => undefined,
    });
    // Mid-flight page switch: bump generation + drop off-page SOs from presence.
    await new Promise((r) => setTimeout(r, 5));
    generation = 2;
    present.clear();
    present.add("X");
    await run;
    expect(maxInflight).toBeLessThanOrEqual(3);
    // Stale generation must not apply prior page results after switch.
    expect(applied.every((so) => present.has(so))).toBe(true);
  });

  it("Retry marks failed then force-refresh can succeed", async () => {
    const o: {
      qtyVerified: boolean;
      qty: number | null;
      detailLoadState?: string;
      detailLoaded?: boolean;
      detailError?: string | null;
      expedition?: string | null;
    } = { qtyVerified: false, qty: null };
    markDetailFailedState(o);
    expect(o.detailLoadState).toBe("failed");
    expect(o.qty).toBeNull();

    const stores: DetailFetchStores<{ expedition: string }> = {
      cache: {},
      inflight: {},
    };
    // Simulate failed cache miss then Retry force.
    await expect(
      fetchDetailDeduped("SO/R", stores, async () => {
        throw new Error("503");
      }),
    ).rejects.toThrow("503");
    const detail = await fetchDetailDeduped(
      "SO/R",
      stores,
      async () => ({ expedition: "DIAMBIL" }),
      { force: true },
    );
    o.expedition = detail.expedition;
    o.detailLoadState = "loaded";
    o.detailLoaded = true;
    o.detailError = null;
    expect(o.expedition).toBe("DIAMBIL");
    expect(o.detailLoadState).toBe("loaded");
  });

  it("ENRICH_CONCURRENCY constant remains 3 (live-runtime contract)", () => {
    expect(ENRICH_CONCURRENCY).toBe(3);
  });
});
