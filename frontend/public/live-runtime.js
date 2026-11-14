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
  let paymentEpoch = 0;
  let taskRequestSequence = 0;
  const boardRequestSequence = Object.create(null);
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


  // Single connection-state controller: updated only by real results (health probe at boot,
  // Inbox request outcomes, auth failures). Never by render(); no polling.
  const conn = { api: "checking", gateway: "unchecked", sync: "none", auth: "ok", syncAt: null };
  function connReduce(st, ev) {
    const n = Object.assign({}, st);
    if (ev.t === "health") {
      n.api = ev.ok ? "ok" : "down";
      if (!ev.ok) { n.gateway = "unchecked"; n.sync = "failed"; }
    } else if (ev.t === "auth") {
      n.auth = "login"; n.sync = "none"; n.gateway = "unchecked";
    } else if (ev.t === "inbox_start") {
      n.gateway = "checking";
    } else if (ev.t === "inbox_ok") {
      n.api = "ok"; n.gateway = "ok"; n.sync = "ok"; n.auth = "ok"; n.syncAt = ev.at || null;
    } else if (ev.t === "inbox_fail") {
      n.syncAt = null;
      if (ev.kind === "auth") { n.auth = "login"; n.sync = "none"; n.gateway = "unchecked"; }
      else if (ev.kind === "network") { n.api = "down"; n.gateway = "unchecked"; n.sync = "failed"; }
      else if (ev.kind === "gateway") { n.api = "ok"; n.gateway = "down"; n.sync = "failed"; }
      else { n.api = "ok"; n.gateway = "unchecked"; n.sync = "failed"; }
    }
    return n;
  }
  function connLabels(st, preview) {
    if (preview) return { api: "PREVIEW SIMULASI", gateway: "PREVIEW SIMULASI", sync: "PREVIEW SIMULASI" };
    const api = st.auth === "login" ? "PERLU LOGIN" : { checking: "MEMERIKSA", ok: "TERHUBUNG", down: "GANGGUAN" }[st.api];
    const gwKnown = st.auth !== "login" && st.api !== "down";
    const gateway = !gwKnown ? "BELUM DIPERIKSA" : { checking: "MEMERIKSA", ok: "TERHUBUNG", down: "GANGGUAN", unchecked: "BELUM DIPERIKSA" }[st.gateway];
    const sync = st.sync === "ok" ? "BERHASIL" + (st.syncAt ? " (" + st.syncAt + ")" : "") : st.sync === "failed" ? "GAGAL" : "BELUM TERSEDIA";
    return { api: api, gateway: gateway, sync: sync };
  }
  function connDispatch(ev) {
    const next = connReduce(conn, ev);
    Object.assign(conn, next);
    window.v3ApplyConnectionStatus();
  }
  window.v3ApplyConnectionStatus = function () {
    const l = connLabels(conn, isPreviewFixture());
    const set = function (id, text) { const el = document.getElementById(id); if (el) el.textContent = text; };
    set("v3-conn-api", "API: " + l.api);
    set("v3-conn-gw", "Gateway Accurate: " + l.gateway);
    set("v3-conn-sync", "Sinkronisasi PO: " + l.sync);
    set("save-indicator", "API " + l.api + " · Gateway " + l.gateway);
  };
  window.v3ConnectionState = function () { return Object.assign({}, conn, { labels: connLabels(conn, isPreviewFixture()) }); };
  async function probeBackendHealth() {
    try {
      const r = await fetch(API + "/health", { cache: "no-store", credentials: "same-origin" });
      connDispatch({ t: "health", ok: r.ok });
    } catch (_) {
      connDispatch({ t: "health", ok: false });
    }
  }

  function redirectToLogin() {
    connDispatch({ t: "auth" });
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
    if (me && me.must_change_password) { window.location.replace("/?view=password"); return; }
    authStatus = "ok";
    const perms = Array.isArray(me && me.permissions)
      ? me.permissions.map(String)
      : [];
    window.__V3_AUTH__ = {
      status: "ok",
      settings_enabled: !!(me && me.settings_enabled),
      system_director: !!(me && me.system_director),
      user_id: me && me.user_id != null ? Number(me.user_id) : null,
      username: me && me.username ? String(me.username) : null,
      role: me && me.role ? String(me.role) : null,
      permissions: perms,
      branch_ids: Array.isArray(me && me.branch_ids)
        ? me.branch_ids.map(String)
        : [],
    };
    document.documentElement.classList.remove("v3-auth-pending", "v3-auth-failed");
    document.documentElement.classList.add("v3-auth-ok");
  }

  function authPermissions() {
    const a = window.__V3_AUTH__;
    return (a && Array.isArray(a.permissions) ? a.permissions : []).map(String);
  }

  function authUserId() {
    const a = window.__V3_AUTH__;
    return a && a.user_id != null ? Number(a.user_id) : null;
  }

  function canPerm(code) {
    const L = window.V3LoadingLedger;
    if (L && typeof L.hasPermission === "function") {
      return L.hasPermission(authPermissions(), code);
    }
    return authPermissions().indexOf(code) !== -1;
  }

  function isPreviewFixture() {
    return (
      window.__V3_PREVIEW_FIXTURE__ === true ||
      /(?:^|[?&])epv3_preview=fixture(?:&|$)/.test(location.search || "")
    );
  }

  function seedPreviewFixtureOrders() {
    // SIMULASI / FIXTURE — bukan Accurate Live. Hanya untuk preview UI Cursor.
    const rows = [
      {
        id: "SO/PREVIEW-MIX-001",
        accurateId: "fixture-mix-1",
        name: "Renea Coffee (SIMULASI)",
        item: "Cup PET 16oz Cetak + Lid Non-Cetak",
        itemCodes: "CUP-16 · LID-16",
        itemProcesses: "Cetak · Tidak Cetak",
        itemUnits: "pcs · pcs",
        qty: 8000,
        qtyVerified: true,
        detailLoaded: true,
        detailLoadState: "loaded",
        detailError: null,
        lineCount: 2,
        sourceLines: [
          {
            id: "L-PRINT",
            itemId: "fi-1",
            item_code: "CUP-16",
            name: "Cup PET 16oz Cetak",
            qty: 5000,
            qtyVerified: true,
            unit: "pcs",
            color: "Putih",
            notes: null,
            production_process: "print",
            processSnapshot: "PRINT",
          },
          {
            id: "L-NON",
            itemId: "fi-2",
            item_code: "LID-16",
            name: "Lid Non-Cetak",
            qty: 3000,
            qtyVerified: true,
            unit: "pcs",
            color: "—",
            notes: null,
            production_process: "non_print",
            processSnapshot: "NON_PRINT",
          },
        ],
        status: "PO Masuk",
        stage: "inbox",
        productionStatus: "Baru",
        branch: "Yogyakarta",
        branchId: null,
        salesName: "Sales Fixture A",
        createdByUser: "user.fixture",
        orderDate: "2026-11-12",
        address: "Jl. Preview Fixture No. 1\nYogyakarta",
        paymentTerms: "COD",
        expedition: "Internal Delivery",
        ship: "15 Nov 2026",
        deliveryZone: "Dalam Kota",
        orderPriority: "Normal",
        bufferLabel: "Non-Buffer",
        poNotes: "Data simulasi Step 158 — bukan Accurate Live.",
        design_status: "approved",
        payment_status: "approved",
        approval: true,
        scheduledQty: 2000,
        done: 500,
        packed: 0,
        productionAssignments: [
          {
            id: "asg-1",
            soLineId: "L-PRINT",
            colorIndex: 1,
            colorName: "Putih",
            operator: "Op Preview",
            machine: "M1",
            targetQty: 2000,
            workDate: "2026-11-13",
          },
        ],
        inkColors: ["Putih"],
        deleted: false,
      },
      {
        id: "SO/PREVIEW-UNK-002",
        accurateId: "fixture-unk-2",
        name: "Toko Unknown (SIMULASI)",
        item: "Item Belum Terverifikasi",
        itemCodes: "UNK-01",
        itemProcesses: "Unknown",
        itemUnits: "pcs",
        qty: 100,
        qtyVerified: true,
        detailLoaded: true,
        detailLoadState: "loaded",
        detailError: null,
        lineCount: 1,
        sourceLines: [
          {
            id: "L-UNK",
            itemId: "fi-3",
            item_code: "UNK-01",
            name: "Item Belum Terverifikasi",
            qty: 100,
            qtyVerified: true,
            unit: "pcs",
            color: "—",
            notes: null,
            production_process: "unknown",
            processSnapshot: "UNKNOWN",
          },
        ],
        status: "PO Masuk",
        stage: "inbox",
        productionStatus: "Baru",
        branch: "Semarang",
        branchId: null,
        salesName: "Belum terverifikasi",
        createdByUser: "user.fixture",
        orderDate: "2026-11-11",
        address: "Alamat simulasi Semarang",
        paymentTerms: "Transfer",
        expedition: null,
        ship: "16 Nov 2026",
        deliveryZone: "Luar Kota",
        orderPriority: "Urgent",
        bufferLabel: "Buffer",
        poNotes: "Proses unknown — tinjau di Inbox/Detail, bukan Jadwal Cetak.",
        design_status: "pending",
        payment_status: "pending",
        approval: false,
        scheduledQty: 0,
        done: 0,
        packed: 0,
        productionAssignments: [],
        inkColors: [],
        deleted: false,
      },
      {
        id: "SO/PREVIEW-PRINT-003",
        accurateId: "fixture-print-3",
        name: "Cafe Cetak Murni (SIMULASI)",
        item: "Cup PP 14oz Cetak",
        itemCodes: "CUP-14",
        itemProcesses: "Cetak",
        itemUnits: "pcs",
        qty: 2000,
        qtyVerified: true,
        detailLoaded: true,
        detailLoadState: "loaded",
        detailError: null,
        lineCount: 1,
        sourceLines: [
          {
            id: "L-P2",
            itemId: "fi-4",
            item_code: "CUP-14",
            name: "Cup PP 14oz Cetak",
            qty: 2000,
            qtyVerified: true,
            unit: "pcs",
            color: "Hitam",
            notes: null,
            production_process: "print",
            processSnapshot: "PRINT",
          },
        ],
        status: "PO Masuk",
        stage: "inbox",
        productionStatus: "Baru",
        branch: "Yogyakarta",
        branchId: null,
        salesName: "Sales Fixture B",
        createdByUser: "user.fixture",
        orderDate: "2026-11-10",
        address: "Jl. Simulasi Cetak 3",
        paymentTerms: "DP 50%",
        expedition: "JNE",
        ship: "18 Nov 2026",
        deliveryZone: "Nasional",
        orderPriority: "Normal",
        bufferLabel: "Non-Buffer",
        poNotes: "Hanya item cetak.",
        design_status: "approved",
        payment_status: "approved",
        approval: true,
        scheduledQty: 0,
        done: 0,
        packed: 0,
        productionAssignments: [],
        inkColors: ["Hitam"],
        deleted: false,
      },
    ];
    fetchError = "";
    inboxTotal = rows.length;
    inboxPage = 1;
    lastSync = "preview-fixture";
    publishOrders(rows);
    window.__V3_INBOX__.mode = "live";
    window.__V3_INBOX__.previewFixture = true;
    window.__V3_INBOX__.fetchError = "";
    return rows;
  }

  async function verifySession() {
    if (isPreviewFixture()) {
      window.__V3_PREVIEW_FIXTURE__ = true;
      try {
        localStorage.setItem(TOKEN_KEY, "preview-fixture-token");
      } catch (_) {}
      markAuthOk({
        username: "preview-fixture",
        role: "viewer",
        user_id: 0,
        permissions: [],
        branch_ids: [],
      });
      return true;
    }
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
    // Slice 1M: trust explicit verification flags; never treat missing qty as verified 0.
    let qtyVerified = false;
    let qty = null;
    if (s.total_quantity_verified === true && s.total_quantity != null) {
      const n = Number(s.total_quantity);
      if (Number.isFinite(n)) {
        qty = n;
        qtyVerified = true;
      }
    } else if (
      lines.length > 0 &&
      lines.every(function (x) {
        return x.qty_verified === true && (x.quantity != null || x.qty != null);
      })
    ) {
      qty = lines.reduce(function (sum, x) {
        const n = Number(x.quantity != null ? x.quantity : x.qty);
        return sum + (Number.isFinite(n) ? n : 0);
      }, 0);
      qtyVerified = Number.isFinite(qty);
      if (!qtyVerified) qty = null;
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
    const QiUrgent = window.V3QtyIntegrity;
    const urgentFields =
      QiUrgent && QiUrgent.urgentFieldsFromAccurateState
        ? QiUrgent.urgentFieldsFromAccurateState(s.urgent_state)
        : (function () {
            const st =
              s.urgent_state == null || !String(s.urgent_state).trim()
                ? null
                : String(s.urgent_state).trim();
            const urgent =
              st === "approved_urgent" || st === "legacy_urgent"
                ? true
                : st === "normal"
                  ? false
                  : null;
            return {
              urgent: urgent,
              urgentState: st,
              orderPriority:
                urgent === true
                  ? "Urgent"
                  : urgent === false
                    ? "Normal"
                    : "Belum terverifikasi",
            };
          })();
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
      detailLoadState: lines.length ? "loaded" : "not_loaded",
      detailError: null,
      lineCount: s.line_count != null ? Number(s.line_count) : lines.length || null,
      sourceLines: lines.map(function (x) {
        const lineQtyVerified = x.qty_verified === true;
        const rawLineQty = x.quantity != null ? x.quantity : x.qty;
        const lineQty =
          lineQtyVerified && rawLineQty != null && Number.isFinite(Number(rawLineQty))
            ? Number(rawLineQty)
            : null;
        return {
          id: x.accurate_line_id || x.id || null,
          itemId: x.accurate_item_id || null,
          item_code: x.item_code || null,
          name: x.name || null,
          qty: lineQty,
          qtyVerified: lineQtyVerified && lineQty != null,
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
      urgent: urgentFields.urgent,
      urgentState: urgentFields.urgentState,
      orderPriority: urgentFields.orderPriority,
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
    let body;
    if (opts.formData) {
      body = opts.formData;
      // Browser sets multipart boundary — do not force JSON content-type.
      delete headers["Content-Type"];
    } else if (opts.body != null) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    let response;
    try {
      response = await fetch(path, {
        method: opts.method || "GET",
        credentials: "same-origin",
        headers: headers,
        cache: "no-store",
        body: body,
      });
    } catch (netErr) {
      const e = new Error("Backend API tidak dapat dihubungi");
      e.kind = "network";
      throw e;
    }
    if (response.status === 401) {
      redirectToLogin();
      const e = new Error("Sesi V3 tidak valid — login ulang");
      e.kind = "auth";
      throw e;
    }
    if (response.status === 403) {
      throw new Error("Akses ditolak (izin/cabang)");
    }
    if (!response.ok) {
      let detail = "";
      let errCode = "";
      try {
        const errBody = await response.json();
        errCode = (errBody && errBody.error && errBody.error.code) || "";
        detail =
          (errBody && errBody.error && errBody.error.message) ||
          (typeof errBody.detail === "string" ? errBody.detail : "") ||
          "";
      } catch (_) {}
      if (response.status === 409 && errCode === "access_changed_reconcile") {
        // An earlier step was already saved: never present this as a plain failure.
        Object.keys(boardCache).forEach(function (so) {
          delete boardCache[so];
        });
        throw new Error(
          "PERLU REKONSILIASI: akses berubah setelah satu langkah tersimpan. Data dimuat ulang — periksa hasilnya sebelum mengulang.",
        );
      }
      if (
        response.status === 409 &&
        (errCode === "access_changed_nothing_written" ||
          errCode === "sync_conflict_nothing_written")
      ) {
        throw new Error(
          "Tidak ada data yang tersimpan (akses/sinkronisasi berubah). Aman untuk dicoba lagi setelah memuat ulang.",
        );
      }
      if (response.status === 503) {
        const e = new Error("Gateway Accurate belum siap / tidak berwenang");
        e.kind = "gateway";
        throw e;
      }
      if (response.status === 502 || response.status === 504) {
        const e = new Error("Backend API tidak merespons (HTTP " + response.status + ")");
        e.kind = "network";
        throw e;
      }
      throw new Error(detail || "API V3 HTTP " + response.status);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  const monitorOrders = Object.create(null);
  function orderBySo(so) {
    return (window.orders || []).find((x) => x.id === so) || monitorOrders[so] || null;
  }

  const detailCache = Object.create(null);
  const detailInflight = Object.create(null);
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
      const lineQtyVerified = x.qty_verified === true;
      const rawLineQty = x.quantity != null ? x.quantity : x.qty;
      const lineQty =
        lineQtyVerified && rawLineQty != null && Number.isFinite(Number(rawLineQty))
          ? Number(rawLineQty)
          : null;
      return {
        id: x.accurate_line_id || x.id || null,
        itemId: x.accurate_item_id || null,
        item_code: x.item_code || null,
        name: x.name || null,
        qty: lineQty,
        qtyVerified: lineQtyVerified && lineQty != null,
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
    if (
      detail.total_quantity_verified === true &&
      detail.total_quantity != null &&
      Number.isFinite(Number(detail.total_quantity))
    ) {
      o.qty = Number(detail.total_quantity);
      o.qtyVerified = true;
    } else if (
      o.sourceLines.length &&
      o.sourceLines.every(function (x) {
        return x.qtyVerified === true && x.qty != null;
      })
    ) {
      o.qty = o.sourceLines.reduce(function (sum, x) {
        return sum + Number(x.qty);
      }, 0);
      o.qtyVerified = Number.isFinite(o.qty);
      if (!o.qtyVerified) {
        o.qty = null;
      }
    } else {
      // Detail loaded but quantity incomplete/unverified — never invent verified zero.
      o.qty = null;
      o.qtyVerified = false;
    }
    o.lineCount =
      detail.line_count != null ? Number(detail.line_count) : o.sourceLines.length;
    o.detailLoaded = true;
    o.detailLoadState = "loaded";
    o.detailError = null;
    if (detail.branch_name || detail.outlet) {
      o.branch = detail.branch_name || detail.outlet;
    }
    if (detail.branch_id) o.branchId = detail.branch_id;
    if (detail.sales != null && String(detail.sales).trim()) {
      o.salesName = String(detail.sales).trim();
      o.salesSource = detail.sales_source || o.salesSource || "detail";
      o.salesMissingReason = null;
    } else if (
      o.salesName &&
      o.salesName !== "Belum terverifikasi"
    ) {
      // Preserve verified list sales when detail omits sales — never wipe, never use creator.
      o.salesMissingReason = null;
    } else {
      o.salesName = "Belum terverifikasi";
      o.salesSource = detail.sales_source || o.salesSource || null;
      o.salesMissingReason = "accurate_sales_field_absent";
    }
    if (detail.created_by_user) o.createdByUser = detail.created_by_user;
    if (detail.order_date) o.orderDate = detail.order_date;
    if (detail.address) o.address = detail.address;
    if (detail.payment_terms) o.paymentTerms = detail.payment_terms;
    // Step 137 — Pengiriman: apply detail expedition; preserve list shipment.name
    // when detail omits; never invent a method when both absent.
    if (detail.expedition != null && String(detail.expedition).trim()) {
      o.expedition = String(detail.expedition).trim();
    } else if (o.expedition != null && String(o.expedition).trim()) {
      // keep list / prior verified Pengiriman
    } else {
      o.expedition = null;
    }
    if (detail.delivery_zone) o.deliveryZone = detail.delivery_zone;
    if (detail.notes) o.poNotes = detail.notes;
    o.ship = detail.deadline || detail.estimated_delivery || o.ship || null;
    // Step 58: keep urgent / urgentState / orderPriority in lockstep; preserve list when detail omits.
    (function () {
      const Qi = window.V3QtyIntegrity;
      const merged =
        Qi && Qi.mergeUrgentFromIncoming
          ? Qi.mergeUrgentFromIncoming(o, detail.urgent_state)
          : null;
      if (merged) {
        o.urgent = merged.urgent;
        o.urgentState = merged.urgentState;
        o.orderPriority = merged.orderPriority;
        return;
      }
      if (
        detail.urgent_state === "approved_urgent" ||
        detail.urgent_state === "legacy_urgent"
      ) {
        o.urgent = true;
        o.orderPriority = "Urgent";
        o.urgentState = String(detail.urgent_state);
      } else if (detail.urgent_state === "normal") {
        o.urgent = false;
        o.orderPriority = "Normal";
        o.urgentState = "normal";
      } else if (!o.orderPriority) {
        o.orderPriority = "Belum terverifikasi";
      }
    })();
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

  async function fetchOrderDetail(number, opts) {
    const force = !!(opts && opts.force);
    const dedupe =
      (typeof window !== "undefined" &&
        window.V3QtyIntegrity &&
        window.V3QtyIntegrity.fetchDetailDeduped) ||
      null;
    const runRequest = function () {
      return request(
        API + "/production/orders/" + encodeURIComponent(number),
      );
    };
    if (dedupe) {
      // force clears cache but still joins inflight — never duplicate in-flight SO fetch.
      return dedupe(
        number,
        { cache: detailCache, inflight: detailInflight },
        runRequest,
        { force: force },
      );
    }
    // Fallback if helper script missing (should not happen in Live shell).
    if (force) delete detailCache[number];
    else if (detailCache[number]) return detailCache[number];
    if (detailInflight[number]) return detailInflight[number];
    const pending = runRequest()
      .then(function (detail) {
        detailCache[number] = detail;
        delete detailInflight[number];
        return detail;
      })
      .catch(function (err) {
        delete detailInflight[number];
        delete detailCache[number];
        throw err;
      });
    detailInflight[number] = pending;
    return pending;
  }

  function markDetailFailed(so) {
    const o = orderBySo(so);
    if (!o) return;
    o.detailLoadState = "failed";
    o.detailLoaded = false;
    o.detailError = "Gagal memuat detail Accurate";
    // Keep qty unverified; never invent zero from a failed enrich.
    if (!o.qtyVerified) {
      o.qty = null;
    }
  }

  async function enrichInboxPage(numbers, opts) {
    const force = !!(opts && opts.force);
    const gen = ++enrichGeneration;
    const queue = (numbers || []).filter(Boolean).slice();
    queue.forEach(function (so) {
      const o = orderBySo(so);
      if (!o) return;
      if (force || o.detailLoadState !== "loaded") {
        o.detailLoadState = "loading";
        o.detailError = null;
      }
    });
    if (typeof window.render === "function") window.render();
    async function worker() {
      while (queue.length && gen === enrichGeneration) {
        const so = queue.shift();
        try {
          const detail = await fetchOrderDetail(so, { force: force });
          if (gen !== enrichGeneration) return;
          // Stale isolation: only apply if SO still on current page orders.
          if (!orderBySo(so)) continue;
          applyDetailToOrder(so, detail);
          if (typeof window.render === "function") window.render();
        } catch (_) {
          if (gen !== enrichGeneration) return;
          markDetailFailed(so);
          if (typeof window.render === "function") window.render();
        }
      }
    }
    const n = Math.min(ENRICH_CONCURRENCY, Math.max(1, queue.length));
    const runners = [];
    for (let i = 0; i < n; i += 1) runners.push(worker());
    await Promise.all(runners);
  }

  window.retryInboxDetail = function (so) {
    if (!so) return;
    // Single-PO retry; force refresh but inflight dedupe still applies.
    enrichInboxPage([so], { force: true });
  };

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
    const epoch = paymentEpoch;
    try {
      const job = await request(
        API + "/production/jobs/by-so/" + encodeURIComponent(so),
      );
      if (epoch !== paymentEpoch) return null;
      jobCache[so] = job;
      const o = orderBySo(so);
      if (o) syncOrderGatesFromJob(o, job);
      return job;
    } catch (err) {
      if (epoch !== paymentEpoch) return null;
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
    (function () {
      const Qi = window.V3QtyIntegrity;
      const merged =
        Qi && Qi.mergeUrgentFromIncoming
          ? Qi.mergeUrgentFromIncoming(order, job.urgent_state)
          : null;
      if (merged) {
        order.urgent = merged.urgent;
        order.urgentState = merged.urgentState;
        order.orderPriority = merged.orderPriority;
        return;
      }
      if (
        job.urgent_state === "approved_urgent" ||
        job.urgent_state === "legacy_urgent"
      ) {
        order.urgent = true;
        order.urgentState = String(job.urgent_state);
        order.orderPriority = "Urgent";
      } else if (job.urgent_state === "normal") {
        order.urgent = false;
        order.urgentState = "normal";
        order.orderPriority = "Normal";
      }
      // else: preserve existing order urgent fields
    })();
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
    const epoch = paymentEpoch;
    const sequence = boardRequestSequence[so] = (boardRequestSequence[so] || 0) + 1;
    let job = jobCache[so];
    if (!job) job = await lookupJob(so);
    if (!job) return null;
    if (!force && boardCache[so]) return boardCache[so];
    const board = await request(API + "/production/jobs/" + job.id + "/board");
    if (epoch !== paymentEpoch || sequence !== boardRequestSequence[so]) return null;
    board.sj_line_authority = mergeAuthorityRows(
      board.sj_line_authority || [],
      authorityOverlay[so] || [],
    );
    boardCache[so] = board;
    jobCache[so] = board.job;
    applyBoardToOrder(so, board);
    return board;
  }

  function invalidatePaymentView(so) {
    const paymentDraft = selectedSo === so ? snapshotDeliveryDraft() : null;
    paymentEpoch++;
    taskRequestSequence++;
    if (typeof window.v3PaymentMonitorRefresh === "function") window.v3PaymentMonitorRefresh();
    delete boardCache[so];
    delete jobCache[so];
    window.__V3_OFFICIAL_TASKS__ = [];
    window.__V3_OFFICIAL_TASK_SOURCE__ = null;
    const order = orderBySo(so);
    if (order) syncOrderGatesFromJob(order, { id: order.v3JobId, design_status: order.design_status, payment_status: "pending" });
    if (selectedSo === so) {
      renderWorkflowDrawer(so);
      restoreDeliveryDraft(paymentDraft);
    }
    if (typeof window.render === "function") window.render();
  }

  async function mutate(lockKey, fn, opts) {
    if (inFlight.has(lockKey)) {
      toast("Transaksi masih diproses — tunggu selesai");
      return null;
    }
    inFlight.add(lockKey);
    const affectedSo = opts && opts.so ? opts.so : selectedSo;
    try {
      const result = await fn();
      try { ops.ts = {}; mm.ts = 0; delete detailCache[so]; for (const k in bufTried) delete bufTried[k]; for (const k in bufFailed) delete bufFailed[k]; } catch (_) { /* views not initialised yet */ }
      // Soft actions (lookup / field-select) must not wipe Delivery form inputs.
      if (opts && opts.soft) return result;
      if (opts && opts.payment) {
        invalidatePaymentView(affectedSo);
        try {
          await refreshOfficialTasks(undefined, true);
          if (!boardCache[affectedSo]) await loadBoard(affectedSo, true);
        } catch (refreshError) {
          toast("Payment tersimpan; refresh gagal. Muat ulang sebelum tindakan berikutnya.");
          throw refreshError;
        }
      }
      if (selectedSo === affectedSo && selectedSo) {
        const draft = snapshotDeliveryDraft();
        if (!(opts && opts.payment)) {
          delete boardCache[selectedSo];
          await loadBoard(selectedSo, true);
        }
        renderWorkflowDrawer(selectedSo);
        restoreDeliveryDraft(draft);
      }
      if (typeof window.render === "function") window.render();
      return result;
    } catch (err) {
      toast(err.message || "Transaksi gagal");
      // A failed response can follow a committed payment write: fail closed, then reload.
      if (opts && opts.payment) {
        try {
          invalidatePaymentView(affectedSo);
        } catch (invalidateError) {
          console.error("invalidatePaymentView", invalidateError);
        }
        try {
          await lookupJob(affectedSo);
          if (jobCache[affectedSo]) await loadBoard(affectedSo, true);
          await refreshOfficialTasks(undefined, true);
          if (selectedSo === affectedSo) renderWorkflowDrawer(affectedSo);
          if (typeof window.render === "function") window.render();
        } catch (restoreError) {
          console.error("restore after failed payment action", restoreError);
        }
      }
      throw err;
    } finally {
      inFlight.delete(lockKey);
    }
  }

  const DELIVERY_DRAFT_IDS = [
    "v3-sj-id",
    "v3-sj-no",
    "v3-sj-line",
    "v3-load-so-line",
    "v3-load-qty",
    "v3-cancel-event",
    "v3-cancel-qty",
    "v3-cancel-reason",
    "v3-ret-event",
    "v3-ret-qty",
    "v3-ret-reason",
    "v3-pod-qty",
    "v3-pod-recv",
    "v3-sj-cancel-reason",
  ];

  function snapshotDeliveryDraft() {
    const out = {};
    DELIVERY_DRAFT_IDS.forEach(function (id) {
      const el = document.getElementById(id);
      if (el) out[id] = el.value;
    });
    const auth = document.getElementById("v3-load-auth-status");
    if (auth) out.__authStatus = auth.textContent || "";
    const designLink = document.getElementById("v3-design-link-status");
    if (designLink) out.__designLinkStatus = designLink.textContent || "";
    const designPath = document.getElementById("v3-design-link-status");
    if (designPath && designPath.dataset && designPath.dataset.path) {
      out.__designLinkPath = designPath.dataset.path;
    }
    return out;
  }

  function restoreDeliveryDraft(draft) {
    if (!draft) return;
    DELIVERY_DRAFT_IDS.forEach(function (id) {
      if (draft[id] == null) return;
      const el = document.getElementById(id);
      if (el) el.value = draft[id];
    });
    const auth = document.getElementById("v3-load-auth-status");
    if (auth && draft.__authStatus != null) auth.textContent = draft.__authStatus;
    if (draft.__designLinkStatus != null || draft.__designLinkPath) {
      applyDesignLinkStatus(
        draft.__designLinkStatus || "",
        draft.__designLinkPath || "",
      );
    }
    syncLoadButtonEnabled();
  }

  function applyDesignLinkStatus(text, path) {
    const el = document.getElementById("v3-design-link-status");
    const copyBtn = document.getElementById("v3-design-link-copy");
    if (el) {
      el.textContent = text || "";
      if (path) el.dataset.path = path;
      else if (text) {
        const m = String(text).match(/(\/t\/[^\s]+)/);
        if (m) el.dataset.path = m[1];
      }
    }
    if (copyBtn) {
      const p = (el && el.dataset.path) || path || "";
      copyBtn.hidden = !p;
      copyBtn.onclick = function () {
        const value = p || (el && el.dataset.path) || "";
        if (!value) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(value).then(
            function () {
              toast("Approval link disalin");
            },
            function () {
              toast("Gagal menyalin link");
            },
          );
        } else {
          toast(value);
        }
      };
    }
  }

  function syncLoadButtonEnabled() {
    const loadBtn = document.getElementById("v3-load-btn");
    if (!loadBtn) return;
    if (!canPerm("production.delivery.manage")) {
      loadBtn.disabled = true;
      return;
    }
    const so = selectedSo;
    const sjId = field("v3-sj-id");
    const sjLine = field("v3-sj-line");
    const soLine = field("v3-load-so-line");
    const L = ledgerApi();
    const view =
      L && L.findLineAuthority && so
        ? L.findLineAuthority(
            authorityRows(boardCache[so], so),
            sjId,
            sjLine,
            soLine,
          )
        : null;
    loadBtn.disabled = !(view && view.actionsEnabled);
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

  function ledgerApi() {
    return window.V3LoadingLedger || null;
  }

  /** Client overlay so Lookup Qty SJ survives board refresh before first Loading event. */
  const authorityOverlay = Object.create(null);

  function mergeAuthorityRows(serverRows, overlayRows) {
    const out = [];
    const seen = Object.create(null);
    function key(r) {
      return (
        String(r.accurate_sj_id || "") +
        "::" +
        String(r.accurate_sj_line_id || "") +
        "::" +
        String(r.so_line_id || "")
      );
    }
    (overlayRows || []).concat(serverRows || []).forEach(function (r) {
      if (!r) return;
      const k = key(r);
      if (!k || seen[k]) {
        if (seen[k] && r.verification === "VERIFIED") {
          // Prefer verified overlay/server row.
          const idx = out.findIndex(function (x) {
            return key(x) === k;
          });
          if (idx >= 0) out[idx] = r;
        }
        return;
      }
      seen[k] = true;
      out.push(r);
    });
    return out;
  }

  function authorityRows(board, so) {
    const server = (board && board.sj_line_authority) || [];
    const overlay = so ? authorityOverlay[so] || [] : [];
    return mergeAuthorityRows(server, overlay);
  }

  function buildAuthoritySummaryHtml(board, events, so) {
    const L = ledgerApi();
    const auth = authorityRows(board, so);
    if (!auth.length && !(events || []).some((e) => e.event_type === "loading")) {
      return (
        '<p class="v49-quiet" id="v3-sj-authority">Qty SJ: isi identitas SJ line lalu Lookup. Loading dibatasi qty packing sah dan sisa SJ.</p>'
      );
    }
    const views = auth.map(function (row) {
      return L && L.viewSjLineAuthority
        ? L.viewSjLineAuthority(row)
        : {
            accurateSjId: row.accurate_sj_id,
            accurateSjNumber: row.accurate_sj_number,
            accurateSjLineId: row.accurate_sj_line_id,
            soLineId: row.so_line_id,
            displayQtySj: "UNKNOWN",
            displayRemaining: "UNKNOWN",
            loadingConfirmed: row.loading_confirmed,
            loadingCancelled: row.loading_cancelled,
            loadingNet: row.loading_net,
            verification: "UNKNOWN",
            actionsEnabled: false,
          };
    });
    if (!views.length) {
      return '<p class="v49-quiet" id="v3-sj-authority">Qty SJ: UNKNOWN (belum terverifikasi)</p>';
    }
    return (
      '<div id="v3-sj-authority" class="v3-sj-authority">' +
      views
        .map(function (v) {
          return (
            '<div class="v3-auth-row" data-sj="' +
            escapeHtml(v.accurateSjId) +
            '" data-sj-line="' +
            escapeHtml(v.accurateSjLineId) +
            '" data-so-line="' +
            escapeHtml(v.soLineId) +
            '">' +
            "<div><b>SJ " +
            escapeHtml(v.accurateSjNumber || v.accurateSjId) +
            "</b> · SJ-line " +
            escapeHtml(v.accurateSjLineId) +
            " · SO-line " +
            escapeHtml(v.soLineId) +
            " · <b>" +
            escapeHtml(v.verification) +
            "</b></div>" +
            "<div>Qty SJ " +
            escapeHtml(v.displayQtySj) +
            " · Loading Confirmed " +
            escapeHtml(v.loadingConfirmed) +
            " · Loading Cancelled " +
            escapeHtml(v.loadingCancelled) +
            " · Loading Net " +
            escapeHtml(v.loadingNet) +
            " · Remaining Loading " +
            escapeHtml(v.displayRemaining) +
            "</div></div>"
          );
        })
        .join("") +
      '<p class="v49-quiet">Loading dibatasi qty packing sah, qty SJ, dan sisa yang belum diloading.</p></div>'
    );
  }

  function buildLoadingLedgerHtml(events, board, so) {
    const L = ledgerApi();
    const rows = L ? L.summarizeLoadingEvents(events || []) : [];
    const authHtml = buildAuthoritySummaryHtml(board, events, so);
    if (!rows.length) {
      return (
        authHtml +
        '<p class="v49-quiet">Belum ada konfirmasi Loading.</p>'
      );
    }
    const canCancel = canPerm(
      (L && L.PERM_DELIVERY_MANAGE) || "production.delivery.manage",
    );
    const canRequest = canPerm(
      (L && L.PERM_LOADING_RETURN_REQUEST) ||
        "production.delivery.loading_return.request",
    );
    return (
      authHtml +
      '<div class="v3-load-ledger">' +
      rows
        .map(function (r) {
          const auth =
            L && L.findLineAuthority
              ? L.findLineAuthority(
                  authorityRows(board, so),
                  r.accurateSjId,
                  r.accurateSjLineId,
                  r.soLineId,
                )
              : null;
          const remSj = auth ? auth.displayRemaining : "UNKNOWN";
          const qtySj = auth ? auth.displayQtySj : "UNKNOWN";
          const actions =
            (canCancel
              ? '<button type="button" class="btn sm" data-v3="load-cancel" data-event-id="' +
                escapeHtml(r.eventId) +
                '">Batalkan Konfirmasi</button>'
              : "") +
            (canRequest && r.remainingOnEvent > 0
              ? '<button type="button" class="btn sm" data-v3="load-return-req" data-event-id="' +
                escapeHtml(r.eventId) +
                '">Ajukan Pengembalian</button>'
              : "");
          return (
            '<div class="v3-load-row" data-load-event="' +
            escapeHtml(r.eventId) +
            '">' +
            "<div><b>#" +
            escapeHtml(r.eventId) +
            "</b> · SJ " +
            escapeHtml(r.accurateSjNumber || r.accurateSjId) +
            " · line " +
            escapeHtml(r.accurateSjLineId) +
            " · SO " +
            escapeHtml(r.soLineId) +
            "</div>" +
            "<div>Qty SJ " +
            escapeHtml(qtySj) +
            " · Loading Confirmed " +
            escapeHtml(r.confirmedQty) +
            " · Loading Cancelled " +
            escapeHtml(r.cancelledQty) +
            " · Loading Net " +
            escapeHtml(r.netLoadedQty) +
            " · Remaining Loading " +
            escapeHtml(remSj) +
            " · Remaining event " +
            escapeHtml(r.remainingOnEvent) +
            "</div>" +
            (actions
              ? '<div class="row" style="margin-top:6px;gap:6px">' +
                actions +
                "</div>"
              : "") +
            "</div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function buildReturnRequestPanelHtml(events) {
    const L = ledgerApi();
    if (!L) return "";
    const pending = L.pendingReturnRequests(events || []);
    const requests = (events || []).filter(function (e) {
      return e.event_type === "loading_return_requested";
    });
    const canApprove = canPerm(L.PERM_LOADING_RETURN_APPROVE);
    const meId = authUserId();
    const pendingHtml = pending.length
      ? pending
          .map(function (ev) {
            const payload = L.parsePayload(ev);
            const self =
              meId != null &&
              ev.actor_user_id != null &&
              Number(ev.actor_user_id) === meId;
            const actions =
              canApprove && !self
                ? '<button type="button" class="btn sm primary" data-v3="load-return-approve" data-request-id="' +
                  escapeHtml(ev.id) +
                  '">Approve</button>' +
                  '<button type="button" class="btn sm danger" data-v3="load-return-reject" data-request-id="' +
                  escapeHtml(ev.id) +
                  '">Reject</button>'
                : canApprove && self
                  ? '<span class="muted">Self-approval diblokir</span>'
                  : "";
            return (
              '<div class="v3-return-pending">' +
              "<div><b>Request #" +
              escapeHtml(ev.id) +
              "</b> · qty " +
              escapeHtml(ev.qty_physical) +
              " · SJ " +
              escapeHtml(ev.accurate_sj_number || ev.accurate_sj_id || "") +
              " · line " +
              escapeHtml(ev.accurate_sj_line_id || "") +
              " · actor " +
              escapeHtml(ev.actor_user_id == null ? "—" : ev.actor_user_id) +
              "</div>" +
              "<div>Alasan: " +
              escapeHtml(ev.reason || "") +
              " · foto att #" +
              escapeHtml(
                payload.evidence_attachment_id != null
                  ? payload.evidence_attachment_id
                  : ev.evidence_ref || "—",
              ) +
              " · reverses #" +
              escapeHtml(
                payload.reverses_event_id != null
                  ? payload.reverses_event_id
                  : "—",
              ) +
              "</div>" +
              (actions
                ? '<div class="row" style="margin-top:6px;gap:6px">' +
                  actions +
                  "</div>"
                : "") +
              "</div>"
            );
          })
          .join("")
      : '<p class="v49-quiet">Tidak ada pending physical return.</p>';
    const histHtml = requests.length
      ? requests
          .map(function (ev) {
            const st = L.returnRequestStatus(events, ev.id);
            const hist = L.returnApprovalHistory(events, ev.id)
              .map(function (h) {
                return (
                  "#" +
                  h.id +
                  " " +
                  h.event_type +
                  (h.actor_user_id != null ? " by " + h.actor_user_id : "")
                );
              })
              .join("; ");
            return (
              "<div>#" +
              escapeHtml(ev.id) +
              " · <b>" +
              escapeHtml(st) +
              "</b> · qty " +
              escapeHtml(ev.qty_physical) +
              (hist ? " · " + escapeHtml(hist) : "") +
              "</div>"
            );
          })
          .join("")
      : "<p>Belum ada pengajuan pengembalian.</p>";
    return (
      '<div class="v3-return-panel">' +
      '<p class="sectionlabel" style="margin-top:10px">Pending Physical Return</p>' +
      pendingHtml +
      historyList("Status & approval history", histHtml) +
      "</div>"
    );
  }

  function buildReturnRequestFormHtml() {
    const canRequest = canPerm(
      (ledgerApi() && ledgerApi().PERM_LOADING_RETURN_REQUEST) ||
        "production.delivery.loading_return.request",
    );
    if (!canRequest) return "";
    return (
      '<div class="v3-return-form" style="margin-top:10px">' +
      '<p class="sectionlabel">Ajukan Pengembalian Fisik</p>' +
      '<label>Loading event id<input id="v3-ret-event" type="number" min="1"/></label>' +
      '<label>Qty pengembalian<input id="v3-ret-qty" type="number" min="1" value="1"/></label>' +
      '<label>Alasan<input id="v3-ret-reason"/></label>' +
      '<label>Foto pengembalian (wajib)<input id="v3-ret-photo" type="file" accept="image/*"/></label>' +
      '<button type="button" class="btn sm" data-v3="load-return-submit">Submit pengajuan</button>' +
      '<p class="v49-quiet">Request tidak melepaskan qty. Approval melepaskan net Loading yang diotorisasi saja.</p>' +
      "</div>"
    );
  }

  function buildCancelFormHtml() {
    const canCancel = canPerm(
      (ledgerApi() && ledgerApi().PERM_DELIVERY_MANAGE) ||
        "production.delivery.manage",
    );
    if (!canCancel) return "";
    return (
      '<div class="v3-cancel-form" style="margin-top:10px">' +
      '<p class="sectionlabel">Batalkan Konfirmasi Loading</p>' +
      '<label>Loading event id<input id="v3-cancel-event" type="number" min="1"/></label>' +
      '<label>Qty batal<input id="v3-cancel-qty" type="number" min="1" value="1"/></label>' +
      '<label>Alasan<input id="v3-cancel-reason"/></label>' +
      '<button type="button" class="btn sm" data-v3="load-cancel-submit">Batalkan Konfirmasi</button>' +
      '<p class="v49-quiet">Hanya confirmation cancel · terbatas sisa qty event · POD tidak bisa dibalik.</p>' +
      "</div>"
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
    const linkableDesign =
      pendingDesign ||
      designs.find(
        (d) =>
          d.status === "approved" &&
          !d.bypass &&
          !d.customer_approval,
      );
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
          (p.screen_size ? " · screen " + escapeHtml(p.screen_size) : "") +
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
      escapeHtml(order.qty === "" || order.qty == null ? "Belum terverifikasi" : order.qty) +
      "</p>" +
      (order.v3Monitor && order.accurateDetailNote
        ? '<p class="v49-quiet">' + escapeHtml(order.accurateDetailNote) + "</p>"
        : "") +
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
          '<label>SO line (print)<input id="v3-design-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<button type="button" class="btn sm" data-v3="design-upload">Upload versi</button>' +
          (pendingDesign
            ? '<button type="button" class="btn sm" data-v3="design-approve">Staff review #' +
              escapeHtml(pendingDesign.id) +
              "</button>" +
              '<button type="button" class="btn sm" data-v3="design-reject">Reject</button>' +
              '<label>Bypass reason<input id="v3-design-bypass-reason"/></label>' +
              '<button type="button" class="btn sm" data-v3="design-bypass">Authorized bypass</button>'
            : "<p class=\"v49-quiet\">Tidak ada versi pending (staff)</p>") +
          (linkableDesign
            ? '<button type="button" class="btn sm" data-v3="design-link">Generate approval link #' +
              escapeHtml(linkableDesign.id) +
              "</button>"
            : "") +
          '<pre id="v3-design-link-status" class="v49-quiet"></pre>' +
          '<button type="button" class="btn sm" id="v3-design-link-copy" hidden>Copy Link</button>' +
          '<p class="v49-quiet">Gate cetak: tautan pelanggan /t/... atau bypass. Staff review saja tidak membuka jadwal.</p>' +
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
          '<button type="button" class="btn sm" data-v3="pay-revalidate">Revalidasi receipt</button>' +
          '<button type="button" class="btn sm" data-v3="pay-invalidate">Invalidate receipt</button>' +
          historyList("Riwayat payment + audit", payHist),
      ) +
      section(
        "Perubahan qty Accurate",
        driftHtml(board) +
          '<p class="v49-quiet">Qty PO V3 (snapshot job) tidak diubah otomatis. Tinjau perubahan di Accurate, lalu catat peninjauan; penyesuaian jadwal dilakukan lewat Cancel/Transfer remaining.</p>',
      ) +
      section(
        "Scheduling",
        '<div id="v3-asg-info" class="flat-notice" role="status">Memuat ringkasan qty...</div>' +
          '<label>SO line<input id="v3-asg-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>Operator (akun resmi, cabang ' + escapeHtml(order.branch || "") + ')<select id="v3-asg-op"><option value="">Memuat operator...</option></select></label>' +
          '<label>Mesin (master mesin)<select id="v3-asg-mc"><option value="">Memuat mesin...</option></select></label>' +
          '<div id="v3-asg-cap" class="v49-quiet"></div>' +
          '<label>Date<input id="v3-asg-date" type="date"/></label>' +
          '<label>Color pass<input id="v3-asg-pass" type="number" min="1" value="1"/></label>' +
          '<label>Qty planned<input id="v3-asg-qty" type="number" min="1" value="' +
          escapeHtml(order.v3Monitor && !order.qty ? "" : order.qty || 1) +
          '"/></label>' +
          '<button type="button" class="btn sm" data-v3="asg-create">Buat assignment</button>' +
          '<label>Assignment id<input id="v3-asg-id" type="number"/></label>' +
          '<button type="button" class="btn sm" data-v3="asg-cancel">Cancel remaining</button>' +
          '<label>Transfer ke operator<select id="v3-asg-top"><option value="">Memuat operator...</option></select></label>' +
          '<label>Transfer ke mesin<select id="v3-asg-tmc"><option value="">Memuat mesin...</option></select></label>' +
          '<button type="button" class="btn sm" data-v3="asg-transfer">Transfer remaining</button>' +
          historyList("Riwayat assignment", asgHist),
      ) +
      section(
        "Screener & Helper",
        '<label>SO line<input id="v3-prep-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>PO qty ceiling<input id="v3-prep-po" type="number" value="' +
          escapeHtml(order.v3Monitor && !order.qty ? "" : order.qty || 1) +
          '"/></label>' +
          '<label>Screen qty<input id="v3-prep-screen" type="number" value="1"/></label>' +
          '<label>Screen size<select id="v3-prep-screen-size"><option value="kecil">Kecil</option><option value="besar">Besar</option></select></label>' +
          '<label>Helper qty<input id="v3-prep-helper" type="number" value="' +
          escapeHtml(order.v3Monitor && !order.qty ? "" : order.qty || 1) +
          '"/></label>' +
          '<label>Evidence<input id="v3-prep-ev" value="prep-evidence"/></label>' +
          '<button type="button" class="btn sm" data-v3="prep-screen">Simpan screener</button>' +
          '<button type="button" class="btn sm" data-v3="prep-helper">Simpan helper</button>' +
          '<p class="v49-quiet">Screen Kecil/Besar wajib dari backend — bukan localStorage.</p>' +
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
          '<label>Output event id (helper verify)<input id="v3-hv-src" type="number"/></label>' +
          '<label>Helper verify qty<input id="v3-hv-qty" type="number" min="1" value="1"/></label>' +
          '<button type="button" class="btn sm" data-v3="out-helper-verify">Helper verify output</button>' +
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
          '<button type="button" class="btn sm" data-v3="pack">Confirm packing batch</button>' +
          '<p class="v49-quiet">Print: packing tidak boleh melebihi output cetak yang sudah dikonfirmasi. Non-print: packing tidak boleh melebihi qty PO. READY gudang = packing sah dikurangi loading aktif.</p>',
      ) +
      section(
        "Delivery / POD",
        loadingReadinessTable(so) +
          '<label>Accurate SJ id<input id="v3-sj-id"/></label>' +
          '<label>Accurate SJ number<input id="v3-sj-no"/></label>' +
          '<label>Accurate SJ line id<input id="v3-sj-line"/></label>' +
          '<label>SO line id<input id="v3-load-so-line" value="' +
          escapeHtml(firstLineId(order)) +
          '"/></label>' +
          '<label>Loading qty<input id="v3-load-qty" type="number" min="1" value="1"/></label>' +
          '<button type="button" class="btn sm" data-v3="load-authority">Lookup Qty SJ</button>' +
          (canPerm("production.delivery.manage")
            ? '<button type="button" class="btn sm" data-v3="load" id="v3-load-btn" disabled>Loading</button>'
            : "") +
          '<pre id="v3-load-auth-status" class="v49-quiet"></pre>' +
          '<p class="sectionlabel" style="margin-top:10px">Riwayat Loading (per event / SJ line)</p>' +
          buildLoadingLedgerHtml(events, board, so) +
          buildCancelFormHtml() +
          buildReturnRequestFormHtml() +
          buildReturnRequestPanelHtml(events) +
          '<label>POD qty (parsial OK)<input id="v3-pod-qty" type="number" min="1" value="1"/></label>' +
          '<label>Nama penerima<input id="v3-pod-recv"/></label>' +
          '<label>Foto 1<input id="v3-pod-photo1" type="file" accept="image/*"/></label>' +
          '<label>Foto 2<input id="v3-pod-photo2" type="file" accept="image/*"/></label>' +
          '<label>TTD pengirim<input id="v3-pod-sig-s" type="file" accept="image/*"/></label>' +
          '<label>TTD penerima<input id="v3-pod-sig-r" type="file" accept="image/*"/></label>' +
          (canPerm("production.delivery.manage")
            ? '<button type="button" class="btn sm" data-v3="pod">Konfirmasi POD</button>'
            : "") +
          '<pre id="v3-pod-status" class="v49-quiet"></pre>' +
          '<label>Cancel SJ reason<input id="v3-sj-cancel-reason"/></label>' +
          (canPerm("production.delivery.manage")
            ? '<button type="button" class="btn sm" data-v3="sj-cancel">Cancel/supersede SJ</button>'
            : "") +
          '<p class="v49-quiet">Loading max = min(qty packing sah, sisa SJ-line Accurate). POD resmi butuh Loading + 2 foto + 2 TTD + nama penerima.</p>',
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
    hydrateScheduling(so);
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
        window.__v3DriftLine = btn.getAttribute("data-line");
        handleAction(btn.getAttribute("data-v3"), so, order);
      });
    });
    ["v3-sj-id", "v3-sj-no", "v3-sj-line", "v3-load-so-line"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", syncLoadButtonEnabled);
      el.addEventListener("change", syncLoadButtonEnabled);
    });
    syncLoadButtonEnabled();
    const designStatus = document.getElementById("v3-design-link-status");
    if (designStatus && designStatus.textContent) {
      applyDesignLinkStatus(
        designStatus.textContent,
        designStatus.dataset.path || "",
      );
    }
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



  function driftHtml(board) {
    const lines = ((board && board.job_lines) || []).filter(function (ln) { return ln.accurate_qty != null; });
    if (!lines.length) return '<p class="v49-quiet">Tidak ada perbedaan qty dengan Accurate.</p>';
    return lines.map(function (ln) {
      return '<div class="flat-notice" role="alert"><b>Line ' + escapeHtml(ln.so_line_id) + "</b>: snapshot job V3 " + opsNum(ln.po_qty) + " ≠ Accurate terbaru " + opsNum(ln.accurate_qty) +
        (ln.drift_detected_at ? " (terdeteksi " + escapeHtml(ln.drift_detected_at.slice(0, 10)) + ")" : "") + "<br>" +
        (ln.drift_acknowledged ? "Sudah ditinjau (tercatat di audit)." :
          '<input id="v3-drift-reason-' + escapeHtml(ln.so_line_id) + '" placeholder="Alasan/tindak lanjut"> <button type="button" class="btn sm" data-v3="drift-ack" data-line="' + escapeHtml(ln.so_line_id) + '">Catat peninjauan</button>') + "</div>";
    }).join("");
  }
  const sch = { people: {}, machines: {}, couriers: {} };
  function selText(id) {
    const el = document.getElementById(id);
    return el && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : "";
  }
  function operatorFields(id) {
    const v = field(id);
    if (!v) throw new Error("Pilih operator dari daftar akun resmi terlebih dahulu");
    return { operator_user_id: Number(v), operator_name: selText(id) };
  }
  function pickMachine(id) {
    const v = field(id);
    if (!v) throw new Error("Pilih mesin dari master mesin terlebih dahulu");
    return v;
  }
  function fillSelect(id, items, labelOf, valueOf, emptyText) {
    const el = document.getElementById(id);
    if (!el) return;
    const keep = el.value;
    el.innerHTML = '<option value="">' + escapeHtml(items.length ? "— pilih —" : emptyText) + "</option>" +
      items.map(function (i) { return '<option value="' + escapeHtml(valueOf(i)) + '">' + escapeHtml(labelOf(i)) + "</option>"; }).join("");
    if (keep) el.value = keep;
  }
  function lineSummary(so) {
    const board = boardCache[so];
    if (!board) return "Ringkasan qty akan tampil setelah board dimuat.";
    const rows = (board.job_lines || []).map(function (ln) {
      const asg = (board.assignments || []).filter(function (a) { return a.so_line_id === ln.so_line_id && Number(a.color_pass) === 1; });
      const planned = asg.reduce(function (n, a) { return n + Number(a.qty_planned) - Number(a.qty_cancelled_remaining || 0); }, 0);
      const done = asg.reduce(function (n, a) { return n + Number(a.qty_confirmed || 0); }, 0);
      const po = Number(ln.po_qty);
      return "Line " + escapeHtml(ln.so_line_id) + ": PO " + opsNum(po) + " · terjadwal " + opsNum(planned) + " · belum terjadwal " + opsNum(Math.max(po - planned, 0)) + " · selesai " + opsNum(done);
    });
    return rows.length ? rows.join("<br>") : "Belum ada line PO tersinkron; jadwal akan ditolak sampai qty line tersedia.";
  }
  function showCapacity(branchId) {
    const el = document.getElementById("v3-asg-cap");
    const sel = document.getElementById("v3-asg-mc");
    if (!el || !sel) return;
    const d = sch.machines[branchId];
    const m = d && sel.value ? d.items.find(function (x) { return x.name === sel.value; }) : null;
    el.textContent = m
      ? "Kapasitas sah: " + opsNum(m.capacity_per_shift) + " per shift × " + m.shifts_per_day + " shift = " + opsNum(m.capacity_per_day) + " per hari (divalidasi backend)."
      : d && !d.enforced ? "Belum ada mesin terdaftar di cabang ini: kapasitas tidak divalidasi. Referensi default " + opsNum(d.default_capacity_per_shift) + " per shift hanya acuan." : "";
  }
  function hydrateScheduling(so) {
    const job = jobCache[so];
    const branchId = job && job.branch_id;
    const info = document.getElementById("v3-asg-info");
    if (info) info.innerHTML = lineSummary(so);
    if (!branchId) return;
    const paint = function () {
      const p = sch.people[branchId], m = sch.machines[branchId];
      if (p) { ["v3-asg-op", "v3-asg-top"].forEach(function (id) { fillSelect(id, p.items, function (i) { return i.display_name; }, function (i) { return i.id; }, "Tidak ada operator berizin di cabang ini"); }); }
      if (m) { ["v3-asg-mc", "v3-asg-tmc"].forEach(function (id) { fillSelect(id, m.items.filter(function (x) { return x.active; }), function (i) { return i.name + " (" + opsNum(i.capacity_per_shift) + "/shift)"; }, function (i) { return i.name; }, "Belum ada mesin di master mesin"); }); showCapacity(branchId); }
    };
    paint();
    if (!sch.people[branchId]) request(API + "/production/ops/assignees?kind=operator&branch=" + encodeURIComponent(branchId)).then(function (d) { sch.people[branchId] = d; paint(); }).catch(function (e) { fillSelect("v3-asg-op", [], null, null, String((e && e.message) || "Gagal memuat operator")); });
    if (!sch.machines[branchId]) request(API + "/production/ops/machines?branch=" + encodeURIComponent(branchId)).then(function (d) { sch.machines[branchId] = d; paint(); }).catch(function (e) { fillSelect("v3-asg-mc", [], null, null, String((e && e.message) || "Gagal memuat mesin")); });
    const mc = document.getElementById("v3-asg-mc");
    if (mc) mc.onchange = function () { showCapacity(branchId); };
  }

  async function handleAction(action, so, order) {
    const lock = action + ":" + so;
    const soft =
      action === "load-authority" ||
      action === "load-cancel" ||
      action === "load-return-req" ||
      action === "design-link";
    await mutate(
      lock,
      async function () {
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
            so_line_id: field("v3-design-line") || firstLineId(order),
          },
        });
        toast("Design version uploaded");
        return;
      }
      if (action === "design-link") {
        const board = boardCache[so] || (await loadBoard(so, true));
        const target =
          (board.design_versions || []).find((d) => d.status === "pending") ||
          (board.design_versions || []).find(
            (d) => d.status === "approved" && !d.bypass && !d.customer_approval,
          );
        if (!target) throw new Error("Tidak ada design untuk approval link");
        const minted = await request(
          API +
            "/production/jobs/" +
            jid +
            "/design/versions/" +
            target.id +
            "/approval-links",
          {
            method: "POST",
            body: {
              so_line_id: field("v3-design-line") || target.so_line_id || null,
            },
          },
        );
        const path = minted.path || minted.url || "";
        applyDesignLinkStatus(
          "Approval link: " +
            path +
            " · expires " +
            (minted.expires_at || "") +
            " · " +
            (minted.disclaimer || ""),
          path,
        );
        toast("Customer approval link dibuat");
        return;
      }
      if (
        action.indexOf("design-") === 0 &&
        action !== "design-upload" &&
        action !== "design-link"
      ) {
        const board = boardCache[so] || (await loadBoard(so, true));
        const pending = (board.design_versions || []).find((d) => d.status === "pending");
        if (!pending) throw new Error("Tidak ada design pending");
        const body = { decision: "approved", reason: null, bypass: false, customer_approval: false };
        if (action === "design-reject") body.decision = "rejected";
        if (action === "design-bypass") {
          body.bypass = true;
          body.reason = field("v3-design-bypass-reason");
          if (!body.reason) throw new Error("Alasan bypass wajib");
        }
        await request(
          API + "/production/jobs/design/versions/" + pending.id + "/decision",
          { method: "POST", body: body },
        );
        toast(
          body.bypass
            ? "Design bypass tersimpan"
            : "Staff review tersimpan — butuh approval link pelanggan untuk membuka gate",
        );
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
      if (action === "pay-revalidate") {
        const rid = Number(field("v3-pay-inv-id"));
        const reason = field("v3-pay-inv-reason");
        if (!rid || !reason.trim()) throw new Error("Receipt row id dan alasan wajib");
        const result = await request(API + "/production/jobs/payment/receipts/" + rid + "/revalidate", {
          method: "POST", body: { reason: reason, idempotency_key: idemKey("revalidate") },
        });
        toast(result.verified ? "Receipt terverifikasi" : "Receipt tidak terverifikasi: " + result.verification_error);
        return result;
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
      if (action === "drift-ack") {
        const line = window.__v3DriftLine;
        const reason = field("v3-drift-reason-" + line);
        if (!reason) throw new Error("Alasan peninjauan wajib diisi");
        await request(API + "/production/ops/jobs/" + jid + "/qty-drift/acknowledge", {
          method: "POST",
          body: { so_line_id: line, reason: reason, idempotency_key: idemKey("drift") },
        });
        toast("Peninjauan perubahan qty Accurate dicatat; qty PO tidak diubah");
        return;
      }
      if (action === "asg-create") {
        await request(API + "/production/jobs/" + jid + "/schedule/assignments", {
          method: "POST",
          body: {
            so_line_id: field("v3-asg-line") || firstLineId(order),
            color_pass: Number(field("v3-asg-pass") || 1),
            ...operatorFields("v3-asg-op"),
            machine_name: pickMachine("v3-asg-mc"),
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
              ...operatorFields("v3-asg-top"),
              machine_name: pickMachine("v3-asg-tmc"),
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
        const body = {
          so_line_id: field("v3-prep-line") || firstLineId(order),
          qty: field(role === "screener" ? "v3-prep-screen" : "v3-prep-helper") || "1",
          po_qty: field("v3-prep-po") || String(order.qty || 1),
          evidence_ref: field("v3-prep-ev") || "prep-evidence",
          idempotency_key: idemKey("prep"),
          assignment_id: field("v3-asg-id") ? Number(field("v3-asg-id")) : null,
        };
        if (role === "screener") {
          body.screen_size = field("v3-prep-screen-size") || "kecil";
        }
        await request(path, { method: "POST", body: body });
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
        let asg = field("v3-out-asg");
        const passNo = Number(field("v3-out-pass") || 1);
        if (!asg) {
          const board = boardCache[so] || (await loadBoard(so, true));
          const match = ((board && board.assignments) || []).find(function (a) {
            return (
              Number(a.color_pass) === passNo &&
              (a.status === "active" || a.status === "completed")
            );
          });
          if (match) {
            asg = String(match.id);
            const el = document.getElementById("v3-out-asg");
            if (el) el.value = asg;
          }
        }
        if (!asg) throw new Error("Assignment id wajib");
        await request(API + "/production/jobs/" + jid + "/outputs", {
          method: "POST",
          body: {
            assignment_id: Number(asg),
            qty_physical: field("v3-out-qty") || "1",
            color_pass: passNo,
            lot_code: field("v3-out-lot") || null,
            idempotency_key: idemKey("out"),
          },
        });
        toast("Output confirmed");
        return;
      }
      if (action === "out-helper-verify") {
        const src = field("v3-hv-src");
        if (!src) throw new Error("Output event id wajib untuk helper verify");
        await request(
          API +
            "/production/jobs/" +
            jid +
            "/outputs/" +
            Number(src) +
            "/helper-verifications",
          {
            method: "POST",
            body: {
              source_output_event_id: Number(src),
              qty_physical: field("v3-hv-qty") || "1",
              idempotency_key: idemKey("hv"),
            },
          },
        );
        toast("Helper verification tersimpan");
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
      if (action === "load-authority") {
        const sjId = field("v3-sj-id");
        const sjNo = field("v3-sj-no");
        const sjLine = field("v3-sj-line");
        const soLine = field("v3-load-so-line") || firstLineId(order);
        if (!sjId || !sjNo || !sjLine || !soLine) {
          throw new Error("SJ id, nomor, line id, dan SO line wajib untuk lookup");
        }
        const auth = await request(
          API +
            "/production/jobs/" +
            jid +
            "/loading-authority?" +
            new URLSearchParams({
              accurate_sj_id: sjId,
              accurate_sj_number: sjNo,
              accurate_sj_line_id: sjLine,
              so_line_id: soLine,
            }).toString(),
        );
        const L = ledgerApi();
        const view =
          L && L.viewSjLineAuthority
            ? L.viewSjLineAuthority(auth)
            : { displayQtySj: "UNKNOWN", displayRemaining: "UNKNOWN", actionsEnabled: false };
        const statusEl = document.getElementById("v3-load-auth-status");
        if (statusEl) {
          statusEl.textContent =
            "Qty SJ " +
            view.displayQtySj +
            " · Confirmed " +
            (auth.loading_confirmed || "0") +
            " · Cancelled " +
            (auth.loading_cancelled || "0") +
            " · Net " +
            (auth.loading_net || "0") +
            " · Sisa SJ " +
            view.displayRemaining +
            " · Qty siap sah " +
            (auth.packed_qty != null ? auth.packed_qty : "UNKNOWN") +
            " · Tersedia Loading " +
            (auth.loading_available != null ? auth.loading_available : "UNKNOWN") +
            (view.actionsEnabled ? " · Loading OK" : " · Loading DISABLED (UNKNOWN)");
        }
        const loadBtn = document.getElementById("v3-load-btn");
        if (loadBtn) loadBtn.disabled = !view.actionsEnabled;
        if (!boardCache[so]) boardCache[so] = { events: [] };
        const list = authorityRows(boardCache[so], so).slice();
        const idx = list.findIndex(function (r) {
          return (
            String(r.accurate_sj_id) === String(auth.accurate_sj_id) &&
            String(r.accurate_sj_line_id) === String(auth.accurate_sj_line_id) &&
            String(r.so_line_id) === String(auth.so_line_id)
          );
        });
        if (idx >= 0) list[idx] = auth;
        else list.push(auth);
        authorityOverlay[so] = list;
        if (!boardCache[so]) boardCache[so] = { events: [] };
        boardCache[so].sj_line_authority = list;
        toast(
          view.actionsEnabled
            ? "Qty SJ terverifikasi: " + view.displayQtySj
            : "Qty SJ UNKNOWN — aksi Loading dinonaktifkan",
        );
        return;
      }
      if (action === "load") {
        if (!canPerm("production.delivery.manage")) {
          throw new Error("Tidak berwenang Loading");
        }
        const sjId = field("v3-sj-id");
        const sjNo = field("v3-sj-no");
        const sjLine = field("v3-sj-line");
        const soLine = field("v3-load-so-line") || firstLineId(order);
        if (!sjId || !sjNo || !sjLine || !soLine) {
          throw new Error("SJ id, nomor, line id, dan SO line wajib");
        }
        const L = ledgerApi();
        let authView =
          L && L.findLineAuthority
            ? L.findLineAuthority(authorityRows(boardCache[so], so), sjId, sjLine, soLine)
            : null;
        if (!authView || !authView.actionsEnabled) {
          const auth = await request(
            API +
              "/production/jobs/" +
              jid +
              "/loading-authority?" +
              new URLSearchParams({
                accurate_sj_id: sjId,
                accurate_sj_number: sjNo,
                accurate_sj_line_id: sjLine,
                so_line_id: soLine,
              }).toString(),
          );
          authView = L && L.viewSjLineAuthority ? L.viewSjLineAuthority(auth) : null;
        }
        if (!authView || !authView.actionsEnabled) {
          throw new Error(
            "Qty SJ UNKNOWN/unverified — Loading diblokir (tidak mengada-ada qty)",
          );
        }
        await request(API + "/production/jobs/" + jid + "/loading", {
          method: "POST",
          body: {
            accurate_sj_id: sjId,
            accurate_sj_number: sjNo,
            accurate_sj_line_id: sjLine,
            so_line_id: soLine,
            qty_physical: field("v3-load-qty") || "1",
            idempotency_key: idemKey("load"),
          },
        });
        toast("Loading tersimpan");
        return;
      }
      if (action === "load-cancel") {
        const eid = btn.getAttribute("data-event-id");
        const cancelEl = document.getElementById("v3-cancel-event");
        if (cancelEl && eid) cancelEl.value = eid;
        toast("Event #" + eid + " dipilih — isi qty/alasan lalu Batalkan Konfirmasi");
        return;
      }
      if (action === "load-return-req") {
        const eid = btn.getAttribute("data-event-id");
        const retEl = document.getElementById("v3-ret-event");
        if (retEl && eid) retEl.value = eid;
        toast("Event #" + eid + " dipilih — isi qty/alasan/foto lalu Submit pengajuan");
        return;
      }
      if (action === "load-cancel-submit") {
        if (!canPerm("production.delivery.manage")) {
          throw new Error("Tidak berwenang batalkan konfirmasi Loading");
        }
        const eid = field("v3-cancel-event");
        const reason = field("v3-cancel-reason");
        if (!eid || !reason) throw new Error("Event id dan alasan wajib");
        await request(
          API + "/production/jobs/" + jid + "/loading/" + eid + "/cancel",
          {
            method: "POST",
            body: {
              qty_physical: field("v3-cancel-qty") || "1",
              reason: reason,
              cancel_kind: "confirmation_cancel",
              idempotency_key: idemKey("lcxl"),
            },
          },
        );
        toast("Konfirmasi Loading dibatalkan (append-only)");
        return;
      }
      if (action === "load-return-submit") {
        if (
          !canPerm(
            (ledgerApi() && ledgerApi().PERM_LOADING_RETURN_REQUEST) ||
              "production.delivery.loading_return.request",
          )
        ) {
          throw new Error("Tidak berwenang ajukan pengembalian");
        }
        const eid = field("v3-ret-event");
        const reason = field("v3-ret-reason");
        if (!eid || !reason) throw new Error("Event id dan alasan wajib");
        const photoEl = document.getElementById("v3-ret-photo");
        const file = photoEl && photoEl.files && photoEl.files[0];
        if (!file) throw new Error("Foto pengembalian wajib");
        const boardEv = ((boardCache[so] && boardCache[so].events) || []).find(
          function (e) {
            return String(e.id) === String(eid);
          },
        );
        const sjId =
          field("v3-sj-id") ||
          (boardEv && boardEv.accurate_sj_id) ||
          "";
        if (!sjId) throw new Error("Accurate SJ id wajib (isi form atau pilih event Loading)");
        const fd = new FormData();
        fd.append("accurate_sj_id", sjId);
        fd.append("purpose", "loading_return_photo");
        fd.append("file", file, file.name || "return.png");
        const uploaded = await request(
          API + "/production/jobs/" + jid + "/attachments",
          { method: "POST", formData: fd },
        );
        await request(
          API +
            "/production/jobs/" +
            jid +
            "/loading/" +
            eid +
            "/return-requests",
          {
            method: "POST",
            body: {
              qty_physical: field("v3-ret-qty") || "1",
              reason: reason,
              evidence_attachment_id: uploaded.id,
              idempotency_key: idemKey("lret"),
            },
          },
        );
        toast("Pengajuan physical return terkirim (qty belum dilepas)");
        return;
      }
      if (action === "load-return-approve" || action === "load-return-reject") {
        if (
          !canPerm(
            (ledgerApi() && ledgerApi().PERM_LOADING_RETURN_APPROVE) ||
              "production.delivery.loading_return.approve",
          )
        ) {
          throw new Error("Tidak berwenang approve/reject physical return");
        }
        const rid = btn.getAttribute("data-request-id");
        if (!rid) throw new Error("Request id wajib");
        const isReject = action === "load-return-reject";
        let reason = null;
        if (isReject) {
          reason = window.prompt("Alasan penolakan physical return:");
          if (!reason || !String(reason).trim()) {
            throw new Error("Alasan penolakan wajib");
          }
        }
        await request(
          API +
            "/production/jobs/" +
            jid +
            "/loading/return-requests/" +
            rid +
            "/" +
            (isReject ? "reject" : "approve"),
          {
            method: "POST",
            body: {
              idempotency_key: idemKey(isReject ? "lrej" : "lapr"),
              reason: reason,
            },
          },
        );
        toast(
          isReject
            ? "Physical return ditolak"
            : "Physical return disetujui — qty Loading dilepas",
        );
        return;
      }
      if (action === "pod") {
        const sjId = field("v3-sj-id");
        const recv = field("v3-pod-recv");
        if (!sjId || !recv) throw new Error("SJ id dan nama penerima wajib");
        const files = [
          ["pod_photo_1", "v3-pod-photo1"],
          ["pod_photo_2", "v3-pod-photo2"],
          ["pod_sig_sender", "v3-pod-sig-s"],
          ["pod_sig_recipient", "v3-pod-sig-r"],
        ];
        const ids = {};
        for (let i = 0; i < files.length; i++) {
          const purpose = files[i][0];
          const el = document.getElementById(files[i][1]);
          const file = el && el.files && el.files[0];
          if (!file) throw new Error("Wajib unggah " + purpose);
          const fd = new FormData();
          fd.append("accurate_sj_id", sjId);
          fd.append("purpose", purpose);
          fd.append("file", file, file.name || purpose + ".png");
          const uploaded = await request(
            API + "/production/jobs/" + jid + "/attachments",
            { method: "POST", formData: fd },
          );
          ids[purpose] = uploaded.id;
        }
        const pod = await request(API + "/production/jobs/" + jid + "/pod", {
          method: "POST",
          body: {
            accurate_sj_id: sjId,
            qty_physical: field("v3-pod-qty") || "1",
            receiver_name: recv,
            idempotency_key: idemKey("pod"),
            attachment_pod_photo_1: ids.pod_photo_1,
            attachment_pod_photo_2: ids.pod_photo_2,
            attachment_pod_sig_sender: ids.pod_sig_sender,
            attachment_pod_sig_recipient: ids.pod_sig_recipient,
          },
        });
        const statusEl = document.getElementById("v3-pod-status");
        if (statusEl) {
          statusEl.textContent =
            "POD #" + pod.id + " OK · attachments " + JSON.stringify(ids);
        }
        toast("POD tersimpan (4 lampiran terikat)");
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
        window.v3LastPayrollRunId = run.id;
        toast("Payroll run #" + run.id);
        return;
      }
      throw new Error("Aksi tidak dikenali: " + action);
    },
      { soft: soft, so: so, payment: action.indexOf("pay-") === 0 },
    ).catch(function () {
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

  function renderPoSummaryDrawer(number) {
    const o = orderBySo(number);
    if (!o) return;
    selectedSo = number;
    const modal = document.getElementById("modal");
    const st = o.detailLoadState || "not_loaded";
    const lines = Array.isArray(o.sourceLines) ? o.sourceLines : [];
    const field = function (label, value, fallback) {
      const empty =
        value == null ||
        !String(value).trim() ||
        ["—", "-", "Belum terverifikasi", "Belum tersedia"].includes(
          String(value).trim(),
        );
      let shown;
      if (!empty) shown = escapeHtml(String(value));
      else if (st === "loading") shown = '<span class="muted">Memuat…</span>';
      else if (st === "failed")
        shown =
          '<span class="muted">Gagal dimuat</span> <button type="button" class="btn sm" onclick="window.retryInboxDetail&&window.retryInboxDetail(\'' +
          escapeHtml(number) +
          "');window.v49PODetail('" +
          escapeHtml(number) +
          "')\">Retry</button>";
      else if (st !== "loaded") shown = '<span class="muted">Belum dimuat</span>';
      else shown = '<span class="muted">' + escapeHtml(fallback || "Belum tersedia") + "</span>";
      return (
        "<div><small>" +
        escapeHtml(label) +
        "</small><b>" +
        shown +
        "</b></div>"
      );
    };
    let lineRows;
    if (st === "loading" && !lines.length) {
      lineRows =
        '<tr><td colspan="6"><span class="muted">Memuat rincian produk…</span></td></tr>';
    } else if (st === "failed" && !lines.length) {
      lineRows =
        '<tr><td colspan="6"><span class="muted">Gagal dimuat</span></td></tr>';
    } else if (st !== "loaded" && !lines.length) {
      lineRows =
        '<tr><td colspan="6"><span class="muted">Detail barang belum dimuat</span></td></tr>';
    } else {
      lineRows =
        lines
          .map(function (x) {
            return (
              "<tr><td>" +
              escapeHtml(x.item_code || "—") +
              "</td><td>" +
              escapeHtml(x.name || "—") +
              "</td><td>" +
              escapeHtml(x.qty == null ? "—" : String(x.qty)) +
              "</td><td>" +
              escapeHtml(x.unit || "—") +
              "</td><td>" +
              escapeHtml(processLabel(x.production_process)) +
              "</td><td>" +
              escapeHtml(x.color || "—") +
              "</td></tr>"
            );
          })
          .join("") ||
        '<tr><td colspan="6">Belum ada rincian produk</td></tr>';
    }
    const qtyHtml = o.qtyVerified
      ? escapeHtml(String(o.qty)) + " pcs"
      : st === "loading"
        ? "Memuat…"
        : st === "failed"
          ? "Gagal dimuat"
          : st === "loaded"
            ? "Qty belum terverifikasi"
            : "Belum dimuat";
    const jenisHtml =
      o.qtyVerified && (o.lineCount != null || lines.length)
        ? escapeHtml(String(o.lineCount != null ? o.lineCount : lines.length))
        : st === "loading"
          ? "Memuat…"
          : st === "failed"
            ? "Gagal dimuat"
            : st === "loaded"
              ? "—"
              : "Belum dimuat";
    const sales =
      o.salesName && o.salesName !== "Belum terverifikasi" ? o.salesName : null;
    const prio =
      o.orderPriority === "Urgent" || o.orderPriority === "Normal"
        ? o.orderPriority
        : null;
    const buf =
      o.bufferLabel === "Buffer" || o.bufferLabel === "Non-Buffer"
        ? o.bufferLabel
        : null;
    modal.innerHTML =
      '<div class="drawerback" id="v49-po-detail-back" onclick="if(event.target===this)v49Close()"><aside class="detaildrawer shipping-drawer" role="dialog" aria-modal="true" aria-label="Ringkasan PO ' +
      escapeHtml(o.id) +
      '" onclick="event.stopPropagation()"><div class="drawerhead"><div><div class="eyebrow">RINGKASAN PO · READ ONLY</div><h2>' +
      escapeHtml(o.id) +
      "</h2><small>" +
      escapeHtml(o.name || "") +
      '</small></div><button class="btn sm" type="button" onclick="v49Close()">✕ Tutup</button></div><div class="drawerbody"><div class="meta">' +
      "<div><small>Tanggal PO</small><b>" +
      escapeHtml(o.orderDate || "—") +
      "</b></div>" +
      "<div><small>Pelanggan</small><b>" +
      escapeHtml(o.name || "—") +
      "</b></div>" +
      field("Alamat pengiriman", o.address) +
      field("Sales", sales, "Belum terverifikasi") +
      field("Metode Pengiriman", o.expedition) +
      field("Estimasi pengiriman", o.ship) +
      field("Zona Pengiriman", o.deliveryZone) +
      "<div><small>Cabang</small><b>" +
      escapeHtml(o.branch || "—") +
      "</b></div>" +
      field("Status Pesanan", prio, "Belum terverifikasi") +
      field("Buffer / Non-Buffer", buf, "Belum terverifikasi") +
      "<div><small>Total Qty PO</small><b>" +
      qtyHtml +
      "</b></div>" +
      "<div><small>Jumlah jenis barang</small><b>" +
      jenisHtml +
      "</b></div></div><div class=\"sectionlabel\">Keterangan PO</div><div class=\"po-notes\" style=\"white-space:pre-wrap\">" +
      (o.poNotes && String(o.poNotes).trim()
        ? escapeHtml(o.poNotes).replace(/\n/g, "<br>")
        : st === "loading"
          ? '<span class="muted">Memuat…</span>'
          : st === "failed"
            ? '<span class="muted">Gagal dimuat</span>'
            : st === "loaded"
              ? '<span class="muted">—</span>'
              : '<span class="muted">Belum dimuat</span>') +
      '</div><div class="sectionlabel">Daftar item</div><div class="v26-scroll"><table><thead><tr><th>Kode</th><th>Nama</th><th>Qty</th><th>Satuan</th><th>Proses</th><th>Warna</th></tr></thead><tbody>' +
      lineRows +
      '</tbody></table></div><div class="v49-quiet">Ringkasan monitoring saja — tanpa mutasi workflow. Sales dari salesman Accurate, bukan user pembuat.</div></div><div class="drawerfoot"><button class="btn" type="button" onclick="v49Close()">Tutup</button><button class="btn primary" type="button" onclick="v49Close();v36OpenTracking(' +
      JSON.stringify(number) +
      ')">Live Tracking</button></div></aside></div>';
    if (!window.__v49EscapeBound) {
      window.__v49EscapeBound = true;
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && document.getElementById("v49-po-detail-back")) {
          ev.preventDefault();
          window.v49Close();
        }
      });
    }
  }

  // Step 158: Detail/Ringkasan PO — read-only, uses inbox/enrich data (no workflow mutation).
  window.v49PODetail = async function (number) {
    const o = orderBySo(number);
    if (!o) return;
    selectedSo = number;
    if (
      !isPreviewFixture() &&
      o.detailLoadState !== "loaded" &&
      o.detailLoadState !== "loading" &&
      typeof window.retryInboxDetail === "function"
    ) {
      try {
        window.retryInboxDetail(number);
      } catch (_) {}
    }
    renderPoSummaryDrawer(number);
  };

  window.v49Close = function () {
    const modal = document.getElementById("modal");
    const back = modal && modal.querySelector(".drawerback");
    const reduce =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finish = () => {
      if (modal) modal.innerHTML = "";
      selectedSo = null;
    };
    if (back && !reduce) {
      back.classList.add("v165-closing");
      clearTimeout(back._v165c);
      back._v165c = setTimeout(finish, 160);
      return;
    }
    finish();
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
    status.textContent = isPreviewFixture()
      ? "PREVIEW SIMULASI/FIXTURE — bukan Accurate Live • halaman " +
        inboxPage +
        " • " +
        (Array.isArray(window.orders) ? window.orders.length : 0) +
        " PO fixture"
      : loading
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
    window.v3ApplyConnectionStatus();

    // Step 163: remove global Accurate pager (Halaman Accurate / Prev / Next / Refresh)
    // on every V3 page. Keep refreshInbox() API for programmatic sync — no UI chrome.
    const legacyPager = document.getElementById("v3-inbox-tools");
    if (legacyPager) legacyPager.remove();
    root
      .querySelectorAll(
        "#v3-inbox-prev, #v3-inbox-next, #v3-inbox-refresh, .v3-inbox-pager, .v3-inbox-pager-label",
      )
      .forEach(function (el) {
        el.remove();
      });

    root.querySelectorAll(".demo").forEach((x) => x.remove());
    root.querySelectorAll(".v36-sectionhead small").forEach((x) => {
      x.textContent = isPreviewFixture()
        ? "DATA SIMULASI/FIXTURE — bukan Accurate Live"
        : "Data hanya dari API Accurate; bukan fixture";
    });
    root
      .querySelectorAll('button[onclick*="v36SimulateReceipt"]')
      .forEach((x) => x.remove());
    root
      .querySelectorAll('button[onclick*="resetDemo"]')
      .forEach((x) => x.remove());

    // Step 158: do not inject legacy "V3" workflow buttons on Inbox rows.
    root.querySelectorAll(".v3-open-wf").forEach(function (btn) {
      const cell = btn.closest("td");
      if (cell) cell.remove();
      else btn.remove();
    });
    return result;
  };

  async function refreshInbox(page) {
    if (loading) return;
    if (isPreviewFixture()) {
      inboxPage = page || 1;
      seedPreviewFixtureOrders();
      if (typeof window.render === "function") window.render();
      return;
    }
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
    connDispatch({ t: "inbox_start" });
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
      // Detail cache only for current page numbers (stale isolation).
      Object.keys(detailCache).forEach(function (so) {
        if (!orderBySo(so)) delete detailCache[so];
      });
      Object.keys(detailInflight).forEach(function (so) {
        if (!orderBySo(so)) delete detailInflight[so];
      });
      window.taskEntries = {};
      // Do not assign window.history — browser History API is read-only.
      lastSync = new Date().toLocaleTimeString("id-ID");
      connDispatch({ t: "inbox_ok", at: lastSync });
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
      connDispatch({ t: "inbox_fail", kind: (err && err.kind) || "other" });
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
    if (state === "partial") return "Loading Parsial";
    return "Menunggu";
  }

  function loadingReadinessTable(soNumber) {
    const row = (window.__V3_OFFICIAL_TASKS__ || []).find(function (item) {
      return item && item.o && item.o.id === soNumber && item.t && item.t.id === "loading";
    });
    const lines = row && row.official && row.official.lines;
    if (!lines || !lines.length) {
      return '<p class="v49-quiet">Kesiapan loading per line belum terverifikasi.</p>';
    }
    const body = lines
      .map(function (ln) {
        const ready = ln.ready_qty == null ? "Belum terverifikasi" : String(ln.ready_qty);
        const sj = ln.sj_remaining_qty == null ? "Belum terverifikasi" : String(ln.sj_remaining_qty);
        return (
          "<tr><td>" +
          escapeHtml(ln.so_line_id || "—") +
          "</td><td>" +
          escapeHtml(ln.production_process || "—") +
          "</td><td>" +
          escapeHtml(ln.status || "Belum terverifikasi") +
          "</td><td>" +
          escapeHtml(ready) +
          "</td><td>" +
          escapeHtml(sj) +
          "</td></tr>"
        );
      })
      .join("");
    return (
      '<p class="sectionlabel">Kesiapan loading per line</p><div class="v36-table-container"><table class="v36-table"><thead><tr><th>SO line</th><th>Proses</th><th>Status</th><th>Ready qty</th><th>Sisa SJ</th></tr></thead><tbody>' +
      body +
      "</tbody></table></div>"
    );
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

  async function refreshOfficialTasks(pageOrders, readOnly) {
    const epoch = paymentEpoch;
    const sequence = ++taskRequestSequence;
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
    window.__V3_OFFICIAL_TASK_ERROR__ = null;
    try {
      body = await request(API + "/production/jobs/tasks", {
        method: "POST",
        body: {
          so_numbers: soNumbers.length ? soNumbers : null,
          sync_ensure: !readOnly && jobs.length > 0,
          jobs: !readOnly && jobs.length ? jobs : null,
        },
      });
    } catch (err) {
      // Read-only GET if create permission missing — still official, never FLOW31.
      try {
        const q =
          API +
          "/production/jobs/tasks" +
          (soNumbers.length
            ? "?so=" + encodeURIComponent(soNumbers.join(","))
            : "");
        body = await request(q);
      } catch (err2) {
        if (epoch !== paymentEpoch || sequence !== taskRequestSequence) return null;
        window.__V3_OFFICIAL_TASK_SOURCE__ = null;
        window.__V3_OFFICIAL_TASKS__ = [];
        window.__V3_OFFICIAL_TASK_ERROR__ =
          (err2 && err2.message) ||
          (err && err.message) ||
          "Gagal memuat /production/jobs/tasks";
        if (typeof window.render === "function") window.render();
        throw err2;
      }
    }
    if (epoch !== paymentEpoch || sequence !== taskRequestSequence) return null;
    window.__V3_OFFICIAL_TASK_SOURCE__ = body && body.source;
    window.__V3_OFFICIAL_TASKS__ = mapOfficialTaskRows((body && body.tasks) || []);
    window.__V3_OFFICIAL_TASK_ERROR__ = null;
    let selectedPaymentChanged = false;
    (body && body.jobs ? body.jobs : []).forEach(function (job) {
      if (!job) return;
      const previous = jobCache[job.accurate_so_number];
      if (!previous || previous.payment_status !== job.payment_status) {
        delete boardCache[job.accurate_so_number];
        if (selectedSo === job.accurate_so_number) selectedPaymentChanged = true;
      }
      jobCache[job.accurate_so_number] = job;
      const o = orderBySo(job.accurate_so_number);
      if (o) syncOrderGatesFromJob(o, job);
    });
    if (selectedPaymentChanged && selectedSo) {
      const so = selectedSo;
      const draft = snapshotDeliveryDraft();
      renderWorkflowDrawer(so);
      restoreDeliveryDraft(draft);
      await loadBoard(so, true);
      if (selectedSo === so && epoch === paymentEpoch && sequence === taskRequestSequence) {
        renderWorkflowDrawer(so);
        restoreDeliveryDraft(draft);
      }
    }
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


  // Operational (non-preview) views for features without an official backend list.
  // Preview fixture keeps the original demo views, isolated by epv3_preview=fixture.
  function notOperational(title, desc, text) {
    const h = typeof window.heading === "function" ? window.heading : function (t, d) { return "<h1>" + t + "</h1><p>" + d + "</p>"; };
    return h(title, desc) + "<div class=\"flat-notice\" role=\"status\"><b>Belum tersedia secara operasional.</b> " + text + "</div>";
  }
  function guardDemoView(name, build) {
    if (typeof window[name] !== "function") return;
    const original = window[name];
    window[name] = function () {
      return isPreviewFixture() ? original.apply(this, arguments) : build.apply(this, arguments);
    };
  }
  const ops = { ts: {}, plan: null, payroll: null, couriers: {}, del: null, rep: null, slip: null, unsynced: null, err: {}, busy: {}, slipId: "", status: "", from: "", to: "" };
  const OPS_TTL_MS = 4000;
  function opsLoad(key, url, assign) {
    if (ops.busy[key]) return;
    ops.busy[key] = true; ops.err[key] = "";
    request(API + url).then(function (d) { assign(d); }).catch(function (e) {
      assign(null); ops.err[key] = String((e && e.message) || "Gagal memuat");
    }).then(function () {
      ops.busy[key] = false; ops.ts[key] = Date.now();
      if (typeof window.render === "function") window.render();
    });
  }
  function opsStale(key) { return !ops.busy[key] && (!ops.ts[key] || Date.now() - ops.ts[key] > OPS_TTL_MS); }
  function opsHead(title, desc) {
    const h = typeof window.heading === "function" ? window.heading : function (t, d) { return "<h1>" + t + "</h1><p>" + d + "</p>"; };
    return h(title, desc);
  }
  function opsNum(v) { const n = Number(v); return Number.isFinite(n) ? n.toLocaleString("id-ID") : "—"; }
  function opsDash(v) { return v == null || v === "" ? '<span class="muted">Belum tersedia</span>' : escapeHtml(String(v)); }
  const DEL_STATUS = { belum_dikirim: "Belum dikirim", sebagian: "Sebagian", terkirim: "Terkirim", dibatalkan: "Dibatalkan" };
  const DEL_SCHEDULE = { belum_dijadwalkan: "Belum dijadwalkan", terjadwal: "Terjadwal", hari_ini: "Hari ini", terlambat: "Terlambat" };
  guardDemoView("shippingScheduleView", function () {
    if (opsStale("del") && !ops.err.del) opsLoad("del", "/production/ops/deliveries" + (ops.status ? "?status=" + encodeURIComponent(ops.status) : ""), function (d) { ops.del = d; });
    const d = ops.del;
    let body;
    if (ops.err.del) body = '<div class="flat-notice" role="alert">' + escapeHtml(ops.err.del) + ' <button type="button" class="btn sm" data-ops="del-reload">Coba lagi</button></div>';
    else if (!d) body = '<div class="flat-notice" role="status">Memuat jadwal pengiriman...</div>';
    else if (!d.items.length) body = '<div class="flat-notice">Belum ada SJ yang sudah di-loading pada cabang Anda.</div>';
    else body = '<div class="v36-table-container"><table class="v36-table"><thead><tr><th>PO</th><th>SJ</th><th>Pelanggan</th><th>Cabang</th><th>Alamat / penerima</th><th>Tgl rencana</th><th>Kurir</th><th>Qty SJ</th><th>Loading</th><th>Terkirim</th><th>Sisa kirim</th><th>Status</th><th>SLA</th><th>Aksi</th></tr></thead><tbody>' +
      d.items.map(function (r) {
        const sla = r.sla && r.sla.date ? r.sla.date : null;
        const act = r.delivery_status === "terkirim" || r.delivery_status === "dibatalkan" ? "" :
          '<button type="button" class="btn sm" data-ops="plan" data-jid="' + escapeHtml(r.job_id) + '" data-sj="' + escapeHtml(r.accurate_sj_id) + '" data-courier="' + escapeHtml(r.courier_user_id == null ? "" : r.courier_user_id) + '" data-so="' + escapeHtml(r.accurate_so_number) + '" data-branch="' + escapeHtml(r.branch_id) + '" data-date="' + escapeHtml(r.planned_date || "") + '">' + (r.planned_date ? "Jadwal ulang" : "Jadwalkan") + "</button>";
        return "<tr><td><b>" + escapeHtml(r.accurate_so_number) + "</b></td><td>" + opsDash(r.accurate_sj_number) + "</td><td>" + opsDash(r.customer_name) + "</td><td>" + opsDash(r.branch_id) + "</td><td>" + (r.address || r.recipient_name ? escapeHtml([r.address, r.recipient_name].filter(Boolean).join(" · ")) : '<span class="muted">Belum tersedia</span>') + "</td><td>" + opsDash(r.planned_date) + "</td><td>" + opsDash(r.courier_name) + "</td><td>" + opsNum(r.qty_sj) + "</td><td>" + opsNum(r.qty_loaded) + "</td><td>" + opsNum(r.qty_delivered) + "</td><td>" + opsNum(r.qty_remaining_to_deliver) + "</td><td>" + escapeHtml(DEL_STATUS[r.delivery_status] || r.delivery_status) + " · " + escapeHtml(DEL_SCHEDULE[r.schedule_status] || r.schedule_status) + (r.po_complete ? " · PO selesai" : "") + "</td><td>" + opsDash(sla) + "</td><td>" + act + "</td></tr>";
      }).join("") + "</tbody></table></div><small>Alamat belum tersedia dan tidak menjadi syarat jadwal, Loading, atau POD; penerima hanya tampil dari POD (" + escapeHtml((d.coverage || "")) + ").</small>";
    let planForm = "";
    if (ops.plan) {
      const cs = ops.couriers[ops.plan.branch];
      planForm = '<section class="flat-notice" id="v3-plan-form"><b>' + (ops.plan.date ? "Jadwal ulang" : "Jadwalkan") + " SJ " + escapeHtml(ops.plan.sj) + " · PO " + escapeHtml(ops.plan.so) + '</b><br><label>Tanggal <input id="v3-plan-date" type="date" value="' + escapeHtml(ops.plan.date) + '"></label> <label>Kurir <select id="v3-plan-courier"><option value="">' + (cs ? (cs.length ? "— belum ditentukan —" : "Tidak ada akun kurir berizin") : "Memuat...") + "</option>" + (cs || []).map(function (c) { return '<option value="' + escapeHtml(c.id) + '"' + (String(c.id) === String(ops.plan.courier) ? " selected" : "") + ">" + escapeHtml(c.display_name) + "</option>"; }).join("") + "</select></label> " + (ops.plan.date ? '<label>Alasan <input id="v3-plan-reason" placeholder="wajib"></label> ' : '<input id="v3-plan-reason" type="hidden" value="">') + '<button type="button" class="btn sm" data-ops="plan-save">Simpan</button> <button type="button" class="btn sm" data-ops="plan-cancel">Batal</button></section>';
    }
    return opsHead("Jadwal Pengiriman", "Daftar SJ dari event Loading/POD resmi V3") + planForm +
      '<div class="v36-toolbar"><label>Status <select id="v3-ops-status">' + [["", "Semua"], ["belum_dikirim", "Belum dikirim"], ["sebagian", "Sebagian"], ["terkirim", "Terkirim"], ["terlambat", "Terlambat"]].map(function (o) { return '<option value="' + o[0] + '"' + (ops.status === o[0] ? " selected" : "") + ">" + o[1] + "</option>"; }).join("") + '</select></label> <button type="button" class="btn sm" data-ops="del-reload">Muat ulang</button></div>' + body;
  });
  guardDemoView("salarySlipView", function () {
    if (opsStale("payroll") && !ops.err.payroll) opsLoad("payroll", "/production/ops/payroll/runs", function (d) { ops.payroll = d; });
    const runs = ops.payroll && ops.payroll.items.length ? '<div class="v36-table-container"><table class="v36-table"><thead><tr><th>Run</th><th>Status</th><th>Cabang</th><th>Periode</th><th>Total bruto (Rp)</th><th>Aksi</th></tr></thead><tbody>' + ops.payroll.items.map(function (r) { return "<tr><td>#" + escapeHtml(r.id) + "</td><td>" + escapeHtml(r.status) + "</td><td>" + opsDash(r.branch_id) + "</td><td>" + escapeHtml(r.period_start) + " s/d " + escapeHtml(r.period_end) + "</td><td>" + opsNum(r.amount_gross_total) + '</td><td><button type="button" class="btn sm" data-ops="slip" data-id="' + escapeHtml(r.id) + '">Buka</button></td></tr>'; }).join("") + "</tbody></table></div>" : ops.err.payroll ? '<div class="flat-notice" role="alert">' + escapeHtml(ops.err.payroll) + "</div>" : ops.payroll ? '<div class="flat-notice">Belum ada payroll run resmi.</div>' : '<div class="flat-notice">Memuat daftar payroll run...</div>';
    let body = runs + '<div class="flat-notice">Masukkan nomor payroll run resmi. Nominal berasal dari backend (payroll/runs); komponen harian dan lembur belum diverifikasi V1 dan tidak dihitung.</div>' +
      '<form class="v36-toolbar" id="v3-slip-form"><label>Run # <input id="v3-slip-id" type="number" min="1" value="' + escapeHtml(ops.slipId) + '"></label> <button class="btn sm" type="submit">Tampilkan</button></form>';
    if (ops.err.slip) body += '<div class="flat-notice" role="alert">' + escapeHtml(ops.err.slip) + "</div>";
    else if (ops.busy.slip) body += '<div class="flat-notice">Memuat...</div>';
    else if (ops.slip) {
      const r = ops.slip;
      body += "<h3>Run #" + escapeHtml(r.id) + " · " + escapeHtml(r.status) + " · " + escapeHtml(r.period_start) + " s/d " + escapeHtml(r.period_end) + '</h3><div class="v36-table-container"><table class="v36-table"><thead><tr><th>Operator</th><th>Cabang</th><th>Qty 1</th><th>Qty 2</th><th>Qty 3</th><th>Qty 4</th><th>Screen</th><th>Total (Rp)</th></tr></thead><tbody>' +
        r.lines.map(function (l) { return "<tr><td>" + escapeHtml(l.operator_name) + "</td><td>" + escapeHtml(l.branch_id) + "</td><td>" + opsNum(l.qty_one) + "</td><td>" + opsNum(l.qty_two) + "</td><td>" + opsNum(l.qty_three) + "</td><td>" + opsNum(l.qty_four) + "</td><td>" + opsNum(l.qty_screen) + "</td><td>" + opsNum(l.amount_gross) + "</td></tr>"; }).join("") + "</tbody></table></div>";
    }
    return opsHead("Cetak Slip Gaji", "Slip gaji dari payroll run resmi") + body;
  });
  guardDemoView("productionReportView", function () {
    if (opsStale("rep") && !ops.err.rep) {
      const q = new URLSearchParams(); if (ops.from) q.set("date_from", ops.from); if (ops.to) q.set("date_to", ops.to);
      opsLoad("rep", "/production/ops/reports/summary" + (q.toString() ? "?" + q : ""), function (d) { ops.rep = d; });
    }
    const d = ops.rep;
    const cols = [["output", "Output"], ["reject", "Reject"], ["packing", "Packing"], ["loading_net", "Loading"], ["pod", "POD"]];
    let body;
    if (ops.err.rep) body = '<div class="flat-notice" role="alert">' + escapeHtml(ops.err.rep) + "</div>";
    else if (!d) body = '<div class="flat-notice">Memuat laporan...</div>';
    else body = '<div class="v36-table-container"><table class="v36-table"><thead><tr><th>Cabang</th>' + cols.map(function (c) { return "<th>" + c[1] + "</th>"; }).join("") + "</tr></thead><tbody>" +
      Object.keys(d.by_branch).map(function (b) { return "<tr><td>" + escapeHtml(b) + "</td>" + cols.map(function (c) { return "<td>" + opsNum(d.by_branch[b][c[0]]) + "</td>"; }).join("") + "</tr>"; }).join("") +
      '<tr><td><b>Total</b></td>' + cols.map(function (c) { return "<td><b>" + opsNum(d.totals[c[0]]) + "</b></td>"; }).join("") + "</tr></tbody></table></div><small>Sumber: event produksi resmi; pass warna 1 saja yang dihitung sebagai cup fisik.</small>";
    return opsHead("Laporan Produksi", "Agregat event produksi resmi") +
      '<form class="v36-toolbar" id="v3-rep-form"><label>Dari <input id="v3-rep-from" type="date" value="' + escapeHtml(ops.from) + '"></label> <label>Sampai <input id="v3-rep-to" type="date" value="' + escapeHtml(ops.to) + '"></label> <button class="btn sm" type="submit">Terapkan</button></form>' + body;
  });
  document.addEventListener("submit", function (ev) {
    const id = ev.target && ev.target.id;
    if (id === "v3-slip-form") {
      ev.preventDefault();
      ops.slipId = document.getElementById("v3-slip-id").value; ops.slip = null; ops.err.slip = "";
      if (ops.slipId) opsLoad("slip", "/production/payroll/runs/" + encodeURIComponent(ops.slipId), function (d) { ops.slip = d; });
    } else if (id === "v3-rep-form") {
      ev.preventDefault();
      ops.from = document.getElementById("v3-rep-from").value; ops.to = document.getElementById("v3-rep-to").value; ops.rep = null; ops.err.rep = ""; ops.ts = {};
      if (typeof window.render === "function") window.render();
    }
  });
  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.id === "v3-ops-status") {
      ops.status = ev.target.value; ops.del = null; ops.err.del = ""; ops.ts = {};
      if (typeof window.render === "function") window.render();
    }
  });
  document.addEventListener("click", function (ev) {
    const t = ev.target && ev.target.closest ? ev.target.closest("[data-ops]") : null;
    if (!t) return;
    const act = t.getAttribute("data-ops");
    if (act === "buf-open") {
      rmOpenRow({ job_id: Number(t.getAttribute("data-jid")), so_number: t.getAttribute("data-so"), branch_id: t.getAttribute("data-branch"), customer_name: t.getAttribute("data-cust") });
      return;
    }
    if (act === "buf-reload" || act === "buf-prev" || act === "buf-next") {
      ops.bufPage = act === "buf-next" ? (ops.bufPage || 1) + 1 : act === "buf-prev" ? Math.max(1, (ops.bufPage || 1) - 1) : (ops.bufPage || 1);
      ops.buf = null; ops.err.buf = ""; ops.ts = {};
      if (typeof window.render === "function") window.render();
      return;
    }
    if (act === "del-reload") { ops.del = null; ops.err.del = ""; ops.ts = {}; }
    else if (act === "plan") {
      ops.plan = { jid: t.getAttribute("data-jid"), sj: t.getAttribute("data-sj"), branch: t.getAttribute("data-branch"), date: t.getAttribute("data-date") || "", so: t.getAttribute("data-so") || "", courier: t.getAttribute("data-courier") || "" };
      const br = ops.plan.branch;
      if (!ops.couriers[br]) request(API + "/production/ops/assignees?kind=courier&branch=" + encodeURIComponent(br)).then(function (d) { ops.couriers[br] = d.items; }).catch(function () { ops.couriers[br] = []; }).then(function () { if (typeof window.render === "function") window.render(); });
    }
    else if (act === "slip") {
      ops.slipId = t.getAttribute("data-id"); ops.slip = null; ops.err.slip = "";
      opsLoad("slip", "/production/payroll/runs/" + encodeURIComponent(ops.slipId), function (d) { ops.slip = d; });
      return;
    }
    else if (act === "plan-cancel") { ops.plan = null; }
    else if (act === "plan-save") {
      const pl = ops.plan; if (!pl) return;
      const date = document.getElementById("v3-plan-date").value;
      const reason = document.getElementById("v3-plan-reason").value.trim();
      const courier = document.getElementById("v3-plan-courier").value;
      if (!date) { toast("Tanggal rencana wajib diisi"); return; }
      if (pl.date && !reason) { toast("Alasan jadwal ulang wajib diisi"); return; }
      request(API + "/production/ops/jobs/" + pl.jid + "/delivery-plan", {
        method: "POST",
        body: { accurate_sj_id: pl.sj, planned_date: date, reason: reason || null, courier_user_id: courier ? Number(courier) : null, idempotency_key: idemKey("delplan") },
      }).then(function () { toast("Jadwal pengiriman tersimpan"); ops.plan = null; ops.del = null; ops.ts = {}; })
        .catch(function (e) { toast(String((e && e.message) || "Gagal menyimpan jadwal")); })
        .then(function () { if (typeof window.render === "function") window.render(); });
      return;
    }
    else return;
    if (typeof window.render === "function") window.render();
  });

  const mm = { data: null, err: "", busy: false, branch: "" };
  function mmLoad() {
    if (mm.busy) return;
    mm.busy = true; mm.err = "";
    request(API + "/production/ops/machines" + (mm.branch ? "?branch=" + encodeURIComponent(mm.branch) : "")).then(function (d) { mm.data = d; }).catch(function (e) { mm.data = null; mm.err = String((e && e.message) || "Gagal memuat"); }).then(function () { mm.busy = false; mm.ts = Date.now(); if (typeof window.render === "function") window.render(); });
  }
  function machineView() {
    if ((!mm.data || Date.now() - (mm.ts || 0) > OPS_TTL_MS) && !mm.busy && !mm.err) mmLoad();
    const d = mm.data;
    let body;
    if (mm.err) body = '<div class="flat-notice" role="alert">' + escapeHtml(mm.err) + ' <button class="btn sm" type="button" data-mm="reload">Coba lagi</button></div>';
    else if (!d) body = '<div class="flat-notice">Memuat master mesin...</div>';
    else body = '<div class="flat-notice">Kapasitas default referensi: ' + opsNum(d.default_capacity_per_shift) + ' per shift (bukan batas universal). Validasi kapasitas aktif ' + (d.enforced ? "karena ada mesin terdaftar." : "setelah mesin pertama didaftarkan.") + "</div>" +
      (d.items.length ? '<div class="v36-table-container"><table class="v36-table"><thead><tr><th>Cabang</th><th>Mesin</th><th>Jenis</th><th>Kapasitas/shift</th><th>Shift/hari</th><th>Status</th><th>Aksi</th></tr></thead><tbody>' +
        d.items.map(function (m) { return "<tr><td>" + escapeHtml(m.branch_id) + "</td><td><b>" + escapeHtml(m.name) + "</b></td><td>" + (m.kind === "semi_auto" ? "Semi Auto" : "Auto") + "</td><td>" + opsNum(m.capacity_per_shift) + "</td><td>" + escapeHtml(m.shifts_per_day) + "</td><td>" + (m.active ? "Aktif" : "Nonaktif") + '</td><td><button type="button" class="btn sm" data-mm="cap" data-id="' + escapeHtml(m.id) + '" data-cap="' + escapeHtml(m.capacity_per_shift) + '">Ubah kapasitas</button> <button type="button" class="btn sm" data-mm="toggle" data-id="' + escapeHtml(m.id) + '" data-active="' + (m.active ? "1" : "0") + '">' + (m.active ? "Nonaktifkan" : "Aktifkan") + "</button></td></tr>"; }).join("") + "</tbody></table></div>" : '<div class="flat-notice">Belum ada mesin.</div>');
    const form = '<form class="v36-toolbar" id="v3-mm-form"><label>Cabang <input id="v3-mm-branch" required value="' + escapeHtml(mm.branch) + '"></label> <label>Nama <input id="v3-mm-name" required></label> <label>Jenis <select id="v3-mm-kind"><option value="auto">Auto</option><option value="semi_auto">Semi Auto</option></select></label> <label>Kapasitas/shift <input id="v3-mm-cap" type="number" min="1" placeholder="default"></label> <label>Shift/hari <input id="v3-mm-shifts" type="number" min="1" value="1"></label> <button class="btn sm" type="submit">Tambah mesin</button></form>';
    return opsHead("Master Mesin", "Mesin dan kapasitas resmi untuk validasi jadwal") + form + body;
  }
  if (typeof window.renderSection === "function") {
    const baseRenderSection = window.renderSection;
    window.renderSection = function (a, stats) {
      return window.section === "machineMaster" ? machineView() : baseRenderSection.call(this, a, stats);
    };
  }
  function mmMutate(promise, okText) {
    promise.then(function () { toast(okText); mm.data = null; sch.machines = {}; }).catch(function (e) { toast(String((e && e.message) || "Gagal menyimpan mesin")); }).then(function () { if (typeof window.render === "function") window.render(); });
  }
  document.addEventListener("submit", function (ev) {
    if (!ev.target || ev.target.id !== "v3-mm-form") return;
    ev.preventDefault();
    const cap = document.getElementById("v3-mm-cap").value;
    mm.branch = document.getElementById("v3-mm-branch").value.trim();
    mmMutate(request(API + "/production/ops/machines", { method: "POST", body: { branch_id: mm.branch, name: document.getElementById("v3-mm-name").value.trim(), kind: document.getElementById("v3-mm-kind").value, capacity_per_shift: cap || null, shifts_per_day: Number(document.getElementById("v3-mm-shifts").value || 1) } }), "Mesin ditambahkan");
  });
  document.addEventListener("click", function (ev) {
    const t = ev.target && ev.target.closest ? ev.target.closest("[data-mm]") : null;
    if (!t) return;
    const act = t.getAttribute("data-mm"), id = t.getAttribute("data-id");
    if (act === "reload") { mm.err = ""; mm.data = null; if (typeof window.render === "function") window.render(); }
    else if (act === "cap") {
      const v = window.prompt("Kapasitas per shift", t.getAttribute("data-cap") || "");
      if (v) mmMutate(request(API + "/production/ops/machines/" + id, { method: "PATCH", body: { capacity_per_shift: v } }), "Kapasitas diubah");
    } else if (act === "toggle") {
      mmMutate(request(API + "/production/ops/machines/" + id, { method: "PATCH", body: { active: t.getAttribute("data-active") !== "1" } }), "Status mesin diubah");
    }
  });
  if (typeof window.go === "function") {
    const originalGo = window.go;
    window.go = function (target) {
      if (target === "contractMonitor") target = "inbox";
      return originalGo.apply(this, arguments.length > 1 ? [target].concat([].slice.call(arguments, 1)) : [target]);
    };
  }
  const bufTried = Object.create(null);
  const bufFailed = Object.create(null);
  function bufEnrich(items) {
    const sos = Array.from(new Set(items.map(function (r) { return r.accurate_so_number; })))
      .filter(function (so) { return so && !bufTried[so] && !orderBySo(so); });
    if (!sos.length) return;
    sos.forEach(function (so) { bufTried[so] = true; });
    (async function () {
      for (const so of sos) {
        monitorOrders[so] = { id: so, name: "", branch: "", qty: "", sourceLines: [], v3Monitor: true };
        try { applyDetailToOrder(so, await fetchOrderDetail(so)); delete bufFailed[so]; } catch (err) { delete monitorOrders[so]; bufFailed[so] = true; }
      }
      if (typeof window.render === "function") window.render();
    })();
  }
  function bufItem(r) {
    const o = orderBySo(r.accurate_so_number);
    const line = o && (o.sourceLines || []).find(function (x) { return x.id != null && String(x.id) === String(r.so_line_id); });
    return { o: o, line: line || null };
  }
  const NA_BUF = '<span class="muted">Belum terverifikasi</span>';
  function bufText(v, failed) { return v == null || v === "" ? (failed ? '<span class="muted">Detail Accurate gagal dimuat</span>' : NA_BUF) : escapeHtml(String(v)); }
  function bufQty(v) { return v == null ? NA_BUF : "<b class=\"right\">" + opsNum(v) + "</b>"; }
  guardDemoView("monitorBuffer", function () {
    if (opsStale("buf") && !ops.err.buf) {
      opsLoad("buf", "/production/ops/buffer?page=" + (ops.bufPage || 1) + "&page_size=50", function (d) { ops.buf = d; if (d) bufEnrich(d.items); });
    }
    const d = ops.buf;
    const h = typeof window.heading === "function" ? window.heading : function (t) { return "<h1>" + t + "</h1>"; };
    let body;
    if (ops.err.buf) body = "<div class=\"flat-notice\" role=\"alert\">" + escapeHtml(ops.err.buf) + " <button type=\"button\" class=\"btn sm\" data-ops=\"buf-reload\">Coba lagi</button></div>";
    else if (!d) body = "<div class=\"flat-notice\" role=\"status\">Memuat monitoring buffer...</div>";
    else if (!d.items.length) body = "<div class=\"flat-notice\">Tidak ada PO Buffer Stock aktif pada cabang Anda.</div>";
    else body = "<div class=\"v36-table-container\"><table class=\"v36-table\"><thead><tr><th>Nomor PO Buffer</th><th>Nama Outlet / Gudang</th><th>Kode Barang</th><th>Nama Barang</th><th>Varian</th><th>Total Buffer Dipesan</th><th>Sudah Selesai Gesut</th><th>Sisa Belum Digesut</th><th>Ready Gudang (Siap Ambil)</th><th>Sudah Diambil / Terkirim</th><th>Status Buffer</th><th>Sales PIC</th><th>Detail</th></tr></thead><tbody>" +
      d.items.map(function (r) {
        const it = bufItem(r), o = it.o, l = it.line, failed = bufFailed[r.accurate_so_number] === true;
        const sales = o && o.salesName && o.salesName !== "Belum terverifikasi" ? o.salesName : null;
        const status = r.integrity === "INTEGRITY_CONFLICT" ? '<span title="' + escapeHtml(r.integrity_detail || "") + '">INTEGRITY_CONFLICT</span>' : bufText(r.buffer_status, failed);
        return "<tr><td><b>" + escapeHtml(r.accurate_so_number) + "</b></td><td>" + bufText(r.customer_name || (o && o.name), failed) + "</td><td>" + bufText(l && l.item_code, failed) + "</td><td>" + bufText(l && l.name, failed) + "</td><td>" + bufText(l && l.color, failed) + "</td><td>" + bufQty(r.total_buffer) + "</td><td>" + bufQty(r.done_gesut) + "</td><td>" + bufQty(r.remaining_gesut) + "</td><td>" + bufQty(r.ready_warehouse) + "</td><td>" + bufQty(r.delivered) + "</td><td>" + status + "</td><td>" + bufText(sales, failed) + "</td><td><button type=\"button\" class=\"btn sm\" data-ops=\"buf-open\" data-jid=\"" + escapeHtml(r.job_id) + "\" data-so=\"" + escapeHtml(r.accurate_so_number) + "\" data-branch=\"" + escapeHtml(r.branch_id) + "\" data-cust=\"" + escapeHtml(r.customer_name || "") + "\">ⓘ Detail</button></td></tr>";
      }).join("") + "</tbody></table></div>" +
      "<small>" + d.items.length + " baris dari " + d.total + " item buffer · halaman " + d.page + (d.page > 1 ? " <button type=\"button\" class=\"btn sm\" data-ops=\"buf-prev\">Sebelumnya</button>" : "") + (d.has_more ? " <button type=\"button\" class=\"btn sm\" data-ops=\"buf-next\">Berikutnya</button>" : "") + "</small>";
    return h("Monitoring Buffer Stock", "Penanda buffer resmi dari job V3 / detail Accurate") +
      "<div class=\"flat-notice\">Hanya PO dengan flag Buffer Stock aktif. Qty dihitung dari event produksi V3 (gesut, packing, loading, POD); data tanpa sumber resmi tampil Belum terverifikasi. Buffer tidak menambah qty SO atau stok Accurate.</div>" + body;
  });

  // Monitoring Penerimaan (operasional): daftar resmi lintas PO dari
  // GET /production/jobs/payment/receipts. Tidak ada fixture/peran demo/simulasi.
  const rm = { q: "", paymentStatus: "", receiptStatus: "", receipts: "", page: 1, pageSize: 25, data: null, loading: false, error: "", stale: true, detail: null };
  const RM_PAY = { approved: ["APPROVED", "Disetujui (terverifikasi)"], bypassed: ["BYPASSED", "Bypass berwenang"], pending: ["PENDING", "Belum terverifikasi"] };
  function rmAmount(v) {
    if (v == null || v === "") return "Belum terverifikasi";
    const n = Number(v);
    return Number.isFinite(n) ? "Rp " + n.toLocaleString("id-ID") : "Belum terverifikasi";
  }
  function unsyncedHtml() {
    if (opsStale("unsynced") && !ops.err.unsynced) opsLoad("unsynced", "/production/ops/payment/unsynced?page=1&limit=50", function (d) { ops.unsynced = d; });
    const d = ops.unsynced;
    let inner;
    if (ops.err.unsynced) inner = escapeHtml(ops.err.unsynced);
    else if (!d) inner = "Memuat PO Accurate tanpa job V3...";
    else if (!d.items.length) inner = "Tidak ada PO Accurate tanpa job V3 pada halaman ini.";
    else inner = "<ul>" + d.items.map(function (i) { return "<li><b>" + escapeHtml(i.po_number) + "</b> · " + escapeHtml(i.customer_name || "Belum terverifikasi") + " · cabang " + escapeHtml(i.branch_id || "Belum terverifikasi") + " · belum ada penerimaan tercatat</li>"; }).join("") + "</ul>";
    return '<section class="flat-notice" id="v3-rm-unsynced"><b>PO Accurate tanpa job V3 (hanya baca)</b><br>' + inner + "</section>";
  }
  async function rmLoad() {
    if (rm.loading) return;
    rm.loading = true; rm.error = "";
    const params = new URLSearchParams({ page: String(rm.page), page_size: String(rm.pageSize) });
    if (rm.q) params.set("q", rm.q);
    if (rm.paymentStatus) params.set("payment_status", rm.paymentStatus);
    if (rm.receiptStatus) params.set("receipt_status", rm.receiptStatus);
    if (rm.receipts) params.set("receipts", rm.receipts);
    try {
      rm.data = await request(API + "/production/jobs/payment/receipts?" + params.toString());
      rm.stale = false;
    } catch (err) {
      rm.data = null; rm.error = String((err && err.message) || "Gagal memuat penerimaan");
      rm.stale = false;
    }
    rm.loading = false;
    if (typeof window.render === "function") window.render();
  }
  function rmRowHtml(r) {
    const pay = RM_PAY[r.payment_status] || RM_PAY.pending;
    const latest = r.receipts && r.receipts[0];
    const none = !r.receipt_count;
    const ref = none
      ? "<span class=\"muted\">Belum ada penerimaan</span>"
      : escapeHtml(latest.accurate_receipt_number || latest.accurate_receipt_id) + "<br><small>" + escapeHtml(r.receipt_count) + " penerimaan</small>";
    const amount = none ? "Belum ada penerimaan" : rmAmount(r.verified_amount);
    const evidence = none ? "—" : latest.evidence_verified ? "Evidence terverifikasi" : "Evidence belum terverifikasi";
    return "<tr><td><b>" + escapeHtml(r.so_number) + "</b><br><small>" + escapeHtml(r.branch_id) + "</small></td>" +
      "<td>" + escapeHtml(r.customer_name || "Belum terverifikasi") + "</td><td>" + ref + "</td>" +
      "<td>" + escapeHtml(amount) + "</td><td>" + evidence + "</td>" +
      "<td><span class=\"tag v165-status--" + (pay[0] === "APPROVED" ? "done" : pay[0] === "PENDING" ? "pending" : "process") + "\">" + pay[1] + "</span>" + (r.bypass_active ? "<br><small>Bypass aktif</small>" : "") + "</td>" +
      "<td>" + (none ? "" : "<button type=\"button\" class=\"btn sm\" data-rm=\"detail\" data-jid=\"" + escapeHtml(r.job_id) + "\">Detail</button> ") +
      "<button type=\"button\" class=\"btn sm\" data-rm=\"open\" data-jid=\"" + escapeHtml(r.job_id) + "\">Buka PO &amp; Payment</button></td></tr>";
  }
  async function rmOpen(jobId) {
    const row = rm.data && rm.data.items.find(function (x) { return x.job_id === jobId; });
    if (!row) return;
    return rmOpenRow(row);
  }
  async function rmOpenRow(row) {
    const so = row.so_number;
    if (!orderBySo(so)) {
      monitorOrders[so] = { id: so, name: row.customer_name || "", branch: row.branch_id || "", qty: "", sourceLines: [], v3Monitor: true };
      try {
        applyDetailToOrder(so, await fetchOrderDetail(so));
      } catch (err) {
        monitorOrders[so].accurateDetailNote = "Detail Accurate tidak tersedia: " + String((err && err.message) || "gagal dimuat");
      }
    }
    try {
      jobCache[so] = { id: row.job_id, accurate_so_number: so, branch_id: row.branch_id };
      delete boardCache[so];
      await loadBoard(so, true);
    } catch (err) {
      delete jobCache[so];
      toast((err && err.message) || "Gagal memuat job");
      return;
    }
    if (!boardCache[so]) { toast("Detail Payment tidak dapat dimuat"); return; }
    renderWorkflowDrawer(so);
  }
  function rmView() {
    const h = typeof window.heading === "function" ? window.heading : function (t, d) { return "<h1>" + t + "</h1><p>" + d + "</p>"; };
    if (rm.stale && !rm.loading) setTimeout(rmLoad, 0);
    const d = rm.data;
    const sel = function (id, label, cur, opts) {
      return "<label>" + label + " <select id=\"" + id + "\">" + opts.map(function (o) { return "<option value=\"" + o[0] + "\"" + (cur === o[0] ? " selected" : "") + ">" + o[1] + "</option>"; }).join("") + "</select></label>";
    };
    let body;
    if (rm.loading && !d) body = "<div class=\"flat-notice\" role=\"status\">Memuat monitoring pembayaran…</div>";
    else if (rm.error) body = "<div class=\"flat-notice\" role=\"alert\"><b>Gagal memuat:</b> " + escapeHtml(rm.error) + " <button type=\"button\" class=\"btn sm\" data-rm=\"reload\">Coba lagi</button></div>";
    else if (!d || !d.items.length) body = "<div class=\"flat-notice\">Tidak ada PO sesuai filter. PO muncul setelah job V3 dibuat dari Inbox/Tugas Tim.</div>";
    else body = "<div class=\"v36-table-container\"><table class=\"v36-table\"><thead><tr><th>No. PO</th><th>Pelanggan</th><th>Referensi penerimaan</th><th>Nominal terverifikasi</th><th>Evidence</th><th>Status pembayaran</th><th>Aksi</th></tr></thead><tbody>" + d.items.map(rmRowHtml).join("") + "</tbody></table></div>" +
      "<div class=\"row\"><button type=\"button\" class=\"btn sm\" data-rm=\"prev\"" + (rm.page <= 1 ? " disabled" : "") + ">‹ Sebelumnya</button><span>Halaman " + d.page + " · " + d.total + " PO</span><button type=\"button\" class=\"btn sm\" data-rm=\"next\"" + (d.has_more ? "" : " disabled") + ">Berikutnya ›</button></div>";
    let detail = "";
    if (rm.detail && d) {
      const r = d.items.find(function (x) { return x.job_id === rm.detail; });
      if (r) detail = "<section class=\"flat-notice\" id=\"v3-rm-detail\"><b>Penerimaan " + escapeHtml(r.so_number) + " · cabang " + escapeHtml(r.branch_id) + "</b><ul>" +
        r.receipts.map(function (x) { return "<li>#" + escapeHtml(x.receipt_id) + " · " + escapeHtml(x.accurate_receipt_number || x.accurate_receipt_id) + " (ID " + escapeHtml(x.accurate_receipt_id) + ") · " + escapeHtml(rmAmount(x.amount)) + " · " + escapeHtml(x.receipt_status) + " · evidence " + (x.evidence_verified ? "terverifikasi" : "belum terverifikasi") + " · " + escapeHtml(x.recorded_at || "Belum terverifikasi") + "</li>"; }).join("") +
        "</ul><small>Revalidasi, invalidasi, dan bypass tersedia pada panel Payment (Buka PO &amp; Payment).</small></section>";
    }
    return h("Monitoring Penerimaan Penjualan", "Status pembayaran resmi dari backend Payment Gate; tidak ada simulasi.") +
      "<div class=\"flat-notice\" id=\"v3-rm-coverage\"><b>Cakupan:</b> hanya PO yang sudah menjadi job V3 (dibuka dari Inbox/Tugas Tim). PO Accurate yang belum menjadi job V3 dicantumkan terpisah di bagian bawah (tanpa membuat job). \"Disetujui\" berarti ada receipt valid dengan evidence terverifikasi; ini bukan penanda lunas (nilai PO tidak dibandingkan). Receipt dibatalkan/reversed tidak dihitung.</div>" +
      "<form class=\"v36-toolbar\" id=\"v3-rm-form\"><label class=\"v36-search\"><span>⌕</span><input id=\"v3-rm-q\" aria-label=\"Cari PO atau penerimaan\" placeholder=\"No. PO / pelanggan / receipt\" value=\"" + escapeHtml(rm.q) + "\"></label>" +
      sel("v3-rm-pay", "Status pembayaran", rm.paymentStatus, [["", "Semua"], ["approved", "Disetujui"], ["bypassed", "Bypass"], ["pending", "Belum terverifikasi"]]) +
      sel("v3-rm-has", "Penerimaan", rm.receipts, [["", "Semua"], ["with", "Sudah ada"], ["without", "Belum ada"]]) +
      sel("v3-rm-rs", "Status receipt", rm.receiptStatus, [["", "Semua"], ["valid", "Valid"], ["invalidated", "Dibatalkan"], ["reversed", "Reversed"]]) +
      "<button type=\"submit\" class=\"btn sm\">Terapkan</button></form>" + body + detail + unsyncedHtml();
  }
  if (typeof window.v36ReceiptView === "function") {
    const demoReceiptView = window.v36ReceiptView;
    window.v36ReceiptView = function (a) {
      return isPreviewFixture() ? demoReceiptView(a) : rmView();
    };
  }
  document.addEventListener("submit", function (ev) {
    if (!ev.target || ev.target.id !== "v3-rm-form") return;
    ev.preventDefault();
    rm.q = document.getElementById("v3-rm-q").value.trim();
    rm.paymentStatus = document.getElementById("v3-rm-pay").value;
    rm.receiptStatus = document.getElementById("v3-rm-rs").value;
    rm.receipts = document.getElementById("v3-rm-has").value;
    rm.page = 1; rm.detail = null; rm.stale = true;
    if (typeof window.render === "function") window.render();
  });
  document.addEventListener("click", function (ev) {
    const t = ev.target && ev.target.closest ? ev.target.closest("[data-rm]") : null;
    if (!t) return;
    const act = t.getAttribute("data-rm");
    if (act === "prev" && rm.page > 1) { rm.page--; rm.stale = true; rm.detail = null; }
    else if (act === "next") { rm.page++; rm.stale = true; rm.detail = null; }
    else if (act === "reload") { rm.stale = true; }
    else if (act === "detail") { rm.detail = Number(t.getAttribute("data-jid")); }
    else if (act === "open") { rmOpen(Number(t.getAttribute("data-jid"))); return; }
    else return;
    if (typeof window.render === "function") window.render();
  });
  window.v3PaymentMonitorRefresh = function () { rm.stale = true; };

  (async function bootLive() {
    clearGhosts();
    if (!isPreviewFixture()) await probeBackendHealth();
    const ok = await verifySession();
    if (!ok) {
      if (typeof window.render === "function") window.render();
      return;
    }
    if (typeof window.render === "function") window.render();
    await refreshInbox(1);
    if (isPreviewFixture()) {
      let banner = document.getElementById("v158-preview-banner");
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "v158-preview-banner";
        banner.setAttribute("role", "status");
        banner.style.cssText =
          "position:sticky;top:0;z-index:50;background:#fff3df;border-bottom:1px solid #f0d8ae;color:#8c622b;padding:8px 14px;font-size:12px;font-weight:700";
        banner.textContent =
          "PREVIEW CURSOR · DATA SIMULASI/FIXTURE — bukan Accurate Live · Step 159 UI only";
        document.body.prepend(banner);
      }
    }
  })();
})();
