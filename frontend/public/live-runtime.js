/* Live Accurate inbox runtime for V49. Read-only. No fabricated transactions. */
(function () {
  "use strict";
  const API = (window.V3_API_BASE || "/api/v1").replace(/\/$/, "");
  const TOKEN_KEY = "epv3_access_token";

  let fetchError = "Koneksi Accurate belum tersedia";
  let lastSync = null;
  let loading = false;

  function authHeaders() {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    return headers;
  }

  function clearGhosts() {
    window.queueDemoSave = function () {};
    window.pushDemoSave = function () {};
    // Prevent offline demo seed from becoming live SO authority.
    if (typeof window.bootDemo === "function") {
      const original = window.bootDemo;
      window.bootDemo = async function () {
        window.orders = [];
        window.taskEntries = {};
        window.history = [];
        if (typeof window.render === "function") window.render();
        return original.apply(this, arguments);
      };
    }
  }
  clearGhosts();

  function mapOrder(s) {
    const number = String(s.po_number || "").trim();
    if (!number) return null;
    const lines = Array.isArray(s.line_items) ? s.line_items : [];
    const qty =
      Number.isFinite(Number(s.total_quantity)) && s.total_quantity != null
        ? Number(s.total_quantity)
        : 0;
    const productionStatus =
      s.production_status === "Terproses" ? "Terproses" : "Baru";
    return {
      id: number,
      accurateId: s.accurate_id ?? null,
      name: s.customer || "Perlu verifikasi",
      item:
        lines.map((x) => x.name || x.item_code).filter(Boolean).join(" + ") ||
        "Detail barang belum dimuat",
      qty,
      qtyVerified: s.total_quantity != null,
      sourceLines: lines.map((x, i) => ({
        id: x.accurate_line_id || "unverified-" + i,
        itemId: x.accurate_item_id || null,
        item_code: x.item_code || null,
        name: x.name || null,
        qty: x.quantity,
        unit: x.unit || null,
        notes: x.notes || null,
        processSnapshot: null,
      })),
      status: productionStatus === "Terproses" ? "Terproses" : "PO Masuk",
      stage: productionStatus === "Terproses" ? "run" : "inbox",
      productionStatus,
      branch: s.branch_id || "Belum terverifikasi",
      salesName: s.sales || "Belum terverifikasi",
      ship: s.deadline || "Belum diketahui",
      scheduleDate: "",
      machine: "",
      operator: "",
      done: 0,
      packed: 0,
      receipt: "Belum terverifikasi",
      sj: "",
      updated: "",
      approval: false,
      inkColors: [],
      urgent: false,
      bufferStock: false,
      bufferQty: 0,
      scheduledQty: 0,
      processKind: "UNVERIFIED",
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

  async function request(path) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: authHeaders(),
      cache: "no-store",
    });
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      throw new Error("Sesi V3 tidak valid — login ulang");
    }
    if (!response.ok) {
      throw new Error(
        response.status === 503
          ? "Gateway Accurate belum siap / tidak berwenang"
          : "API V3 mengembalikan HTTP " + response.status,
      );
    }
    return response.json();
  }

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
        ? "Sumber: Gateway Accurate • Sinkron: " + lastSync
        : "Sumber belum terhubung: " + fetchError;
    const content = root.querySelector(".content");
    if (content && !status.parentElement) content.prepend(status);
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
    return result;
  };

  async function refreshInbox(page) {
    if (loading) return;
    loading = true;
    if (typeof window.render === "function") window.render();
    try {
      if (!localStorage.getItem(TOKEN_KEY)) {
        throw new Error("Login V3 diperlukan sebelum membaca Inbox Accurate");
      }
      const data = await request(
        API + "/production/inbox?page=" + (page || 1) + "&limit=50",
      );
      if (!Array.isArray(data.rows) || data.mode !== "live") {
        throw new Error("Respons sumber bukan data live yang terverifikasi");
      }
      window.orders = data.rows.map(mapOrder).filter(Boolean);
      window.taskEntries = {};
      window.history = [];
      lastSync = new Date().toLocaleTimeString("id-ID");
      fetchError = "";
    } catch (err) {
      window.orders = [];
      window.taskEntries = {};
      window.history = [];
      lastSync = null;
      fetchError = err && err.message ? err.message : "Tidak dapat membaca Accurate";
    } finally {
      loading = false;
      if (typeof window.render === "function") window.render();
    }
  }

  window.v50RefreshInbox = refreshInbox;
  window.v3Logout = function () {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
  };

  window.v49PODetail = async function (number) {
    const o = (window.orders || []).find((x) => x.id === number);
    if (!o) return;
    const modal = document.getElementById("modal");
    modal.innerHTML =
      '<div class="drawerback"><aside class="detaildrawer shipping-drawer" role="dialog" aria-modal="true"><div class="drawerhead"><h2>Detail Sales Order Accurate</h2><button class="btn sm" onclick="v49Close()">✕ Tutup</button></div><div class="drawerbody">Memuat detail dokumen…</div></aside></div>';
    try {
      const detail = await request(
        API + "/production/orders/" + encodeURIComponent(number),
      );
      const lines = Array.isArray(detail.line_items) ? detail.line_items : [];
      const cells = lines
        .map(
          (line) =>
            "<tr><td>" +
            escape(line.item_code || "—") +
            "</td><td>" +
            escape(line.name || "—") +
            "</td><td>" +
            (line.quantity == null
              ? "Belum diketahui"
              : escape(String(line.quantity))) +
            "</td><td>" +
            escape(line.unit || "—") +
            "</td></tr>",
        )
        .join("");
      modal.querySelector(".drawerbody").innerHTML =
        "<p><b>" +
        escape(detail.po_number) +
        "</b> · " +
        escape(detail.customer || "Pelanggan belum diketahui") +
        "</p><p>Status proses V3: <b>" +
        escape(detail.production_status || "Baru") +
        "</b></p><p>Sales: " +
        escape(detail.sales || "Belum diketahui") +
        " · Cabang: " +
        escape(detail.branch_id || "Belum diketahui") +
        "</p><p>Deadline: " +
        escape(detail.deadline || "Belum diketahui") +
        '</p><div class="v26-scroll"><table><thead><tr><th>Kode</th><th>Produk</th><th>Qty</th><th>Satuan</th></tr></thead><tbody>' +
        (cells || '<tr><td colspan="4">Tidak ada baris</td></tr>') +
        '</tbody></table></div><p class="v49-quiet">Dokumen Accurate hanya dibaca. Mutasi produksi menunggu API kanonik V3.</p>';
    } catch (err) {
      modal.querySelector(".drawerbody").textContent =
        "Detail belum tersedia: " + err.message;
    }
  };

  // Block mutation-looking demo confirmations from claiming success without API.
  document.addEventListener(
    "click",
    function (event) {
      const button = event.target.closest("button");
      if (!button) return;
      const label = (button.textContent || "").toLowerCase();
      if (
        label.includes("simulasi") ||
        label.includes("demo") ||
        label.includes("reset demo")
      ) {
        event.preventDefault();
        event.stopPropagation();
        if (typeof window.toast === "function") {
          window.toast("Aksi transaksi belum aktif — menunggu API V3");
        }
      }
    },
    true,
  );

  window.orders = [];
  if (typeof window.render === "function") window.render();
  refreshInbox(1);
})();
