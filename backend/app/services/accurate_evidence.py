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

_INVALID_RECEIPT_STATUS = {
    "void",
    "voided",
    "cancelled",
    "canceled",
    "reversed",
    "invalid",
    "draft",
    "unposted",
    "unknown",
}
_INVALID_SJ_STATUS = {
    "void",
    "voided",
    "cancelled",
    "canceled",
    "superseded",
    "draft",
    "unposted",
    "unknown",
}


def _enforce() -> bool:
    settings = get_settings()
    if settings.accurate_evidence_enforce:
        return True
    # Production/staging always enforce. Local test suite may skip.
    return settings.app_env not in {"test"}


def _party_id(raw) -> str:
    if isinstance(raw, dict):
        return str(raw.get("id") or "").strip()
    return ""


def _party_name(raw) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name") or "").strip().lower()
    return str(raw or "").strip().lower()


async def require_valid_receipt(
    accurate_receipt_id: str,
    *,
    expected_so_number: str | None = None,
    expected_branch_id: str | None = None,
    expected_customer_id: str | None = None,
) -> dict:
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
            "accurate_credentials_missing",
        }:
            raise HTTPException(
                503,
                "Verifikasi receipt Accurate tidak tersedia — "
                "gunakan bypass berizin+audit atau konfigurasi gateway",
            ) from exc
        raise

    if data.get("cancelled") is True or data.get("reversed") is True:
        raise HTTPException(409, "Receipt Accurate tidak valid / sudah dibatalkan")
    if data.get("verifiable") is False:
        raise HTTPException(409, "Receipt Accurate tidak dapat diverifikasi")

    status = str(
        data.get("status") or data.get("receipt_status") or data.get("state") or ""
    ).lower()
    if status in _INVALID_RECEIPT_STATUS:
        raise HTTPException(409, "Receipt Accurate tidak valid / sudah dibatalkan")

    so_link = str(
        data.get("sales_order_number")
        or data.get("so_number")
        or data.get("po_number")
        or ""
    ).strip()
    if expected_so_number and so_link and so_link != expected_so_number.strip():
        raise HTTPException(
            409,
            "Receipt Accurate tidak cocok dengan Sales Order job",
        )

    branch = data.get("branch")
    branch_id = _party_id(branch) or str(data.get("branch_id") or "").strip()
    if expected_branch_id and branch_id and branch_id != expected_branch_id.strip():
        raise HTTPException(409, "Receipt Accurate tidak cocok dengan cabang job")

    customer = data.get("customer")
    customer_id = _party_id(customer) or str(data.get("customer_id") or "").strip()
    if (
        expected_customer_id
        and customer_id
        and customer_id != expected_customer_id.strip()
    ):
        raise HTTPException(409, "Receipt Accurate tidak cocok dengan customer job")

    return {
        "verified": True,
        "mode": "gateway",
        "accurate_receipt_id": rid,
        "payload_status": status or "unknown",
        "sales_order_number": so_link or None,
        "branch_id": branch_id or None,
        "customer_id": customer_id or None,
        "amount": data.get("amount"),
        "live_verified": bool(data.get("live_verified")),
    }


async def require_valid_sj(
    *,
    accurate_sj_id: str,
    accurate_sj_number: str,
    expected_so_number: str | None = None,
    expected_branch_id: str | None = None,
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
            "accurate_credentials_missing",
        }:
            raise HTTPException(
                503,
                "Verifikasi SJ Accurate tidak tersedia — "
                "loading diblokir sampai gateway siap",
            ) from exc
        raise

    if data.get("cancelled") is True:
        raise HTTPException(409, "Surat Jalan Accurate tidak aktif")
    if data.get("verifiable") is False:
        raise HTTPException(409, "Surat Jalan Accurate tidak dapat diverifikasi")

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
    if status in _INVALID_SJ_STATUS:
        raise HTTPException(409, "Surat Jalan Accurate tidak aktif")

    so_link = str(
        data.get("sales_order_number")
        or data.get("so_number")
        or data.get("po_number")
        or ""
    ).strip()
    if expected_so_number and so_link and so_link != expected_so_number.strip():
        raise HTTPException(
            409,
            "Surat Jalan Accurate tidak cocok dengan Sales Order job",
        )

    branch = data.get("branch")
    branch_id = _party_id(branch) or str(data.get("branch_id") or "").strip()
    if expected_branch_id and branch_id and branch_id != expected_branch_id.strip():
        raise HTTPException(409, "Surat Jalan Accurate tidak cocok dengan cabang job")

    return {
        "verified": True,
        "mode": "gateway",
        "accurate_sj_id": sj_id,
        "accurate_sj_number": sj_no,
        "payload_status": status or "unknown",
        "sales_order_number": so_link or None,
        "branch_id": branch_id or None,
        "live_verified": bool(data.get("live_verified")),
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
            "and loading are blocked (bypass payment remains audited escape). "
            "Live Accurate verification requires ACCURATE_API_TOKEN + "
            "ACCURATE_DATABASE_ID on the gateway (not claimed here)."
        ),
    }
