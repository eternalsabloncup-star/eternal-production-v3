/** Step 158/161 — shared column resize (pure + DOM attach). */

export type ColumnWidthMap = Record<string, number>;

export const COLUMN_RESIZE_MIN: Record<string, number> = {
  id: 120,
  name: 140,
  item: 160,
  number: 72,
  date: 110,
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
  if (key === "item") return COLUMN_RESIZE_MIN.item;
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
  return Math.min(n, 720);
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
  onGeometry?: () => void;
  /** Sticky horizontal keys in left-to-right order. */
  stickyKeys?: string[];
  /** Applied when storage has no value for a key (not written until user resizes). */
  defaults?: ColumnWidthMap;
  /** Lock every visible column width so resizing one does not redistribute others. */
  lockAll?: boolean;
};

function escapeKey(key: string): string {
  return typeof CSS !== "undefined" && CSS.escape
    ? CSS.escape(key)
    : String(key).replace(/"/g, '\\"');
}

/** Assign data-column on header/body cells that lack keys (index-stable). */
export function ensureColumnKeys(table: HTMLElement): string[] {
  const headerRow =
    (table.querySelector(
      "thead tr:not(.sheet-group-row):last-of-type",
    ) as HTMLTableRowElement | null) ||
    (table.querySelector("thead tr:last-child") as HTMLTableRowElement | null);
  if (!headerRow) return [];
  const ths = [...headerRow.querySelectorAll("th")];
  const keys = ths.map((th, i) => {
    let key = th.getAttribute("data-column") || "";
    if (!key) {
      key = "c" + i;
      th.setAttribute("data-column", key);
    }
    return key;
  });
  table.querySelectorAll("tbody tr").forEach((tr) => {
    const cells = [...tr.children].filter(
      (el) => (el as HTMLElement).tagName === "TD",
    ) as HTMLElement[];
    cells.forEach((td, i) => {
      if (!td.getAttribute("data-column") && keys[i]) {
        td.setAttribute("data-column", keys[i]);
      }
    });
  });
  return keys;
}

export function ensureColgroup(table: HTMLElement, keys: string[]): void {
  let cg = table.querySelector("colgroup");
  if (!cg) {
    cg = document.createElement("colgroup");
    table.insertBefore(cg, table.firstChild);
  }
  const existing = new Map<string, HTMLElement>();
  cg.querySelectorAll("col").forEach((col) => {
    const k = col.getAttribute("data-column");
    if (k) existing.set(k, col as HTMLElement);
  });
  keys.forEach((key) => {
    if (existing.has(key)) return;
    const col = document.createElement("col");
    col.setAttribute("data-column", key);
    cg!.appendChild(col);
  });
}

/**
 * Attach drag handles to th[data-column]. Safe to call repeatedly (idempotent).
 * Resizing one column updates only that column (others stay locked).
 */
export function attachColumnResize(
  table: HTMLElement | null | undefined,
  opts: AttachColumnResizeOpts,
): ColumnWidthMap {
  if (!table || !opts?.storageKey) return {};
  const stickyKeys = opts.stickyKeys || ["id", "name"];
  const lockAll = opts.lockAll !== false;
  const keys = ensureColumnKeys(table);
  if (!keys.length) return {};
  ensureColgroup(table, keys);

  const widths: ColumnWidthMap = {
    ...(opts.defaults || {}),
    ...loadColumnWidths(opts.storageKey),
  };

  const applyPair = (key: string, w: number) => {
    const col = table.querySelector(
      `col[data-column="${escapeKey(key)}"]`,
    ) as HTMLElement | null;
    if (col) {
      col.style.width = w + "px";
      col.style.minWidth = w + "px";
    }
    const sel = `th[data-column="${escapeKey(key)}"], td[data-column="${escapeKey(key)}"]`;
    table.querySelectorAll(sel).forEach((el) => {
      const node = el as HTMLElement;
      const cs = node.getAttribute("colspan");
      if (cs && Number(cs) > 1) return;
      node.style.width = w + "px";
      node.style.minWidth = w + "px";
      node.style.maxWidth = w + "px";
      node.style.boxSizing = "border-box";
    });
  };

  const measureKey = (key: string) => {
    const th = table.querySelector(
      `thead tr:not(.sheet-group-row) th[data-column="${escapeKey(key)}"], thead th[data-column="${escapeKey(key)}"]`,
    ) as HTMLElement | null;
    return th ? Math.round(th.getBoundingClientRect().width) : 0;
  };

  const syncSticky = () => {
    let left = 0;
    stickyKeys.forEach((key) => {
      if (!keys.includes(key)) return;
      const kind = opts.kindOf ? opts.kindOf(key) : null;
      const w = clampColumnWidth(
        key,
        widths[key] || measureKey(key) || minWidthFor(key, kind),
        kind,
      );
      widths[key] = w;
      table
        .querySelectorAll(
          `th[data-column="${escapeKey(key)}"], td[data-column="${escapeKey(key)}"]`,
        )
        .forEach((el) => {
          const node = el as HTMLElement;
          const cs = node.getAttribute("colspan");
          if (cs && Number(cs) > 1) {
            // Group header that starts at this sticky key: pin to cumulative left.
            node.style.left = left + "px";
            return;
          }
          node.style.left = left + "px";
        });
      left += w;
    });
  };

  const syncTableWidth = () => {
    let sum = 0;
    keys.forEach((key) => {
      const th = table.querySelector(
        `thead tr:not(.sheet-group-row) th[data-column="${escapeKey(key)}"], thead th[data-column="${escapeKey(key)}"]`,
      ) as HTMLElement | null;
      if (th && th.classList.contains("v40-col-hidden")) return;
      sum += widths[key] || measureKey(key) || minWidthFor(key);
    });
    if (sum > 0) {
      table.style.tableLayout = "fixed";
      table.style.width = sum + "px";
      table.style.minWidth = sum + "px";
    }
  };

  // Lock natural / default / stored widths so one resize does not steal from neighbors.
  keys.forEach((key) => {
    const th = table.querySelector(
      `thead tr:not(.sheet-group-row) th[data-column="${escapeKey(key)}"], thead th[data-column="${escapeKey(key)}"]`,
    ) as HTMLElement | null;
    if (!th || th.classList.contains("v40-col-hidden")) return;
    const kind = opts.kindOf ? opts.kindOf(key) : null;
    let w = widths[key];
    if (w == null && lockAll) {
      w = measureKey(key) || minWidthFor(key, kind);
    }
    if (w != null) {
      widths[key] = clampColumnWidth(key, w, kind);
      applyPair(key, widths[key]);
    }
  });
  syncSticky();
  syncTableWidth();

  const headerRow =
    (table.querySelector(
      "thead tr:not(.sheet-group-row):last-of-type",
    ) as HTMLElement | null) ||
    (table.querySelector("thead tr:last-child") as HTMLElement | null);
  if (!headerRow) return widths;

  headerRow.querySelectorAll("th[data-column]").forEach((th) => {
    const key = th.getAttribute("data-column") || "";
    if (!key) return;
    if ((th as HTMLElement).classList.contains("v40-col-hidden")) return;
    if (th.querySelector("[data-col-resize]")) return;
    const kind = opts.kindOf ? opts.kindOf(key) : null;
    const handle = document.createElement("span");
    handle.setAttribute("data-col-resize", key);
    handle.className = "col-resize-handle";
    handle.title = "Seret untuk ubah lebar kolom";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", "Ubah lebar kolom " + key);
    handle.tabIndex = 0;
    handle.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      handle.classList.add("is-dragging");
      const startX = ev.clientX;
      const startW =
        widths[key] ||
        Math.max(
          minWidthFor(key, kind),
          Math.round((th as HTMLElement).getBoundingClientRect().width),
        );
      try {
        handle.setPointerCapture(ev.pointerId);
      } catch {
        /* ignore */
      }
      const onMove = (e: PointerEvent) => {
        const next = clampColumnWidth(key, startW + (e.clientX - startX), kind);
        widths[key] = next;
        applyPair(key, next);
        syncSticky();
        syncTableWidth();
        if (opts.onGeometry) opts.onGeometry();
      };
      const onUp = () => {
        handle.classList.remove("is-dragging");
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        saveColumnWidths(opts.storageKey, widths);
        syncSticky();
        syncTableWidth();
        if (opts.onGeometry) opts.onGeometry();
        if (opts.onChange) opts.onChange({ ...widths });
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });
    th.appendChild(handle);
  });

  if (opts.onGeometry) opts.onGeometry();
  return widths;
}
