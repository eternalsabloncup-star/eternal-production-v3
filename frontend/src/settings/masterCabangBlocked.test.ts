import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const runtime = readFileSync("public/live-runtime.js", "utf8");
const html = readFileSync("public/production.html", "utf8");

describe("Master Cabang PostgreSQL UI", () => {
  it("exposes writable Direktur path with create/save and audit, without localStorage SoT", () => {
    expect(runtime).toMatch(/data-testid=\\"master-cabang-writable\\"/);
    expect(runtime).toMatch(/data-testid=\\"master-cabang-create\\"/);
    expect(runtime).toMatch(/data-testid=\\"master-cabang-audit\\"/);
    expect(runtime).toContain("Tambah cabang");
    expect(runtime).toContain("Simpan cabang");
    expect(runtime).toContain("/production/settings/branches");
    expect(runtime).toContain("method: \"POST\"");
    expect(runtime).toContain("method: \"PATCH\"");
    expect(runtime).not.toMatch(/localStorage.*production_branches|production_branches.*localStorage/);
  });

  it("keeps non-Direktur honesty banner without fake save", () => {
    expect(runtime).toMatch(/data-testid=\\"master-cabang-blocked\\"/);
    expect(runtime).toContain("hanya baca untuk akun ini");
  });

  it("settings katalog marks Master Cabang as SELESAI* PostgreSQL", () => {
    expect(html).toContain("Master Cabang");
    expect(html).toContain("production_branches");
    expect(html).toContain("SELESAI*");
    expect(html).toContain("COVERAGE TERBATAS");
  });
});
