import { describe, expect, it } from "vitest";
import {
  COLUMN_PRESETS,
  PO_SHEET_COLUMN_KEYS,
  SHEET_PREF_KEY_V6,
  bufferStockLabel,
  itemSummaryLines,
  multiLineItemField,
  officialSalesLabel,
  orderPriorityLabel,
  preserveNotesNewlines,
  salesNeverFallsBackToCreator,
  sheetFootSourceLabel,
  workflowStatusLabel,
} from "./poSheet";

describe("Slice 1F PO sheet helpers", () => {
  it("bumps sheet pref key and includes PDF PO columns", () => {
    expect(SHEET_PREF_KEY_V6).toBe("eternal_v2_production_sheet_columns_v6");
    expect(PO_SHEET_COLUMN_KEYS).toContain("orderDate");
    expect(PO_SHEET_COLUMN_KEYS).toContain("paymentTerms");
    expect(PO_SHEET_COLUMN_KEYS).toContain("createdByUser");
    expect(PO_SHEET_COLUMN_KEYS).toContain("orderPriority");
    expect(PO_SHEET_COLUMN_KEYS).toContain("bufferLabel");
    expect(PO_SHEET_COLUMN_KEYS).toContain("productionStatus");
    expect(PO_SHEET_COLUMN_KEYS).toContain("itemCodes");
    expect(PO_SHEET_COLUMN_KEYS).toContain("liveTracking");
    expect(PO_SHEET_COLUMN_KEYS).toContain("scheduleDate");
    expect(PO_SHEET_COLUMN_KEYS).toContain("action");
  });

  it("defines Operasional / Administrasi / Barang / Semua presets", () => {
    expect(Object.keys(COLUMN_PRESETS)).toEqual([
      "Operasional",
      "Administrasi",
      "Barang",
      "Semua",
    ]);
    expect(COLUMN_PRESETS.Semua).toHaveLength(PO_SHEET_COLUMN_KEYS.length);
    expect(COLUMN_PRESETS.Barang).toContain("itemCodes");
    expect(COLUMN_PRESETS.Administrasi).toContain("paymentTerms");
    expect(COLUMN_PRESETS.Operasional).toContain("orderPriority");
  });

  it("null urgent/buffer → Belum terverifikasi, not Ya/Tidak", () => {
    expect(orderPriorityLabel({ urgent: null })).toBe("Belum terverifikasi");
    expect(orderPriorityLabel({ urgent: undefined })).toBe("Belum terverifikasi");
    expect(orderPriorityLabel({ urgent: true })).toBe("Urgent");
    expect(orderPriorityLabel({ urgent: false })).toBe("Normal");
    expect(bufferStockLabel({ bufferStock: null })).toBe("Belum terverifikasi");
    expect(bufferStockLabel({ bufferStock: true })).toBe("Buffer");
    expect(bufferStockLabel({ bufferStock: false })).toBe("Non-Buffer");
  });

  it("sales missing stays unverified — never invents creator/branch", () => {
    expect(officialSalesLabel({ salesName: null, createdByUser: "Admin" })).toBe(
      "Belum terverifikasi",
    );
    expect(
      officialSalesLabel({ salesName: "Belum terverifikasi", branch: "Yogyakarta" }),
    ).toBe("Belum terverifikasi");
    expect(officialSalesLabel({ salesName: "Sales Jogja Official" })).toBe(
      "Sales Jogja Official",
    );
  });

  it("multi-item summary is one PO row with newline-joined lines", () => {
    const row = {
      id: "PO/1",
      sourceLines: [
        {
          item_code: "100003",
          name: "Cup",
          qty: 1000,
          unit: "PCS",
          production_process: "print",
          color: "Hijau",
        },
        {
          item_code: "100460",
          name: "Lid",
          qty: 1000,
          unit: "PCS",
          production_process: "non_print",
          color: "Bening",
        },
      ],
    };
    const summary = itemSummaryLines(row);
    expect(summary.split("\n")).toHaveLength(2);
    expect(summary).toContain("100003");
    expect(summary).toContain("100460");
    expect(multiLineItemField(row.sourceLines, "name").split("\n")).toEqual([
      "Cup",
      "Lid",
    ]);
    expect(multiLineItemField(row.sourceLines, "process").split("\n")).toEqual([
      "Cetak",
      "Tidak Cetak",
    ]);
  });

  it("workflow label and notes newlines", () => {
    expect(workflowStatusLabel({ productionStatus: "Terproses" })).toBe("Terproses");
    expect(workflowStatusLabel({})).toBe("Baru");
    expect(preserveNotesNewlines("baris1\nbaris2")).toBe("baris1\nbaris2");
  });

  it("sheetfoot distinguishes live vs demo", () => {
    expect(sheetFootSourceLabel({ mode: "live" })).toContain("Accurate Live");
    expect(sheetFootSourceLabel({ mode: "error" })).not.toContain("Data demo");
    expect(sheetFootSourceLabel(null)).toContain("Data demo");
  });

  it("sales≠creator contract helper", () => {
    expect(
      salesNeverFallsBackToCreator({
        sales: null,
        created_by_user: "Admin",
        sales_source: null,
      }),
    ).toBe(true);
    expect(
      salesNeverFallsBackToCreator({
        sales: "Sales A",
        created_by_user: "Admin",
        sales_source: "salesmanList",
      }),
    ).toBe(true);
  });
});
