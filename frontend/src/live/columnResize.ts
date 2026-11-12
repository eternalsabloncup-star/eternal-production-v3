/** Step 158 — shared column resize prefs (pure + DOM attach). */

export type ColumnWidthMap = Record<string, number>;

export const COLUMN_RESIZE_MIN: Record<string, number> = {
  id: 120,
  name: 140,
  number: 72,
  date: 100,
  action: 96,
  text: 88,
  default: 88,
};

export function minWidthFor(
  key: string,
  kind?: string | null,
): number {
  if (key === "id") return COLUMN_RESIZE_MIN.id;
  if (key === "name") return COLUMN_RESIZE_MIN.name;
  if (kind === "number") return COLUMN_RESIZE_MIN.number;
  if (kind === "date") return COLUMN_RESIZE_MIN.date;
  if (kind === "action") return COLUMN_RESIZE_MIN.action;
  return COLUMN_RESIZE_MIN.text;
}

export function clampColumnWidth(
  key: string,
  width: number,
  kind?: string | null,
): number {
  const min = minWidthFor(key, kind);
  const n = Math.round(Number(width) || 0);
  if (!Number.isFinite(n) || n < min) return min;
  return n;
}

export function loadColumnWidths(storageKey: string): ColumnWidthMap {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const out: ColumnWidthMap = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) out[k] = n;
    }
    return out;
  } catch {
    return {};
  }
}

export function saveColumnWidths(
  storageKey: string,
  widths: ColumnWidthMap,
): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(widths || {}));
  } catch {
    /* ignore quota */
  }
}

export function clearColumnWidths(storageKey: string): void {
  try {
    localStorage.removeItem(storageKey);
  } catch {
    /* ignore */
  }
}

export function stickyLeftOffsets(
  order: string[],
  widths: ColumnWidthMap,
  locked: string[] = ["id", "name"],
): Record<string, number> {
  const out: Record<string, number> = {};
  let left = 0;
  for (const key of order) {
    if (!locked.includes(key)) continue;
    out[key] = left;
    left += widths[key] || minWidthFor(key);
  }
  return out;
}

/** Prevent header drag/sort while resizing. */
export function isResizeHandleEvent(target: EventTarget | null): boolean {
  return !!(
    target &&
    target instanceof Element &&
    target.closest("[data-col-resize]")
  );
}

export type AttachColumnResizeOpts = {
  storageKey: string;
  kindOf?: (key: string) => string | null | undefined;
  onChange?: (widths: ColumnWidthMap) => void;
};

/**
 * Attach drag handles to th[data-column]. Safe to call repeatedly (idempotent).
 * Does not start sort/filter/drag — handle uses stopPropagation.
 */
export function attachColumnResize(
  table: HTMLElement | null | undefined,
  opts: AttachColumnResizeOpts,
): ColumnWidthMap {
  if (!table) return {};
  const widths = loadColumnWidths(opts.storageKey);
  const heads = table.querySelectorAll("thead th[data-column]");
  heads.forEach((th) => {
    const key = th.getAttribute("data-column") || "";
    if (!key) return;
    const kind = opts.kindOf ? opts.kindOf(key) : null;
    if (widths[key] != null) {
      const w = clampColumnWidth(key, widths[key], kind);
      widths[key] = w;
      (th as HTMLElement).style.width = w + "px";
      (th as HTMLElement).style.minWidth = w + "px";
      (th as HTMLElement).style.maxWidth = w + "px";
      table.querySelectorAll(`td[data-column="${CSS.escape(key)}"]`).forEach((td) => {
        (td as HTMLElement).style.width = w + "px";
        (td as HTMLElement).style.minWidth = w + "px";
        (td as HTMLElement).style.maxWidth = w + "px";
      });
    }
    if (th.querySelector("[data-col-resize]")) return;
    const handle = document.createElement("span");
    handle.setAttribute("data-col-resize", key);
    handle.className = "col-resize-handle";
    handle.title = "Seret untuk ubah lebar kolom";
    handle.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const startX = ev.clientX;
      const startW =
        widths[key] ||
        Math.max(
          minWidthFor(key, kind),
          Math.round((th as HTMLElement).getBoundingClientRect().width),
        );
      const pointerId = ev.pointerId;
      try {
        handle.setPointerCapture(pointerId);
      } catch {
        /* ignore */
      }
      const onMove = (e: PointerEvent) => {
        const next = clampColumnWidth(key, startW + (e.clientX - startX), kind);
        widths[key] = next;
        (th as HTMLElement).style.width = next + "px";
        (th as HTMLElement).style.minWidth = next + "px";
        (th as HTMLElement).style.maxWidth = next + "px";
        table
          .querySelectorAll(`td[data-column="${CSS.escape(key)}"]`)
          .forEach((td) => {
            (td as HTMLElement).style.width = next + "px";
            (td as HTMLElement).style.minWidth = next + "px";
            (td as HTMLElement).style.maxWidth = next + "px";
          });
        // Sticky name offset follows id width when resizing id.
        if (key === "id") {
          const nameTh = table.querySelector(
            'th[data-column="name"]',
          ) as HTMLElement | null;
          const nameTds = table.querySelectorAll('td[data-column="name"]');
          if (nameTh) nameTh.style.left = next + "px";
          nameTds.forEach((td) => {
            (td as HTMLElement).style.left = next + "px";
          });
        }
      };
      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        saveColumnWidths(opts.storageKey, widths);
        if (opts.onChange) opts.onChange({ ...widths });
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });
    th.appendChild(handle);
  });
  return widths;
}
