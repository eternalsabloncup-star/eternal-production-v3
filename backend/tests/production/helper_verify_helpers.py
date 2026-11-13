"""Test helper: mint helper-verified events for packing eligibility."""

from __future__ import annotations

from httpx import AsyncClient


async def helper_verify_output(
    client: AsyncClient,
    job_id: int,
    output_event_id: int,
    qty: str | int,
    *,
    headers: dict | None = None,
    idem: str | None = None,
) -> dict:
    h = headers or {}
    key = idem or f"hv-{output_event_id}-{qty}"
    if len(key) < 8:
        key = f"hv-key-{output_event_id}-{qty}"
    r = await client.post(
        f"/api/v1/production/jobs/{job_id}/outputs/{output_event_id}/helper-verifications",
        headers=h,
        json={
            "source_output_event_id": output_event_id,
            "qty_physical": str(qty),
            "idempotency_key": key,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()
