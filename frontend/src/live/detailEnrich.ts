/** Slice 1M.1 — detail fetch cache / inflight dedupe (pure). */

export type DetailFetchStores<T> = {
  cache: Record<string, T>;
  inflight: Record<string, Promise<T>>;
};

/**
 * Fetch SO detail with:
 * - valid cache hit (unless force)
 * - inflight promise reuse even when force=true (no duplicate in-flight request)
 * - force clears cache then reuses inflight if present, else starts new request
 * - failures must not remain in cache
 */
export async function fetchDetailDeduped<T>(
  number: string,
  stores: DetailFetchStores<T>,
  requestFn: () => Promise<T>,
  opts?: { force?: boolean },
): Promise<T> {
  const force = !!(opts && opts.force);
  if (force) {
    delete stores.cache[number];
  } else if (stores.cache[number] !== undefined) {
    return stores.cache[number];
  }
  if (Object.prototype.hasOwnProperty.call(stores.inflight, number)) {
    return stores.inflight[number];
  }
  const pending = requestFn()
    .then((detail) => {
      stores.cache[number] = detail;
      delete stores.inflight[number];
      return detail;
    })
    .catch((err) => {
      delete stores.inflight[number];
      delete stores.cache[number];
      throw err;
    });
  stores.inflight[number] = pending;
  return pending;
}

/** Stale generation / page isolation: apply only when still current. */
export function shouldApplyDetail(
  enrichGeneration: number,
  startedGeneration: number,
  orderStillPresent: boolean,
): boolean {
  return enrichGeneration === startedGeneration && orderStillPresent;
}

export function markDetailFailedState(o: {
  qtyVerified?: boolean;
  qty?: number | null;
  detailLoadState?: string;
  detailLoaded?: boolean;
  detailError?: string | null;
}): void {
  o.detailLoadState = "failed";
  o.detailLoaded = false;
  o.detailError = "Gagal memuat detail Accurate";
  if (!o.qtyVerified) {
    o.qty = null;
  }
}
