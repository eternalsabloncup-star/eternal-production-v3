/* Step 158/161 — shared column resize (browser mirror of src/live/columnResize.ts) */
(function (global) {
  "use strict";
  var MIN = {
    id: 120,
    name: 140,
    item: 160,
    number: 72,
    date: 110,
    action: 96,
    text: 88,
    default: 88,
  };

  function minWidthFor(key, kind) {
    if (key === "id") return MIN.id;
    if (key === "name") return MIN.name;
    if (key === "item") return MIN.item;
    if (kind === "number") return MIN.number;
    if (kind === "date") return MIN.date;
    if (kind === "action") return MIN.action;
    return MIN.text;
  }

  function clampColumnWidth(key, width, kind) {
    var min = minWidthFor(key, kind);
    var n = Math.round(Number(width) || 0);
    if (!Number.isFinite(n) || n < min) return min;
    return Math.min(n, 720);
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

  function ensureColumnKeys(table) {
    var headerRow =
      table.querySelector("thead tr:not(.sheet-group-row):last-of-type") ||
      table.querySelector("thead tr:last-child");
    if (!headerRow) return [];
    var ths = Array.prototype.slice.call(headerRow.querySelectorAll("th"));
    var keys = ths.map(function (th, i) {
      var key = th.getAttribute("data-column") || "";
      if (!key) {
        key = "c" + i;
        th.setAttribute("data-column", key);
      }
      return key;
    });
    Array.prototype.forEach.call(table.querySelectorAll("tbody tr"), function (tr) {
      var cells = Array.prototype.filter.call(tr.children, function (el) {
        return el.tagName === "TD";
      });
      cells.forEach(function (td, i) {
        if (!td.getAttribute("data-column") && keys[i]) {
          td.setAttribute("data-column", keys[i]);
        }
      });
    });
    return keys;
  }

  function ensureColgroup(table, keys) {
    var cg = table.querySelector("colgroup");
    if (!cg) {
      cg = document.createElement("colgroup");
      table.insertBefore(cg, table.firstChild);
    }
    var existing = {};
    Array.prototype.forEach.call(cg.querySelectorAll("col"), function (col) {
      var k = col.getAttribute("data-column");
      if (k) existing[k] = col;
    });
    keys.forEach(function (key) {
      if (existing[key]) return;
      var col = document.createElement("col");
      col.setAttribute("data-column", key);
      cg.appendChild(col);
    });
  }

  function applyWidth(table, key, w) {
    var col = table.querySelector('col[data-column="' + escapeAttr(key) + '"]');
    if (col) {
      col.style.width = w + "px";
      col.style.minWidth = w + "px";
    }
    table
      .querySelectorAll(
        'th[data-column="' + escapeAttr(key) + '"], td[data-column="' + escapeAttr(key) + '"]',
      )
      .forEach(function (el) {
        var cs = el.getAttribute("colspan");
        if (cs && Number(cs) > 1) return;
        el.style.width = w + "px";
        el.style.minWidth = w + "px";
        el.style.maxWidth = w + "px";
        el.style.boxSizing = "border-box";
      });
  }

  function attachColumnResize(table, opts) {
    if (!table || !opts || !opts.storageKey) return {};
    var stickyKeys = opts.stickyKeys || ["id", "name"];
    var lockAll = opts.lockAll !== false;
    var keys = ensureColumnKeys(table);
    if (!keys.length) return {};
    ensureColgroup(table, keys);

    var widths = Object.assign({}, opts.defaults || {}, loadColumnWidths(opts.storageKey));

    function measureKey(key) {
      var th =
        table.querySelector(
          'thead tr:not(.sheet-group-row) th[data-column="' + escapeAttr(key) + '"]',
        ) ||
        table.querySelector('thead th[data-column="' + escapeAttr(key) + '"]');
      return th ? Math.round(th.getBoundingClientRect().width) : 0;
    }

    function syncSticky() {
      var left = 0;
      stickyKeys.forEach(function (key) {
        if (keys.indexOf(key) < 0) return;
        var kind = opts.kindOf ? opts.kindOf(key) : null;
        var w = clampColumnWidth(
          key,
          widths[key] || measureKey(key) || minWidthFor(key, kind),
          kind,
        );
        widths[key] = w;
        table
          .querySelectorAll(
            'th[data-column="' +
              escapeAttr(key) +
              '"], td[data-column="' +
              escapeAttr(key) +
              '"]',
          )
          .forEach(function (el) {
            el.style.left = left + "px";
          });
        left += w;
      });
    }

    function syncTableWidth() {
      var sum = 0;
      keys.forEach(function (key) {
        var th =
          table.querySelector(
            'thead tr:not(.sheet-group-row) th[data-column="' + escapeAttr(key) + '"]',
          ) ||
          table.querySelector('thead th[data-column="' + escapeAttr(key) + '"]');
        if (th && th.classList.contains("v40-col-hidden")) return;
        sum += widths[key] || measureKey(key) || minWidthFor(key);
      });
      if (sum > 0) {
        table.style.tableLayout = "fixed";
        table.style.width = sum + "px";
        table.style.minWidth = sum + "px";
      }
    }

    keys.forEach(function (key) {
      var th =
        table.querySelector(
          'thead tr:not(.sheet-group-row) th[data-column="' + escapeAttr(key) + '"]',
        ) ||
        table.querySelector('thead th[data-column="' + escapeAttr(key) + '"]');
      if (!th || th.classList.contains("v40-col-hidden")) return;
      var kind = opts.kindOf ? opts.kindOf(key) : null;
      var w = widths[key];
      if (w == null && lockAll) w = measureKey(key) || minWidthFor(key, kind);
      if (w != null) {
        widths[key] = clampColumnWidth(key, w, kind);
        applyWidth(table, key, widths[key]);
      }
    });
    syncSticky();
    syncTableWidth();

    var headerRow =
      table.querySelector("thead tr:not(.sheet-group-row):last-of-type") ||
      table.querySelector("thead tr:last-child");
    if (!headerRow) return widths;

    Array.prototype.forEach.call(headerRow.querySelectorAll("th[data-column]"), function (th) {
      var key = th.getAttribute("data-column") || "";
      if (!key) return;
      if (th.classList && th.classList.contains("v40-col-hidden")) return;
      if (th.querySelector("[data-col-resize]")) return;
      var kind = opts.kindOf ? opts.kindOf(key) : null;
      var handle = document.createElement("span");
      handle.setAttribute("data-col-resize", key);
      handle.className = "col-resize-handle";
      handle.title = "Seret untuk ubah lebar kolom";
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", "vertical");
      handle.setAttribute("aria-label", "Ubah lebar kolom " + key);
      handle.tabIndex = 0;
      handle.addEventListener("pointerdown", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        handle.classList.add("is-dragging");
        var startX = ev.clientX;
        var startW =
          widths[key] ||
          Math.max(minWidthFor(key, kind), Math.round(th.getBoundingClientRect().width));
        try {
          handle.setPointerCapture(ev.pointerId);
        } catch (e) {
          /* ignore */
        }
        function onMove(e) {
          var next = clampColumnWidth(key, startW + (e.clientX - startX), kind);
          widths[key] = next;
          applyWidth(table, key, next);
          syncSticky();
          syncTableWidth();
          if (opts.onGeometry) opts.onGeometry();
        }
        function onUp() {
          handle.classList.remove("is-dragging");
          handle.removeEventListener("pointermove", onMove);
          handle.removeEventListener("pointerup", onUp);
          handle.removeEventListener("pointercancel", onUp);
          saveColumnWidths(opts.storageKey, widths);
          syncSticky();
          syncTableWidth();
          if (opts.onGeometry) opts.onGeometry();
          if (opts.onChange) opts.onChange(Object.assign({}, widths));
        }
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
      });
      th.appendChild(handle);
    });

    if (opts.onGeometry) opts.onGeometry();
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
    ensureColumnKeys: ensureColumnKeys,
    ensureColgroup: ensureColgroup,
    attachColumnResize: attachColumnResize,
  };
})(typeof window !== "undefined" ? window : globalThis);
