/** Slice 1D — Accurate Live inbox state synchronization helpers. */

export type InboxOrder = {
  id: string;
  productionStatus?: string;
  name?: string;
  item?: string;
  qty?: number;
  branch?: string;
  salesName?: string;
};

export type InboxMeta = {
  page: number;
  pageSize: number;
  total: number | null;
  rowCount: number;
};

/** Mirror live-runtime publish: shared global identity for renderer + runtime. */
export function publishSharedOrders<T>(
  globalScope: { orders?: T[] },
  rows: T[],
): T[] {
  const list = Array.isArray(rows) ? rows : [];
  globalScope.orders = list;
  return list;
}

export function isSharedOrdersReference(
  localOrders: unknown,
  windowOrders: unknown,
): boolean {
  return localOrders === windowOrders;
}

export function countBaruTerproses(orders: InboxOrder[]): {
  baru: number;
  terproses: number;
  pageCount: number;
} {
  let baru = 0;
  let terproses = 0;
  for (const o of orders) {
    if (o.productionStatus === "Terproses") terproses += 1;
    else baru += 1; // monitoring statuses: Baru | Terproses only
  }
  return { baru, terproses, pageCount: orders.length };
}

/** Page KPI must use current page rows — never Accurate grand total. */
export function pageKpiCount(
  orders: InboxOrder[],
  accurateTotal: number | null,
): number {
  void accurateTotal;
  return orders.length;
}

export function shouldClearOnApiError(status: number): boolean {
  return status >= 400;
}

export function shouldRedirectUnauthorized(status: number): boolean {
  return status === 401;
}

export function rejectDemoFallback(mode: string | undefined): boolean {
  return mode !== "live";
}
