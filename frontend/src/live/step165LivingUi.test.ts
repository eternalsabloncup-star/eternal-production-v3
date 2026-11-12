import { describe, expect, it } from "vitest";

/** Mirrors production.html toast(kind) heuristic — visual only. */
function classifyToastKind(msg: string): "error" | "success" | "info" {
  if (
    /gagal|error|ditolak|diblokir|invalid|unauthorized|403|401|wajib|belum memenuhi|menunggu prasyarat|tidak dapat/i.test(
      msg,
    )
  ) {
    return "error";
  }
  if (
    /berhasil|tersimpan|dibuat|dicabut|di-refresh|aktif|konfirmasi|disimpan|tercatat/i.test(
      msg,
    )
  ) {
    return "success";
  }
  return "info";
}

/** Mirrors production.html tag() tone selection — visual only. */
function classifyStatusTone(label: string): {
  tone: string;
  role: string;
} {
  const s = String(label ?? "");
  if (/Belum\s*Terverifikasi|UNKNOWN/i.test(s)) {
    return { tone: "unverified", role: "v165-status--unverified" };
  }
  if (/Urgent/i.test(s)) return { tone: "", role: "v165-status--urgent" };
  if (/Normal/i.test(s)) return { tone: "", role: "v165-status--normal" };
  if (/Selesai|Lunas|Siap|Synced|Approved|Baru/i.test(s)) {
    return {
      tone: "green",
      role: /Selesai/i.test(s) ? "v165-status--done" : "",
    };
  }
  if (/Hapus|Konflik|Bermasalah/i.test(s)) return { tone: "red", role: "" };
  if (
    /Pending|Menunggu|Belum|Sedang|Produksi|QC|Verifikasi|Dijadwalkan|Packing|DP/i.test(
      s,
    )
  ) {
    return {
      tone: "amber",
      role: /(Pending|Menunggu|Belum)/i.test(s)
        ? "v165-status--pending"
        : "v165-status--process",
    };
  }
  return { tone: "", role: "" };
}

describe("Step 165 living UI feedback heuristics", () => {
  it("classifies toast kinds without inventing success", () => {
    expect(classifyToastKind("Transaksi gagal")).toBe("error");
    expect(classifyToastKind("Job V3 dibuat untuk SO/1")).toBe("success");
    expect(classifyToastKind("Qty PO belum terverifikasi — penjadwalan diblokir hingga detail Accurate memuat qty resmi")).toBe(
      "error",
    );
    expect(classifyToastKind("Filter halaman ini")).toBe("info");
  });

  it("maps official status labels to distinct visual roles", () => {
    expect(classifyStatusTone("Normal").role).toBe("v165-status--normal");
    expect(classifyStatusTone("Urgent").role).toBe("v165-status--urgent");
    expect(classifyStatusTone("Belum Terverifikasi").tone).toBe("unverified");
    expect(classifyStatusTone("Selesai").role).toBe("v165-status--done");
    expect(classifyStatusTone("Menunggu").role).toBe("v165-status--pending");
    expect(classifyStatusTone("Produksi").role).toBe("v165-status--process");
  });
});
