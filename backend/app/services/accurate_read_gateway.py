"""Narrow read-only Accurate gateway adapter for Production V3.

No legacy JWT/Accurate secrets are copied into V3. A separate, authenticated,
read-only integration gateway is required. Fail closed when not configured.
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException

from app.core.config import Settings, get_settings


class ReadGateway:
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
            raise HTTPException(503, "Gateway Accurate read-only belum dikonfigurasi")
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
            raise HTTPException(503, "Konfigurasi gateway Accurate tidak aman")

    async def get(self, path: str, *, params: dict | None = None) -> dict:
        self.check_configuration()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
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
                raise HTTPException(503, "Gateway Accurate menolak akses baca")
            if resp.status_code == 404:
                raise HTTPException(404, "Dokumen tidak ditemukan di Accurate")
            if resp.status_code != 200:
                raise HTTPException(502, "Gateway Accurate gagal membaca dokumen")
            result = resp.json()
            if not isinstance(result, dict):
                raise HTTPException(502, "Format respons gateway Accurate tidak valid")
            return result
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Gateway Accurate tidak dapat dihubungi") from exc
        except ValueError as exc:
            raise HTTPException(502, "Respons gateway Accurate bukan JSON valid") from exc


def sanitize_so_number(number: str) -> str:
    number = (number or "").strip()
    if not number or len(number) > 120 or any(ord(c) < 32 for c in number):
        raise HTTPException(422, "Nomor SO tidak valid")
    return quote(number, safe="")


def normalize_summary(row: dict) -> dict:
    """No guessing item qty, processed state, or approvals from legacy stage."""
    so_id = str(row.get("accurate_id") or row.get("id") or "").strip() or None
    number = str(row.get("po_number") or row.get("number") or "").strip()
    if not number:
        return {}
    return {
        "accurate_id": so_id,
        "po_number": number,
        "customer": row.get("customer") or row.get("customer_name"),
        "outlet": row.get("outlet"),
        "branch_id": row.get("branch_id"),
        "sales": row.get("sales"),
        "order_date": row.get("order_date") or row.get("trans_date"),
        "deadline": row.get("deadline") or row.get("estimated_delivery"),
        "line_items": None,
        "total_quantity": None,
        "production_status": "Baru",
    }


async def list_sales_orders(
    gateway: ReadGateway, *, page: int, limit: int, keyword: str
) -> dict:
    payload = await gateway.get(
        "/sales-orders", params={"page": page, "limit": limit, "keyword": keyword}
    )
    rows = payload.get("rows")
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
    if not isinstance(so, dict) or not (so.get("po_number") or so.get("number")):
        raise HTTPException(502, "Detail Sales Order tidak valid")
    result = normalize_summary(so)
    lines = so.get("line_items")
    if not isinstance(lines, list):
        raise HTTPException(502, "Detail Sales Order tidak memiliki daftar item")
    result.update(
        {
            "line_items": [
                {
                    "accurate_line_id": line.get("accurate_line_id"),
                    "accurate_item_id": line.get("accurate_item_id"),
                    "item_code": line.get("item_code"),
                    "name": line.get("name"),
                    "quantity": line.get("quantity"),
                    "unit": line.get("unit"),
                    "color": line.get("color"),
                    "notes": line.get("notes"),
                }
                for line in lines
                if isinstance(line, dict)
            ],
            "total_quantity": so.get("total_quantity"),
            "address": so.get("address"),
            "recipient": so.get("recipient"),
            "payment_terms": so.get("payment_terms"),
            "created_by_user": so.get("created_by_user"),
            "expedition": so.get("expedition"),
            "delivery_zone": so.get("delivery_zone"),
            "notes": so.get("notes"),
        }
    )
    return result
