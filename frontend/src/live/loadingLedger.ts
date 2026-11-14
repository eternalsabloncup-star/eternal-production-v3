/** Loading ledger helpers — SJ-line authority; Loading is capped by packing-verified qty and SJ-line remaining. */

export type LoadingLedgerEvent = {
  id: number;
  event_type: string;
  qty_physical?: string | number | null;
  accurate_sj_id?: string | null;
  accurate_sj_number?: string | null;
  accurate_sj_line_id?: string | null;
  so_line_id?: string | null;
  actor_user_id?: number | null;
  reason?: string | null;
  payload_json?: string | null;
  evidence_ref?: string | null;
  created_at?: string | null;
};

export type LoadingRowSummary = {
  eventId: number;
  accurateSjId: string;
  accurateSjNumber: string;
  accurateSjLineId: string;
  soLineId: string;
  confirmedQty: number;
  cancelledQty: number;
  netLoadedQty: number;
  remainingOnEvent: number;
};

export type SjLineAuthority = {
  accurate_sj_id: string;
  accurate_sj_number?: string | null;
  accurate_sj_line_id: string;
  so_line_id: string;
  verification?: string | null;
  qty_sj_pcs?: string | number | null;
  loading_confirmed?: string | number | null;
  loading_cancelled?: string | number | null;
  loading_net?: string | number | null;
  remaining_loading?: string | number | null;
  actions_enabled?: boolean | null;
  note?: string | null;
};

export type LineAuthorityView = {
  accurateSjId: string;
  accurateSjNumber: string;
  accurateSjLineId: string;
  soLineId: string;
  verification: "VERIFIED" | "UNKNOWN";
  qtySj: number | null;
  loadingConfirmed: number;
  loadingCancelled: number;
  loadingNet: number;
  remainingLoading: number | null;
  actionsEnabled: boolean;
  displayQtySj: string;
  displayRemaining: string;
};

function qty(ev: LoadingLedgerEvent): number {
  const n = Number(ev.qty_physical);
  return Number.isFinite(n) ? n : 0;
}

function parsePayload(ev: LoadingLedgerEvent): Record<string, unknown> {
  if (!ev.payload_json) return {};
  try {
    const data = JSON.parse(ev.payload_json);
    return data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function numOrNull(raw: string | number | null | undefined): number | null {
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function reversesEventId(ev: LoadingLedgerEvent): number | null {
  const raw = parsePayload(ev).reverses_event_id;
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function requestEventId(ev: LoadingLedgerEvent): number | null {
  const raw = parsePayload(ev).request_event_id;
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** Per confirmed Loading event: confirmed / cancelled / net remaining on that event. */
export function summarizeLoadingEvents(
  events: LoadingLedgerEvent[],
): LoadingRowSummary[] {
  const loadings = (events || []).filter((e) => e.event_type === "loading");
  const cancels = (events || []).filter((e) => e.event_type === "loading_cancelled");
  return loadings.map((load) => {
    const cancelledQty = cancels
      .filter((c) => reversesEventId(c) === load.id)
      .reduce((s, c) => s + qty(c), 0);
    const confirmedQty = qty(load);
    const remainingOnEvent = Math.max(0, confirmedQty - cancelledQty);
    return {
      eventId: load.id,
      accurateSjId: String(load.accurate_sj_id || ""),
      accurateSjNumber: String(load.accurate_sj_number || load.accurate_sj_id || ""),
      accurateSjLineId: String(load.accurate_sj_line_id || ""),
      soLineId: String(load.so_line_id || ""),
      confirmedQty,
      cancelledQty,
      netLoadedQty: remainingOnEvent,
      remainingOnEvent,
    };
  });
}

/** Net confirmed Loading for an SJ line key. */
export function netLoadedForLine(
  events: LoadingLedgerEvent[],
  accurateSjId: string,
  accurateSjLineId: string,
  soLineId: string,
): number {
  return summarizeLoadingEvents(events)
    .filter(
      (r) =>
        r.accurateSjId === accurateSjId &&
        r.accurateSjLineId === accurateSjLineId &&
        r.soLineId === soLineId,
    )
    .reduce((s, r) => s + r.netLoadedQty, 0);
}

export function lineAuthorityKey(
  accurateSjId: string,
  accurateSjLineId: string,
  soLineId: string,
): string {
  return `${accurateSjId}::${accurateSjLineId}::${soLineId}`;
}

/** Map board sj_line_authority → UI view. Unknown qty → UNKNOWN, never invent. */
export function viewSjLineAuthority(row: SjLineAuthority): LineAuthorityView {
  const verified = row.verification === "VERIFIED";
  const qtySj = verified ? numOrNull(row.qty_sj_pcs) : null;
  const confirmed = numOrNull(row.loading_confirmed) ?? 0;
  const cancelled = numOrNull(row.loading_cancelled) ?? 0;
  const net = numOrNull(row.loading_net);
  const loadingNet =
    net != null ? net : Math.max(0, confirmed - cancelled);
  const remaining =
    verified && qtySj != null ? numOrNull(row.remaining_loading) : null;
  const actionsEnabled = Boolean(row.actions_enabled) && verified && qtySj != null;
  return {
    accurateSjId: String(row.accurate_sj_id || ""),
    accurateSjNumber: String(row.accurate_sj_number || row.accurate_sj_id || ""),
    accurateSjLineId: String(row.accurate_sj_line_id || ""),
    soLineId: String(row.so_line_id || ""),
    verification: actionsEnabled ? "VERIFIED" : "UNKNOWN",
    qtySj,
    loadingConfirmed: confirmed,
    loadingCancelled: cancelled,
    loadingNet,
    remainingLoading: remaining,
    actionsEnabled,
    displayQtySj: qtySj == null ? "UNKNOWN" : String(qtySj),
    displayRemaining: remaining == null ? "UNKNOWN" : String(remaining),
  };
}

export function findLineAuthority(
  rows: SjLineAuthority[] | null | undefined,
  accurateSjId: string,
  accurateSjLineId: string,
  soLineId: string,
): LineAuthorityView | null {
  const hit = (rows || []).find(
    (r) =>
      String(r.accurate_sj_id || "") === accurateSjId &&
      String(r.accurate_sj_line_id || "") === accurateSjLineId &&
      String(r.so_line_id || "") === soLineId,
  );
  return hit ? viewSjLineAuthority(hit) : null;
}

export type ReturnRequestStatus = "pending" | "approved" | "rejected";

export function returnRequestStatus(
  events: LoadingLedgerEvent[],
  requestId: number,
): ReturnRequestStatus {
  for (const ev of events || []) {
    if (requestEventId(ev) !== requestId) continue;
    if (ev.event_type === "loading_return_rejected") return "rejected";
    if (
      ev.event_type === "loading_cancelled" &&
      parsePayload(ev).cancel_kind === "physical_return"
    ) {
      return "approved";
    }
  }
  return "pending";
}

export function pendingReturnRequests(
  events: LoadingLedgerEvent[],
): LoadingLedgerEvent[] {
  return (events || []).filter(
    (e) =>
      e.event_type === "loading_return_requested" &&
      returnRequestStatus(events, e.id) === "pending",
  );
}

export const PERM_DELIVERY_MANAGE = "production.delivery.manage";
export const PERM_LOADING_RETURN_REQUEST =
  "production.delivery.loading_return.request";
export const PERM_LOADING_RETURN_APPROVE =
  "production.delivery.loading_return.approve";

export function hasPermission(
  permissions: string[] | null | undefined,
  needed: string,
): boolean {
  return (permissions || []).includes(needed);
}
