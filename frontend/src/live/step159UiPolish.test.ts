import { describe, expect, it } from "vitest";
import {
  clampColumnWidth,
  loadColumnWidths,
  saveColumnWidths,
  clearColumnWidths,
  stickyLeftOffsets,
  minWidthFor,
} from "./columnResize";

describe("Step 159 UI polish helpers", () => {
  it("sticky name left tracks resized id width", () => {
    const offs = stickyLeftOffsets(["id", "name", "qty"], { id: 220, name: 180 });
    expect(offs.id).toBe(0);
    expect(offs.name).toBe(220);
  });

  it("reset clears persisted widths back to empty defaults", () => {
    saveColumnWidths("epv3:colw:inbox", { id: 240, name: 200 });
    expect(loadColumnWidths("epv3:colw:inbox").id).toBe(240);
    clearColumnWidths("epv3:colw:inbox");
    expect(loadColumnWidths("epv3:colw:inbox")).toEqual({});
    expect(clampColumnWidth("id", 10)).toBe(minWidthFor("id"));
  });
});
