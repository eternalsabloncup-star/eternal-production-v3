/**
 * Loading ledger helpers for Panel V3 live-runtime (SJ-line authority).
 * Keep in sync with frontend/src/live/loadingLedger.ts
 */
(function (root) {
  "use strict";

  function qty(ev) {
    var n = Number(ev && ev.qty_physical);
    return Number.isFinite(n) ? n : 0;
  }

  function parsePayload(ev) {
    if (!ev || !ev.payload_json) return {};
    try {
      var data = JSON.parse(ev.payload_json);
      return data && typeof data === "object" ? data : {};
    } catch (_e) {
      return {};
    }
  }

  function numOrNull(raw) {
    if (raw == null || raw === "") return null;
    var n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function reversesEventId(ev) {
    var raw = parsePayload(ev).reverses_event_id;
    if (raw == null || raw === "") return null;
    var n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function requestEventId(ev) {
    var raw = parsePayload(ev).request_event_id;
    if (raw == null || raw === "") return null;
    var n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function summarizeLoadingEvents(events) {
    var list = events || [];
    var loadings = list.filter(function (e) {
      return e.event_type === "loading";
    });
    var cancels = list.filter(function (e) {
      return e.event_type === "loading_cancelled";
    });
    return loadings.map(function (load) {
      var cancelledQty = cancels
        .filter(function (c) {
          return reversesEventId(c) === load.id;
        })
        .reduce(function (s, c) {
          return s + qty(c);
        }, 0);
      var confirmedQty = qty(load);
      var remainingOnEvent = Math.max(0, confirmedQty - cancelledQty);
      return {
        eventId: load.id,
        accurateSjId: String(load.accurate_sj_id || ""),
        accurateSjNumber: String(load.accurate_sj_number || load.accurate_sj_id || ""),
        accurateSjLineId: String(load.accurate_sj_line_id || ""),
        soLineId: String(load.so_line_id || ""),
        confirmedQty: confirmedQty,
        cancelledQty: cancelledQty,
        netLoadedQty: remainingOnEvent,
        remainingOnEvent: remainingOnEvent,
        createdAt: load.created_at || "",
        actorUserId: load.actor_user_id || null,
      };
    });
  }

  function netLoadedForLine(events, accurateSjId, accurateSjLineId, soLineId) {
    return summarizeLoadingEvents(events)
      .filter(function (r) {
        return (
          r.accurateSjId === accurateSjId &&
          r.accurateSjLineId === accurateSjLineId &&
          r.soLineId === soLineId
        );
      })
      .reduce(function (s, r) {
        return s + r.netLoadedQty;
      }, 0);
  }

  function viewSjLineAuthority(row) {
    var verified = row && row.verification === "VERIFIED";
    var qtySj = verified ? numOrNull(row.qty_sj_pcs) : null;
    var confirmed = numOrNull(row && row.loading_confirmed) || 0;
    var cancelled = numOrNull(row && row.loading_cancelled) || 0;
    var netRaw = numOrNull(row && row.loading_net);
    var loadingNet = netRaw != null ? netRaw : Math.max(0, confirmed - cancelled);
    var remaining =
      verified && qtySj != null ? numOrNull(row.remaining_loading) : null;
    var actionsEnabled = !!(row && row.actions_enabled) && verified && qtySj != null;
    return {
      accurateSjId: String((row && row.accurate_sj_id) || ""),
      accurateSjNumber: String(
        (row && (row.accurate_sj_number || row.accurate_sj_id)) || "",
      ),
      accurateSjLineId: String((row && row.accurate_sj_line_id) || ""),
      soLineId: String((row && row.so_line_id) || ""),
      verification: actionsEnabled ? "VERIFIED" : "UNKNOWN",
      qtySj: qtySj,
      loadingConfirmed: confirmed,
      loadingCancelled: cancelled,
      loadingNet: loadingNet,
      remainingLoading: remaining,
      actionsEnabled: actionsEnabled,
      displayQtySj: qtySj == null ? "UNKNOWN" : String(qtySj),
      displayRemaining: remaining == null ? "UNKNOWN" : String(remaining),
      note: (row && row.note) || null,
    };
  }

  function findLineAuthority(rows, accurateSjId, accurateSjLineId, soLineId) {
    var list = rows || [];
    for (var i = 0; i < list.length; i++) {
      var r = list[i];
      if (
        String(r.accurate_sj_id || "") === accurateSjId &&
        String(r.accurate_sj_line_id || "") === accurateSjLineId &&
        String(r.so_line_id || "") === soLineId
      ) {
        return viewSjLineAuthority(r);
      }
    }
    return null;
  }

  function returnRequestStatus(events, requestId) {
    var list = events || [];
    for (var i = 0; i < list.length; i++) {
      var ev = list[i];
      if (requestEventId(ev) !== requestId) continue;
      if (ev.event_type === "loading_return_rejected") return "rejected";
      if (
        ev.event_type === "loading_cancelled" &&
        parsePayload(ev).cancel_kind === "physical_return"
      ) {
        return "approved";
      }
    }
    return "pending";
  }

  function pendingReturnRequests(events) {
    return (events || []).filter(function (e) {
      return (
        e.event_type === "loading_return_requested" &&
        returnRequestStatus(events, e.id) === "pending"
      );
    });
  }

  function returnApprovalHistory(events, requestId) {
    return (events || []).filter(function (e) {
      return requestEventId(e) === requestId;
    });
  }

  var PERM_DELIVERY_MANAGE = "production.delivery.manage";
  var PERM_LOADING_RETURN_REQUEST = "production.delivery.loading_return.request";
  var PERM_LOADING_RETURN_APPROVE = "production.delivery.loading_return.approve";

  function hasPermission(permissions, needed) {
    return (permissions || []).indexOf(needed) !== -1;
  }

  root.V3LoadingLedger = {
    summarizeLoadingEvents: summarizeLoadingEvents,
    netLoadedForLine: netLoadedForLine,
    reversesEventId: reversesEventId,
    requestEventId: requestEventId,
    returnRequestStatus: returnRequestStatus,
    pendingReturnRequests: pendingReturnRequests,
    returnApprovalHistory: returnApprovalHistory,
    parsePayload: parsePayload,
    viewSjLineAuthority: viewSjLineAuthority,
    findLineAuthority: findLineAuthority,
    PERM_DELIVERY_MANAGE: PERM_DELIVERY_MANAGE,
    PERM_LOADING_RETURN_REQUEST: PERM_LOADING_RETURN_REQUEST,
    PERM_LOADING_RETURN_APPROVE: PERM_LOADING_RETURN_APPROVE,
    hasPermission: hasPermission,
  };
})(typeof window !== "undefined" ? window : globalThis);
