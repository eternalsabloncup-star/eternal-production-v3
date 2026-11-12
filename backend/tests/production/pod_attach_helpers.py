"""Helpers to upload the four required POD attachments in tests."""

from __future__ import annotations

# Minimal valid 1x1 PNG
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

POD_PURPOSES = (
    "pod_photo_1",
    "pod_photo_2",
    "pod_sig_sender",
    "pod_sig_recipient",
)


async def upload_pod_bundle(
    client, job_id: int, accurate_sj_id: str, *, headers: dict | None = None
) -> dict[str, int]:
    ids: dict[str, int] = {}
    for purpose in POD_PURPOSES:
        resp = await client.post(
            f"/api/v1/production/jobs/{job_id}/attachments",
            headers=headers,
            data={"accurate_sj_id": accurate_sj_id, "purpose": purpose},
            files={"file": (f"{purpose}.png", PNG_1X1, "image/png")},
        )
        assert resp.status_code == 200, resp.text
        ids[purpose] = resp.json()["id"]
    return ids


def pod_body(
    accurate_sj_id: str,
    qty: str,
    idem: str,
    ids: dict[str, int],
    receiver: str = "Budi",
) -> dict:
    return {
        "accurate_sj_id": accurate_sj_id,
        "qty_physical": qty,
        "idempotency_key": idem,
        "receiver_name": receiver,
        "attachment_pod_photo_1": ids["pod_photo_1"],
        "attachment_pod_photo_2": ids["pod_photo_2"],
        "attachment_pod_sig_sender": ids["pod_sig_sender"],
        "attachment_pod_sig_recipient": ids["pod_sig_recipient"],
    }
