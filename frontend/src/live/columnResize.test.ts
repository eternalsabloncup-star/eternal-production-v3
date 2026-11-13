import { describe, expect, it, beforeEach } from "vitest";
import {
  clampColumnWidth,
  clearColumnWidths,
  ensureColumnKeys,
  isResizeHandleEvent,
  loadColumnWidths,
  minWidthFor,
  saveColumnWidths,
  stickyLeftOffsets,
} from "./columnResize";

describe("columnResize", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("clamps below min width per column kind", () => {
    expect(clampColumnWidth("id", 10)).toBe(minWidthFor("id"));
    expect(clampColumnWidth("qty", 10, "number")).toBe(minWidthFor("qty", "number"));
    expect(clampColumnWidth("notes", 200, "text")).toBe(200);
    expect(clampColumnWidth("notes", 900, "text")).toBe(720);
    expect(minWidthFor("item")).toBe(160);
  });

  it("assigns stable data-column keys when missing", () => {
    const table = document.createElement("table");
    table.innerHTML =
      "<thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody>";
    const keys = ensureColumnKeys(table);
    expect(keys).toEqual(["c0", "c1"]);
    expect(table.querySelector("th")?.getAttribute("data-column")).toBe("c0");
    expect(table.querySelector("td")?.getAttribute("data-column")).toBe("c0");
  });

  it("persists widths per storage key", () => {
    saveColumnWidths("epv3:w:inbox", { id: 180, name: 220 });
    saveColumnWidths("epv3:w:schedule", { id: 160 });
    expect(loadColumnWidths("epv3:w:inbox")).toEqual({ id: 180, name: 220 });
    expect(loadColumnWidths("epv3:w:schedule")).toEqual({ id: 160 });
    clearColumnWidths("epv3:w:inbox");
    expect(loadColumnWidths("epv3:w:inbox")).toEqual({});
    expect(loadColumnWidths("epv3:w:schedule")).toEqual({ id: 160 });
  });

  it("computes sticky left offsets from resized id", () => {
    const offs = stickyLeftOffsets(["id", "name", "qty"], { id: 200, name: 180 });
    expect(offs.id).toBe(0);
    expect(offs.name).toBe(200);
  });

  it("detects resize handle events without treating as sort/drag", () => {
    const handle = document.createElement("span");
    handle.setAttribute("data-col-resize", "id");
    const th = document.createElement("th");
    th.appendChild(handle);
    expect(isResizeHandleEvent(handle)).toBe(true);
    // closest() only walks ancestors — parent th is not a resize target
    expect(isResizeHandleEvent(th)).toBe(false);
    expect(isResizeHandleEvent(document.createElement("div"))).toBe(false);
  });
});
