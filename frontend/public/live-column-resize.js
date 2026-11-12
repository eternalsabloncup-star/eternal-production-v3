/* Step 158 — shared column resize (browser mirror of src/live/columnResize.ts) */
(function (global) {
  "use strict";
  var MIN = {
    id: 120,
    name: 140,
    number: 72,
    date: 100,
    action: 96,
    text: 88,
    default: 88,
  };

  function minWidthFor(key, kind) {
    if (key === "id") return MIN.id;
    if (key === "name") return MIN.name;
    if (kind === "number") return MIN.number;
    if (kind === "date") return MIN.date;
    if (kind === "action") return MIN.action;
    return MIN.text;
  }

  function clampColumnWidth(key, width, kind) {
    var min = minWidthFor(key, kind);
    var n = Math.round(Number(width) || 0);
    if (!Number.isFinite(n) || n < min) return min;
    return n;
  }

  function loadColumnWidths(storageKey) {
    try {
      var raw = localStorage.getItem(storageKey);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      var out = {};
      Object.keys(parsed).forEach(function (k) {
        var n = Number(parsed[k]);
        if (Number.isFinite(n) && n > 0) out[k] = n;
      });
      return out;
    } catch (e) {
      return {};
    }
  }

  function saveColumnWidths(storageKey, widths) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(widths || {}));
    } catch (e) {
      /* ignore */
    }
  }

  function clearColumnWidths(storageKey) {
    try {
      localStorage.removeItem(storageKey);
    } catch (e) {
      /* ignore */
    }
  }

  function stickyLeftOffsets(order, widths, locked) {
    locked = locked || ["id", "name"];
    var out = {};
    var left = 0;
    (order || []).forEach(function (key) {
      if (locked.indexOf(key) < 0) return;
      out[key] = left;
      left += widths[key] || minWidthFor(key);
    });
    return out;
  }

  function isResizeHandleEvent(target) {
    return !!(
      target &&
      target.closest &&
      target.closest("[data-col-resize]")
    );
  }

  function escapeAttr(key) {
    if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(key);
    return String(key).replace(/"/g, '\\"');
  }

  function applyWidth(table, key, w) {
    var th = table.querySelector('th[data-column="' + escapeAttr(key) + '"]');
    if (th) {
      th.style.width = w + "px";
      th.style.minWidth = w + "px";
      th.style.maxWidth = w + "px";
      th.style.boxSizing = "border-box";
    }
    table
      .querySelectorAll('td[data-column="' + escapeAttr(key) + '"]')
      .forEach(function (td) {
        td.style.width = w + "px";
        td.style.minWidth = w + "px";
        td.style.maxWidth = w + "px";
        td.style.boxSizing = "border-box";
      });
    if (key === "id") {
      var nameTh = table.querySelector('th[data-column="name"]');
      var nameTds = table.querySelectorAll('td[data-column="name"]');
      if (nameTh) nameTh.style.left = w + "px";
      nameTds.forEach(function (td) {
        td.style.left = w + "px";
      });
    }
  }

  function attachColumnResize(table, opts) {
    if (!table || !opts || !opts.storageKey) return {};
    var widths = loadColumnWidths(opts.storageKey);
    function syncSticky() {
      var idTh = table.querySelector('th[data-column="id"]');
      var idW = widths.id || (idTh ? Math.round(idTh.getBoundingClientRect().width) : minWidthFor("id"));
      widths.id = clampColumnWidth("id", idW);
      table.querySelectorAll('th[data-column="name"], td[data-column="name"]').forEach(function (el) {
        el.style.left = widths.id + "px";
      });
    }
    table.querySelectorAll("thead th[data-column]").forEach(function (th) {
      var key = th.getAttribute("data-column") || "";
      if (!key) return;
      if (th.classList && th.classList.contains("v40-col-hidden")) return;
      var kind = opts.kindOf ? opts.kindOf(key) : null;
      if (widths[key] != null) {
        widths[key] = clampColumnWidth(key, widths[key], kind);
        applyWidth(table, key, widths[key]);
      }
      if (th.querySelector("[data-col-resize]")) return;
      var handle = document.createElement("span");
      handle.setAttribute("data-col-resize", key);
      handle.className = "col-resize-handle";
      handle.title = "Seret untuk ubah lebar kolom";
      handle.addEventListener("pointerdown", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var startX = ev.clientX;
        var startW =
          widths[key] ||
          Math.max(
            minWidthFor(key, kind),
            Math.round(th.getBoundingClientRect().width),
          );
        try {
          handle.setPointerCapture(ev.pointerId);
        } catch (e) {
          /* ignore */
        }
        function onMove(e) {
          var next = clampColumnWidth(key, startW + (e.clientX - startX), kind);
          widths[key] = next;
          applyWidth(table, key, next);
          if (key === "id") syncSticky();
        }
        function onUp() {
          handle.removeEventListener("pointermove", onMove);
          handle.removeEventListener("pointerup", onUp);
          handle.removeEventListener("pointercancel", onUp);
          saveColumnWidths(opts.storageKey, widths);
          syncSticky();
          if (opts.onChange) opts.onChange(Object.assign({}, widths));
        }
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
      });
      th.appendChild(handle);
    });
    syncSticky();
    return widths;
  }

  global.V3ColumnResize = {
    COLUMN_RESIZE_MIN: MIN,
    minWidthFor: minWidthFor,
    clampColumnWidth: clampColumnWidth,
    loadColumnWidths: loadColumnWidths,
    saveColumnWidths: saveColumnWidths,
    clearColumnWidths: clearColumnWidths,
    stickyLeftOffsets: stickyLeftOffsets,
    isResizeHandleEvent: isResizeHandleEvent,
    attachColumnResize: attachColumnResize,
  };
})(typeof window !== "undefined" ? window : globalThis);
