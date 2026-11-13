/** Pure Private Staging auth/routing helpers (Slice 1C). */

export type AuthStatus = "pending" | "ok" | "failed";

export function resolveV3ApiBase(configured?: string | null): string {
  const raw = (configured || "/api/v1").trim();
  return raw.replace(/\/$/, "") || "/api/v1";
}

export function isErpV1ApiBase(base: string): boolean {
  return /:8000(?:\/|$)/.test(base) || /127\.0\.0\.1:8000/.test(base);
}

export function hasAccessToken(storage: {
  getItem(key: string): string | null;
}): boolean {
  const token = storage.getItem("epv3_access_token");
  return Boolean(token && token.trim());
}

/** Dashboard data must stay hidden until Backend V3 verifies the JWT. */
export function canShowOperationalDashboard(status: AuthStatus): boolean {
  return status === "ok";
}

/** Accurate inbox rows must be live mode — never fixture/demo payloads. */
export function isVerifiedLiveAccuratePayload(data: unknown): boolean {
  if (!data || typeof data !== "object") return false;
  const row = data as { mode?: unknown; rows?: unknown };
  return row.mode === "live" && Array.isArray(row.rows);
}

export function shouldRedirectToLogin(params: {
  tokenPresent: boolean;
  meStatus?: number;
}): boolean {
  if (!params.tokenPresent) return true;
  if (params.meStatus === 401 || params.meStatus === 403) return true;
  if (params.meStatus != null && params.meStatus >= 500) return false;
  if (params.meStatus != null && params.meStatus !== 200) return true;
  return false;
}
