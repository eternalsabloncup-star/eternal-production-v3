import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, fetchHealth, getApiBaseUrl } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("uses configured API base URL", () => {
    expect(getApiBaseUrl()).toMatch(/\/api\/v1$/);
  });

  it("parses health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            status: "ok",
            service: "ETERNAL PRODUCTION V3",
            version: "0.1.0",
            environment: "test",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const health = await fetchHealth();
    expect(health.status).toBe("ok");
  });

  it("raises structured API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: { code: "database_unavailable", message: "Database connection failed" },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(fetchHealth()).rejects.toBeInstanceOf(ApiClientError);
  });
});
