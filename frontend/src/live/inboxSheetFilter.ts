/** Slice 1G — Inbox Accurate header filters (Mode A: loaded page only). */

import {
  bufferStockLabel,
  multiLineItemField,
  officialSalesLabel,
  orderPriorityLabel,
  processLabel,
  type PoLineLike,
  type PoRowLike,
} from "./poSheet";

export const FILTER_SCOPE_MODE_A = "page" as const;
export const FILTER_SCOPE_LABEL =
  "Filter halaman ini — tidak berlaku untuk seluruh Accurate";
export const FILTER_SCOPE_LIMITATION =
  "Filter seluruh Accurate (Mode B) belum tersedia — tidak ada scan lintas halaman";

export type InboxFilterKind = "text" | "number" | "date" | "action";

export type InboxColFilter = {
  selected: string[] | null;
  text: string;
  min: string;
  max: string;
  dateFrom?: string;
  dateTo?: string;
};

export type InboxSort = { key: string | null; dir: "asc" | "desc" | null };

/** Data columns that receive Excel-style filters. Action columns are excluded. */
export const INBOX_FILTERABLE_COLUMNS: ReadonlyArray<{
  key: string;
  label: string;
  kind: InboxFilterKind;
  multiItem?: "item_code" | "name" | "unit" | "process" | "color";
}> = [
  { key: "id", label: "No PO", kind: "text" },
  { key: "orderDate", label: "Tanggal PO", kind: "date" },
  { key: "name", label: "Pelanggan", kind: "text" },
  { key: "address", label: "Alamat", kind: "text" },
  { key: "paymentTerms", label: "Syarat Pembayaran", kind: "text" },
  { key: "createdByUser", label: "User Pembuat", kind: "text" },
  { key: "salesName", label: "Sales", kind: "text" },
  { key: "expedition", label: "Ekspedisi", kind: "text" },
  { key: "ship", label: "Estimasi Kirim", kind: "date" },
  { key: "deliveryZone", label: "Zona", kind: "text" },
  { key: "branch", label: "Cabang", kind: "text" },
  { key: "orderPriority", label: "Status Pesanan", kind: "text" },
  { key: "bufferLabel", label: "Buffer / Non-Buffer", kind: "text" },
  { key: "productionStatus", label: "Status Workflow", kind: "text" },
  { key: "itemCodes", label: "Kode Barang", kind: "text", multiItem: "item_code" },
  { key: "item", label: "Nama Barang", kind: "text", multiItem: "name" },
  { key: "itemQtys", label: "Qty Barang", kind: "text", multiItem: undefined },
  { key: "itemUnits", label: "Satuan", kind: "text", multiItem: "unit" },
  { key: "itemProcesses", label: "Proses Barang", kind: "text", multiItem: "process" },
  { key: "inkColors", label: "Warna Barang", kind: "text", multiItem: "color" },
  { key: "qty", label: "Total Qty", kind: "number" },
  { key: "lineCount", label: "Jumlah Jenis", kind: "number" },
  { key: "poNotes", label: "Keterangan PO", kind: "text" },
];

export const INBOX_ACTION_COLUMNS = ["detailPo", "liveTracking", "action"] as const;

export function isInboxFilterableColumn(key: string): boolean {
  return INBOX_FILTERABLE_COLUMNS.some((c) => c.key === key);
}

export function inboxColumnMeta(key: string) {
  return INBOX_FILTERABLE_COLUMNS.find((c) => c.key === key) || null;
}

function linesOf(row: PoRowLike | null | undefined): PoLineLike[] {
  return Array.isArray(row?.sourceLines) ? row!.sourceLines! : [];
}

/** Structured display/token values for a column — never from rendered HTML. */
export function inboxFieldTokens(row: PoRowLike, key: string): string[] {
  const meta = inboxColumnMeta(key);
  if (!meta) return [];

  if (meta.multiItem) {
    const lines = linesOf(row);
    if (lines.length) {
      return lines.map((line) => {
        if (meta.multiItem === "process") return processLabel(line.production_process);
        if (meta.multiItem === "item_code") {
          const v = line.item_code;
          return v != null && String(v).trim() ? String(v).trim() : "";
        }
        if (meta.multiItem === "name") {
          const v = line.name;
          return v != null && String(v).trim() ? String(v).trim() : "";
        }
        if (meta.multiItem === "unit") {
          const v = line.unit;
          return v != null && String(v).trim() ? String(v).trim() : "";
        }
        if (meta.multiItem === "color") {
          const v = line.color;
          return v != null && String(v).trim() ? String(v).trim() : "";
        }
        return "";
      });
    }
    // Fallback scalars when detail not enriched yet.
    if (meta.multiItem === "item_code") return [String(row.itemCodes || "")];
    if (meta.multiItem === "name") return [String(row.item || "")];
    if (meta.multiItem === "unit") return [String(row.itemUnits || "")];
    if (meta.multiItem === "process") return [String(row.itemProcesses || "")];
    return [""];
  }

  if (key === "itemQtys") {
    const lines = linesOf(row);
    if (lines.length) {
      return lines.map((line) => {
        const n = Number(line.qty);
        return Number.isFinite(n) ? String(n) : "";
      });
    }
    return [""];
  }

  switch (key) {
    case "id":
      return [String(row.id || "")];
    case "orderDate":
      return [String(row.orderDate || "")];
    case "name":
      return [String(row.name || "")];
    case "address":
      return [String(row.address || "")];
    case "paymentTerms":
      return [String(row.paymentTerms || "")];
    case "createdByUser":
      return [String(row.createdByUser || "")];
    case "salesName":
      return [officialSalesLabel(row)];
    case "expedition":
      return [String(row.expedition || "")];
    case "ship":
      return [String(row.ship || "")];
    case "deliveryZone":
      return [String(row.deliveryZone || "")];
    case "branch":
      return [String(row.branch || "")];
    case "orderPriority":
      return [orderPriorityLabel(row)];
    case "bufferLabel":
      return [bufferStockLabel(row)];
    case "productionStatus":
      return [String(row.productionStatus || "Baru")];
    case "qty": {
      const n = row.qty;
      return [n == null || Number.isNaN(Number(n)) ? "" : String(n)];
    }
    case "lineCount": {
      const n =
        row.lineCount != null
          ? row.lineCount
          : Array.isArray(row.sourceLines)
            ? row.sourceLines.length
            : null;
      return [n == null ? "" : String(n)];
    }
    case "poNotes":
      return [String(row.poNotes || "")];
    default:
      return [""];
  }
}

export function inboxScalarValue(row: PoRowLike, key: string): string | number | null {
  const meta = inboxColumnMeta(key);
  if (!meta) return null;
  if (meta.kind === "number") {
    const raw = inboxFieldTokens(row, key)[0];
    if (raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  if (meta.multiItem || key === "itemQtys") {
    return multiLineItemField(
      row.sourceLines,
      key === "itemCodes"
        ? "item_code"
        : key === "item"
          ? "name"
          : key === "itemQtys"
            ? "qty"
            : key === "itemUnits"
              ? "unit"
              : key === "itemProcesses"
                ? "process"
                : "color",
    );
  }
  return inboxFieldTokens(row, key)[0] ?? "";
}

function parseDateToken(v: string): number | null {
  const s = String(v || "").trim();
  if (!s) return null;
  // ISO yyyy-mm-dd
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return Date.UTC(+iso[1], +iso[2] - 1, +iso[3]);
  // Accurate-ish dd/mm/yyyy
  const dmy = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})/);
  if (dmy) return Date.UTC(+dmy[3], +dmy[2] - 1, +dmy[1]);
  // Legacy demo "12 Nov 2024"
  const mon = s.match(/^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/);
  if (mon) {
    const months: Record<string, number> = {
      jan: 0,
      january: 0,
      feb: 1,
      february: 1,
      mar: 2,
      march: 2,
      apr: 3,
      april: 3,
      may: 4,
      mei: 4,
      jun: 5,
      june: 5,
      juni: 5,
      jul: 6,
      july: 6,
      juli: 6,
      aug: 7,
      august: 7,
      agustus: 7,
      sep: 8,
      september: 8,
      oct: 9,
      october: 9,
      okt: 9,
      oktober: 9,
      nov: 10,
      november: 10,
      dec: 11,
      december: 11,
      des: 11,
      desember: 11,
    };
    const mi = months[mon[2].toLowerCase()];
    if (mi != null) return Date.UTC(+mon[3], mi, +mon[1]);
  }
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

export function orderMatchesColFilter(
  row: PoRowLike,
  key: string,
  filter: InboxColFilter,
): boolean {
  const meta = inboxColumnMeta(key);
  if (!meta) return true;
  const tokens = inboxFieldTokens(row, key).map((t) => String(t ?? ""));

  if (filter.selected) {
    const set = new Set(filter.selected);
    const hit = tokens.some((t) => set.has(t));
    if (!hit) return false;
  }

  if (filter.text) {
    const q = filter.text.toLocaleLowerCase("id-ID");
    const hit = tokens.some((t) => t.toLocaleLowerCase("id-ID").includes(q));
    if (!hit) return false;
  }

  if (meta.kind === "number") {
    const n = inboxScalarValue(row, key);
    if (typeof n !== "number") {
      // empty/null qty: fail closed for range filters, pass if no range
      if (filter.min !== "" || filter.max !== "") return false;
    } else {
      if (filter.min !== "" && filter.min != null && n < Number(filter.min)) return false;
      if (filter.max !== "" && filter.max != null && n > Number(filter.max)) return false;
    }
  }

  if (meta.kind === "date") {
    const token = tokens[0] || "";
    const ts = parseDateToken(token);
    if (filter.dateFrom) {
      const from = parseDateToken(filter.dateFrom);
      if (from != null && (ts == null || ts < from)) return false;
    }
    if (filter.dateTo) {
      const to = parseDateToken(filter.dateTo);
      if (to != null && (ts == null || ts > to)) return false;
    }
  }

  return true;
}

export function filterInboxRows(
  rows: PoRowLike[],
  opts: {
    search?: string;
    status?: string;
    branch?: string;
    colFilters?: Record<string, InboxColFilter>;
    sort?: InboxSort | null;
  },
): PoRowLike[] {
  const q = String(opts.search || "")
    .trim()
    .toLocaleLowerCase("id-ID");
  const status = opts.status || "Semua";
  const branch = opts.branch || "Semua";
  const colFilters = opts.colFilters || {};

  let out = rows.filter((o) => {
    if (status !== "Semua") {
      const workflow =
        o.productionStatus ||
        ((o as { stage?: string }).stage === "inbox" ? "Baru" : "Terproses");
      if (workflow !== status) return false;
    }
    if (branch !== "Semua" && String(o.branch || "") !== branch) return false;
    if (q) {
      const hay = [
        o.id,
        o.name,
        o.item,
        officialSalesLabel(o),
        multiLineItemField(o.sourceLines, "name"),
        multiLineItemField(o.sourceLines, "item_code"),
      ]
        .join(" ")
        .toLocaleLowerCase("id-ID");
      if (!hay.includes(q)) return false;
    }
    for (const [key, f] of Object.entries(colFilters)) {
      if (!orderMatchesColFilter(o, key, f)) return false;
    }
    return true;
  });

  // Deduplicate by PO id (multi-item must never inflate rows)
  const seen = new Set<string>();
  out = out.filter((o) => {
    const id = String(o.id || "");
    if (!id) return true;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });

  const sort = opts.sort;
  if (sort?.key && sort.dir) {
    const key = sort.key;
    const meta = inboxColumnMeta(key);
    const dir = sort.dir === "desc" ? -1 : 1;
    out = out.slice().sort((a, b) => {
      let cmp = 0;
      if (meta?.kind === "number") {
        const va = inboxScalarValue(a, key);
        const vb = inboxScalarValue(b, key);
        const na = typeof va === "number" ? va : Number.NEGATIVE_INFINITY;
        const nb = typeof vb === "number" ? vb : Number.NEGATIVE_INFINITY;
        cmp = na - nb;
      } else if (meta?.kind === "date") {
        const ta = parseDateToken(String(inboxFieldTokens(a, key)[0] || "")) ?? 0;
        const tb = parseDateToken(String(inboxFieldTokens(b, key)[0] || "")) ?? 0;
        cmp = ta - tb;
      } else {
        const va = String(inboxFieldTokens(a, key)[0] || "");
        const vb = String(inboxFieldTokens(b, key)[0] || "");
        cmp = va.localeCompare(vb, "id-ID", { numeric: true });
      }
      if (cmp !== 0) return dir * cmp;
      return String(a.id || "").localeCompare(String(b.id || ""));
    });
  }

  return out;
}

export function uniqueInboxOptions(
  rows: PoRowLike[],
  key: string,
  colFilters: Record<string, InboxColFilter>,
): string[] {
  const others = { ...colFilters };
  delete others[key];
  const base = filterInboxRows(rows, { colFilters: others });
  const set = new Set<string>();
  for (const row of base) {
    for (const token of inboxFieldTokens(row, key)) set.add(String(token ?? ""));
  }
  return [...set].sort((a, b) => a.localeCompare(b, "id-ID", { numeric: true }));
}

export function emptyFilterIsInactive(f: InboxColFilter | null | undefined): boolean {
  if (!f) return true;
  const noSel = f.selected == null;
  return (
    noSel &&
    !f.text &&
    (f.min === "" || f.min == null) &&
    (f.max === "" || f.max == null) &&
    !f.dateFrom &&
    !f.dateTo
  );
}

export function kpiFromLoadedPage(rows: PoRowLike[]): {
  totalLoaded: number;
  baru: number;
  terproses: number;
} {
  // KPI always from unfiltered loaded page — never from multi-item expansion
  const ids = new Set<string>();
  let baru = 0;
  let terproses = 0;
  for (const o of rows) {
    const id = String(o.id || "");
    if (id) {
      if (ids.has(id)) continue;
      ids.add(id);
    }
    const workflow =
      o.productionStatus ||
      ((o as { stage?: string }).stage === "inbox" ? "Baru" : "Terproses");
    if (workflow === "Baru" || (o as { stage?: string }).stage === "inbox") baru += 1;
    else terproses += 1;
  }
  return { totalLoaded: ids.size || rows.length, baru, terproses };
}

export function pageFilterFootnote(opts: {
  filteredCount: number;
  loadedCount: number;
  accurateTotal: number | null | undefined;
  filtersActive: boolean;
}): string {
  const base = `Filter halaman ini: ${opts.filteredCount} / ${opts.loadedCount} PO dimuat`;
  const accurate =
    opts.accurateTotal != null
      ? ` · Total Accurate ${opts.accurateTotal.toLocaleString("id-ID")} (tidak difilter client-side)`
      : "";
  const note = opts.filtersActive ? " · filter aktif hanya pada halaman ini" : "";
  return base + accurate + note;
}

export function modeBAvailable(): boolean {
  // Backend/Gateway global filter query not implemented in Slice 1G.
  return false;
}
