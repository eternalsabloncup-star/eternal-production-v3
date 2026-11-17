import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync("public/production.html", "utf8");
const runtime = readFileSync("public/live-runtime.js", "utf8");

describe("Final Ringkas/Lengkap column view (Tahap E1)", () => {
  it("production.html exposes setSheetColumnView and FULL_ONLY maps", () => {
    expect(html).toContain("sheetColumnView='lengkap'");
    expect(html).toContain("function setSheetColumnView(v)");
    expect(html).toContain("function effectiveSheetVisible()");
    expect(html).toContain("SHEET_FULL_ONLY");
    expect(html).toContain("INBOX_FULL_ONLY");
    expect(html).toContain('data-testid="sheet-view-ringkas"');
    expect(html).toContain('data-testid="sheet-view-lengkap"');
    expect(html).toContain("sheetColumnViewButtons()");
  });

  it("go() resets column view to lengkap (session-only, Final setView parity)", () => {
    expect(html).toMatch(/function go\(id\)\{[\s\S]*?sheetColumnView='lengkap'/);
  });

  it("inbox, sheet, and tasks toolbars include Ringkas/Lengkap", () => {
    expect(html).toMatch(/v36InboxView[\s\S]*sheetColumnViewButtons\(\)/);
    expect(html).toMatch(/function sheetPageHtml[\s\S]*sheetColumnViewButtons\(\)/);
    expect(html).toMatch(/task-toolbar[\s\S]*sheetColumnViewButtons\(\)/);
  });

  it("payment, buffer, and delivery Live monitors expose Ringkas/Lengkap", () => {
    expect(runtime).toContain('data-rm="view"');
    expect(runtime).toContain('data-ops="buf-view"');
    expect(runtime).toContain('data-ops="del-view"');
    expect(runtime).toContain("columnView: \"lengkap\"");
    expect(runtime).toContain("ops.bufView");
    expect(runtime).toContain("ops.delView");
  });

  it("Lengkap toast does not claim all columns; count uses effectiveSheetVisible", () => {
    // Contract: Lengkap lifts FULL_ONLY hide over Kolom Tampil selection (Default V1 subset),
    // not "Pilih Semua". Indicator must not say every column is visible.
    expect(html).not.toContain("Tampilan Lengkap: semua kolom terlihat");
    expect(html).toContain("Tampilan Lengkap: kolom sekunder ditampilkan sesuai pilihan Kolom Tampil");
    expect(html).toContain("function sheetVisibleCountLabel()");
    expect(html).toMatch(/sheetVisibleCountLabel\(\)/);
    expect(html).toContain('data-testid="sheet-visible-count"');
    expect(html).toContain("V1_SCHEDULE_DEFAULT_VISIBLE");
    expect(html).toContain("Pilih Semua");
  });
});

describe("Final Audit F2 — Owner menu decisions", () => {
  it("sidebar Live omits Master Mesin but keeps machineMaster page + API path", () => {
    // Owner F2: hide Master Mesin from primary nav; do not delete backend/page/API.
    expect(html).not.toMatch(/nav\('machineMaster'/);
    expect(html).toContain("go('machineMaster')");
    expect(html).toContain("Master Mesin");
    expect(runtime).toContain('window.section === "machineMaster"');
    expect(runtime).toContain("/production/ops/machines");
  });

  it("does not treat filter 'pilihan' copy as a separate sidebar menu", () => {
    // "Pilihan" appears only in filter/column UI copy — not a nav('...') item.
    expect(html).not.toMatch(/nav\('[^']*','[^']*[Pp]ilihan/);
    expect(html).toMatch(/Cari dalam pilihan|Kolom Tampil|sesuai pilihan Kolom Tampil/);
  });
});

describe("Final Audit E3 — four confirmed frontend gaps", () => {
  it("payment monitor maps approval_at and gated bypass_by (FULL_ONLY in Ringkas)", () => {
    expect(runtime).toContain("approval_at");
    expect(runtime).toContain("bypass_by");
    expect(runtime).toContain('data-testid="col-approval-at"');
    expect(runtime).toContain('data-testid="col-bypass-by"');
    expect(runtime).toContain("Belum tersedia");
    expect(runtime).toMatch(/showGateCols\s*=\s*rm\.columnView\s*!==\s*"ringkas"/);
  });

  it("schedule maps qty_helper_prepared to helperQty FULL_ONLY column", () => {
    expect(runtime).toContain("qty_helper_prepared");
    expect(runtime).toContain("helperQtyPrepared");
    expect(html).toContain("key:'helperQty'");
    expect(html).toContain('data-testid="col-helper-qty"');
    expect(html).toMatch(/SHEET_FULL_ONLY=new Set\(\[[^\]]*helperQty/);
  });

  it("tasks expose gate_reason / Prasyarat from official reason", () => {
    expect(html).toContain("key:'gate_reason'");
    expect(html).toContain('data-testid="col-gate-reason"');
    expect(html).toMatch(/gate_reason.*Prasyarat|Prasyarat.*gate_reason/);
    expect(runtime).toContain("gateReason");
    expect(runtime).toMatch(/task\.reason\s*\|\|\s*task\.gate_reason/);
    expect(html).toMatch(/sheetColumnView!=='ringkas'\|\|!\[[^\]]*gate_reason/);
    expect(html).toMatch(/taskRowActionable\(x\)\|\|\(x&&x\.status==='Menunggu'\)/);
  });
});
