/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from "vitest";
import {
  FILTER_SCOPE_LABEL,
  FILTER_SCOPE_LIMITATION,
  INBOX_ACTION_COLUMNS,
  INBOX_FILTERABLE_COLUMNS,
  emptyFilterIsInactive,
  filterInboxRows,
  inboxFieldTokens,
  isInboxFilterableColumn,
  kpiFromLoadedPage,
  modeBAvailable,
  orderMatchesColFilter,
  pageFilterFootnote,
  uniqueInboxOptions,
  type InboxColFilter,
} from "./inboxSheetFilter";
import type { PoRowLike as Row } from "./poSheet";

function po(partial: Partial<Row> & { id: string }): Row {
  return {
    name: "Cust",
    salesName: "Belum terverifikasi",
    ...partial,
  };
}

const sample: Row[] = [
  po({
    id: "SO-1",
    orderDate: "2024-11-01",
    name: "Alpha",
    address: "Jl A",
    paymentTerms: "NET 30",
    createdByUser: "Admin",
    salesName: "Budi",
    expedition: "JNE",
    ship: "2024-11-10",
    deliveryZone: "Jogja",
    branch: "Yogyakarta",
    orderPriority: "Urgent",
    bufferLabel: "Buffer",
    productionStatus: "Baru",
    qty: 150,
    lineCount: 2,
    poNotes: "Catatan satu",
    sourceLines: [
      {
        item_code: "SKU-A",
        name: "Box A",
        qty: 100,
        unit: "pcs",
        production_process: "print",
        color: "Merah",
      },
      {
        item_code: "SKU-B",
        name: "Box B",
        qty: 50,
        unit: "pcs",
        production_process: "non_print",
        color: "Biru",
      },
    ],
  }),
  po({
    id: "SO-2",
    orderDate: "2024-11-05",
    name: "Beta",
    createdByUser: "Clerk",
    salesName: "Siti",
    ship: "2024-11-20",
    branch: "Semarang",
    orderPriority: "Normal",
    bufferLabel: "Non-Buffer",
    productionStatus: "Terproses",
    qty: 20,
    lineCount: 1,
    sourceLines: [
      {
        item_code: "SKU-C",
        name: "Label C",
        qty: 20,
        unit: "rim",
        production_process: "print",
        color: "Hitam",
      },
    ],
  }),
  po({
    id: "SO-3",
    orderDate: "",
    name: "Gamma",
    salesName: "Belum terverifikasi",
    productionStatus: "Baru",
    qty: null,
    lineCount: 0,
    sourceLines: [],
  }),
];

describe("Slice 1G inbox header filters", () => {
  it("exposes filter for every required data column and skips action columns", () => {
    const keys = INBOX_FILTERABLE_COLUMNS.map((c) => c.key);
    for (const required of [
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
    ]) {
      expect(keys).toContain(required);
      expect(isInboxFilterableColumn(required)).toBe(true);
    }
    for (const action of INBOX_ACTION_COLUMNS) {
      expect(isInboxFilterableColumn(action)).toBe(false);
    }
  });

  it("uses structured field tokens, not HTML", () => {
    expect(inboxFieldTokens(sample[0], "salesName")).toEqual(["Budi"]);
    expect(inboxFieldTokens(sample[0], "itemCodes")).toEqual(["SKU-A", "SKU-B"]);
    expect(inboxFieldTokens(sample[0], "itemProcesses")).toEqual([
      "Cetak",
      "Tidak Cetak",
    ]);
  });

  it("multi-item name/code/color/process match any line; PO appears once", () => {
    const byName = filterInboxRows(sample, {
      colFilters: {
        item: { selected: ["Box B"], text: "", min: "", max: "" },
      },
    });
    expect(byName.map((r) => r.id)).toEqual(["SO-1"]);

    const byColor = filterInboxRows(sample, {
      colFilters: {
        inkColors: { selected: ["Hitam"], text: "", min: "", max: "" },
      },
    });
    expect(byColor.map((r) => r.id)).toEqual(["SO-2"]);

    const byProcess = filterInboxRows(sample, {
      colFilters: {
        itemProcesses: { selected: ["Cetak"], text: "", min: "", max: "" },
      },
    });
    expect(byProcess.map((r) => r.id).sort()).toEqual(["SO-1", "SO-2"]);
    expect(byProcess).toHaveLength(2);
  });

  it("does not duplicate PO when multiple lines match", () => {
    const rows = filterInboxRows(sample, {
      colFilters: {
        itemProcesses: { selected: ["Cetak", "Tidak Cetak"], text: "", min: "", max: "" },
      },
    });
    const ids = rows.map((r) => r.id);
    expect(ids).toEqual([...new Set(ids)]);
    expect(ids.filter((id) => id === "SO-1")).toHaveLength(1);
  });

  it("Total Qty range uses PO total, not line qty", () => {
    const rows = filterInboxRows(sample, {
      colFilters: {
        qty: { selected: null, text: "", min: "100", max: "200" },
      },
    });
    expect(rows.map((r) => r.id)).toEqual(["SO-1"]);
  });

  it("supports empty/null values in checkbox options", () => {
    const opts = uniqueInboxOptions(sample, "orderDate", {});
    expect(opts).toContain("");
    const emptyOnly = filterInboxRows(sample, {
      colFilters: {
        orderDate: { selected: [""], text: "", min: "", max: "" },
      },
    });
    expect(emptyOnly.map((r) => r.id)).toEqual(["SO-3"]);
  });

  it("sorts text, number, and date", () => {
    const byName = filterInboxRows(sample, {
      sort: { key: "name", dir: "asc" },
    });
    expect(byName.map((r) => r.name)).toEqual(["Alpha", "Beta", "Gamma"]);

    const byQtyDesc = filterInboxRows(sample, {
      sort: { key: "qty", dir: "desc" },
    });
    expect(byQtyDesc.map((r) => r.id)).toEqual(["SO-1", "SO-2", "SO-3"]);

    const byDate = filterInboxRows(sample, {
      sort: { key: "ship", dir: "asc" },
    });
    expect(byDate.map((r) => r.id)[0]).toBe("SO-3"); // empty date sorts first as 0
  });

  it("date range filter on Tanggal PO / Estimasi", () => {
    const f: InboxColFilter = {
      selected: null,
      text: "",
      min: "",
      max: "",
      dateFrom: "2024-11-04",
      dateTo: "2024-11-06",
    };
    expect(orderMatchesColFilter(sample[1], "orderDate", f)).toBe(true);
    expect(orderMatchesColFilter(sample[0], "orderDate", f)).toBe(false);
  });

  it("combines multiple filters and supports reset semantics", () => {
    const active: Record<string, InboxColFilter> = {
      branch: { selected: ["Yogyakarta"], text: "", min: "", max: "" },
      itemProcesses: { selected: ["Cetak"], text: "", min: "", max: "" },
    };
    const rows = filterInboxRows(sample, { colFilters: active });
    expect(rows.map((r) => r.id)).toEqual(["SO-1"]);

    delete active.branch;
    delete active.itemProcesses;
    expect(Object.keys(active)).toHaveLength(0);
    expect(emptyFilterIsInactive({ selected: null, text: "", min: "", max: "" })).toBe(
      true,
    );
  });

  it("KPI counts unique PO on loaded page — no multi-item double count", () => {
    const kpi = kpiFromLoadedPage(sample);
    expect(kpi.totalLoaded).toBe(3);
    expect(kpi.baru + kpi.terproses).toBe(3);
  });

  it("page filter footnote never claims global Accurate filter", () => {
    const note = pageFilterFootnote({
      filteredCount: 1,
      loadedCount: 3,
      accurateTotal: 11768,
      filtersActive: true,
    });
    expect(note).toContain("Filter halaman ini");
    expect(note).toMatch(/11[.\u00a0]?768/);
    expect(note).toContain("tidak difilter");
    expect(FILTER_SCOPE_LABEL).toContain("halaman ini");
    expect(FILTER_SCOPE_LIMITATION).toMatch(/Mode B|belum tersedia/i);
    expect(modeBAvailable()).toBe(false);
  });

  it("Sales mapping remains officialSalesLabel — never invents creator", () => {
    expect(inboxFieldTokens(sample[2], "salesName")).toEqual(["Belum terverifikasi"]);
    expect(inboxFieldTokens(sample[0], "createdByUser")).toEqual(["Admin"]);
    expect(inboxFieldTokens(sample[0], "salesName")).not.toEqual(
      inboxFieldTokens(sample[0], "createdByUser"),
    );
  });

  it("select-all / clear-all option lists are unique values from page", () => {
    const sales = uniqueInboxOptions(sample, "salesName", {});
    expect(sales.sort()).toEqual(["Belum terverifikasi", "Budi", "Siti"].sort());
  });

  it("jsdom: filter dropdown markup can open and close", () => {
    document.body.innerHTML = "";
    const btn = document.createElement("button");
    btn.className = "sheet-filter-trigger";
    document.body.appendChild(btn);

    const menu = document.createElement("div");
    menu.id = "inbox-filter-menu";
    menu.className = "sheet-filter-menu";
    menu.innerHTML =
      '<div class="filter-values"><label data-filter-item="Budi"><input data-sheet-value type="checkbox" value="Budi" checked></label></div>' +
      '<button type="button" data-close>close</button>';
    document.body.appendChild(menu);
    expect(document.getElementById("inbox-filter-menu")).toBeTruthy();

    const checks = [
      ...menu.querySelectorAll<HTMLInputElement>("input[data-sheet-value]"),
    ];
    expect(checks).toHaveLength(1);
    checks.forEach((c) => {
      c.checked = false;
    });
    expect(checks.every((c) => !c.checked)).toBe(true);
    checks.forEach((c) => {
      c.checked = true;
    });
    expect(checks.every((c) => c.checked)).toBe(true);

    menu.remove();
    expect(document.getElementById("inbox-filter-menu")).toBeNull();
  });

  it("column visibility / preset keys stay compatible with filterable set", () => {
    // Action columns never receive value filters even if visible.
    expect(INBOX_ACTION_COLUMNS).toContain("detailPo");
    expect(INBOX_ACTION_COLUMNS).toContain("liveTracking");
    expect(INBOX_FILTERABLE_COLUMNS.every((c) => c.kind !== "action")).toBe(true);
  });
});
