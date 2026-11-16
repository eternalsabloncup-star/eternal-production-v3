import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const html = readFileSync(
  resolve(__dirname, "../../public/production.html"),
  "utf8",
);

describe("Jadwal Produksi sticky parity (Fase 3)", () => {
  it("marks schedule sheet sticky identity columns for resize + smoke", () => {
    expect(html).toContain('v3-schedule-sheet');
    expect(html).toContain('data-v3-sticky="id,name"');
    expect(html).toContain("COLW_KEYS.schedule");
  });

  it("marks task sheet sticky SO + customer", () => {
    expect(html).toContain('data-v3-colw="${COLW_KEYS.tasks}" data-v3-sticky="so,customer"');
    expect(html).toMatch(/task-sheet th\[data-column="so"\]/);
  });
});
