/** Slice 1F addendum — Live Tracking open policy (no demo drawer, no invented progress). */

export type TrackingSource = {
  id?: string | null;
  number?: string | null;
  so_number?: string | null;
  po_number?: string | null;
  /** Official public/customer tracking URL if Backend ever provides one. */
  tracking_url?: string | null;
  public_tracking_url?: string | null;
  trackingUrl?: string | null;
  publicTrackingUrl?: string | null;
  tracking?: {
    url?: string | null;
    public_url?: string | null;
    publicUrl?: string | null;
    token?: string | null;
    so_number?: string | null;
    job_id?: number | null;
  } | null;
  v3JobId?: number | null;
} | null;

export type TrackingDecision =
  | { status: "open"; so: string; url: string }
  | {
      status: "unavailable";
      so: string;
      reason: "missing_so" | "no_official_url" | "invalid_url" | "cross_po_mismatch";
      message: string;
    };

const UNAVAILABLE_MSG = "Tracking belum tersedia";

/** Default path prefix for same-origin official tracking pages (future). */
export const TRACKING_PATH_PREFIXES = ["/track/", "/t/"] as const;

export function trackingUnavailableMessage(): string {
  return UNAVAILABLE_MSG;
}

export function extractOfficialTrackingUrl(source: TrackingSource): string | null {
  if (!source || typeof source !== "object") return null;
  const nested = source.tracking;
  const candidates = [
    source.tracking_url,
    source.public_tracking_url,
    source.trackingUrl,
    source.publicTrackingUrl,
    nested && nested.url,
    nested && nested.public_url,
    nested && nested.publicUrl,
  ];
  for (const raw of candidates) {
    if (raw == null) continue;
    const url = String(raw).trim();
    if (url) return url;
  }
  return null;
}

/**
 * Strict allowlist: https (or http localhost) absolute URLs, or same-origin /track|/t paths.
 * Rejects javascript:/data:/PO-as-token fabrication.
 */
export function isAllowedTrackingUrl(
  url: string,
  opts?: { origin?: string; allowedHosts?: readonly string[] },
): boolean {
  const raw = String(url || "").trim();
  if (!raw) return false;
  const lower = raw.toLowerCase();
  if (
    lower.startsWith("javascript:") ||
    lower.startsWith("data:") ||
    lower.startsWith("vbscript:") ||
    lower.startsWith("blob:")
  ) {
    return false;
  }

  const origin = (opts?.origin || (typeof location !== "undefined" ? location.origin : "")).replace(
    /\/$/,
    "",
  );
  const allowedHosts = new Set(
    (opts?.allowedHosts || []).map((h) => String(h).toLowerCase()),
  );

  try {
    const base = origin || "http://127.0.0.1";
    const parsed = new URL(raw, base);
    if (parsed.username || parsed.password) return false;
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return false;

    const pathOk = TRACKING_PATH_PREFIXES.some((p) => parsed.pathname.startsWith(p));
    if (!pathOk) return false;

    const host = parsed.hostname.toLowerCase();
    const isLocal =
      host === "localhost" || host === "127.0.0.1" || host === "[::1]";
    if (parsed.protocol === "http:" && !isLocal) return false;

    if (origin) {
      const originUrl = new URL(origin);
      if (parsed.origin === originUrl.origin) return true;
    }
    if (allowedHosts.has(host)) return true;
    // Absolute same-path relative resolved against origin already handled.
    return false;
  } catch {
    return false;
  }
}

function sourceSo(source: TrackingSource): string | null {
  if (!source) return null;
  // Prefer explicit SO fields — never treat numeric job id as a document number.
  for (const key of ["so_number", "po_number", "number"] as const) {
    const v = source[key];
    if (v != null && String(v).trim()) return String(v).trim();
  }
  if (source.tracking?.so_number != null && String(source.tracking.so_number).trim()) {
    return String(source.tracking.so_number).trim();
  }
  const id = source.id;
  if (id != null && String(id).trim()) {
    const s = String(id).trim();
    // Reject pure numeric job ids as SO identity.
    if (!/^\d+$/.test(s)) return s;
  }
  return null;
}

/**
 * Decide whether Live Tracking may open a new tab.
 * Never invents a URL from the PO number / job id alone.
 * Never mutates job state — pure decision helper.
 */
export function decideLiveTrackingOpen(args: {
  so: string;
  order?: TrackingSource;
  job?: TrackingSource;
  origin?: string;
  allowedHosts?: readonly string[];
}): TrackingDecision {
  const so = String(args.so || "").trim();
  if (!so) {
    return {
      status: "unavailable",
      so: "",
      reason: "missing_so",
      message: UNAVAILABLE_MSG,
    };
  }

  // Cross-PO guard: if sources declare a different SO, refuse.
  for (const src of [args.order, args.job]) {
    if (!src) continue;
    const declared = sourceSo(src);
    if (declared && declared !== so) {
      return {
        status: "unavailable",
        so,
        reason: "cross_po_mismatch",
        message: UNAVAILABLE_MSG,
      };
    }
  }

  const url =
    extractOfficialTrackingUrl(args.job ?? null) ||
    extractOfficialTrackingUrl(args.order ?? null);
  if (!url) {
    return {
      status: "unavailable",
      so,
      reason: "no_official_url",
      message: UNAVAILABLE_MSG,
    };
  }

  if (
    !isAllowedTrackingUrl(url, {
      origin: args.origin,
      allowedHosts: args.allowedHosts,
    })
  ) {
    return {
      status: "unavailable",
      so,
      reason: "invalid_url",
      message: UNAVAILABLE_MSG,
    };
  }

  return { status: "open", so, url };
}

/** Demo/sim drawers must never be used for Inbox Live Tracking. */
export function isDemoTrackingUiForbidden(): true {
  return true;
}
