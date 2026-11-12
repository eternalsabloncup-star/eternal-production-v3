/**
 * Jadwal Produksi — V1 default column order / visibility (presentation only).
 * Runtime mirror lives in frontend/public/production.html.
 */

export type ScheduleColumnCategory =
  | "IDENTITAS PO"
  | "PENJADWALAN"
  | "PRODUKSI"
  | "PROGRESS PRODUKSI"
  | "STATUS"
  | "LAINNYA";

/** V1 screenshot order — only keys that exist (or are officially added) in V3. */
export const V1_DEFAULT_ORDER: string[] = [
  "id", // No PO
  "name", // Customer
  "assignmentDate", // Tgl Pengerjaan
  "operator", // Operator
  "item", // Item
  "scheduled", // Qty Cetak (Scheduled)
  "assignmentQty", // Qty Pengerjaan Operator
  "progress", // Progress
  "qty", // Total Qty
  "orderPriority", // Prio
  "bufferLabel", // Buffer
  "ship", // Tanggal Pengiriman
  // GAP: Sumber Jadwal — no authoritative V3 field
  "branch", // Outlet (Cabang)
  "screen", // Screen (mesin) — presentation split from operator
  "inkSequence", // Per. / Jumlah Warna
  "designGate", // Design
  "paymentGate", // Payment
  "holdStatus", // HOLD (only when o.hold known)
  "prepStatus", // Persiapan (demo/task evidence when present)
  "packed", // Packing
  "status", // Status Akhir
];

/** Default visible = V1 list keys that are implemented. */
export const V1_DEFAULT_VISIBLE: string[] = [...V1_DEFAULT_ORDER, "action"];

export const COLUMN_CATEGORY: Record<string, ScheduleColumnCategory> = {
  id: "IDENTITAS PO",
  name: "IDENTITAS PO",
  orderDate: "IDENTITAS PO",
  address: "IDENTITAS PO",
  salesName: "IDENTITAS PO",
  branch: "IDENTITAS PO",
  assignmentDate: "PENJADWALAN",
  scheduleDate: "PENJADWALAN",
  operator: "PENJADWALAN",
  screen: "PENJADWALAN",
  item: "PRODUKSI",
  itemCodes: "PRODUKSI",
  itemQtys: "PRODUKSI",
  itemUnits: "PRODUKSI",
  itemProcesses: "PRODUKSI",
  inkColors: "PRODUKSI",
  inkSequence: "PRODUKSI",
  scheduled: "PROGRESS PRODUKSI",
  assignmentQty: "PROGRESS PRODUKSI",
  progress: "PROGRESS PRODUKSI",
  qty: "PROGRESS PRODUKSI",
  done: "PROGRESS PRODUKSI",
  remainingTotal: "PROGRESS PRODUKSI",
  remainingScheduled: "PROGRESS PRODUKSI",
  unassigned: "PROGRESS PRODUKSI",
  packed: "PROGRESS PRODUKSI",
  prepStatus: "PROGRESS PRODUKSI",
  orderPriority: "STATUS",
  bufferLabel: "STATUS",
  ship: "STATUS",
  designGate: "STATUS",
  paymentGate: "STATUS",
  holdStatus: "STATUS",
  status: "STATUS",
  productionStatus: "STATUS",
  receipt: "STATUS",
  deadline: "STATUS",
  action: "LAINNYA",
};

/** Gaps vs V1 screenshot (not inventable without official source). */
export const V1_COLUMN_GAPS: { v1Label: string; reason: string }[] = [
  {
    v1Label: "Sumber Jadwal",
    reason: "Tidak ada field authoritative di V3 (job/assignment/Accurate).",
  },
];

export function mergeColumnOrder(
  preferred: string[] | null | undefined,
  allKeys: string[],
): string[] {
  const known = new Set(allKeys);
  if (!Array.isArray(preferred) || !preferred.length) {
    return defaultOrderWithRemainder(allKeys);
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of preferred) {
    if (!known.has(k) || seen.has(k)) continue;
    seen.add(k);
    out.push(k);
  }
  const missing = allKeys.filter((k) => !seen.has(k));
  const actionAt = out.indexOf("action");
  if (actionAt >= 0) {
    return [...out.slice(0, actionAt), ...missing, out[actionAt], ...out.slice(actionAt + 1)];
  }
  return [...out, ...missing];
}

export function defaultOrderWithRemainder(allKeys: string[]): string[] {
  const known = new Set(allKeys);
  const head = V1_DEFAULT_ORDER.filter((k) => known.has(k));
  const used = new Set(head);
  const rest = allKeys.filter((k) => !used.has(k) && k !== "action");
  const hasAction = allKeys.includes("action");
  return hasAction ? [...head, ...rest, "action"] : [...head, ...rest];
}

export function defaultVisibleSet(allKeys: string[]): Set<string> {
  const known = new Set(allKeys);
  return new Set(V1_DEFAULT_VISIBLE.filter((k) => known.has(k)));
}

/** Contiguous category spans for group header; skips non-contiguous mixes. */
export function contiguousCategorySpans(
  visibleOrderedKeys: string[],
): { category: ScheduleColumnCategory; span: number }[] {
  const spans: { category: ScheduleColumnCategory; span: number }[] = [];
  for (const key of visibleOrderedKeys) {
    if (key === "action") continue;
    const cat = COLUMN_CATEGORY[key] || "LAINNYA";
    const last = spans[spans.length - 1];
    if (last && last.category === cat) last.span += 1;
    else spans.push({ category: cat, span: 1 });
  }
  return spans;
}

export function filterColumnsByQuery(
  keys: string[],
  labels: Record<string, string>,
  query: string,
): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return keys;
  return keys.filter((k) => {
    const label = (labels[k] || k).toLowerCase();
    return label.includes(q) || k.toLowerCase().includes(q);
  });
}
