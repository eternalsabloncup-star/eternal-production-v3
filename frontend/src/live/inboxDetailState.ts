/** Step 86 — Inbox Accurate detail-dependent field presentation states. */

export type InboxDetailLoadState =
  | "not_loaded"
  | "loading"
  | "loaded"
  | "failed"
  | string;

export type InboxAbsenceKind = "unavailable" | "unverified";

const PLACEHOLDER_VALUES = new Set([
  "",
  "—",
  "-",
  "Belum terverifikasi",
  "Belum tersedia",
  "Belum dimuat",
  "Memuat…",
  "Memuat...",
  "Gagal dimuat",
  "Gagal memuat",
  "Detail barang belum dimuat",
  "Perlu verifikasi",
]);

export function escapeInboxText(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** True when the cell already has a real display value (list or prior enrich). */
export function inboxFieldHasVerifiedDisplay(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return true;
  const s = String(value).trim();
  if (!s) return false;
  if (PLACEHOLDER_VALUES.has(s)) return false;
  return true;
}

export function inboxDetailLoadState(
  o: { detailLoadState?: InboxDetailLoadState | null } | null | undefined,
): string {
  return (o && o.detailLoadState) || "not_loaded";
}

export function inboxDetailRetryHtml(
  soNumber: unknown,
  escapeFn: (s: unknown) => string = escapeInboxText,
): string {
  const so = escapeFn(soNumber || "");
  return (
    '<span class="muted">Gagal dimuat</span> ' +
    '<button type="button" class="btn sm" onclick="window.retryInboxDetail&&window.retryInboxDetail(\'' +
    so +
    "')\">Retry</button>"
  );
}

export function inboxDetailPendingHtml(
  o: { detailLoadState?: InboxDetailLoadState | null; id?: string | null } | null | undefined,
  escapeFn: (s: unknown) => string = escapeInboxText,
): string {
  const state = inboxDetailLoadState(o);
  if (state === "loading") return '<span class="muted">Memuat…</span>';
  if (state === "failed") return inboxDetailRetryHtml(o && o.id, escapeFn);
  if (state === "loaded") return ""; // caller chooses absence label
  return '<span class="muted">Belum dimuat</span>';
}

export function inboxAbsenceHtml(kind: InboxAbsenceKind = "unavailable"): string {
  const label = kind === "unverified" ? "Belum terverifikasi" : "Belum tersedia";
  return '<span class="muted">' + label + "</span>";
}

/**
 * Shared presentation for detail-dependent Inbox columns.
 * Preserves verified list/prior values while detail is pending.
 */
export function inboxDetailDependentHtml(
  o: {
    detailLoadState?: InboxDetailLoadState | null;
    id?: string | null;
  } | null | undefined,
  options: {
    value: unknown;
    absence?: InboxAbsenceKind;
    escapeFn?: (s: unknown) => string;
    wrap?: (escapedValue: string) => string;
  },
): string {
  const escapeFn = options.escapeFn || escapeInboxText;
  const absence = options.absence || "unavailable";
  if (inboxFieldHasVerifiedDisplay(options.value)) {
    const escaped = escapeFn(String(options.value));
    return options.wrap ? options.wrap(escaped) : escaped;
  }
  const pending = inboxDetailPendingHtml(o, escapeFn);
  if (pending) return pending;
  return inboxAbsenceHtml(absence);
}
