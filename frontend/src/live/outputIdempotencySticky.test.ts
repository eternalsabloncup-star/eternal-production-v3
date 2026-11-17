import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const runtime = readFileSync("public/live-runtime.js", "utf8");

describe("Output sticky idempotency_key", () => {
  it("defines sticky slot helpers and uses them for out-confirm", () => {
    expect(runtime).toContain("function stickyIdemKey");
    expect(runtime).toContain("function stickyIdemCommit");
    expect(runtime).toContain("function stickyIdemPeek");
    expect(runtime).toContain("function stickyIdemMarkUncertain");
    expect(runtime).toContain('stickyIdemKey("out", fingerprint)');
    expect(runtime).toContain("idempotency_key: outKey");
    expect(runtime).toContain("BELUM PASTI");
    expect(runtime).toContain("replay key");
    expect(runtime).toContain("window.__V3_IDEM__");
  });

  it("does not mint a fresh random key inline for out-confirm", () => {
    // The out-confirm block must use sticky key, not a bare idemKey("out") call.
    const start = runtime.indexOf('if (action === "out-confirm")');
    const end = runtime.indexOf('if (action === "out-helper-verify")', start);
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    const block = runtime.slice(start, end);
    expect(block).toContain("stickyIdemKey");
    expect(block).not.toMatch(/idempotency_key:\s*idemKey\("out"\)/);
  });
});
