/** Slice 1H — map Accurate/V3 production_process → UI processSnapshot. */

export type ProductionProcess = "print" | "non_print" | "unknown";
export type ProcessSnapshot = "PRINT" | "NON_PRINT" | "UNKNOWN" | null;

export function normalizeProductionProcess(
  value: unknown,
): ProductionProcess {
  if (value == null) return "unknown";
  const n = String(value).trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (n === "print") return "print";
  if (n === "non_print" || n === "nonprint") return "non_print";
  return "unknown";
}

/** Never invent PRINT from missing/unknown process. */
export function processSnapshotFromProcess(
  value: unknown,
): ProcessSnapshot {
  const p = normalizeProductionProcess(value);
  if (p === "print") return "PRINT";
  if (p === "non_print") return "NON_PRINT";
  return null;
}

export function effectiveLineMode(
  line: {
    processSnapshot?: ProcessSnapshot;
    production_process?: unknown;
    itemId?: string | null;
  },
  itemModeFallback?: (itemId: string) => string,
): string {
  if (line.processSnapshot === "PRINT" || line.processSnapshot === "NON_PRINT") {
    return line.processSnapshot;
  }
  const fromProcess = processSnapshotFromProcess(line.production_process);
  if (fromProcess === "PRINT" || fromProcess === "NON_PRINT") return fromProcess;
  if (line.itemId && typeof itemModeFallback === "function") {
    return itemModeFallback(String(line.itemId));
  }
  return "UNKNOWN";
}

/** Live empty sourceLines must stay empty — never invent demo catalog lines. */
export function orderSourceLinesForLive<T extends { sourceLines?: unknown }>(
  order: T,
  inventDemoLines: () => unknown[],
  isLive: boolean,
): unknown[] {
  if (Array.isArray(order.sourceLines)) {
    return order.sourceLines as unknown[];
  }
  if (isLive) return [];
  return inventDemoLines();
}
