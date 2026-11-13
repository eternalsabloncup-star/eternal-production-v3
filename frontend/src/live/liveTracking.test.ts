import { describe, expect, it } from "vitest";
import {
  decideLiveTrackingOpen,
  extractOfficialTrackingUrl,
  isAllowedTrackingUrl,
  isDemoTrackingUiForbidden,
  trackingUnavailableMessage,
  type TrackingSource,
} from "./liveTracking";

const ORIGIN = "https://v3.eternalpackaging.id";

describe("Slice 1F addendum Live Tracking", () => {
  it("unavailable when Backend has no official tracking URL", () => {
    const d = decideLiveTrackingOpen({
      so: "PO/11/11/2026/000005",
      order: { id: "PO/11/11/2026/000005", v3JobId: 12 },
      job: { so_number: "PO/11/11/2026/000005", v3JobId: 12 },
      origin: ORIGIN,
    });
    expect(d.status).toBe("unavailable");
    if (d.status === "unavailable") {
      expect(d.reason).toBe("no_official_url");
      expect(d.message).toBe("Tracking belum tersedia");
    }
  });

  it("opens only allowlisted official URL for the same PO", () => {
    const url = `${ORIGIN}/track/abcTokenSafe`;
    const d = decideLiveTrackingOpen({
      so: "PO/A",
      order: { id: "PO/A", tracking_url: url },
      origin: ORIGIN,
    });
    expect(d).toEqual({ status: "open", so: "PO/A", url });
  });

  it("refuses cross-PO mix even if URL present", () => {
    const d = decideLiveTrackingOpen({
      so: "PO/A",
      order: { id: "PO/A" },
      job: {
        so_number: "PO/B",
        tracking_url: `${ORIGIN}/track/x`,
      },
      origin: ORIGIN,
    });
    expect(d.status).toBe("unavailable");
    if (d.status === "unavailable") expect(d.reason).toBe("cross_po_mismatch");
  });

  it("never treats PO number as a tracking token/URL", () => {
    expect(extractOfficialTrackingUrl({ id: "PO/1", number: "PO/1" })).toBeNull();
    expect(
      isAllowedTrackingUrl(`${ORIGIN}/track/PO/11/11/2026/000005`, { origin: ORIGIN }),
    ).toBe(true); // path shape ok IF officially supplied
    const invented = decideLiveTrackingOpen({
      so: "PO/11/11/2026/000005",
      order: { id: "PO/11/11/2026/000005" },
      origin: ORIGIN,
    });
    expect(invented.status).toBe("unavailable");
  });

  it("rejects unsafe / non-allowlisted URLs", () => {
    expect(isAllowedTrackingUrl("javascript:alert(1)", { origin: ORIGIN })).toBe(false);
    expect(isAllowedTrackingUrl("https://evil.example/track/x", { origin: ORIGIN })).toBe(
      false,
    );
    expect(isAllowedTrackingUrl(`${ORIGIN}/production.html`, { origin: ORIGIN })).toBe(
      false,
    );
    expect(
      isAllowedTrackingUrl("http://127.0.0.1:5173/track/local", {
        origin: "http://127.0.0.1:5173",
      }),
    ).toBe(true);
  });

  it("demo tracking UI is forbidden; message is stable", () => {
    expect(isDemoTrackingUiForbidden()).toBe(true);
    expect(trackingUnavailableMessage()).toBe("Tracking belum tersedia");
  });

  it("decideLiveTrackingOpen is pure — no mutation of inputs", () => {
    const order = { id: "PO/Z", stage: "inbox" } as TrackingSource & { stage: string };
    const before = JSON.stringify(order);
    decideLiveTrackingOpen({ so: "PO/Z", order, origin: ORIGIN });
    expect(JSON.stringify(order)).toBe(before);
  });
});
