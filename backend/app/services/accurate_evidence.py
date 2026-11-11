"""Authoritative Accurate evidence checks for payment receipts and Surat Jalan.

Fail closed when the read gateway is unconfigured, unreachable, or the
document is missing/invalid. Test env skips unless V3_ACCURATE_EVIDENCE_ENFORCE
is enabled — never invents success.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import get_settings
from app.services.accurate_read_gateway import ReadGateway


def _enforce() -> bool:
    settings = get_settings()
    if settings.accurate_evidence_enforce:
        return True
    # Production/staging always enforce. Local test suite may skip.
    return settings.app_env not in {"test"}


async def require_valid_receipt(accurate_receipt_id: str) -> dict:
    rid = (accurate_receipt_id or "").strip()
    if not rid:
        raise HTTPException(422, "Referensi receipt Accurate wajib")
    if not _enforce():
        return {
            "verified": False,
            "mode": "test_skip",
            "accurate_receipt_id": rid,
            "note": "Evidence enforce off (test) — not production authority",
        }
    gateway = ReadGateway()
    try:
        data = await gateway.get(f"/receipts/{quote(rid, safe='')}")
    except HTTPException as exc:
        # Re-map missing document / auth / config to fail-closed messages.
        detail = exc.detail
        code = ""
        if isinstance(detail, dict):
            code = str(detail.get("code") or "")
        if exc.status_code == 404 or code == "document_not_found":
            raise HTTPException(
                409,
                "Receipt Accurate tidak ditemukan — gate payment tidak dapat dibuka",
            ) from exc
        if exc.status_code == 503 or code in {
            "gateway_unconfigured",
            "gateway_auth_rejected",
            "gateway_insecure_url",
        }:
            raise HTTPException(
                503,
                "Verifikasi receipt Accurate tidak tersedia — "
                "gunakan bypass berizin+audit atau konfigurasi gateway",
            ) from exc
        raise
    status = str(
        data.get("status") or data.get("receipt_status") or data.get("state") or ""
    ).lower()
    if status in {"void", "cancelled", "canceled", "reversed", "invalid"}:
        raise HTTPException(409, "Receipt Accurate tidak valid / sudah dibatalkan")
    return {
        "verified": True,
        "mode": "gateway",
        "accurate_receipt_id": rid,
        "payload_status": status or "unknown",
    }


async def require_valid_sj(
    *, accurate_sj_id: str, accurate_sj_number: str
) -> dict:
    sj_id = (accurate_sj_id or "").strip()
    sj_no = (accurate_sj_number or "").strip()
    if not sj_id or not sj_no:
        raise HTTPException(422, "Identitas SJ Accurate wajib")
    if not _enforce():
        return {
            "verified": False,
            "mode": "test_skip",
            "accurate_sj_id": sj_id,
            "accurate_sj_number": sj_no,
            "note": "Evidence enforce off (test) — not production authority",
        }
    gateway = ReadGateway()
    try:
        data = await gateway.get(f"/delivery-notes/{quote(sj_id, safe='')}")
    except HTTPException as exc:
        detail = exc.detail
        code = ""
        if isinstance(detail, dict):
            code = str(detail.get("code") or "")
        if exc.status_code == 404 or code == "document_not_found":
            raise HTTPException(
                409,
                "Surat Jalan Accurate tidak ditemukan — loading ditolak",
            ) from exc
        if exc.status_code == 503 or code in {
            "gateway_unconfigured",
            "gateway_auth_rejected",
            "gateway_insecure_url",
        }:
            raise HTTPException(
                503,
                "Verifikasi SJ Accurate tidak tersedia — "
                "loading diblokir sampai gateway siap",
            ) from exc
        raise
    number = str(
        data.get("number")
        or data.get("sj_number")
        or data.get("delivery_note_number")
        or ""
    ).strip()
    if number and number != sj_no:
        raise HTTPException(
            409,
            "Nomor SJ tidak cocok dengan identitas Accurate yang diverifikasi",
        )
    status = str(
        data.get("status") or data.get("sj_status") or data.get("state") or ""
    ).lower()
    if status in {"void", "cancelled", "canceled", "superseded"}:
        raise HTTPException(409, "Surat Jalan Accurate tidak aktif")
    return {
        "verified": True,
        "mode": "gateway",
        "accurate_sj_id": sj_id,
        "accurate_sj_number": sj_no,
        "payload_status": status or "unknown",
    }


def evidence_capability() -> dict:
    """UI/API capability probe — never claims verification without gateway."""
    settings = get_settings()
    gateway = ReadGateway()
    configured = bool(gateway.base_url and gateway.token)
    enforce = _enforce()
    return {
        "receipt_verify": configured and enforce,
        "sj_verify": configured and enforce,
        "gateway_configured": configured,
        "enforce": enforce,
        "app_env": settings.app_env,
        "note": (
            "Gateway paths /receipts/{id} and /delivery-notes/{id} required "
            "for authoritative evidence. Without them, payment receipt open "
            "and loading are blocked (bypass payment remains audited escape)."
        ),
    }
