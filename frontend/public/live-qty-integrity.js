/** Slice 1M.1 — qty / Tenggat / Inbox cell / detail dedupe (shared by production.html + live-runtime). */
(function (global) {
  "use strict";

  function isQtyUnverified(o) {
    if (!o) return true;
    if (o.qtyUnverified === true) return true;
    if (o.qtyVerified === false) return true;
    if (o.qtyVerified === true) {
      return o.qty == null || !Number.isFinite(Number(o.qty));
    }
    // Legacy/demo rows without an explicit flag: missing/non-finite qty is unknown.
    if (o.qty == null || !Number.isFinite(Number(o.qty))) return true;
    return false;
  }

  function productionQtySnapshot(o, opts) {
    const live = opts && opts.live === true;
    if (live && isQtyUnverified(o)) {
      return {
        qty: null,
        scheduled: 0,
        done: 0,
        packed: 0,
        unassigned: 0,
        remainingScheduled: 0,
        remainingTotal: null,
        invalid: false,
        unknownQty: 1,
        qtyUnverified: true,
      };
    }
    const qty = live
      ? Math.max(0, Math.trunc(Number(opts && opts.printPhysicalQty) || 0))
      : Math.max(0, Math.trunc(Number(o.qty) || 0));
    const scheduled = Math.min(
      qty,
      Math.max(0, Math.trunc(Number(o.scheduledQty) || 0)),
    );
    const done = Math.min(qty, Math.max(0, Math.trunc(Number(o.done) || 0)));
    const packed = Math.max(0, Math.trunc(Number(o.packed) || 0));
    return {
      qty: qty,
      scheduled: scheduled,
      done: done,
      packed: packed,
      unassigned: Math.max(0, qty - scheduled),
      remainingScheduled: Math.max(0, scheduled - done),
      remainingTotal: Math.max(0, qty - done),
      invalid:
        scheduled > qty || done > qty || done > scheduled || packed > done,
      unknownQty: live
        ? Math.max(0, Number(opts && opts.unknownPhysicalQty) || 0)
        : 0,
      qtyUnverified: false,
    };
  }

  function scheduleLeadLabel(o, q) {
    const snap = q || productionQtySnapshot(o, { live: true });
    if (snap.qtyUnverified) {
      return "Qty belum terverifikasi";
    }
    const m = String(o.ship || "").match(/(\d{1,2}) Nov 2026/);
    if (!m) return "Belum ada target";
    const n = Number(m[1]) - 9;
    if (snap.remainingTotal == null) return "Qty belum terverifikasi";
    if (!snap.remainingTotal) return "Selesai";
    if (n < 0) return "Terlambat " + Math.abs(n) + " hari";
    if (n === 0) return "Hari ini";
    if (n === 1) return "Besok";
    return n + " hari lagi";
  }

  function scheduleOverviewSum(rows, productionQtyFor, leadFor) {
    const unique = [];
    const seen = {};
    (rows || []).forEach(function (o) {
      const id = o && o.id;
      if (!id || seen[id]) return;
      seen[id] = true;
      unique.push(o);
    });
    const sum = {
      qty: 0,
      scheduled: 0,
      done: 0,
      remainingTotal: 0,
      unassigned: 0,
      remainingScheduled: 0,
      unknownQty: 0,
      unverifiedPoCount: 0,
      invalid: 0,
      deadline: 0,
      cells: [],
    };
    unique.forEach(function (o) {
      const q = productionQtyFor(o);
      if (q.qtyUnverified) {
        sum.unverifiedPoCount += 1;
        sum.unknownQty += q.unknownQty || 1;
      } else {
        sum.qty += q.qty || 0;
        sum.scheduled += q.scheduled || 0;
        sum.done += q.done || 0;
        sum.remainingTotal += q.remainingTotal || 0;
        sum.unassigned += q.unassigned || 0;
        sum.remainingScheduled += q.remainingScheduled || 0;
        sum.unknownQty += q.unknownQty || 0;
      }
      if (q.invalid) sum.invalid += 1;
      const lead = leadFor(o);
      if (
        lead === "Hari ini" ||
        lead === "Besok" ||
        String(lead).indexOf("Terlambat") === 0
      ) {
        sum.deadline += 1;
      }
    });
    const qtyLabel = sum.unverifiedPoCount
      ? "Total Qty Cetak (terverifikasi)"
      : "Total Qty Cetak";
    sum.cells = [
      [qtyLabel, sum.qty],
      ["Qty Terjadwal", sum.scheduled],
      ["Sudah Dicetak", sum.done],
      ["Belum Dicetak", sum.remainingTotal],
      ["Sisa Terjadwal", sum.remainingScheduled],
      ["Belum Dijadwalkan", sum.unassigned],
    ];
    if (sum.unverifiedPoCount) {
      sum.cells.push(["PO Qty belum terverifikasi", sum.unverifiedPoCount]);
    } else if (sum.unknownQty) {
      sum.cells.push(["Qty Proses Belum Terverifikasi", sum.unknownQty]);
    }
    return sum;
  }

  function escapeAttr(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inboxQtyCellHtml(o, escapeFn) {
    const esc = escapeFn || escapeAttr;
    const state = o.detailLoadState || "not_loaded";
    if (
      o.qtyVerified === true &&
      o.qty != null &&
      Number.isFinite(Number(o.qty))
    ) {
      return (
        '<b class="right">' + Number(o.qty).toLocaleString("id-ID") + "</b>"
      );
    }
    if (state === "loading") return '<span class="muted">Memuat…</span>';
    if (state === "failed") {
      const so = esc(o.id || "");
      return (
        '<span class="muted">Gagal memuat</span> <button type="button" class="btn sm" onclick="window.retryInboxDetail&&window.retryInboxDetail(\'' +
        so +
        "')\">Retry</button>"
      );
    }
    if (state === "loaded") {
      return '<span class="muted">Qty belum terverifikasi</span>';
    }
    return '<span class="muted">Belum dimuat</span>';
  }

  function scheduleDetailProgress(o) {
    if (isQtyUnverified(o)) {
      return { label: "UNKNOWN", pct: 0, unknown: true };
    }
    const qty = Number(o.qty);
    const done = Math.max(0, Math.trunc(Number(o.done) || 0));
    if (!Number.isFinite(qty) || qty <= 0) {
      return { label: "UNKNOWN", pct: 0, unknown: true };
    }
    const pct = Math.min(100, Math.round((100 * done) / qty));
    return {
      label:
        pct +
        "% · " +
        done.toLocaleString("id-ID") +
        " / " +
        qty.toLocaleString("id-ID") +
        " pcs",
      pct: pct,
      unknown: false,
    };
  }

  function fetchDetailDeduped(number, stores, requestFn, opts) {
    const force = !!(opts && opts.force);
    if (force) {
      delete stores.cache[number];
    } else if (stores.cache[number] !== undefined) {
      return Promise.resolve(stores.cache[number]);
    }
    if (Object.prototype.hasOwnProperty.call(stores.inflight, number)) {
      return stores.inflight[number];
    }
    const pending = requestFn()
      .then(function (detail) {
        stores.cache[number] = detail;
        delete stores.inflight[number];
        return detail;
      })
      .catch(function (err) {
        delete stores.inflight[number];
        delete stores.cache[number];
        throw err;
      });
    stores.inflight[number] = pending;
    return pending;
  }

  function shouldApplyDetail(enrichGeneration, startedGeneration, present) {
    return enrichGeneration === startedGeneration && !!present;
  }

  global.V3QtyIntegrity = {
    isQtyUnverified: isQtyUnverified,
    productionQtySnapshot: productionQtySnapshot,
    scheduleLeadLabel: scheduleLeadLabel,
    scheduleOverviewSum: scheduleOverviewSum,
    escapeAttr: escapeAttr,
    inboxQtyCellHtml: inboxQtyCellHtml,
    scheduleDetailProgress: scheduleDetailProgress,
    fetchDetailDeduped: fetchDetailDeduped,
    shouldApplyDetail: shouldApplyDetail,
  };
})(typeof window !== "undefined" ? window : globalThis);
