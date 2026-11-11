import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App status shell", () => {
  it("renders brand and healthy status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/health")) {
          return new Response(
            JSON.stringify({
              status: "ok",
              service: "ETERNAL PRODUCTION V3",
              version: "0.1.0",
              environment: "test",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/ready")) {
          return new Response(
            JSON.stringify({ status: "ready", database: "ok" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("not found", { status: 404 });
      }),
    );

    render(<App />);

    expect(screen.getByText("ETERNAL PRODUCTION V3")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("ok").length).toBeGreaterThanOrEqual(2);
    });
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("ETERNAL PRODUCTION V3", { selector: "dd" })).toBeInTheDocument();
  });
});
