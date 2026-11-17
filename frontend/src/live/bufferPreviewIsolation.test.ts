import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync("public/production.html", "utf8");
const runtime = readFileSync("public/live-runtime.js", "utf8");

describe("Buffer preview vs Live isolation (Tahap C P1)", () => {
  it("live-runtime replaces monitorBuffer and tags the Live panel", () => {
    expect(runtime).toContain('guardDemoView("monitorBuffer"');
    expect(runtime).toContain("/production/ops/buffer");
    expect(runtime).toMatch(/data-testid=\\"buffer-live-monitor\\"/);
    expect(runtime).toMatch(/window\.setOrderFlag\s*=\s*function/);
    expect(runtime).toMatch(/data-testid=\\"buffer-demo-rows-blocked\\"/);
    expect(runtime).toContain("guardDemoBufferMutations");
  });

  it("demo monitorBuffer refuses to render operational rows outside preview", () => {
    expect(html).toContain('data-testid="buffer-demo-blocked"');
    expect(html).toContain('data-testid="buffer-demo-monitor"');
    expect(html).toMatch(/function setOrderFlag\(id,flag\)\{if\(typeof v3Operational/);
    expect(html).toContain("Aksi Buffer/Urgent simulasi diblokir di Live");
  });

  it("Live settings do not expose demo buffer percent as company SoT", () => {
    expect(html).toContain('data-testid="buffer-settings-live"');
    expect(html).toContain("GET /production/ops/buffer");
    expect(html).toMatch(
      /productionSettingsTab==='prioritas'\)content=\(operational\s*\?`[\s\S]*buffer-settings-live/,
    );
  });

  it("preview fixture gate remains URL/flag based (no silent Live fixture)", () => {
    expect(runtime).toContain("function isPreviewFixture()");
    expect(runtime).toContain("epv3_preview=fixture");
    expect(runtime).toContain("__V3_PREVIEW_FIXTURE__");
    expect(html).toContain("epv3_preview=fixture");
  });

  it("Live never calls obsolete Final path /api/v3/buffer-stock (BUF-path E1)", () => {
    expect(runtime).not.toMatch(/opsLoad\([^)]*buffer-stock/);
    expect(runtime).not.toMatch(/request\([^)]*buffer-stock/);
    expect(runtime).not.toMatch(/fetch\([^)]*buffer-stock/);
    expect(html).not.toMatch(/['"`][^'"`]*\/api\/v3\/buffer-stock/);
    expect(runtime).toContain("/production/ops/buffer");
    expect(runtime).toContain('data-ops="buf-view"');
    expect(runtime).toContain('data-testid="sheet-view-ringkas"');
  });
});
