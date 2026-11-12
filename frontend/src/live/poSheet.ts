/** Slice 1F — PO sheet column helpers (one row per PO; multi-line item summary). */

export type PoLineLike = {
  item_code?: string | null;
  name?: string | null;
  qty?: number | null;
  unit?: string | null;
  color?: string | null;
  production_process?: string | null;
};

export type PoRowLike = {
  id?: string | null;
  name?: string | null;
  salesName?: string | null;
  salesSource?: string | null;
  createdByUser?: string | null;
  branch?: string | null;
  urgent?: boolean | null;
  bufferStock?: boolean | null;
  orderPriority?: string | null;
  bufferLabel?: string | null;
  productionStatus?: string | null;
  sourceLines?: PoLineLike[] | null;
  item?: string | null;
  itemCodes?: string | null;
  itemUnits?: string | null;
  itemProcesses?: string | null;
  qty?: number | null;
  lineCount?: number | null;
  poNotes?: string | null;
};

export const SHEET_PREF_KEY_V6 = "eternal_v2_production_sheet_columns_v6";

/** PDF / Accurate PO fields + retained schedule keys used by production.html. */
export const PO_SHEET_COLUMN_KEYS = [
  "id",
  "orderDate",
  "name",
  "address",
  "paymentTerms",
  "createdByUser",
  "salesName",
  "expedition",
  "ship",
  "deliveryZone",
  "branch",
  "orderPriority",
  "bufferLabel",
  "productionStatus",
  "itemCodes",
  "item",
  "itemQtys",
  "itemUnits",
  "itemProcesses",
  "inkColors",
  "qty",
  "lineCount",
  "poNotes",
  "detailPo",
  "liveTracking",
  // preserved schedule / production columns
  "inkSequence",
  "assignmentQty",
  "assignmentDate",
  "scheduled",
  "done",
  "remainingTotal",
  "remainingScheduled",
  "unassigned",
  "packed",
  "deadline",
  "scheduleDate",
  "operator",
  "progress",
  "status",
  "receipt",
  "sj",
  "action",
] as const;

export type PoSheetColumnKey = (typeof PO_SHEET_COLUMN_KEYS)[number];

export const COLUMN_PRESETS: Record<
  "Operasional" | "Administrasi" | "Barang" | "Semua",
  readonly PoSheetColumnKey[]
> = {
  Operasional: [
    "id",
    "orderDate",
    "name",
    "salesName",
    "branch",
    "orderPriority",
    "bufferLabel",
    "productionStatus",
    "ship",
    "item",
    "qty",
    "scheduleDate",
    "operator",
    "status",
    "detailPo",
    "liveTracking",
    "action",
  ],
  Administrasi: [
    "id",
    "orderDate",
    "name",
    "address",
    "paymentTerms",
    "createdByUser",
    "salesName",
    "expedition",
    "deliveryZone",
    "branch",
    "poNotes",
    "receipt",
    "sj",
    "detailPo",
    "action",
  ],
  Barang: [
    "id",
    "name",
    "itemCodes",
    "item",
    "itemQtys",
    "itemUnits",
    "itemProcesses",
    "inkColors",
    "qty",
    "lineCount",
    "detailPo",
    "action",
  ],
  Semua: PO_SHEET_COLUMN_KEYS,
};

export function processLabel(process: string | null | undefined): string {
  if (process === "print") return "Cetak";
  if (process === "non_print") return "Tidak Cetak";
  return "Unknown";
}

export function officialSalesLabel(row: PoRowLike | null | undefined): string {
  const sales = row?.salesName != null ? String(row.salesName).trim() : "";
  if (sales && sales !== "Belum terverifikasi") return sales;
  return "Belum terverifikasi";
}

/** Never treat null urgent/buffer as Ya/Tidak false. */
export function orderPriorityLabel(row: PoRowLike | null | undefined): string {
  if (row?.orderPriority) return String(row.orderPriority);
  if (row?.urgent === true) return "Urgent";
  if (row?.urgent === false) return "Normal";
  return "Belum terverifikasi";
}

export function bufferStockLabel(row: PoRowLike | null | undefined): string {
  if (row?.bufferLabel) return String(row.bufferLabel);
  if (row?.bufferStock === true) return "Buffer";
  if (row?.bufferStock === false) return "Non-Buffer";
  return "Belum terverifikasi";
}

export function workflowStatusLabel(row: PoRowLike | null | undefined): string {
  const s = row?.productionStatus;
  if (s === "Terproses") return "Terproses";
  if (s === "Baru") return "Baru";
  return s ? String(s) : "Baru";
}

export function multiLineItemField(
  lines: PoLineLike[] | null | undefined,
  field: "item_code" | "name" | "qty" | "unit" | "process" | "color",
): string {
  const list = Array.isArray(lines) ? lines : [];
  if (!list.length) return "";
  return list
    .map((line) => {
      if (field === "process") return processLabel(line.production_process);
      if (field === "qty") {
        const n = Number(line.qty);
        return Number.isFinite(n) ? String(n) : "—";
      }
      const raw = line[field === "item_code" ? "item_code" : field === "name" ? "name" : field === "unit" ? "unit" : "color"];
      return raw != null && String(raw).trim() ? String(raw).trim() : "—";
    })
    .join("\n");
}

/** One PO row — multi-item text is newline-joined, never duplicated as extra PO rows. */
export function itemSummaryLines(row: PoRowLike | null | undefined): string {
  const lines = row?.sourceLines;
  if (Array.isArray(lines) && lines.length) {
    return lines
      .map((line) => {
        const code = line.item_code || "—";
        const name = line.name || "—";
        const qty = line.qty == null ? "—" : String(line.qty);
        const unit = line.unit || "";
        const process = processLabel(line.production_process);
        const color = line.color || "—";
        return `${code} · ${name} · ${qty}${unit ? " " + unit : ""} · ${process} · ${color}`;
      })
      .join("\n");
  }
  return row?.item ? String(row.item) : "";
}

export function preserveNotesNewlines(notes: string | null | undefined): string {
  return notes == null ? "" : String(notes);
}

export function sheetFootSourceLabel(meta: {
  mode?: string | null;
  fetchError?: string | null;
} | null): string {
  if (meta && meta.mode === "live") return "Accurate Live (halaman ini)";
  if (meta && meta.mode === "error") return "Sumber Accurate error — bukan data demo";
  return "Data demo, bukan Accurate nyata";
}

export function salesNeverFallsBackToCreator(row: {
  sales?: string | null;
  created_by_user?: string | null;
  sales_source?: string | null;
}): boolean {
  if (!row.sales) return row.sales_source == null;
  if (row.created_by_user && row.sales === row.created_by_user) {
    // Equal values are allowed only when Accurate sales field itself matches;
    // missing sales must never copy creator.
    return row.sales_source != null;
  }
  return true;
}
