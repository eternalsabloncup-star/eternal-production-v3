# Slice 137 / Step 139 — Pengiriman list `shipment` Live gate

## Proven offline

- Detail path: `shipment.name` → gateway `expedition` → Inbox/detail PO (Step 135).
- List path code: request includes `shipment` (+ native expedition keys); normalizer/contract/backend summary pass `expedition` when present (Step 137).
- Enrich fallback: page-scoped detail fetch, concurrency **3**, cache + inflight dedupe, generation isolation on page/filter change, Retry force-refresh (no invent).

## LIVE GATE (not proven offline)

Accurate `sales-order/list.do` **`fields=` compatibility for nested `shipment`** is **not** proven without a new Owner-approved Live call.

Possible outcomes after Live check:

1. Accurate returns `shipment` on list → Inbox Pengiriman fills without waiting for detail.
2. Accurate ignores `shipment` in `fields` → list `expedition` stays null; **existing page enrich** still fills Pengiriman from detail (no extra unbounded N+1).
3. Accurate rejects the fields list → treat as P0; remove `shipment` from list fields and rely on enrich only.

**Do not claim list.do returns `shipment` until Live evidence exists.**

## Ops

- No Accurate Live/write from agents without Owner approval.
- Alembic `20261112_0007` remains staging/VPS **BLOCKED** until Owner approval (isolated test upgrade/downgrade only).
