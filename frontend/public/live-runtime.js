/* V49 live runtime — Accurate inbox + contextual Production V3 API wiring.
 * Server is authority. No fabricated transaction success. No auto job-create on view.
 */
(function () {
  "use strict";
  const API = (window.V3_API_BASE || "/api/v1").replace(/\/$/, "");
  const TOKEN_KEY = "epv3_access_token";

  if (!document.getElementById("v3-live-style")) {
    const style = document.createElement("style");
    style.id = "v3-live-style";
    style.textContent =
      ".v3-inbox-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:0 0 10px;padding:8px 10px;background:#fff;border:1px solid #dfe7e9;border-radius:8px}" +
      ".v3-inbox-tools label{font-size:11px;display:flex;flex-direction:column;gap:4px}" +
      ".v3-actions-grid{display:grid;gap:12px}" +
      ".v3-section{border:1px solid #dce6e8;border-radius:8px;padding:10px;background:#fafcfc}" +
      ".v3-section h3{margin:0 0 8px;font-size:13px}" +
      ".v3-section label{display:flex;flex-direction:column;gap:3px;font-size:11px;margin:0 0 6px}" +
      ".v3-section .btn{margin:2px 4px 2px 0}" +
      ".v3-hist{margin-top:8px;font-size:11px}" +
      ".v3-hist-body{max-height:140px;overflow:auto;margin-top:6px}" +
      ".v3-open-wf{white-space:nowrap}";
    document.head.appendChild(style);
  }

  let fetchError = "Koneksi Accurate belum tersedia";
  let lastSync = null;
  let loading = false;
  let authStatus = "pending"; // pending | ok | failed — JWT must be verified by Backend V3
  let inboxPage = 1;
  let inboxKeyword = "";
  let inboxTotal = null; // Accurate total — never use as current-page KPI
  let inboxPageSize = 50;
  let selectedSo = null;
  let boardCache = Object.create(null); // so -> board
  let jobCache = Object.create(null); // so -> job summary
  const inFlight = new Set();

  /** Publish inbox rows to the shared global used by production.html (var orders). */
  function publishOrders(list) {
    const rows = Array.isArray(list) ? list : [];
    window.orders = rows;
    // Keep metadata for KPI vs Accurate total separation.
    window.__V3_INBOX__ = {
      page: inboxPage,
      pageSize: inboxPageSize,
      total: inboxTotal,
      rowCount: rows.length,
      mode: fetchError ? "error" : "live",
      fetchError: fetchError || "",
      shared: window.orders === rows,
    };
    return rows;
  }

  function redirectToLogin() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch (_) {}
    authStatus = "failed";
    window.__V3_AUTH__ = { status: "failed" };
    document.documentElement.classList.remove("v3-auth-pending", "v3-auth-ok");
    document.documentElement.classList.add("v3-auth-failed");
    window.location.replace("/");
  }

  function markAuthOk(me) {
    authStatus = "ok";
    window.__V3_AUTH__ = {
      status: "ok",
      username: me && me.username ? String(me.username) : null,
      role: me && me.role ? String(me.role) : null,
    };
    document.documentElement.classList.remove("v3-auth-pending", "v3-auth-failed");
    document.documentElement.classList.add("v3-auth-ok");
  }

  async function verifySession() {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    if (!String(token).trim()) {
      redirectToLogin();
      return false;
    }
    try {
      const response = await fetch(API + "/auth/me", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: authHeaders(),
      });
      if (!response.ok) {
        // Invalid/expired JWT or unverifiable session → login only.
        redirectToLogin();
        return false;
      }
      const me = await response.json();
      markAuthOk(me);
      return true;
    } catch (_) {
      redirectToLogin();
      return false;
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function authHeaders() {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    return headers;
  }

  function idemKey(prefix) {
    return (
      String(prefix || "v3") +
      "-" +
      Date.now().toString(36) +
      "-" +
      Math.random().toString(36).slice(2, 10)
    );
  }

  function toast(msg) {
    if (typeof window.toast === "function") window.toast(msg);
    else window.alert(msg);
  }

  function clearGhosts() {
    window.queueDemoSave = function () {};
    window.pushDemoSave = function () {};
    // Never present fixture/demo rows as Accurate Live.
    publishOrders([]);
    window.taskEntries = {};
    const block = function () {
      toast("Aksi demo dinonaktifkan — gunakan panel V3 pada SO terpilih");
      return false;
    };
    [
      "resetDemo",
      "v36SimulateReceipt",
      "v26Reset",
      "bootDemo",
    ].forEach(function (name) {
      if (typeof window[name] === "function") {
        const original = window[name];
        window[name] = function () {
          if (name === "bootDemo") {
            publishOrders([]);
            return;
          }
          return block();
        };
        window[name]._v3Original = original;
      }
    });
  }
  clearGhosts();

  function mapOrder(s) {
    // Accurate SO number: prefer explicit number; V3 inbox still may send po_number as SO key.
    const number = String(s.number || s.po_number || "").trim();
    if (!number) return null;
    const lines = Array.isArray(s.line_items) ? s.line_items : [];
    const qtyVerified =
      s.total_quantity != null ||
      (lines.length > 0 &&
        lines.every((x) => x.quantity != null || x.qty != null));
    let qty = null;
    if (s.total_quantity != null && Number.isFinite(Number(s.total_quantity))) {
      qty = Number(s.total_quantity);
    } else if (lines.length) {
      qty = lines.reduce(function (sum, x) {
        const n = Number(x.quantity != null ? x.quantity : x.qty);
        return sum + (Number.isFinite(n) ? n : 0);
      }, 0);
    }
    const productionStatus =
      s.production_status === "Terproses" ? "Terproses" : "Baru";
    const branchLabel =
      s.branch_name ||
      s.outlet ||
      (s.branch && s.branch.name) ||
      null;
    const salesOfficial =
      s.sales != null && String(s.sales).trim() ? String(s.sales).trim() : null;
    return {
      id: number,
      accurateId: s.accurate_id ?? null,
      name: s.customer || "Perlu verifikasi",
      item:
        lines.map((x) => x.name || x.item_code).filter(Boolean).join(" + ") ||
        "Detail barang belum dimuat",
      itemCodes: lines
        .map(function (x) {
          return x.item_code;
        })
        .filter(Boolean)
        .join(" · "),
      itemProcesses: lines
        .map(function (x) {
          return x.production_process === "print"
            ? "Cetak"
            : x.production_process === "non_print"
              ? "Tidak Cetak"
              : "Unknown";
        })
        .join(" · "),
      itemUnits: lines
        .map(function (x) {
          return x.unit || "";
        })
        .filter(Boolean)
        .join(" · "),
      qty: qtyVerified ? qty : null,
      qtyVerified: Boolean(qtyVerified),
      detailLoaded: Boolean(lines.length),
      lineCount: s.line_count != null ? Number(s.line_count) : lines.length || null,
      sourceLines: lines.map(function (x) {
        return {
          id: x.accurate_line_id || x.id || null,
          itemId: x.accurate_item_id || null,
          item_code: x.item_code || null,
          name: x.name || null,
          qty: x.quantity != null ? x.quantity : x.qty,
          unit: x.unit || null,
          color: x.color || null,
          notes: x.notes || null,
          production_process:
            x.production_process === "print" || x.production_process === "non_print"
              ? x.production_process
              : "unknown",
          // Official process snapshot — never invent PRINT from blank/unknown.
          processSnapshot:
            x.production_process === "print"
              ? "PRINT"
              : x.production_process === "non_print"
                ? "NON_PRINT"
                : "UNKNOWN",
        };
      }),
      status: productionStatus === "Terproses" ? "Terproses" : "PO Masuk",
      // Keep inbox until V3 schedule assignments exist — do not invent "run" from Terproses alone.
      stage: "inbox",
      productionStatus,
      branch: branchLabel || "Belum terverifikasi",
      branchId: s.branch_id || null,
      salesName: salesOfficial || "Belum terverifikasi",
      salesSource: s.sales_source || null,
      salesMissingReason: salesOfficial
        ? null
        : "accurate_sales_field_absent",
      createdByUser: s.created_by_user || null,
      orderDate: s.order_date || null,
      address: s.address || null,
      paymentTerms: s.payment_terms || null,
      expedition: s.expedition || null,
      deliveryZone: s.delivery_zone || null,
      poNotes: s.notes || null,
      orderPriority:
        s.urgent_state === "approved_urgent" || s.urgent_state === "legacy_urgent"
          ? "Urgent"
          : s.urgent_state === "normal"
            ? "Normal"
            : "Belum terverifikasi",
      bufferLabel:
        s.buffer_stock === true
          ? "Buffer"
          : s.buffer_stock === false
            ? "Non-Buffer"
            : "Belum terverifikasi",
      ship: s.deadline || s.estimated_delivery || null,
      scheduleDate: "",
      machine: "",
      operator: "",
      done: 0,
      packed: 0,
      receipt: "Belum terverifikasi",
      sj: "",
      updated: "",
      approval: false,
      inkColors: lines
        .map(function (x) {
          return x.color;
        })
        .filter(Boolean),
      // Slice 1A: unknown Accurate mapping → null/unknown, never invent false.
      urgent: null,
      urgentState: s.urgent_state == null ? null : String(s.urgent_state),
      bufferStock: s.buffer_stock === true ? true : s.buffer_stock === false ? false : null,
      bufferQty: null,
      scheduledQty: 0,
      productionAssignments: [],
      processKind: (function () {
        const processes = Array.from(
          new Set(
            lines.map(function (x) {
              return x.production_process === "print" || x.production_process === "non_print"
                ? x.production_process
                : "unknown";
            }),
          ),
        );
        if (processes.length === 1 && processes[0] === "print") return "PRINT";
        if (processes.length === 1 && processes[0] === "non_print") return "NON_PRINT";
        if (processes.indexOf("print") >= 0 && processes.indexOf("non_print") >= 0)
          return "MIXED";
        return "UNKNOWN";
      })(),
      v3JobId: null,
      design_status: null,
      payment_status: null,
      sample_status: null,
      delivery: {
        sjNumber: "",
        shipDate: "",
        shipTime: "",
        receiver: "",
        phone: "",
        address: "",
        zone: "",
        driver: "",
        vehicle: "",
        plate: "",
        sjQty: 0,
        loadedQty: 0,
        deliveredQty: 0,
        status: "Belum diverifikasi",
        proof: "Belum tersedia",
        receivedAt: "",
        notes: "",
        syncAt: "—",
      },
    };
  }

  async function request(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, authHeaders(), opts.headers || {});
    if (opts.body != null) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: headers,
      cache: "no-store",
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
    });
    if (response.status === 401) {
      redirectToLogin();
      throw new Error("Sesi V3 tidak valid — login ulang");
    }
    if (response.status === 403) {
      throw new Error("Akses ditolak (izin/cabang)");
    }
    if (!response.ok) {
      let detail = "";
      try {
        const errBody = await response.json();
        detail =
          (errBody && errBody.error && errBody.error.message) ||
          (typeof errBody.detail === "string" ? errBody.detail : "") ||
          "";
      } catch (_) {}
      if (response.status === 503) {
        throw new Error("Gateway Accurate belum siap / tidak berwenang");
      }
      throw new Error(detail || "API V3 HTTP " + response.status);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function orderBySo(so) {
    return (window.orders || []).find((x) => x.id === so) || null;
  }

  const detailCache = Object.create(null);
  let enrichGeneration = 0;
  const ENRICH_CONCURRENCY = 3; // bounded — never fire 50 detail calls unbounded

  function processLabel(process) {
    if (process === "print") return "Cetak";
    if (process === "non_print") return "Tidak Cetak";
    return "Unknown";
  }

  function applyDetailToOrder(number, detail) {
    const o = orderBySo(number);
    if (!o || !detail) return o;
    const lines = Array.isArray(detail.line_items) ? detail.line_items : [];
    o.sourceLines = lines.map(function (x) {
      return {
        id: x.accurate_line_id || x.id || null,
        itemId: x.accurate_item_id || null,
        item_code: x.item_code || null,
        name: x.name || null,
        qty: x.quantity != null ? x.quantity : x.qty,
        unit: x.unit || null,
        color: x.color || null,
        notes: x.notes || null,
        production_process:
          x.production_process === "print" || x.production_process === "non_print"
            ? x.production_process
            : "unknown",
        processSnapshot:
          x.production_process === "print"
            ? "PRINT"
            : x.production_process === "non_print"
              ? "NON_PRINT"
              : "UNKNOWN",
      };
    });
    o.item =
      o.sourceLines
        .map(function (x) {
          return x.name || x.item_code;
        })
        .filter(Boolean)
        .join(" + ") || "Tidak ada baris barang";
    if (detail.total_quantity != null && Number.isFinite(Number(detail.total_quantity))) {
      o.qty = Number(detail.total_quantity);
      o.qtyVerified = true;
    } else if (o.sourceLines.length) {
      o.qty = o.sourceLines.reduce(function (sum, x) {
        const n = Number(x.qty);
        return sum + (Number.isFinite(n) ? n : 0);
      }, 0);
      o.qtyVerified = true;
    }
    o.lineCount =
      detail.line_count != null ? Number(detail.line_count) : o.sourceLines.length;
    o.detailLoaded = true;
    if (detail.branch_name || detail.outlet) {
      o.branch = detail.branch_name || detail.outlet;
    }
    if (detail.branch_id) o.branchId = detail.branch_id;
    if (detail.sales != null && String(detail.sales).trim()) {
      o.salesName = String(detail.sales).trim();
      o.salesSource = detail.sales_source || o.salesSource || "detail";
      o.salesMissingReason = null;
    } else if (
      !o.salesName ||
      o.salesName === "Belum terverifikasi"
    ) {
      // Never fall back to creator / branch / login; never wipe a verified list sales.
      o.salesName = "Belum terverifikasi";
      o.salesSource = detail.sales_source || o.salesSource || null;
      o.salesMissingReason = "accurate_sales_field_absent";
    }
    if (detail.created_by_user) o.createdByUser = detail.created_by_user;
    if (detail.order_date) o.orderDate = detail.order_date;
    if (detail.address) o.address = detail.address;
    if (detail.payment_terms) o.paymentTerms = detail.payment_terms;
    if (detail.expedition) o.expedition = detail.expedition;
    if (detail.delivery_zone) o.deliveryZone = detail.delivery_zone;
    if (detail.notes) o.poNotes = detail.notes;
    o.ship = detail.deadline || detail.estimated_delivery || o.ship || null;
    if (
      detail.urgent_state === "approved_urgent" ||
      detail.urgent_state === "legacy_urgent"
    ) {
      o.orderPriority = "Urgent";
      o.urgentState = String(detail.urgent_state);
    } else if (detail.urgent_state === "normal") {
      o.orderPriority = "Normal";
      o.urgentState = "normal";
    } else if (!o.orderPriority) {
      o.orderPriority = "Belum terverifikasi";
    }
    if (detail.buffer_stock === true) {
      o.bufferLabel = "Buffer";
      o.bufferStock = true;
    } else if (detail.buffer_stock === false) {
      o.bufferLabel = "Non-Buffer";
      o.bufferStock = false;
    } else if (!o.bufferLabel) {
      o.bufferLabel = "Belum terverifikasi";
    }
    o.itemCodes = o.sourceLines
      .map(function (x) {
        return x.item_code;
      })
      .filter(Boolean)
      .join(" · ");
    o.itemProcesses = o.sourceLines
      .map(function (x) {
        return processLabel(x.production_process);
      })
      .join(" · ");
    o.itemUnits = o.sourceLines
      .map(function (x) {
        return x.unit || "";
      })
      .filter(Boolean)
      .join(" · ");
    o.inkColors = o.sourceLines
      .map(function (x) {
        return x.color;
      })
      .filter(Boolean);
    const processes = Array.from(
      new Set(
        o.sourceLines.map(function (x) {
          return x.production_process;
        }),
      ),
    );
    if (processes.length === 1 && processes[0] === "print") o.processKind = "PRINT";
    else if (processes.length === 1 && processes[0] === "non_print")
      o.processKind = "NON_PRINT";
    else if (processes.indexOf("print") >= 0 && processes.indexOf("non_print") >= 0)
      o.processKind = "MIXED";
    else o.processKind = "UNKNOWN";
    return o;
  }

  async function fetchOrderDetail(number) {
    if (detailCache[number]) return detailCache[number];
    const detail = await request(
      API + "/production/orders/" + encodeURIComponent(number),
    );
    detailCache[number] = detail;
    return detail;
  }

  async function enrichInboxPage(numbers) {
    const gen = ++enrichGeneration;
    const queue = (numbers || []).filter(Boolean).slice();
    async function worker() {
      while (queue.length && gen === enrichGeneration) {
        const so = queue.shift();
        try {
          const detail = await fetchOrderDetail(so);
          if (gen !== enrichGeneration) return;
          applyDetailToOrder(so, detail);
          if (typeof window.render === "function") window.render();
        } catch (_) {
          // Leave row as "belum dimuat" — never invent fixture data.
        }
      }
    }
    const n = Math.min(ENRICH_CONCURRENCY, Math.max(1, queue.length));
    const runners = [];
    for (let i = 0; i < n; i += 1) runners.push(worker());
    await Promise.all(runners);
  }

  // Prefer Accurate sales field; never invent demo salesperson names.
  window.sampleSalesName = function (o) {
    if (o && o.salesName && o.salesName !== "Belum terverifikasi") return o.salesName;
    return "Belum terverifikasi";
  };
  window.sampleColorEntries = function (o) {
    if (o && Array.isArray(o.inkColors) && o.inkColors.length) {
      return o.inkColors.map(function (name, i) {
        return { order: i + 1, name: name };
      });
    }
    return [];
  };

  function syncOrderGatesFromJob(o, job) {
    if (!o || !job) return;
    o.v3JobId = job.id;
    o.design_status = job.design_status;
    o.payment_status = job.payment_status;
    o.sample_status = job.sample_status;
    o.productionStatus = job.processing_status || o.productionStatus;
    const designOk =
      job.design_status === "approved" || job.design_status === "bypassed";
    const paymentOk =
      job.payment_status === "approved" || job.payment_status === "bypassed";
    o.approval = designOk && paymentOk;
    // Mirror into demo gateState for shared UI helpers — values come from V3 job only.
    if (typeof window.gateFor === "function") {
      const g = window.gateFor(o);
      g.design = designOk
        ? job.design_status === "bypassed"
          ? "BYPASSED"
          : "APPROVED"
        : "PENDING";
      g.payment = paymentOk
        ? job.payment_status === "bypassed"
          ? "BYPASSED"
          : "APPROVED"
        : "PENDING";
    }
  }

  async function lookupJob(so) {
    try {
      const job = await request(
        API + "/production/jobs/by-so/" + encodeURIComponent(so),
      );
      jobCache[so] = job;
      const o = orderBySo(so);
      if (o) syncOrderGatesFromJob(o, job);
      return job;
    } catch (err) {
      if (String(err.message || "").includes("belum dibuat") || String(err.message || "").includes("404")) {
        delete jobCache[so];
        return null;
      }
      throw err;
    }
  }

  async function createJob(order) {
    if (!order || !order.id) throw new Error("SO tidak valid");
    const branchId =
      (order.branchId && String(order.branchId).trim()) ||
      (order.branch_id && String(order.branch_id).trim()) ||
      null;
    if (!branchId) throw new Error("Cabang SO belum terverifikasi dari Accurate");
    const lineItems = (order.sourceLines || [])
      .filter((x) => x && x.id)
      .map((x) => ({
        accurate_line_id: String(x.id),
        accurate_item_id: x.itemId != null ? String(x.itemId) : null,
        quantity: x.qty,
        production_process:
          x.production_process === "print" || x.production_process === "non_print"
            ? x.production_process
            : "unknown",
      }));
    const job = await request(API + "/production/jobs", {
      method: "POST",
      body: {
        accurate_so_number: order.id,
        branch_id: branchId,
        accurate_id: order.accurateId != null ? String(order.accurateId) : null,
        customer_name: order.name || null,
        buffer_stock: order.bufferStock === true || order.bufferStock === false ? order.bufferStock : null,
        urgent_state: order.urgentState || null,
        line_items: lineItems.length ? lineItems : null,
      },
    });
    jobCache[order.id] = job;
    syncOrderGatesFromJob(order, job);
    order.bufferStock =
      job.buffer_stock === true ? true : job.buffer_stock === false ? false : null;
    order.urgentState = job.urgent_state == null ? null : String(job.urgent_state);
    order.urgent =
      order.urgentState === "approved_urgent" || order.urgentState === "legacy_urgent"
        ? true
        : order.urgentState
          ? false
          : null;
    return job;
  }

  function applyBoardToOrder(so, board) {
    const o = orderBySo(so);
    if (!o || !board) return;
    if (board.job) syncOrderGatesFromJob(o, board.job);
    const assignments = Array.isArray(board.assignments) ? board.assignments : [];
    // Canonical V3 assignments only — never invent demo operators for live.
    o.productionAssignments = assignments
      .filter(function (a) {
        return a && a.status !== "cancelled_remaining";
      })
      .map(function (a) {
        return {
          id: String(a.id),
          soLineId: String(a.so_line_id || ""),
          lineId: String(a.so_line_id || ""),
          colorIndex: Number(a.color_pass) || 1,
          colorName: "Warna " + (Number(a.color_pass) || 1),
          operator: String(a.operator_name || ""),
          machine: String(a.machine_name || ""),
          workDate: String(a.work_date || ""),
          targetQty: Number(a.qty_planned) || 0,
          completedQty:
            a.qty_confirmed != null && Number.isFinite(Number(a.qty_confirmed))
              ? Number(a.qty_confirmed)
              : null,
        };
      });
    // Effective scheduled qty = min coverage of color_pass 1 per print line (physical cups).
    const byLine = Object.create(null);
    o.productionAssignments.forEach(function (a) {
      const key = a.soLineId || "_";
      if (!byLine[key]) byLine[key] = Object.create(null);
      const pass = a.colorIndex || 1;
      byLine[key][pass] = (byLine[key][pass] || 0) + (Number(a.targetQty) || 0);
    });
    let scheduled = 0;
    Object.keys(byLine).forEach(function (lineId) {
      const passes = byLine[lineId];
      const pass1 = passes[1];
      if (pass1 != null) scheduled += pass1;
      else {
        const vals = Object.keys(passes).map(function (k) {
          return passes[k];
        });
        if (vals.length) scheduled += Math.min.apply(null, vals);
      }
    });
    o.scheduledQty = scheduled;
    if (o.productionAssignments.length) {
      const first = o.productionAssignments[0];
      o.operator = first.operator;
      o.machine = first.machine;
      o.scheduleDate = first.workDate || o.scheduleDate;
      if (o.stage === "inbox") {
        o.stage = "schedule";
        o.status = "Dijadwalkan";
      }
    }
  }

  async function loadBoard(so, force) {
    let job = jobCache[so];
    if (!job) job = await lookupJob(so);
    if (!job) return null;
    if (!force && boardCache[so]) return boardCache[so];
    const board = await request(API + "/production/jobs/" + job.id + "/board");
    boardCache[so] = board;
    jobCache[so] = board.job;
    applyBoardToOrder(so, board);
    return board;
  }

  async function mutate(lockKey, fn) {
    if (inFlight.has(lockKey)) {
      toast("Transaksi masih diproses — tunggu selesai");
      return null;
    }
    inFlight.add(lockKey);
    try {
      const result = await fn();
      if (selectedSo) {
        delete boardCache[selectedSo];
        await loadBoard(selectedSo, true);
        renderWorkflowDrawer(selectedSo);
      }
      if (typeof window.render === "function") window.render();
      return result;
    } catch (err) {
      toast(err.message || "Transaksi gagal");
      throw err;
    } finally {
      inFlight.delete(lockKey);
    }
  }

  function requireJob(so) {
    const job = jobCache[so];
    if (!job) throw new Error("Buat job V3 terlebih dahulu (tombol Mulai Proses V3)");
    return job;
  }

  function field(id) {
    const el = document.getElementById(id);
    return el ? String(el.value || "").trim() : "";
  }

  function firstLineId(order) {
    const line = (order.sourceLines || [])[0];
    return line && line.id ? String(line.id) : "line-1";
  }

  function historyList(title, rowsHtml) {
    return (
      '<details class="v3-hist"><summary>' +
      escapeHtml(title) +
      "</summary><div class=\"v3-hist-body\">" +
      (rowsHtml || "<p>Tidak ada riwayat</p>") +
      "</div></details>"
    );
  }

  function renderWorkflowDrawer(so) {
    selectedSo = so;
    const order = orderBySo(so);
    const modal = document.getElementById("modal");
    if (!modal || !order) return;
    const board = boardCache[so];
    const job = jobCache[so] || (board && board.job) || null;
    const designs = (board && board.design_versions) || [];
    const receipts = (board && board.payment_receipts) || [];
    const bypasses = (board && board.payment_bypasses) || [];
    const assignments = (board && board.assignments) || [];
    const samples = (board && board.samples) || [];
    const prepStates = (board && board.prep_states) || [];
    const events = (board && board.events) || [];
    const pendingDesign = designs.find((d) => d.status === "pending");
    const activeBypass = bypasses.find((b) => b.active);
    const pendingSample = samples.find((s) => s.status === "pending");

    const designHist = designs
      .map(
        (d) =>
          "<div>v" +
          escapeHtml(d.version_no) +
          " #" +
          escapeHtml(d.id) +
          " · " +
          escapeHtml(d.file_name) +
          " · <b>" +
          escapeHtml(d.status) +
          "</b></div>",
      )
      .join("");
    const payHist =
      receipts
        .map(
          (r) =>
            "<div>Receipt #" +
            escapeHtml(r.id) +
            " · " +
            escapeHtml(r.accurate_receipt_id) +
            " · <b>" +
            escapeHtml(r.status) +
            "</b></div>",
        )
        .join("") +
      bypasses
        .map(
          (b) =>
            "<div>Bypass #" +
            escapeHtml(b.id) +
            " · " +
            (b.active ? "aktif" : "dicabut") +
            " · " +
            escapeHtml(b.reason || "") +
            "</div>",
        )
        .join("");
    const asgHist = assignments
      .map(
        (a) =>
          "<div>#" +
          escapeHtml(a.id) +
          " · " +
          escapeHtml(a.operator_name) +
          " / " +
          escapeHtml(a.machine_name) +
          " · pass " +
          escapeHtml(a.color_pass) +
          " · " +
          escapeHtml(a.qty_confirmed) +
          "/" +
          escapeHtml(a.qty_planned) +
          " · <b>" +
          escapeHtml(a.status) +
          "</b></div>",
      )
      .join("");
    const prepHist = prepStates
      .map(
        (p) =>
          "<div>" +
          escapeHtml(p.role) +
          " · line " +
          escapeHtml(p.so_line_id) +
          " · qty " +
          escapeHtml(p.qty) +
          " · " +
          escapeHtml(p.evidence_ref || "") +
          "</div>",
      )
      .join("");
    const sampleHist = samples
      .map(
        (s) =>
          "<div>v" +
          escapeHtml(s.version_no) +
          " #" +
          escapeHtml(s.id) +
          " · " +
          escapeHtml(s.file_name) +
          " · <b>" +
          escapeHtml(s.status) +
          "</b></div>",
      )
      .join("");
    const eventHist = events
      .slice()
      .reverse()
      .slice(0, 40)
      .map(
        (e) =>
          "<div>#" +
          escapeHtml(e.id) +
          " · " +
          escapeHtml(e.event_type) +
          " · qty " +
          escapeHtml(e.qty_physical == null ? "—" : e.qty_physical) +
          (e.accurate_sj_number
            ? " · SJ " + escapeHtml(e.accurate_sj_number)
            : "") +
          "</div>",
      )
      .join("");

    const disabledNote = !job
      ? '<p class="v49-quiet">Job V3 belum ada. Gunakan <b>Mulai Proses V3</b> (eksplisit) sebelum transaksi.</p>'
      : "";

    modal.innerHTML =
      '<div class="drawerback"><aside class="detaildrawer shipping-drawer" role="dialog" aria-modal="true" data-v3-so="' +
      escapeHtml(so) +
      '"><div class="drawerhead"><h2>V3 Workflow · ' +
      escapeHtml(so) +
      '</h2><button type="button" class="btn sm" id="v3-close-drawer">✕ Tutup</button></div><div class="drawerbody v3-workflow-body">' +
      "<p><b>" +
      escapeHtml(order.name) +
      "</b> · Cabang " +
      escapeHtml(order.branch) +
      " · Qty SO " +
      escapeHtml(order.qty) +
      "</p>" +
      (job
        ? "<p>Job #<b>" +
          escapeHtml(job.id) +
          "</b> · Design <b>" +
          escapeHtml(job.design_status) +
          "</b> · Payment <b>" +
          escapeHtml(job.payment_status) +
          "</b> · Sample <b>" +
          escapeHtml(job.sample_status) +
          "</b> · Proses <b>" +
          escapeHtml(job.processing_status) +
          "</b></p>"
        : disabledNote) +
      (!job
        ? '<p><button type="button" class="btn" id="v3-create-job">Mulai Proses V3</button></p>'
        : "") +
      '<div class="v3-actions-grid">' +
      section(
        "Design",
        '<label>File<input id="v3-design-file" value="design.pdf"/></label>' +
          '<label>Storage key<input id="v3-design-key" value="designs/' +
          escapeHtml(so) +
          '.pdf"/></label>' +
          '<button type="button" class="btn sm" data-v3="design-upload">Upload versi</button>' +
          (pendingDesign
            ? '<button type="button" class="btn sm" data-v3="design-approve">Approve #' +
              escapeHtml(pendingDesign.id) +
              "</button>" +
              '<button type="button" class="btn sm" data-v3="design-reject">Reject</button>' +
              '<button type="button" class="btn sm" data-v3="design-customer">Customer approval</button>' +
              '<label>Bypass reason<input id="v3-design-bypass-reason"/></label>' +
              '<button type="button" class="btn sm" data-v3="design-bypass">Authorized bypass</button>'
            : "<p class=\"v49-quiet\">Tidak ada versi pending</p>") +
          historyList("Riwayat design", designHist),
      ) +
      section(
        "Payment",
        '<p class="v49-quiet" id="v3-evidence-note">Receipt/SJ membutuhkan verifikasi gateway Accurate bila enforce aktif. Bypass payment tetap berizin+audit.</p>' +
          '<label>Accurate receipt id<input id="v3-pay-rid"/></label>' +
          '<label>Amount<input id="v3-pay-amt" type="number" min="0" step="0.01"/></label>' +
          '<button type="button" class="btn sm" data-v3="pay-receipt">Catat receipt (verified)</button>' +
          '<label>Bypass reason<input id="v3-pay-bypass-reason"/></label>' +
          '<button type="button" class="btn sm" data-v3="pay-bypass">Bypass payment</button>' +
          (activeBypass
            ? '<button type="button" class="btn sm" data-v3="pay-revoke">Revoke bypass #' +
              escapeHtml(activeBypass.id) +
              "</button>"
            : "") +
          '<label>Invalidate receipt id<input id="v3-pay-inv-id" type="number" placeholder="receipt row id"/></label>' +
          '<label>Invalidate reason<input id="v3-pay-inv-reason" placeholder="alasan wajib"/></label>' +
          '<button type="button" class="btn sm" data-v3="pay-invalidate">Invalidate receipt</button>' +
          historyList("Riwayat payment + audit", payHist),
      ) +
      section(
        "Scheduling",
        '<label>SO line<input id="v3-asg-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>Operator<input id="v3-asg-op" value="Operator A"/></label>' +
          '<label>Machine<input id="v3-asg-mc" value="Semi Auto 01"/></label>' +
          '<label>Date<input id="v3-asg-date" type="date"/></label>' +
          '<label>Color pass<input id="v3-asg-pass" type="number" min="1" value="1"/></label>' +
          '<label>Qty planned<input id="v3-asg-qty" type="number" min="1" value="' +
          escapeHtml(order.qty || 1) +
          '"/></label>' +
          '<button type="button" class="btn sm" data-v3="asg-create">Buat assignment</button>' +
          '<label>Assignment id<input id="v3-asg-id" type="number"/></label>' +
          '<button type="button" class="btn sm" data-v3="asg-cancel">Cancel remaining</button>' +
          '<label>Transfer to operator<input id="v3-asg-top"/></label>' +
          '<label>Transfer machine<input id="v3-asg-tmc" value="Semi Auto 02"/></label>' +
          '<button type="button" class="btn sm" data-v3="asg-transfer">Transfer remaining</button>' +
          historyList("Riwayat assignment", asgHist),
      ) +
      section(
        "Screener & Helper",
        '<label>SO line<input id="v3-prep-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>PO qty ceiling<input id="v3-prep-po" type="number" value="' +
          escapeHtml(order.qty || 1) +
          '"/></label>' +
          '<label>Screen qty<input id="v3-prep-screen" type="number" value="1"/></label>' +
          '<label>Helper qty<input id="v3-prep-helper" type="number" value="' +
          escapeHtml(order.qty || 1) +
          '"/></label>' +
          '<label>Evidence<input id="v3-prep-ev" value="prep-evidence"/></label>' +
          '<button type="button" class="btn sm" data-v3="prep-screen">Simpan screener</button>' +
          '<button type="button" class="btn sm" data-v3="prep-helper">Simpan helper</button>' +
          historyList("Status prep", prepHist),
      ) +
      section(
        "Sample",
        '<label>File<input id="v3-sample-file" value="sample.jpg"/></label>' +
          '<label>Storage key<input id="v3-sample-key" value="samples/' +
          escapeHtml(so) +
          '.jpg"/></label>' +
          '<button type="button" class="btn sm" data-v3="sample-upload">Upload sample</button>' +
          (pendingSample
            ? '<button type="button" class="btn sm" data-v3="sample-approve">Approve #' +
              escapeHtml(pendingSample.id) +
              "</button>" +
              '<button type="button" class="btn sm" data-v3="sample-reject">Reject/revise</button>'
            : "<p class=\"v49-quiet\">Tidak ada sample pending</p>") +
          historyList("Riwayat sample", sampleHist),
      ) +
      section(
        "Operator output / reject",
        '<label>Assignment id<input id="v3-out-asg" type="number"/></label>' +
          '<label>Qty physical<input id="v3-out-qty" type="number" min="1" value="1"/></label>' +
          '<label>Color pass<input id="v3-out-pass" type="number" min="1" value="1"/></label>' +
          '<label>Lot<input id="v3-out-lot"/></label>' +
          '<button type="button" class="btn sm" data-v3="out-confirm">Confirm output</button>' +
          '<label>Source output event id<input id="v3-out-src" type="number"/></label>' +
          '<label>Correction delta<input id="v3-out-delta" type="number"/></label>' +
          '<label>Correction reason<input id="v3-out-creason"/></label>' +
          '<button type="button" class="btn sm" data-v3="out-correct">Correct output</button>' +
          '<label>Reject qty<input id="v3-rej-qty" type="number" min="1" value="1"/></label>' +
          '<label>Reject reason<input id="v3-rej-reason"/></label>' +
          '<button type="button" class="btn sm" data-v3="rej-record">Register reject</button>' +
          '<label>Reject event id<input id="v3-rej-id" type="number"/></label>' +
          '<button type="button" class="btn sm" data-v3="rej-verify">Verify reject</button>',
      ) +
      section(
        "Packing",
        '<label>SO line<input id="v3-pack-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>Qty<input id="v3-pack-qty" type="number" min="1" value="1"/></label>' +
          '<label>Lot<input id="v3-pack-lot"/></label>' +
          '<button type="button" class="btn sm" data-v3="pack">Confirm packing batch</button>',
      ) +
      section(
        "Delivery",
        '<label>Accurate SJ id<input id="v3-sj-id"/></label>' +
          '<label>Accurate SJ number<input id="v3-sj-no"/></label>' +
          '<label>Loading qty<input id="v3-load-qty" type="number" min="1" value="1"/></label>' +
          '<button type="button" class="btn sm" data-v3="load">Loading</button>' +
          '<label>POD qty<input id="v3-pod-qty" type="number" min="1" value="1"/></label>' +
          '<label>Receiver<input id="v3-pod-recv"/></label>' +
          '<label>Evidence<input id="v3-pod-ev" value="pod-photo"/></label>' +
          '<button type="button" class="btn sm" data-v3="pod">POD</button>' +
          '<label>Cancel SJ reason<input id="v3-sj-cancel-reason"/></label>' +
          '<button type="button" class="btn sm" data-v3="sj-cancel">Cancel/supersede SJ</button>' +
          '<p class="v49-quiet">SJ harus identitas Accurate resmi. Tanpa id/number, aksi ditolak server.</p>',
      ) +
      section(
        "Tracking",
        '<button type="button" class="btn sm" data-v3="track-refresh">Refresh timeline</button>' +
          historyList("Event ledger", eventHist),
      ) +
      section(
        "Payroll",
        '<label>Rate component (eligible)<select id="v3-rate-comp"><option value="one">one</option><option value="two">two</option><option value="three">three</option><option value="four">four</option><option value="screen">screen</option></select></label>' +
          '<label>Amount<input id="v3-rate-amt" type="number" min="0" step="0.01" value="20"/></label>' +
          '<label>Effective from<input id="v3-rate-from" type="date"/></label>' +
          '<button type="button" class="btn sm" data-v3="rate-set">Set rate</button>' +
          '<button type="button" class="btn sm" data-v3="rate-get">Lihat rates hari ini</button>' +
          '<label>Period start<input id="v3-pay-start" type="date"/></label>' +
          '<label>Period end<input id="v3-pay-end" type="date"/></label>' +
          '<button type="button" class="btn sm" data-v3="payroll-run">Hitung periode</button>' +
          '<pre id="v3-payroll-out" class="v49-quiet"></pre>' +
          '<p class="v49-quiet">Payroll hanya dari confirmed output server. daily/overtime <b>tidak</b> dihitung (attendance/OT belum ada; V1 parity unverified).</p>',
      ) +
      "</div></div></aside></div>";

    const today = new Date().toISOString().slice(0, 10);
    ["v3-asg-date", "v3-rate-from", "v3-pay-start", "v3-pay-end"].forEach(
      function (id) {
        const el = document.getElementById(id);
        if (el && !el.value) el.value = today;
      },
    );
    request(API + "/production/jobs/evidence/capability")
      .then(function (cap) {
        const note = document.getElementById("v3-evidence-note");
        if (!note) return;
        note.textContent =
          "Evidence: gateway " +
          (cap.gateway_configured ? "configured" : "NOT configured") +
          "; enforce=" +
          String(cap.enforce) +
          "; receipt_verify=" +
          String(cap.receipt_verify) +
          "; sj_verify=" +
          String(cap.sj_verify) +
          ". " +
          (cap.note || "");
      })
      .catch(function () {});
    const closeBtn = document.getElementById("v3-close-drawer");
    if (closeBtn) closeBtn.onclick = function () {
      selectedSo = null;
      modal.innerHTML = "";
    };
    const createBtn = document.getElementById("v3-create-job");
    if (createBtn) {
      createBtn.onclick = function () {
        mutate("create-" + so, async function () {
          await createJob(order);
          toast("Job V3 dibuat untuk " + so);
          await loadBoard(so, true);
        });
      };
    }
    modal.querySelectorAll("[data-v3]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        handleAction(btn.getAttribute("data-v3"), so, order);
      });
    });
  }

  function section(title, body) {
    return (
      '<section class="v3-section"><h3>' +
      escapeHtml(title) +
      "</h3>" +
      body +
      "</section>"
    );
  }

  async function handleAction(action, so, order) {
    const lock = action + ":" + so;
    await mutate(lock, async function () {
      const job = action === "track-refresh" || action.indexOf("rate") === 0 || action.indexOf("payroll") === 0
        ? jobCache[so]
        : requireJob(so);
      const jid = job && job.id;
      if (action === "design-upload") {
        await request(API + "/production/jobs/" + jid + "/design/versions", {
          method: "POST",
          body: {
            file_name: field("v3-design-file") || "design.pdf",
            storage_key: field("v3-design-key") || "designs/" + so + ".pdf",
          },
        });
        toast("Design version uploaded");
        return;
      }
      if (action.indexOf("design-") === 0 && action !== "design-upload") {
        const board = boardCache[so] || (await loadBoard(so, true));
        const pending = (board.design_versions || []).find((d) => d.status === "pending");
        if (!pending) throw new Error("Tidak ada design pending");
        const body = { decision: "approved", reason: null, bypass: false, customer_approval: false };
        if (action === "design-reject") body.decision = "rejected";
        if (action === "design-customer") body.customer_approval = true;
        if (action === "design-bypass") {
          body.bypass = true;
          body.reason = field("v3-design-bypass-reason");
          if (!body.reason) throw new Error("Alasan bypass wajib");
        }
        await request(
          API + "/production/jobs/design/versions/" + pending.id + "/decision",
          { method: "POST", body: body },
        );
        toast("Design decision tersimpan");
        return;
      }
      if (action === "pay-receipt") {
        const rid = field("v3-pay-rid");
        if (!rid) throw new Error("Accurate receipt id wajib");
        const amt = field("v3-pay-amt");
        await request(API + "/production/jobs/" + jid + "/payment/receipts", {
          method: "POST",
          body: {
            accurate_receipt_id: rid,
            amount: amt ? amt : null,
          },
        });
        toast("Receipt tercatat");
        return;
      }
      if (action === "pay-bypass") {
        const reason = field("v3-pay-bypass-reason");
        if (!reason) throw new Error("Alasan bypass wajib");
        await request(API + "/production/jobs/" + jid + "/payment/bypass", {
          method: "POST",
          body: { reason: reason },
        });
        toast("Payment bypass aktif");
        return;
      }
      if (action === "pay-revoke") {
        const board = boardCache[so] || (await loadBoard(so, true));
        const active = (board.payment_bypasses || []).find((b) => b.active);
        if (!active) throw new Error("Tidak ada bypass aktif");
        await request(
          API + "/production/jobs/payment/bypass/" + active.id + "/revoke",
          { method: "POST", body: { reason: "revoked from V3 panel" } },
        );
        toast("Bypass dicabut");
        return;
      }
      if (action === "pay-invalidate") {
        const rid = field("v3-pay-inv-id");
        const reason = field("v3-pay-inv-reason");
        if (!rid) throw new Error("Receipt id wajib");
        if (!reason || reason.length < 4) {
          throw new Error("Alasan invalidate wajib (min 4 karakter)");
        }
        if (
          !window.confirm(
            "Invalidate receipt #" +
              rid +
              "? Gate payment akan ditutup jika tidak ada evidence/bypass lain. Audit akan dicatat.",
          )
        ) {
          return;
        }
        await request(
          API + "/production/jobs/payment/receipts/" + rid + "/invalidate",
          { method: "POST", body: { reason: reason } },
        );
        toast("Receipt diinvalidasi + audit event");
        return;
      }
      if (action === "asg-create") {
        await request(API + "/production/jobs/" + jid + "/schedule/assignments", {
          method: "POST",
          body: {
            so_line_id: field("v3-asg-line") || firstLineId(order),
            color_pass: Number(field("v3-asg-pass") || 1),
            operator_name: field("v3-asg-op") || "Operator A",
            machine_name: field("v3-asg-mc") || "Semi Auto 01",
            work_date: field("v3-asg-date"),
            qty_planned: field("v3-asg-qty") || "1",
          },
        });
        toast("Assignment dibuat");
        return;
      }
      if (action === "asg-cancel") {
        const id = field("v3-asg-id");
        if (!id) throw new Error("Assignment id wajib");
        await request(
          API +
            "/production/jobs/schedule/assignments/" +
            id +
            "/cancel-remaining",
          { method: "POST", body: { reason: "cancel remaining from V3 panel" } },
        );
        toast("Sisa assignment dibatalkan");
        return;
      }
      if (action === "asg-transfer") {
        const id = field("v3-asg-id");
        if (!id) throw new Error("Assignment id wajib");
        await request(
          API +
            "/production/jobs/schedule/assignments/" +
            id +
            "/transfer-remaining",
          {
            method: "POST",
            body: {
              operator_name: field("v3-asg-top") || "Operator B",
              machine_name: field("v3-asg-tmc") || "Semi Auto 02",
              work_date: field("v3-asg-date"),
              reason: "transfer remaining from V3 panel",
            },
          },
        );
        toast("Sisa dipindahkan ke assignment baru");
        return;
      }
      if (action === "prep-screen" || action === "prep-helper") {
        const role = action === "prep-screen" ? "screener" : "helper";
        const path =
          API +
          "/production/jobs/" +
          jid +
          "/prep/" +
          (role === "screener" ? "screener" : "helper");
        await request(path, {
          method: "POST",
          body: {
            so_line_id: field("v3-prep-line") || firstLineId(order),
            qty: field(role === "screener" ? "v3-prep-screen" : "v3-prep-helper") || "1",
            po_qty: field("v3-prep-po") || String(order.qty || 1),
            evidence_ref: field("v3-prep-ev") || "prep-evidence",
            idempotency_key: idemKey("prep"),
            assignment_id: field("v3-asg-id") ? Number(field("v3-asg-id")) : null,
          },
        });
        toast("Prep " + role + " tersimpan");
        return;
      }
      if (action === "sample-upload") {
        await request(API + "/production/jobs/" + jid + "/samples", {
          method: "POST",
          body: {
            file_name: field("v3-sample-file") || "sample.jpg",
            storage_key: field("v3-sample-key") || "samples/" + so + ".jpg",
            assignment_id: field("v3-out-asg") ? Number(field("v3-out-asg")) : null,
          },
        });
        toast("Sample uploaded");
        return;
      }
      if (action === "sample-approve" || action === "sample-reject") {
        const board = boardCache[so] || (await loadBoard(so, true));
        const pending = (board.samples || []).find((s) => s.status === "pending");
        if (!pending) throw new Error("Tidak ada sample pending");
        await request(API + "/production/jobs/samples/" + pending.id + "/decision", {
          method: "POST",
          body: {
            decision: action === "sample-approve" ? "approved" : "revised",
            reason: action === "sample-approve" ? null : "revision requested",
          },
        });
        toast("Sample decision tersimpan");
        return;
      }
      if (action === "out-confirm") {
        const asg = field("v3-out-asg");
        if (!asg) throw new Error("Assignment id wajib");
        await request(API + "/production/jobs/" + jid + "/outputs", {
          method: "POST",
          body: {
            assignment_id: Number(asg),
            qty_physical: field("v3-out-qty") || "1",
            color_pass: Number(field("v3-out-pass") || 1),
            lot_code: field("v3-out-lot") || null,
            idempotency_key: idemKey("out"),
          },
        });
        toast("Output confirmed");
        return;
      }
      if (action === "out-correct") {
        const src = field("v3-out-src");
        const delta = field("v3-out-delta");
        const reason = field("v3-out-creason");
        if (!src || !delta || !reason) throw new Error("Source, delta, reason wajib");
        await request(API + "/production/jobs/" + jid + "/outputs/corrections", {
          method: "POST",
          body: {
            source_event_id: Number(src),
            qty_physical_delta: delta,
            reason: reason,
            idempotency_key: idemKey("corr"),
          },
        });
        toast("Correction event tersimpan");
        return;
      }
      if (action === "rej-record") {
        const asg = field("v3-out-asg");
        const reason = field("v3-rej-reason");
        if (!asg || !reason) throw new Error("Assignment dan alasan reject wajib");
        await request(API + "/production/jobs/" + jid + "/rejects", {
          method: "POST",
          body: {
            assignment_id: Number(asg),
            qty_physical: field("v3-rej-qty") || "1",
            color_pass: Number(field("v3-out-pass") || 1),
            lot_code: field("v3-out-lot") || null,
            reason: reason,
            idempotency_key: idemKey("rej"),
          },
        });
        toast("Reject tercatat");
        return;
      }
      if (action === "rej-verify") {
        const id = field("v3-rej-id");
        if (!id) throw new Error("Reject event id wajib");
        await request(API + "/production/jobs/rejects/" + id + "/verify", {
          method: "POST",
          body: { approved_qty: field("v3-rej-qty") || "1" },
        });
        toast("Reject verified");
        return;
      }
      if (action === "pack") {
        await request(API + "/production/jobs/" + jid + "/packing", {
          method: "POST",
          body: {
            so_line_id: field("v3-pack-line") || firstLineId(order),
            qty_physical: field("v3-pack-qty") || "1",
            lot_code: field("v3-pack-lot") || null,
            idempotency_key: idemKey("pack"),
          },
        });
        toast("Packing batch tersimpan");
        return;
      }
      if (action === "load") {
        const sjId = field("v3-sj-id");
        const sjNo = field("v3-sj-no");
        if (!sjId || !sjNo) throw new Error("Identitas SJ Accurate wajib");
        await request(API + "/production/jobs/" + jid + "/loading", {
          method: "POST",
          body: {
            accurate_sj_id: sjId,
            accurate_sj_number: sjNo,
            qty_physical: field("v3-load-qty") || "1",
            idempotency_key: idemKey("load"),
          },
        });
        toast("Loading tersimpan");
        return;
      }
      if (action === "pod") {
        const sjId = field("v3-sj-id");
        const recv = field("v3-pod-recv");
        const ev = field("v3-pod-ev");
        if (!sjId || !recv || !ev) throw new Error("SJ id, penerima, bukti wajib");
        await request(API + "/production/jobs/" + jid + "/pod", {
          method: "POST",
          body: {
            accurate_sj_id: sjId,
            qty_physical: field("v3-pod-qty") || "1",
            evidence_ref: ev,
            receiver_name: recv,
            idempotency_key: idemKey("pod"),
          },
        });
        toast("POD tersimpan");
        return;
      }
      if (action === "sj-cancel") {
        const sjId = field("v3-sj-id");
        const reason = field("v3-sj-cancel-reason");
        if (!sjId || !reason) throw new Error("SJ id dan alasan wajib");
        await request(API + "/production/jobs/" + jid + "/sj/cancel", {
          method: "POST",
          body: {
            accurate_sj_id: sjId,
            reason: reason,
            idempotency_key: idemKey("sjc"),
          },
        });
        toast("SJ cancelled/superseded (history preserved)");
        return;
      }
      if (action === "track-refresh") {
        await loadBoard(so, true);
        toast("Timeline di-refresh dari server");
        return;
      }
      if (action === "rate-set") {
        await request(API + "/production/payroll/rates", {
          method: "POST",
          body: {
            component: field("v3-rate-comp") || "one",
            amount: field("v3-rate-amt") || "0",
            effective_from: field("v3-rate-from"),
          },
        });
        toast("Rate tersimpan");
        return;
      }
      if (action === "rate-get") {
        const rates = await request(API + "/production/payroll/rates");
        const out = document.getElementById("v3-payroll-out");
        if (out) out.textContent = JSON.stringify(rates, null, 2);
        return;
      }
      if (action === "payroll-run") {
        const run = await request(API + "/production/payroll/runs", {
          method: "POST",
          body: {
            period_start: field("v3-pay-start"),
            period_end: field("v3-pay-end"),
            idempotency_key: idemKey("payrun"),
            branch_id:
              order.branch && order.branch !== "Belum terverifikasi"
                ? order.branch
                : null,
          },
        });
        const detail = await request(
          API + "/production/payroll/runs/" + run.id,
        );
        const out = document.getElementById("v3-payroll-out");
        if (out) out.textContent = JSON.stringify(detail, null, 2);
        toast("Payroll run #" + run.id);
        return;
      }
      throw new Error("Aksi tidak dikenali: " + action);
    }).catch(function () {
      /* toast already shown */
    });
  }

  window.v3OpenWorkflow = async function (so) {
    selectedSo = so;
    const order = orderBySo(so);
    if (!order) {
      toast("SO tidak ada di inbox halaman ini");
      return;
    }
    try {
      await lookupJob(so);
      if (jobCache[so]) await loadBoard(so, true);
    } catch (err) {
      toast(err.message || "Gagal memuat job");
    }
    renderWorkflowDrawer(so);
  };

  // Read-only PO detail — never creates a job.
  window.v49PODetail = async function (number) {
    const o = orderBySo(number);
    if (!o) return;
    selectedSo = number;
    const modal = document.getElementById("modal");
    modal.innerHTML =
      '<div class="drawerback"><aside class="detaildrawer shipping-drawer" role="dialog" aria-modal="true"><div class="drawerhead"><h2>Detail Sales Order Accurate</h2><button type="button" class="btn sm" onclick="v49Close()">✕ Tutup</button></div><div class="drawerbody">Memuat detail dokumen…</div></aside></div>';
    try {
      const detail = await fetchOrderDetail(number);
      applyDetailToOrder(number, detail);
      if (typeof window.render === "function") window.render();
      const lines = Array.isArray(detail.line_items) ? detail.line_items : [];
      const cells = lines
        .map(function (line) {
          return (
            "<tr><td>" +
            escapeHtml(line.item_code || "—") +
            "</td><td>" +
            escapeHtml(line.name || "—") +
            "</td><td>" +
            (line.quantity == null
              ? "Belum diketahui"
              : escapeHtml(String(line.quantity))) +
            "</td><td>" +
            escapeHtml(line.unit || "—") +
            "</td><td>" +
            escapeHtml(processLabel(line.production_process)) +
            "</td><td>" +
            escapeHtml(line.color || "—") +
            "</td><td>" +
            escapeHtml(line.notes || "—") +
            "</td></tr>"
          );
        })
        .join("");
      let gateHtml =
        '<p class="v49-quiet">Job produksi V3 belum dibuat. Membuka detail tidak membuat job.</p>';
      try {
        const job = await lookupJob(number);
        if (job) {
          gateHtml =
            "<p>Job V3 #<b>" +
            escapeHtml(String(job.id)) +
            "</b> · Design: <b>" +
            escapeHtml(job.design_status || "—") +
            "</b> · Payment: <b>" +
            escapeHtml(job.payment_status || "—") +
            "</b> · Sample: <b>" +
            escapeHtml(job.sample_status || "—") +
            "</b> · Proses: <b>" +
            escapeHtml(job.processing_status || "—") +
            '</b></p><p><button type="button" class="btn" id="v3-open-from-detail">Buka panel transaksi V3</button></p>';
        } else {
          gateHtml +=
            '<p><button type="button" class="btn" id="v3-open-from-detail">Buka panel transaksi V3</button></p>';
        }
      } catch (jobErr) {
        gateHtml =
          '<p class="v49-quiet">' +
          escapeHtml(jobErr.message || "Job tidak dapat dibaca") +
          "</p>";
      }
      const branchLabel =
        detail.branch_name ||
        detail.outlet ||
        detail.branch_id ||
        "Belum terverifikasi";
      modal.querySelector(".drawerbody").innerHTML =
        "<p><b>" +
        escapeHtml(detail.number || detail.po_number || number) +
        "</b> · Accurate ID: " +
        escapeHtml(detail.accurate_id || "—") +
        "</p><p>Pelanggan: <b>" +
        escapeHtml(detail.customer || "Pelanggan belum diketahui") +
        "</b></p><p>Tanggal PO: " +
        escapeHtml(detail.order_date || "—") +
        " · Estimasi kirim: " +
        escapeHtml(detail.deadline || detail.estimated_delivery || "—") +
        "</p><p>Alamat: " +
        escapeHtml(detail.address || "—") +
        "</p><p>Syarat bayar: " +
        escapeHtml(detail.payment_terms || "—") +
        " · Ekspedisi: " +
        escapeHtml(detail.expedition || "—") +
        " · Zona: " +
        escapeHtml(detail.delivery_zone || "—") +
        "</p><p>Sales: <b>" +
        escapeHtml(detail.sales || "Belum diketahui") +
        "</b> · Pembuat PO: <b>" +
        escapeHtml(detail.created_by_user || "Belum diketahui") +
        "</b></p><p>Cabang: <b>" +
        escapeHtml(branchLabel) +
        "</b> <span class=\"v49-quiet\">(id " +
        escapeHtml(detail.branch_id || "—") +
        ")</span></p><p>Buffer: " +
        escapeHtml(
          detail.buffer_stock === true
            ? "Buffer"
            : detail.buffer_stock === false
              ? "Non Buffer"
              : "Unknown",
        ) +
        " · Urgent: " +
        escapeHtml(detail.urgent_state || "Unknown") +
        '</p><p>Keterangan:</p><div class="po-notes" style="white-space:pre-wrap">' +
        escapeHtml(detail.notes || "—") +
        "</div><p>Total qty: <b>" +
        escapeHtml(
          detail.total_quantity == null ? "—" : String(detail.total_quantity),
        ) +
        "</b> · Jenis barang: <b>" +
        escapeHtml(
          detail.line_count == null ? String(lines.length) : String(detail.line_count),
        ) +
        "</b></p><p>Status proses V3: <b>" +
        escapeHtml(detail.production_status || "Baru") +
        "</b></p>" +
        gateHtml +
        '<div class="v26-scroll"><table><thead><tr><th>Kode</th><th>Produk</th><th>Qty</th><th>Satuan</th><th>Proses</th><th>Warna</th><th>Catatan</th></tr></thead><tbody>' +
        (cells || '<tr><td colspan="7">Tidak ada baris</td></tr>') +
        '</tbody></table></div><p class="v49-quiet">Accurate read-only. Transaksi hanya via panel V3 contextual. Inbox tidak memproses.</p>';
      const openBtn = document.getElementById("v3-open-from-detail");
      if (openBtn) {
        openBtn.onclick = function () {
          window.v3OpenWorkflow(number);
        };
      }
    } catch (err) {
      modal.querySelector(".drawerbody").textContent =
        "Detail belum tersedia: " + (err.message || err);
    }
  };

  window.v49Close = function () {
    const modal = document.getElementById("modal");
    if (modal) modal.innerHTML = "";
    selectedSo = null;
  };

  const oldRender = window.render;
  window.render = function () {
    const result = oldRender ? oldRender.apply(this, arguments) : undefined;
    const root = document.getElementById("v3-app");
    if (!root) return result;
    let status = document.getElementById("v50-source-status");
    if (!status) {
      status = document.createElement("div");
      status.id = "v50-source-status";
      status.setAttribute("role", "status");
      status.className = "v50-source-status flat-notice";
    }
    status.textContent = loading
      ? "Membaca pesanan Accurate…"
      : lastSync
        ? "Sumber: Gateway Accurate • Sinkron: " +
          lastSync +
          " • halaman " +
          inboxPage +
          " • menampilkan " +
          (Array.isArray(window.orders) ? window.orders.length : 0) +
          (inboxTotal != null ? " dari total Accurate " + inboxTotal : "") +
          " (KPI halaman ≠ total Accurate)"
        : "Sumber belum terhubung: " + fetchError;
    const content = root.querySelector(".content");
    if (content && !status.parentElement) content.prepend(status);

    let toolbar = document.getElementById("v3-inbox-tools");
    if (!toolbar && content) {
      toolbar = document.createElement("div");
      toolbar.id = "v3-inbox-tools";
      toolbar.className = "v3-inbox-tools";
      toolbar.innerHTML =
        '<label>Cari SO <input id="v3-inbox-q" type="search" placeholder="Nomor / keyword"/></label>' +
        '<button type="button" class="btn sm" id="v3-inbox-search">Cari</button>' +
        '<button type="button" class="btn sm" id="v3-inbox-prev">Prev</button>' +
        '<button type="button" class="btn sm" id="v3-inbox-next">Next</button>' +
        '<button type="button" class="btn sm" id="v3-inbox-refresh">Refresh</button>';
      content.prepend(toolbar);
      document.getElementById("v3-inbox-search").onclick = function () {
        inboxKeyword = field("v3-inbox-q");
        inboxPage = 1;
        refreshInbox(1);
      };
      document.getElementById("v3-inbox-prev").onclick = function () {
        if (inboxPage > 1) refreshInbox(inboxPage - 1);
      };
      document.getElementById("v3-inbox-next").onclick = function () {
        refreshInbox(inboxPage + 1);
      };
      document.getElementById("v3-inbox-refresh").onclick = function () {
        refreshInbox(inboxPage);
      };
    }

    root.querySelectorAll(".demo").forEach((x) => x.remove());
    root.querySelectorAll(".v36-sectionhead small").forEach((x) => {
      x.textContent = "Data hanya dari API Accurate; bukan fixture";
    });
    root
      .querySelectorAll('button[onclick*="v36SimulateReceipt"]')
      .forEach((x) => x.remove());
    root
      .querySelectorAll('button[onclick*="resetDemo"]')
      .forEach((x) => x.remove());

    // Inject contextual V3 open buttons on SO rows without removing existing UI.
    root.querySelectorAll("tbody tr").forEach(function (tr) {
      const first = tr.querySelector("td");
      if (!first) return;
      const so = (first.textContent || "").trim();
      if (!so || !orderBySo(so)) return;
      if (tr.querySelector(".v3-open-wf")) return;
      const td = document.createElement("td");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn sm v3-open-wf";
      btn.textContent = "V3";
      btn.title = "Panel transaksi V3 untuk SO ini";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        window.v3OpenWorkflow(so);
      });
      td.appendChild(btn);
      tr.appendChild(td);
    });
    return result;
  };

  async function refreshInbox(page) {
    if (loading) return;
    if (authStatus !== "ok") {
      inboxTotal = null;
      publishOrders([]);
      fetchError =
        authStatus === "pending"
          ? "Memverifikasi sesi V3…"
          : "Login V3 diperlukan sebelum membaca Inbox Accurate";
      if (typeof window.render === "function") window.render();
      return;
    }
    loading = true;
    inboxPage = page || 1;
    if (typeof window.render === "function") window.render();
    try {
      if (!localStorage.getItem(TOKEN_KEY)) {
        redirectToLogin();
        throw new Error("Login V3 diperlukan sebelum membaca Inbox Accurate");
      }
      const q =
        API +
        "/production/inbox?page=" +
        inboxPage +
        "&limit=" +
        inboxPageSize +
        (inboxKeyword
          ? "&keyword=" + encodeURIComponent(inboxKeyword)
          : "");
      const data = await request(q);
      if (!Array.isArray(data.rows) || data.mode !== "live") {
        throw new Error("Respons sumber bukan data live yang terverifikasi");
      }
      const prevJobs = jobCache;
      const mapped = data.rows.map(mapOrder).filter(Boolean);
      mapped.forEach(function (o) {
        if (prevJobs[o.id]) syncOrderGatesFromJob(o, prevJobs[o.id]);
      });
      // Accurate total is metadata only — never substitute as page KPI.
      const totalRaw = data.total;
      inboxTotal =
        totalRaw == null || totalRaw === ""
          ? null
          : Number.isFinite(Number(totalRaw))
            ? Number(totalRaw)
            : null;
      if (data.pageSize != null && Number(data.pageSize) > 0) {
        inboxPageSize = Number(data.pageSize);
      }
      fetchError = "";
      publishOrders(mapped);
      // Drop board cache for SO not on this page to limit cross-PO leakage memory.
      Object.keys(boardCache).forEach(function (so) {
        if (!orderBySo(so)) delete boardCache[so];
      });
      // Detail cache only for current page numbers.
      Object.keys(detailCache).forEach(function (so) {
        if (!orderBySo(so)) delete detailCache[so];
      });
      window.taskEntries = {};
      // Do not assign window.history — browser History API is read-only.
      lastSync = new Date().toLocaleTimeString("id-ID");
      // Bounded background enrich — fills produk/qty from Accurate detail (not list).
      enrichInboxPage(
        mapped.map(function (o) {
          return o.id;
        }),
      );
      // Slice 1H: canonical Tugas Tim from V3 jobs (optional ensure_job for page SOs).
      refreshOfficialTasks(mapped).catch(function () {});
    } catch (err) {
      enrichGeneration += 1;
      inboxTotal = null;
      fetchError = err && err.message ? err.message : "Tidak dapat membaca Accurate";
      publishOrders([]);
      window.taskEntries = {};
      window.__V3_OFFICIAL_TASKS__ = [];
      window.__V3_OFFICIAL_TASK_SOURCE__ = null;
      lastSync = null;
      if (String(fetchError).indexOf("Sesi V3 tidak valid") >= 0) {
        redirectToLogin();
      }
    } finally {
      loading = false;
      if (typeof window.render === "function") window.render();
    }
  }

  function officialStateToUi(state) {
    if (state === "done") return "Selesai";
    if (state === "actionable") return "Siap";
    return "Menunggu";
  }

  function mapOfficialTaskRows(tasks) {
    const ordersById = Object.create(null);
    (window.orders || []).forEach(function (o) {
      if (o && o.id) ordersById[o.id] = o;
    });
    return (tasks || []).map(function (task) {
      const order =
        ordersById[task.accurate_so_number] || {
          id: task.accurate_so_number,
          name: task.customer_name || task.accurate_so_number,
          branch: task.branch_id || "",
          item: "",
          ship: "",
          design_status: task.design_status,
          payment_status: task.payment_status,
        };
      if (task.design_status != null) order.design_status = task.design_status;
      if (task.payment_status != null) order.payment_status = task.payment_status;
      if (task.job_id != null) order.v3JobId = task.job_id;
      const status = officialStateToUi(task.state);
      return {
        o: order,
        t: {
          id: task.kind,
          role: task.role,
          label: task.label,
          verb: task.verb,
          group: task.group || task.kind,
        },
        e: {
          status: status,
          note: task.reason || "",
          updated: "V3 official",
          qty: 0,
          file: "",
        },
        status: status,
        lineItem: order.item || "",
        official: task,
      };
    });
  }

  async function refreshOfficialTasks(pageOrders) {
    const rows = Array.isArray(pageOrders) ? pageOrders : window.orders || [];
    const jobs = rows
      .filter(function (o) {
        return o && o.id && o.branchId;
      })
      .map(function (o) {
        return {
          accurate_so_number: o.id,
          branch_id: String(o.branchId),
          accurate_id: o.accurateId != null ? String(o.accurateId) : null,
          customer_name: o.name || null,
          buffer_stock:
            o.bufferStock === true || o.bufferStock === false ? o.bufferStock : null,
          urgent_state: o.urgentState || null,
          line_items: (o.sourceLines || [])
            .filter(function (x) {
              return x && x.id;
            })
            .map(function (x) {
              return {
                accurate_line_id: String(x.id),
                accurate_item_id: x.itemId != null ? String(x.itemId) : null,
                quantity: x.qty,
                production_process:
                  x.production_process === "print" ||
                  x.production_process === "non_print"
                    ? x.production_process
                    : "unknown",
              };
            }),
        };
      });
    const soNumbers = jobs.map(function (j) {
      return j.accurate_so_number;
    });
    let body;
    try {
      body = await request(API + "/production/jobs/tasks", {
        method: "POST",
        body: {
          so_numbers: soNumbers.length ? soNumbers : null,
          sync_ensure: jobs.length > 0,
          jobs: jobs.length ? jobs : null,
        },
      });
    } catch (err) {
      // Read-only fallback if create permission missing.
      const q =
        API +
        "/production/jobs/tasks" +
        (soNumbers.length
          ? "?so=" + encodeURIComponent(soNumbers.join(","))
          : "");
      body = await request(q);
    }
    window.__V3_OFFICIAL_TASK_SOURCE__ = body && body.source;
    window.__V3_OFFICIAL_TASKS__ = mapOfficialTaskRows((body && body.tasks) || []);
    (body && body.jobs ? body.jobs : []).forEach(function (job) {
      if (!job) return;
      jobCache[job.accurate_so_number] = job;
      const o = orderBySo(job.accurate_so_number);
      if (o) syncOrderGatesFromJob(o, job);
    });
    if (typeof window.render === "function") window.render();
    return body;
  }

  window.v50RefreshInbox = refreshInbox;
  window.v3RefreshOfficialTasks = refreshOfficialTasks;
  window.v3Logout = function () {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
  };
  window.v3Api = {
    request: request,
    lookupJob: lookupJob,
    createJob: createJob,
    loadBoard: loadBoard,
    escapeHtml: escapeHtml,
    idemKey: idemKey,
  };
  window.v3EnsureJob = createJob; // explicit create only — do not use on view

  document.addEventListener(
    "click",
    function (event) {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.closest(".v3-workflow-body") || button.classList.contains("v3-open-wf")) {
        return;
      }
      const label = (button.textContent || "").toLowerCase();
      const onclick = button.getAttribute("onclick") || "";
      if (
        label.includes("simulasi") ||
        label.includes("demo") ||
        label.includes("reset demo") ||
        onclick.includes("resetDemo") ||
        onclick.includes("v36SimulateReceipt")
      ) {
        event.preventDefault();
        event.stopPropagation();
        toast("Aksi demo/simulasi dinonaktifkan — gunakan panel V3");
      }
    },
    true,
  );

  // Neutralize legacy mutation helpers that would invent success without API.
  [
    "advance",
    "pack",
    "printOn",
    "approveSample",
    "cancelRemaining",
    "confirmDriverDelivery",
    "loadSJ",
    "receiveSJ",
    "createSJ",
    "v26Action",
    "v26ShipAction",
    "v26MoveAction",
    "v28Action",
    "intakeAction",
    "v23TransferRemaining",
    "flow31ShipAction",
  ].forEach(function (name) {
    if (typeof window[name] === "function") {
      window[name] = function () {
        toast(
          "Handler simulasi " +
            name +
            " dinonaktifkan — transaksi hanya via panel V3 / API Postgres",
        );
        return false;
      };
    }
  });

  publishOrders([]);
  window.v3AuthStatus = function () {
    return authStatus;
  };
  window.v3PublishOrders = publishOrders;

  // Slice 1F addendum — Live Tracking (Inbox): no demo drawer, no invented progress.
  const TRACKING_PATH_PREFIXES = ["/track/", "/t/"];

  function extractOfficialTrackingUrl(source) {
    if (!source || typeof source !== "object") return null;
    const nested = source.tracking;
    const candidates = [
      source.tracking_url,
      source.public_tracking_url,
      source.trackingUrl,
      source.publicTrackingUrl,
      nested && nested.url,
      nested && nested.public_url,
      nested && nested.publicUrl,
    ];
    for (let i = 0; i < candidates.length; i += 1) {
      const raw = candidates[i];
      if (raw == null) continue;
      const url = String(raw).trim();
      if (url) return url;
    }
    return null;
  }

  function isAllowedTrackingUrl(url) {
    const raw = String(url || "").trim();
    if (!raw) return false;
    const lower = raw.toLowerCase();
    if (
      lower.indexOf("javascript:") === 0 ||
      lower.indexOf("data:") === 0 ||
      lower.indexOf("vbscript:") === 0 ||
      lower.indexOf("blob:") === 0
    ) {
      return false;
    }
    try {
      const parsed = new URL(raw, window.location.origin);
      if (parsed.username || parsed.password) return false;
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return false;
      const pathOk = TRACKING_PATH_PREFIXES.some(function (p) {
        return parsed.pathname.indexOf(p) === 0;
      });
      if (!pathOk) return false;
      const host = parsed.hostname.toLowerCase();
      const isLocal =
        host === "localhost" || host === "127.0.0.1" || host === "[::1]";
      if (parsed.protocol === "http:" && !isLocal) return false;
      return parsed.origin === window.location.origin;
    } catch (_) {
      return false;
    }
  }

  function declaredSo(source) {
    if (!source || typeof source !== "object") return null;
    const candidates = [
      source.so_number,
      source.po_number,
      source.number,
      source.tracking && source.tracking.so_number,
      source.id,
    ];
    for (let i = 0; i < candidates.length; i += 1) {
      const raw = candidates[i];
      if (raw == null) continue;
      const s = String(raw).trim();
      if (!s) continue;
      if (/^\d+$/.test(s)) continue; // numeric job id ≠ SO number
      return s;
    }
    return null;
  }

  function decideLiveTrackingOpen(so, order, job) {
    const id = String(so || "").trim();
    if (!id) {
      return { status: "unavailable", reason: "missing_so" };
    }
    const declared = declaredSo(job) || declaredSo(order);
    if (declared && declared !== id) {
      return { status: "unavailable", reason: "cross_po_mismatch" };
    }
    const url =
      extractOfficialTrackingUrl(job) || extractOfficialTrackingUrl(order);
    if (!url) return { status: "unavailable", reason: "no_official_url" };
    if (!isAllowedTrackingUrl(url)) {
      return { status: "unavailable", reason: "invalid_url" };
    }
    return { status: "open", url: url };
  }

  function showTrackingUnavailable() {
    // Never open SIMULASI OFFLINE drawer; never invent progress; no fake links.
    document.getElementById("v36-tracking-overlay")?.remove();
    toast("Tracking belum tersedia");
  }

  window.v3OpenLiveTracking = function (so) {
    const id = String(so || "").trim();
    const order = orderBySo(id);
    if (!order) {
      showTrackingUnavailable();
      return;
    }
    // Read-only decision from cached job summary only — no mutation, no demo timeline.
    const job = jobCache[id] || null;
    const decision = decideLiveTrackingOpen(id, order, job);
    if (decision.status === "open" && decision.url) {
      window.open(decision.url, "_blank", "noopener,noreferrer");
      return;
    }
    showTrackingUnavailable();
  };

  // Authoritative overrides — disable legacy demo tracking entry points.
  window.v36OpenTracking = function (id) {
    document.getElementById("v36-tracking-overlay")?.remove();
    window.v3OpenLiveTracking(id);
  };
  window.v36RenderTracking = function () {
    document.getElementById("v36-tracking-overlay")?.remove();
    // Intentionally empty of progress UI — demo path removed.
  };

  (async function bootLive() {
    clearGhosts();
    const ok = await verifySession();
    if (!ok) {
      if (typeof window.render === "function") window.render();
      return;
    }
    if (typeof window.render === "function") window.render();
    await refreshInbox(1);
  })();
})();
