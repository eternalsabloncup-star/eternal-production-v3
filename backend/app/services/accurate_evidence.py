"""Authoritative Accurate evidence checks for payment receipts and Surat Jalan.

Fail closed when the read gateway is unconfigured, unreachable, or the
document is missing/invalid. Receipts always require evidence, including tests;
the older test-only skip remains limited to Surat Jalan verification.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import get_settings
from app.services.accurate_read_gateway import ReadGateway

# Only the posted contract is currently established by the gateway tests.
# Unmapped upstream statuses require explicit contract verification.
_VALID_RECEIPT_STATUS = {"posted"}
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
    expected_so_id: str | None = None,
) -> dict:
    rid = (accurate_receipt_id or "").strip()
    if not rid:
        raise HTTPException(422, "Referensi receipt Accurate wajib")
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
    if data.get("verifiable") is not True:
        raise HTTPException(409, "Receipt Accurate tidak dapat diverifikasi")

    status = str(
        data.get("status") or data.get("receipt_status") or data.get("state") or ""
    ).strip().lower()
    if status not in _VALID_RECEIPT_STATUS:
        raise HTTPException(409, "Receipt Accurate tidak valid / sudah dibatalkan")

    # Fixture evidence is restricted to isolated tests. Never infer authority
    # from a successful HTTP response or a caller-supplied amount.
    if data.get("live_verified") is not True and not (
        get_settings().app_env == "test" and data.get("source") == "fixture"
    ):
        raise HTTPException(409, "Sumber receipt Accurate belum terverifikasi")
    canonical_id = str(data.get("id") or "").strip()
    if (
        not canonical_id or len(canonical_id) > 120
        or isinstance(data.get("id"), (bool, dict, list))
        or (data.get("live_verified") is True and not canonical_id.isdigit())
    ):
        raise HTTPException(409, "Identitas receipt Accurate tidak valid")
    try:
        raw_amount = data["amount_decimal"] if "amount_decimal" in data else data.get("amount")
        if isinstance(raw_amount, bool):
            raise ValueError
        effective_amount = Decimal(str(raw_amount))
        if not effective_amount.is_finite() or effective_amount <= 0:
            raise ValueError
        # Match storage precision without turning a tiny positive into zero.
        effective_amount = effective_amount.quantize(Decimal("0.01"))
        if effective_amount <= 0 or effective_amount >= Decimal("1e16"):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise HTTPException(409, "Nilai efektif receipt Accurate harus positif")

    # SO link only from receipt→SO fields — never treat customer PO / missing link
    # as verification against the job.
    so_link = str(
        data.get("sales_order_number") or data.get("so_number") or ""
    ).strip()
    if expected_so_number:
        if not so_link:
            raise HTTPException(
                409,
                "Receipt Accurate tidak menautkan Sales Order — verifikasi ditolak",
            )

        if so_link != expected_so_number.strip():
            raise HTTPException(
                409,
                "Receipt Accurate tidak cocok dengan Sales Order job",
            )

    if expected_so_id and str(data.get("sales_order_id") or "").strip() != expected_so_id.strip():
        raise HTTPException(409, "Identitas Sales Order receipt tidak cocok / ambigu")

    branch = data.get("branch")
    branch_id = _party_id(branch) or str(data.get("branch_id") or "").strip()
    if expected_branch_id and branch_id != expected_branch_id.strip():
        raise HTTPException(409, "Receipt Accurate tidak cocok dengan cabang job")

    customer = data.get("customer")
    customer_id = _party_id(customer) or str(data.get("customer_id") or "").strip()
    if (
        expected_customer_id
        and customer_id
        and customer_id != expected_customer_id.strip()
    ):
        raise HTTPException(409, "Receipt Accurate tidak cocok dengan customer job")

    paid_raw = data.get("paid_at")
    paid_at = str(paid_raw).strip() if paid_raw not in (None, "") else None

    return {
        "verified": True,
        "mode": "gateway",
        "accurate_receipt_id": canonical_id,
        "accurate_receipt_number": str(data.get("number") or "").strip() or None,
        "payload_status": status or "unknown",
        "sales_order_number": so_link or None,
        "branch_id": branch_id or None,
        "customer_id": customer_id or None,
        "amount": effective_amount,
        "paid_at": paid_at,
        "live_verified": bool(data.get("live_verified")),
        "source": data.get("source"),
    }


def _normalize_sj_line_items(raw_lines) -> list[dict]:
    """Pass through gateway line contract; never invent ids from SKU/index."""
    if not isinstance(raw_lines, list):
        return []
    out: list[dict] = []
    for row in raw_lines:
        if not isinstance(row, dict):
            continue
        out.append(dict(row))
    return out


def resolve_sj_loading_line(
    evidence: dict,
    *,
    accurate_sj_line_id: str,
    so_line_id: str,
) -> dict:
    """Exact SJ-line × SO-line match. Fail closed on missing/ambiguous identity."""
    sj_line = (accurate_sj_line_id or "").strip()
    so_line = (so_line_id or "").strip()
    if not sj_line or not so_line:
        raise HTTPException(422, "Identitas baris SJ dan SO line wajib")
    if evidence.get("mode") == "test_skip" or not evidence.get("verified"):
        raise HTTPException(
            503,
            "Verifikasi SJ line Accurate tidak tersedia — loading diblokir",
        )
    lines = evidence.get("line_items") or []
    if not isinstance(lines, list) or not lines:
        raise HTTPException(409, "Surat Jalan Accurate tidak memuat baris otoritatif")
    matches = [
        ln
        for ln in lines
        if isinstance(ln, dict)
        and str(ln.get("accurate_sj_line_id") or "").strip() == sj_line
        and str(ln.get("so_line_id") or "").strip() == so_line
    ]
    if not matches:
        raise HTTPException(
            409,
            "Baris SJ tidak cocok dengan SO line pada bukti Accurate",
        )
    if len(matches) > 1:
        raise HTTPException(409, "Identitas baris SJ ambigu pada bukti Accurate")
    line = matches[0]
    if line.get("loading_eligible") is not True:
        raise HTTPException(
            409,
            "Baris SJ tidak eligible untuk Loading (identitas/qty/unit_ratio)",
        )
    return line


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
            "line_items": [],
            "loading_eligible": False,
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
        data.get("sales_order_number") or data.get("so_number") or ""
    ).strip()
    if expected_so_number:
        if not so_link:
            raise HTTPException(
                409,
                "Surat Jalan Accurate tidak menautkan Sales Order — loading ditolak",
            )
        if so_link != expected_so_number.strip():
            raise HTTPException(
                409,
                "Surat Jalan Accurate tidak cocok dengan Sales Order job",
            )

    branch = data.get("branch")
    branch_id = _party_id(branch) or str(data.get("branch_id") or "").strip()
    if expected_branch_id and branch_id and branch_id != expected_branch_id.strip():
        raise HTTPException(409, "Surat Jalan Accurate tidak cocok dengan cabang job")

    line_items = _normalize_sj_line_items(data.get("line_items"))
    return {
        "verified": True,
        "mode": "gateway",
        "accurate_sj_id": sj_id,
        "accurate_sj_number": sj_no,
        "payload_status": status or "unknown",
        "sales_order_number": so_link or None,
        "branch_id": branch_id or None,
        "live_verified": bool(data.get("live_verified")),
        "line_items": line_items,
        "loading_eligible": bool(line_items)
        and all(ln.get("loading_eligible") is True for ln in line_items),
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
