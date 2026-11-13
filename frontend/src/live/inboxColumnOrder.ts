/** Slice 1H — Inbox Accurate column order (drag/drop + localStorage). */

export const INBOX_COLUMN_ORDER_KEY = "eternal_v3_inbox_column_order_v1";

/** Locked sticky identity columns — always first, not reorderable. */
export const INBOX_LOCKED_COLUMNS = ["id", "name"] as const;

export type InboxColumnKey = string;

export function defaultInboxColumnOrder(allKeys: readonly string[]): string[] {
  const locked = INBOX_LOCKED_COLUMNS.filter((k) => allKeys.includes(k));
  const rest = allKeys.filter((k) => !(INBOX_LOCKED_COLUMNS as readonly string[]).includes(k));
  return [...locked, ...rest];
}

export function normalizeInboxColumnOrder(
  saved: unknown,
  allKeys: readonly string[],
): string[] {
  const defaults = defaultInboxColumnOrder(allKeys);
  if (!Array.isArray(saved)) return defaults;
  const allowed = new Set(allKeys);
  const seen = new Set<string>();
  const rest: string[] = [];
  for (const key of saved) {
    if (typeof key !== "string" || !allowed.has(key)) continue;
    if ((INBOX_LOCKED_COLUMNS as readonly string[]).includes(key)) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    rest.push(key);
  }
  for (const key of defaults) {
    if ((INBOX_LOCKED_COLUMNS as readonly string[]).includes(key)) continue;
    if (seen.has(key)) continue;
    rest.push(key);
  }
  const locked = INBOX_LOCKED_COLUMNS.filter((k) => allKeys.includes(k));
  return [...locked, ...rest];
}

export function isInboxColumnLocked(key: string): boolean {
  return (INBOX_LOCKED_COLUMNS as readonly string[]).includes(key);
}

/** Move a movable column before/after a target. Locked columns stay pinned left. */
export function moveInboxColumn(
  order: readonly string[],
  source: string,
  target: string,
  place: "before" | "after" = "before",
): string[] {
  if (!source || !target || source === target) return [...order];
  if (isInboxColumnLocked(source) || isInboxColumnLocked(target)) return [...order];
  const next = order.filter((k) => k !== source);
  const at = next.indexOf(target);
  if (at < 0) return [...order];
  const insertAt = place === "after" ? at + 1 : at;
  next.splice(insertAt, 0, source);
  return normalizeInboxColumnOrder(next, order);
}

/** Keyboard nudge: move source one step left/right among movable columns. */
export function nudgeInboxColumn(
  order: readonly string[],
  source: string,
  direction: -1 | 1,
): string[] {
  if (isInboxColumnLocked(source)) return [...order];
  const idx = order.indexOf(source);
  if (idx < 0) return [...order];
  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= order.length) return [...order];
  const target = order[targetIdx];
  if (isInboxColumnLocked(target)) return [...order];
  return moveInboxColumn(order, source, target, direction < 0 ? "before" : "after");
}

export function readInboxColumnOrder(
  storage: Pick<Storage, "getItem"> | null | undefined,
  allKeys: readonly string[],
): string[] {
  try {
    const raw = storage?.getItem(INBOX_COLUMN_ORDER_KEY);
    return normalizeInboxColumnOrder(raw ? JSON.parse(raw) : null, allKeys);
  } catch {
    return defaultInboxColumnOrder(allKeys);
  }
}

export function writeInboxColumnOrder(
  storage: Pick<Storage, "setItem"> | null | undefined,
  order: readonly string[],
): void {
  try {
    storage?.setItem(INBOX_COLUMN_ORDER_KEY, JSON.stringify(order));
  } catch {
    /* ignore quota / private mode */
  }
}
