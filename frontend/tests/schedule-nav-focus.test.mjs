/**
 * Focused pure checks for Fase 1B final-fix schedule navigation helpers.
 * Mirrors live-runtime selection rules (no DOM / no Live writes).
 */
import assert from "node:assert/strict";

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

// Off-inbox dual operators: assignment id must not swap.
const hitA = scheduleApiItemFor(items, "SO/OFF", {
  lineId: "L-PRINT",
  assignmentId: 11,
});
const hitB = scheduleApiItemFor(items, "SO/OFF", {
  lineId: "L-PRINT",
  assignmentId: 12,
});
assert.equal(hitA.row_key, "2:L-PRINT:a11");
assert.equal(hitB.row_key, "2:L-PRINT:a12");

// Live runtime independent of inbox success flag.
assert.equal(isLiveRuntime(false), true);
assert.equal(isLiveRuntime(true), false);

// Missing SO → null (caller must surface error, not silent no-op).
assert.equal(scheduleApiItemFor(items, "SO/MISSING", {}), null);

console.log("schedule-nav-focus.test.mjs PASS");
