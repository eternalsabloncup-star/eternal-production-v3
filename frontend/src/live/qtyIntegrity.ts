/** Slice 1M.1 — qty verification, Tenggat, KPI, Inbox qty cell (pure). */

export type DetailLoadState =
  | "not_loaded"
  | "loading"
  | "loaded"
  | "failed"
  | string
  | null
  | undefined;

export type QtyOrderLike = {
  id?: string;
  qty?: number | null;
  qtyVerified?: boolean;
  qtyUnverified?: boolean;
  detailLoadState?: DetailLoadState;
  detailError?: string | null;
  ship?: string | null;
  done?: number | null;
  packed?: number | null;
  scheduledQty?: number | null;
  sourceLines?: Array<{
    qty?: number | null;
    qtyVerified?: boolean;
    production_process?: string | null;
    processSnapshot?: string | null;
  }> | null;
};

export type ProductionQtySnapshot = {
  qty: number | null;
  scheduled: number;
  done: number;
  packed: number;
  unassigned: number;
  remainingScheduled: number;
  remainingTotal: number | null;
  invalid: boolean;
  unknownQty: number;
  qtyUnverified: boolean;
};

export function isQtyUnverified(o: QtyOrderLike | null | undefined): boolean {
  if (!o) return true;
  if (o.qtyUnverified === true) return true;
  if (o.qtyVerified === false) return true;
  if (o.qtyVerified === true) {
    return o.qty == null || !Number.isFinite(Number(o.qty));
  }
  // Legacy/demo rows without an explicit flag: missing/non-finite qty is unknown.
  if (o.qty == null || !Number.isFinite(Number(o.qty))) return true;
  return false;
}

export function productionQtySnapshot(
  o: QtyOrderLike,
  opts?: {
    live?: boolean;
    printPhysicalQty?: number;
    unknownPhysicalQty?: number;
  },
): ProductionQtySnapshot {
  const live = opts?.live === true;
  if (live && isQtyUnverified(o)) {
    return {
      qty: null,
      scheduled: 0,
      done: 0,
      packed: 0,
      unassigned: 0,
      remainingScheduled: 0,
      remainingTotal: null,
      invalid: false,
      unknownQty: 1,
      qtyUnverified: true,
    };
  }
  const qty = live
    ? Math.max(0, Math.trunc(Number(opts?.printPhysicalQty) || 0))
    : Math.max(0, Math.trunc(Number(o.qty) || 0));
  const scheduled = Math.min(
    qty,
    Math.max(0, Math.trunc(Number(o.scheduledQty) || 0)),
  );
  const done = Math.min(qty, Math.max(0, Math.trunc(Number(o.done) || 0)));
  const packed = Math.max(0, Math.trunc(Number(o.packed) || 0));
  return {
    qty,
    scheduled,
    done,
    packed,
    unassigned: Math.max(0, qty - scheduled),
    remainingScheduled: Math.max(0, scheduled - done),
    remainingTotal: Math.max(0, qty - done),
    invalid:
      scheduled > qty || done > qty || done > scheduled || packed > done,
    unknownQty: live ? Math.max(0, Number(opts?.unknownPhysicalQty) || 0) : 0,
    qtyUnverified: false,
  };
}

/** Tenggat / lead label — never "Selesai" when qty unverified. */
export function scheduleLeadLabel(
  o: QtyOrderLike,
  q?: ProductionQtySnapshot,
): string {
  const snap = q || productionQtySnapshot(o, { live: true });
  if (snap.qtyUnverified) {
    return "Qty belum terverifikasi";
  }
  const m = String(o.ship || "").match(/(\d{1,2}) Nov 2026/);
  if (!m) return "Belum ada target";
  const n = Number(m[1]) - 9;
  if (snap.remainingTotal == null) return "Qty belum terverifikasi";
  if (!snap.remainingTotal) return "Selesai";
  if (n < 0) return "Terlambat " + Math.abs(n) + " hari";
  if (n === 0) return "Hari ini";
  if (n === 1) return "Besok";
  return n + " hari lagi";
}

export type ScheduleOverviewSum = {
  qty: number;
  scheduled: number;
  done: number;
  remainingTotal: number;
  unassigned: number;
  remainingScheduled: number;
  unknownQty: number;
  unverifiedPoCount: number;
  invalid: number;
  deadline: number;
  cells: Array<[string, number | string]>;
};

export function scheduleOverviewSum(
  rows: QtyOrderLike[],
  productionQtyFor: (o: QtyOrderLike) => ProductionQtySnapshot,
  leadFor: (o: QtyOrderLike) => string,
): ScheduleOverviewSum {
  const unique: QtyOrderLike[] = [];
  const seen = new Set<string>();
  for (const o of rows || []) {
    const id = o && o.id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    unique.push(o);
  }
  const sum: ScheduleOverviewSum = {
    qty: 0,
    scheduled: 0,
    done: 0,
    remainingTotal: 0,
    unassigned: 0,
    remainingScheduled: 0,
    unknownQty: 0,
    unverifiedPoCount: 0,
    invalid: 0,
    deadline: 0,
    cells: [],
  };
  for (const o of unique) {
    const q = productionQtyFor(o);
    if (q.qtyUnverified) {
      sum.unverifiedPoCount += 1;
      sum.unknownQty += q.unknownQty || 1;
    } else {
      sum.qty += q.qty || 0;
      sum.scheduled += q.scheduled || 0;
      sum.done += q.done || 0;
      sum.remainingTotal += q.remainingTotal || 0;
      sum.unassigned += q.unassigned || 0;
      sum.remainingScheduled += q.remainingScheduled || 0;
      sum.unknownQty += q.unknownQty || 0;
    }
    if (q.invalid) sum.invalid += 1;
    const lead = leadFor(o);
    if (
      lead === "Hari ini" ||
      lead === "Besok" ||
      lead.startsWith("Terlambat")
    ) {
      sum.deadline += 1;
    }
  }
  const qtyLabel = sum.unverifiedPoCount
    ? "Total Qty Cetak (terverifikasi)"
    : "Total Qty Cetak";
  sum.cells = [
    [qtyLabel, sum.qty],
    ["Qty Terjadwal", sum.scheduled],
    ["Sudah Dicetak", sum.done],
    ["Belum Dicetak", sum.remainingTotal],
    ["Sisa Terjadwal", sum.remainingScheduled],
    ["Belum Dijadwalkan", sum.unassigned],
  ];
  if (sum.unverifiedPoCount) {
    sum.cells.push([
      "PO Qty belum terverifikasi",
      sum.unverifiedPoCount,
    ]);
  }
  if (sum.unknownQty && !sum.unverifiedPoCount) {
    sum.cells.push(["Qty Proses Belum Terverifikasi", sum.unknownQty]);
  }
  return sum;
}

export function escapeAttr(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Inbox Accurate qty cell — states from detailLoadState + verification. */
export function inboxQtyCellHtml(
  o: QtyOrderLike,
  escapeFn: (s: unknown) => string = escapeAttr,
): string {
  const state = o.detailLoadState || "not_loaded";
  if (o.qtyVerified === true && o.qty != null && Number.isFinite(Number(o.qty))) {
    return `<b class="right">${Number(o.qty).toLocaleString("id-ID")}</b>`;
  }
  if (state === "loading") {
    return '<span class="muted">Memuat…</span>';
  }
  if (state === "failed") {
    const so = escapeFn(o.id || "");
    return `<span class="muted">Gagal memuat</span> <button type="button" class="btn sm" onclick="window.retryInboxDetail&&window.retryInboxDetail('${so}')">Retry</button>`;
  }
  if (state === "loaded") {
    return '<span class="muted">Qty belum terverifikasi</span>';
  }
  return '<span class="muted">Belum dimuat</span>';
}

/** Progress % for schedule detail — UNKNOWN when qty unverified. */
export function scheduleDetailProgress(
  o: QtyOrderLike,
): { label: string; pct: number; unknown: boolean } {
  if (isQtyUnverified(o)) {
    return { label: "UNKNOWN", pct: 0, unknown: true };
  }
  const qty = Number(o.qty);
  const done = Math.max(0, Math.trunc(Number(o.done) || 0));
  if (!Number.isFinite(qty) || qty <= 0) {
    return { label: "UNKNOWN", pct: 0, unknown: true };
  }
  const pct = Math.min(100, Math.round((100 * done) / qty));
  return {
    label: `${pct}% · ${done.toLocaleString("id-ID")} / ${qty.toLocaleString("id-ID")} pcs`,
    pct,
    unknown: false,
  };
}
