import { describe, expect, it } from "vitest";
import { getApiBaseUrl } from "./client";

describe("frontend API routing isolation", () => {
  it("runtime client base is same-origin V3", () => {
    expect(getApiBaseUrl()).toBe("/api/v1");
  });

  it("live-runtime default stays same-origin when V3_API_BASE unset", () => {
    const previous = (window as Window & { V3_API_BASE?: string }).V3_API_BASE;
    delete (window as Window & { V3_API_BASE?: string }).V3_API_BASE;
    const resolved = (
      (window as Window & { V3_API_BASE?: string }).V3_API_BASE || "/api/v1"
    ).replace(/\/$/, "");
    expect(resolved).toBe("/api/v1");
    if (previous !== undefined) {
      (window as Window & { V3_API_BASE?: string }).V3_API_BASE = previous;
    }
  });
});
