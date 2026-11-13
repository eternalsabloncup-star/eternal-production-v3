import { describe, expect, it } from "vitest";

import {
  canShowOperationalDashboard,
  hasAccessToken,
  isErpV1ApiBase,
  isVerifiedLiveAccuratePayload,
  resolveV3ApiBase,
  shouldRedirectToLogin,
} from "./authGate";

describe("Private Staging auth gate rules", () => {
  it("blocks dashboard without verified session", () => {
    expect(canShowOperationalDashboard("pending")).toBe(false);
    expect(canShowOperationalDashboard("failed")).toBe(false);
    expect(canShowOperationalDashboard("ok")).toBe(true);
  });

  it("treats missing token as unauthenticated access to production.html", () => {
    expect(hasAccessToken({ getItem: () => null })).toBe(false);
    expect(shouldRedirectToLogin({ tokenPresent: false })).toBe(true);
  });

  it("redirects invalid and expired JWT (401/403 from /auth/me)", () => {
    expect(shouldRedirectToLogin({ tokenPresent: true, meStatus: 401 })).toBe(
      true,
    );
    expect(shouldRedirectToLogin({ tokenPresent: true, meStatus: 403 })).toBe(
      true,
    );
  });

  it("allows dashboard only after successful auth verification", () => {
    expect(shouldRedirectToLogin({ tokenPresent: true, meStatus: 200 })).toBe(
      false,
    );
    expect(canShowOperationalDashboard("ok")).toBe(true);
  });

  it("rejects fixture/demo payloads masquerading as Accurate live", () => {
    expect(isVerifiedLiveAccuratePayload({ mode: "fixture", rows: [] })).toBe(
      false,
    );
    expect(
      isVerifiedLiveAccuratePayload({ mode: "demo", rows: [{ id: 1 }] }),
    ).toBe(false);
    expect(isVerifiedLiveAccuratePayload({ rows: [] })).toBe(false);
    expect(isVerifiedLiveAccuratePayload({ mode: "live", rows: [] })).toBe(true);
  });

  it("API routing stays on V3 /api/v1, not ERP V1 port 8000", () => {
    expect(resolveV3ApiBase(undefined)).toBe("/api/v1");
    expect(isErpV1ApiBase(resolveV3ApiBase(undefined))).toBe(false);
    expect(isErpV1ApiBase("http://127.0.0.1:8000/api/v1")).toBe(true);
    expect(isErpV1ApiBase("http://127.0.0.1:8100/api/v1")).toBe(false);
  });
});
