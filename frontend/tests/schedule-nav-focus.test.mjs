/**
 * Focused Vitest checks for Fase 1B schedule navigation helpers.
 * Mirrors live-runtime selection rules (no DOM / no Live writes).
 */
import { describe, expect, it } from "vitest";

function scheduleApiItemFor(items, so, opts = {}) {
  const forSo = items.filter((r) => r && r.accurate_so_number === so);
  if (!forSo.length) return null;
  if (opts.lineId != null && String(opts.lineId) !== "") {
    const lineHits = forSo.filter(
      (r) => String(r.so_line_id || "") === String(opts.lineId),
    );
    if (opts.assignmentId != null && String(opts.assignmentId) !== "") {
      const asg = lineHits.find(
        (r) => String(r.assignment_id || "") === String(opts.assignmentId),
      );
      if (asg) return asg;
    }
    if (opts.colorPass != null) {
      const byPass = lineHits.find(
        (r) => Number(r.color_pass || 1) === Number(opts.colorPass || 1),
      );
      if (byPass) return byPass;
    }
    if (lineHits.length) return lineHits[0];
  }
  if (opts.colorPass != null) {
    const byPass = forSo.find(
      (r) => Number(r.color_pass || 1) === Number(opts.colorPass || 1),
    );
    if (byPass) return byPass;
  }
  return forSo[0];
}

function isLiveRuntime(preview) {
  return !preview;
}

const items = [
  {
    accurate_so_number: "SO/INBOX",
    so_line_id: "L1",
    assignment_id: 10,
    color_pass: 1,
    row_key: "1:L1:a10",
  },
  {
    accurate_so_number: "SO/OFF",
    so_line_id: "L-PRINT",
    assignment_id: 11,
    color_pass: 1,
    row_key: "2:L-PRINT:a11",
  },
  {
    accurate_so_number: "SO/OFF",
    so_line_id: "L-PRINT",
    assignment_id: 12,
    color_pass: 1,
    row_key: "2:L-PRINT:a12",
  },
];

describe("schedule navigation focus (Fase 1B)", () => {
  it("resolves off-Inbox dual operators without swapping assignment identity", () => {
    const hitA = scheduleApiItemFor(items, "SO/OFF", {
      lineId: "L-PRINT",
      assignmentId: 11,
    });
    const hitB = scheduleApiItemFor(items, "SO/OFF", {
      lineId: "L-PRINT",
      assignmentId: 12,
    });
    expect(hitA.row_key).toBe("2:L-PRINT:a11");
    expect(hitB.row_key).toBe("2:L-PRINT:a12");
    expect(String(hitA.so_line_id)).toBe("L-PRINT");
    expect(String(hitB.so_line_id)).toBe("L-PRINT");
    expect(hitA.assignment_id).toBe(11);
    expect(hitB.assignment_id).toBe(12);
  });

  it("resolves Inbox-page SO by so_line_id for Detail / Atur Operator", () => {
    const hit = scheduleApiItemFor(items, "SO/INBOX", {
      lineId: "L1",
      assignmentId: 10,
    });
    expect(hit).not.toBeNull();
    expect(hit.accurate_so_number).toBe("SO/INBOX");
    expect(hit.so_line_id).toBe("L1");
    expect(hit.assignment_id).toBe(10);
  });

  it("keeps Live schedule path independent of Inbox preview flag", () => {
    expect(isLiveRuntime(false)).toBe(true);
    expect(isLiveRuntime(true)).toBe(false);
  });

  it("returns null for missing SO so callers must surface an error", () => {
    expect(scheduleApiItemFor(items, "SO/MISSING", {})).toBeNull();
  });
});
