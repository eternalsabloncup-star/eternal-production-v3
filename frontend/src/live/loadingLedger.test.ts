import { describe, expect, it } from "vitest";
import {
  findLineAuthority,
  hasPermission,
  netLoadedForLine,
  pendingReturnRequests,
  PERM_LOADING_RETURN_APPROVE,
  PERM_LOADING_RETURN_REQUEST,
  returnRequestStatus,
  reversesEventId,
  summarizeLoadingEvents,
  viewSjLineAuthority,
} from "./loadingLedger";

describe("loadingLedger", () => {
  const events = [
    {
      id: 10,
      event_type: "loading",
      qty_physical: "40",
      accurate_sj_id: "SJ1",
      accurate_sj_number: "SJ-1",
      accurate_sj_line_id: "L1",
      so_line_id: "SO1",
      payload_json: null,
    },
    {
      id: 11,
      event_type: "loading_cancelled",
      qty_physical: "10",
      accurate_sj_id: "SJ1",
      accurate_sj_line_id: "L1",
      so_line_id: "SO1",
      payload_json: JSON.stringify({
        reverses_event_id: 10,
        cancel_kind: "confirmation_cancel",
      }),
    },
    {
      id: 12,
      event_type: "loading_return_requested",
      qty_physical: "5",
      accurate_sj_id: "SJ1",
      accurate_sj_line_id: "L1",
      so_line_id: "SO1",
      actor_user_id: 2,
      payload_json: JSON.stringify({ reverses_event_id: 10 }),
      reason: "barang retur",
    },
    {
      id: 13,
      event_type: "loading",
      qty_physical: "20",
      accurate_sj_id: "SJ1",
      accurate_sj_number: "SJ-1",
      accurate_sj_line_id: "L2",
      so_line_id: "SO2",
      payload_json: null,
    },
  ];

  it("summarizes confirmed / cancelled / net per loading event", () => {
    const rows = summarizeLoadingEvents(events);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      eventId: 10,
      confirmedQty: 40,
      cancelledQty: 10,
      netLoadedQty: 30,
      remainingOnEvent: 30,
    });
    expect(rows[1].netLoadedQty).toBe(20);
  });

  it("nets loaded qty for an SJ line", () => {
    expect(netLoadedForLine(events, "SJ1", "L1", "SO1")).toBe(30);
    expect(netLoadedForLine(events, "SJ1", "L2", "SO2")).toBe(20);
  });

  it("tracks pending return request status", () => {
    expect(returnRequestStatus(events, 12)).toBe("pending");
    expect(pendingReturnRequests(events).map((e) => e.id)).toEqual([12]);
    expect(reversesEventId(events[1])).toBe(10);
  });

  it("marks approved / rejected return requests", () => {
    const approved = [
      ...events,
      {
        id: 20,
        event_type: "loading_cancelled",
        qty_physical: "5",
        payload_json: JSON.stringify({
          request_event_id: 12,
          reverses_event_id: 10,
          cancel_kind: "physical_return",
        }),
      },
    ];
    expect(returnRequestStatus(approved, 12)).toBe("approved");

    const rejected = [
      ...events,
      {
        id: 21,
        event_type: "loading_return_rejected",
        qty_physical: "5",
        payload_json: JSON.stringify({ request_event_id: 12 }),
      },
    ];
    expect(returnRequestStatus(rejected, 12)).toBe("rejected");
  });

  it("gates UI actions by permission codes", () => {
    expect(hasPermission(["production.delivery.manage"], PERM_LOADING_RETURN_REQUEST)).toBe(
      false,
    );
    expect(
      hasPermission(
        [PERM_LOADING_RETURN_REQUEST, PERM_LOADING_RETURN_APPROVE],
        PERM_LOADING_RETURN_APPROVE,
      ),
    ).toBe(true);
  });

  it("shows UNKNOWN when SJ qty is unverified — never invents", () => {
    const unknown = viewSjLineAuthority({
      accurate_sj_id: "SJ1",
      accurate_sj_line_id: "L1",
      so_line_id: "SO1",
      verification: "UNKNOWN",
      qty_sj_pcs: null,
      loading_confirmed: "30",
      loading_cancelled: "0",
      loading_net: "30",
      remaining_loading: null,
      actions_enabled: false,
    });
    expect(unknown.displayQtySj).toBe("UNKNOWN");
    expect(unknown.displayRemaining).toBe("UNKNOWN");
    expect(unknown.actionsEnabled).toBe(false);

    const verified = viewSjLineAuthority({
      accurate_sj_id: "SJ1",
      accurate_sj_line_id: "L1",
      so_line_id: "SO1",
      verification: "VERIFIED",
      qty_sj_pcs: "100",
      loading_confirmed: "40",
      loading_cancelled: "10",
      loading_net: "30",
      remaining_loading: "70",
      actions_enabled: true,
    });
    expect(verified.displayQtySj).toBe("100");
    expect(verified.displayRemaining).toBe("70");
    expect(verified.actionsEnabled).toBe(true);
    expect(
      findLineAuthority(
        [
          {
            accurate_sj_id: "SJ1",
            accurate_sj_line_id: "L1",
            so_line_id: "SO1",
            verification: "VERIFIED",
            qty_sj_pcs: "100",
            loading_confirmed: "0",
            loading_cancelled: "0",
            loading_net: "0",
            remaining_loading: "100",
            actions_enabled: true,
          },
        ],
        "SJ1",
        "L1",
        "SO1",
      )?.displayQtySj,
    ).toBe("100");
  });
});
