"""Narrow read-only Accurate gateway client for Production V3.

Machine-to-machine Bearer token against a dedicated gateway.
No ERP V1 JWT/Accurate secrets. Fail closed. Bounded retries on transport only.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException

from app.core.config import Settings, get_settings

_MAX_RETRIES = 2
_RETRYABLE = {408, 429, 500, 502, 503, 504}


class GatewayError(Exception):
    """Structured gateway failure (translated to HTTP at the edge)."""

    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def as_http(self) -> HTTPException:
        return HTTPException(
            self.status_code,
            detail={"code": self.code, "message": self.message},
        )


class ReadGateway:
    """M2M client: Authorization Bearer <V3_ACCURATE_READ_GATEWAY_TOKEN>."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        settings: Settings | None = None,
    ):
        cfg = settings or get_settings()
        self.base_url = (
            base_url if base_url is not None else cfg.accurate_read_gateway_url
        ).rstrip("/")
        self.token = token if token is not None else cfg.accurate_read_gateway_token

    def check_configuration(self) -> None:
        if not self.base_url or not self.token:
            raise GatewayError(
                "gateway_unconfigured",
                "Gateway Accurate read-only belum dikonfigurasi",
                status_code=503,
            )
        parsed = urlparse(self.base_url)
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http"
                    and parsed.hostname in {"127.0.0.1", "localhost"}
                )
            )
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise GatewayError(
                "gateway_insecure_url",
                "Konfigurasi gateway Accurate tidak aman",
                status_code=503,
            )

    async def get(self, path: str, *, params: dict | None = None) -> dict:
        try:
            self.check_configuration()
        except GatewayError as exc:
            raise exc.as_http() from exc

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-Client": "eternal-production-v3",
        }
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(12, connect=3),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    resp = await client.get(
                        self.base_url + path, params=params, headers=headers
                    )
                if resp.status_code in (401, 403):
                    raise GatewayError(
                        "gateway_auth_rejected",
                        "Gateway Accurate menolak akses baca",
                        status_code=503,
                    ).as_http()
                if resp.status_code == 404:
                    raise GatewayError(
                        "document_not_found",
                        "Dokumen tidak ditemukan di Accurate",
                        status_code=404,
                    ).as_http()
                if resp.status_code in _RETRYABLE and attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                if resp.status_code != 200:
                    raise GatewayError(
                        "gateway_bad_status",
                        "Gateway Accurate gagal membaca dokumen",
                        status_code=502,
                    ).as_http()
                result = resp.json()
                if not isinstance(result, dict):
                    raise GatewayError(
                        "gateway_invalid_payload",
                        "Format respons gateway Accurate tidak valid",
                        status_code=502,
                    ).as_http()
                return result
            except HTTPException:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise GatewayError(
                    "gateway_unreachable",
                    "Gateway Accurate tidak dapat dihubungi",
                    status_code=502,
                ).as_http() from last_error
            except ValueError as exc:
                raise GatewayError(
                    "gateway_invalid_json",
                    "Respons gateway Accurate bukan JSON valid",
                    status_code=502,
                ).as_http() from exc
        raise GatewayError(
            "gateway_unreachable",
            "Gateway Accurate tidak dapat dihubungi",
            status_code=502,
        ).as_http()


def sanitize_so_number(number: str) -> str:
    number = (number or "").strip()
    if not number or len(number) > 120 or any(ord(c) < 32 for c in number):
        raise HTTPException(422, "Nomor SO tidak valid")
    return quote(number, safe="")


def normalize_summary(row: dict) -> dict:
    """No guessing item qty, processed state, or approvals from legacy stage.

    V3 inbox historically stores the Accurate SO number in the field named
    ``po_number``. Customer-provided PO is exposed separately and never
    fabricated from the SO number.
    """
    so_id = str(row.get("accurate_id") or row.get("id") or "").strip() or None
    so_number = str(row.get("number") or "").strip()
    raw_customer_po = row.get("po_number") or row.get("customer_po_number")
    customer_po = (
        str(raw_customer_po).strip()
        if raw_customer_po is not None and str(raw_customer_po).strip()
        else None
    )
    # Compatibility: inbox/frontend key ``po_number`` = Accurate SO number.
    if not so_number:
        return {}
    customer = row.get("customer") or row.get("customer_name")
    if isinstance(customer, dict):
        customer = customer.get("name") or customer.get("id")
    branch_id = row.get("branch_id")
    branch_name = row.get("branch_name") or row.get("outlet")
    if isinstance(row.get("branch"), dict):
        branch_id = branch_id or row["branch"].get("id")
        branch_name = branch_name or row["branch"].get("name")
    buffer_stock = row.get("buffer_stock")
    if buffer_stock is not None and not isinstance(buffer_stock, bool):
        buffer_stock = None
    urgent_state = row.get("urgent_state")
    if urgent_state is not None:
        urgent_state = str(urgent_state).strip() or None
    sales = row.get("sales")
    if sales is not None:
        sales = str(sales).strip() or None
    sales_source = row.get("sales_source")
    if sales_source is not None:
        sales_source = str(sales_source).strip() or None
    return {
        "accurate_id": so_id,
        "number": so_number,
        "po_number": so_number,
        "customer_po_number": customer_po,
        "customer": customer,
        "outlet": branch_name or row.get("outlet"),
        "branch_id": branch_id,
        "branch_name": branch_name,
        "sales": sales,
        "sales_source": sales_source,
        "order_date": row.get("order_date") or row.get("trans_date"),
        "deadline": row.get("deadline") or row.get("estimated_delivery"),
        # List summaries intentionally omit lines — detail endpoint is source of truth.
        "line_items": None,
        "total_quantity": None,
        "line_count": None,
        "production_status": "Baru",
        # Nullable — missing Accurate mapping stays null (not false).
        "buffer_stock": buffer_stock,
        "urgent_state": urgent_state,
    }


async def list_sales_orders(
    gateway: ReadGateway, *, page: int, limit: int, keyword: str
) -> dict:
    payload = await gateway.get(
        "/sales-orders", params={"page": page, "limit": limit, "keyword": keyword}
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = payload.get("items")
    if not isinstance(rows, list):
        raise HTTPException(502, "Gateway mengembalikan daftar SO tidak valid")
    normalized = [normalize_summary(row) for row in rows if isinstance(row, dict)]
    normalized = [row for row in normalized if row]
    return {
        "rows": normalized,
        "total": int(payload.get("total") or len(normalized)),
        "page": page,
        "pageSize": limit,
        "source": "accurate_gateway",
        "mode": "live",
    }


async def get_sales_order(gateway: ReadGateway, number: str) -> dict:
    data = await gateway.get(f"/sales-orders/{sanitize_so_number(number)}")
    so = data.get("sales_order", data.get("preview", data))
    if not isinstance(so, dict) or not so.get("number"):
        raise HTTPException(502, "Detail Sales Order tidak valid")
    result = normalize_summary(so)
    lines = so.get("line_items")
    if not isinstance(lines, list):
        raise HTTPException(502, "Detail Sales Order tidak memiliki daftar item")
    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        process = line.get("production_process")
        if process not in {"print", "non_print", "unknown"}:
            process = "unknown"
        parsed_lines.append(
            {
                "accurate_line_id": line.get("accurate_line_id") or line.get("id"),
                "accurate_item_id": line.get("accurate_item_id")
                or line.get("item_id"),
                "item_code": line.get("item_code") or line.get("sku"),
                "name": line.get("name") or line.get("description"),
                "quantity": line.get("quantity")
                if line.get("quantity") is not None
                else line.get("qty"),
                "unit": line.get("unit") or line.get("uom"),
                "color": line.get("color"),
                "notes": line.get("notes"),
                "production_process": process,
            }
        )
    total_qty = so.get("total_quantity")
    if total_qty is None:
        total_qty = 0
        for line in parsed_lines:
            try:
                total_qty += float(line.get("quantity") or 0)
            except (TypeError, ValueError):
                pass
    result.update(
        {
            "line_items": parsed_lines,
            "total_quantity": total_qty,
            "line_count": so.get("line_count")
            if so.get("line_count") is not None
            else len(parsed_lines),
            "address": so.get("address"),
            "recipient": so.get("recipient"),
            "payment_terms": so.get("payment_terms"),
            "created_by_user": so.get("created_by_user"),
            "expedition": so.get("expedition"),
            "delivery_zone": so.get("delivery_zone"),
            "deadline": so.get("estimated_delivery")
            or so.get("deadline")
            or result.get("deadline"),
            "notes": so.get("notes"),
            "branch_name": so.get("branch_name")
            or result.get("branch_name")
            or result.get("outlet"),
            "sales": so.get("sales") if so.get("sales") is not None else result.get("sales"),
            "sales_source": so.get("sales_source")
            if so.get("sales_source") is not None
            else result.get("sales_source"),
            "buffer_stock": result.get("buffer_stock"),
            "urgent_state": result.get("urgent_state"),
        }
    )
    return result
