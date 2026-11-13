import { describe, expect, it, beforeEach } from "vitest";
import {
  clearColumnWidths,
  loadColumnWidths,
  saveColumnWidths,
} from "./columnResize";

describe("step162 reset lebar prefs", () => {
  beforeEach(() => localStorage.clear());

  it("clearColumnWidths removes only width prefs for that table key", () => {
    saveColumnWidths("epv3:colw:schedule", { id: 200, name: 260 });
    saveColumnWidths("epv3:colw:inbox", { id: 180 });
    clearColumnWidths("epv3:colw:schedule");
    expect(loadColumnWidths("epv3:colw:schedule")).toEqual({});
    expect(loadColumnWidths("epv3:colw:inbox")).toEqual({ id: 180 });
  });
});
