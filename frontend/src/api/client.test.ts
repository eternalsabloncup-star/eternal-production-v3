import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, fetchHealth, getApiBaseUrl } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api client routing", () => {
  it("defaults to same-origin V3 /api/v1 (not ERP V1 port 8000)", () => {
    const base = getApiBaseUrl();
    expect(base).toBe("/api/v1");
    expect(base.includes("8000")).toBe(false);
    expect(base.startsWith("http://127.0.0.1")).toBe(false);
  });

  it("honors VITE_API_BASE_URL without trailing slash", () => {
    const base = getApiBaseUrl();
    expect(base.endsWith("/")).toBe(false);
    expect(base).toMatch(/\/api\/v1$/);
  });

  it("parses health payload via configured base", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      void input;
      return new Response(
        JSON.stringify({
          status: "ok",
          service: "ETERNAL PRODUCTION V3",
          version: "0.1.0",
          environment: "test",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const health = await fetchHealth();
    expect(health.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledWith = String(fetchMock.mock.calls[0]![0]);
    expect(calledWith).toBe(`${getApiBaseUrl()}/health`);
    expect(calledWith.includes("8000")).toBe(false);
  });

  it("raises structured API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "database_unavailable",
              message: "Database connection failed",
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(fetchHealth()).rejects.toBeInstanceOf(ApiClientError);
  });
});
