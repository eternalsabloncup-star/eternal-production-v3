/** Slice 1N.1 / Step 58 — single source for Accurate urgent → UI flags. */

export type UrgentFlag = boolean | null;

export type UrgentFields = {
  urgent: UrgentFlag;
  urgentState: string | null;
  orderPriority: string;
};

/** Canonical Accurate urgent_state → boolean|null (never invent false for unknown). */
export function urgentFlagFromState(
  urgentState: string | null | undefined,
): UrgentFlag {
  if (urgentState == null) return null;
  const s = String(urgentState).trim();
  if (!s) return null;
  if (s === "approved_urgent" || s === "legacy_urgent") return true;
  if (s === "normal") return false;
  return null;
}

export function orderPriorityFromState(
  urgentState: string | null | undefined,
): string {
  const flag = urgentFlagFromState(urgentState);
  if (flag === true) return "Urgent";
  if (flag === false) return "Normal";
  return "Belum terverifikasi";
}

export function urgentFieldsFromAccurateState(
  urgentState: string | null | undefined,
): UrgentFields {
  const state =
    urgentState == null || !String(urgentState).trim()
      ? null
      : String(urgentState).trim();
  return {
    urgent: urgentFlagFromState(state),
    urgentState: state,
    orderPriority: orderPriorityFromState(state),
  };
}

/**
 * Apply detail/list urgent_state onto an order.
 * When incoming state is absent, preserve verified list/prior fields.
 */
export function mergeUrgentFromIncoming(
  existing: {
    urgent?: UrgentFlag;
    urgentState?: string | null;
    orderPriority?: string | null;
  },
  incomingUrgentState: string | null | undefined,
): UrgentFields {
  const hasIncoming =
    incomingUrgentState != null && String(incomingUrgentState).trim() !== "";
  if (!hasIncoming) {
    const keptState =
      existing.urgentState != null && String(existing.urgentState).trim()
        ? String(existing.urgentState).trim()
        : null;
    if (keptState) {
      return urgentFieldsFromAccurateState(keptState);
    }
    // Preserve explicit boolean if somehow set without state string.
    if (existing.urgent === true) {
      return {
        urgent: true,
        urgentState: existing.urgentState || "approved_urgent",
        orderPriority: existing.orderPriority || "Urgent",
      };
    }
    if (existing.urgent === false) {
      return {
        urgent: false,
        urgentState: existing.urgentState || "normal",
        orderPriority: existing.orderPriority || "Normal",
      };
    }
    return {
      urgent: null,
      urgentState: null,
      orderPriority: existing.orderPriority || "Belum terverifikasi",
    };
  }
  return urgentFieldsFromAccurateState(incomingUrgentState);
}

/** Dashboard / filter: count only verified urgent === true. */
export function countUrgentOrders<T extends { urgent?: UrgentFlag }>(
  rows: T[],
): number {
  return (rows || []).filter((o) => o && o.urgent === true).length;
}

export function filterUrgentOrders<T extends { urgent?: UrgentFlag }>(
  rows: T[],
): T[] {
  return (rows || []).filter((o) => o && o.urgent === true);
}
