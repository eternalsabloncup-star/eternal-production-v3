/** Step 160 — schedule two-level header geometry (pure). */

export type GroupSpan = {
  key: string;
  span: number;
  label: string;
  keys: string[];
  hidden?: boolean;
  action?: boolean;
};

/**
 * Build group-header spans from column order + visibility.
 * Hidden columns are omitted (display:none siblings must not affect colspan).
 * Consecutive visible columns of the same category share one colspan cell.
 */
export function buildScheduleGroupSpans(
  orderedKeys: string[],
  visible: Set<string> | string[],
  categoryOf: (key: string) => string,
): GroupSpan[] {
  const vis = visible instanceof Set ? visible : new Set(visible);
  const keys = orderedKeys.filter((k) => vis.has(k));
  const out: GroupSpan[] = [];
  let i = 0;
  while (i < keys.length) {
    const key = keys[i];
    if (key === "action") {
      out.push({ key: "action", span: 1, label: "", keys: ["action"], action: true });
      i += 1;
      continue;
    }
    const cat = categoryOf(key) || "LAINNYA";
    let span = 1;
    while (
      i + span < keys.length &&
      keys[i + span] !== "action" &&
      (categoryOf(keys[i + span]) || "LAINNYA") === cat
    ) {
      span += 1;
    }
    out.push({
      key,
      span,
      label: cat,
      keys: keys.slice(i, i + span),
    });
    i += span;
  }
  return out;
}

/** Sum of child widths must equal group width (tolerance in px). */
export function groupWidthMatchesChildren(
  groupLeft: number,
  groupRight: number,
  childRects: Array<{ left: number; right: number }>,
  tolerance = 2,
): boolean {
  if (!childRects.length) return Math.abs(groupRight - groupLeft) <= tolerance;
  const left = Math.min(...childRects.map((r) => r.left));
  const right = Math.max(...childRects.map((r) => r.right));
  return (
    Math.abs(groupLeft - left) <= tolerance &&
    Math.abs(groupRight - right) <= tolerance
  );
}

export function sumWidths(widths: number[]): number {
  return widths.reduce((s, n) => s + (Number.isFinite(n) ? n : 0), 0);
}
