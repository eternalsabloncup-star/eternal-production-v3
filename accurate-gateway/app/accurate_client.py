"""HTTPS Accurate Online adapter — read-only, bounded retries, fail-closed.

Official paths (Accurate Online API / swagger):
  POST {account}/oauth/open-db.do  → session + host
  GET  {host}/accurate/api/sales-order/list.do
  GET  {host}/accurate/api/sales-order/detail.do
  GET  {host}/accurate/api/sales-receipt/detail.do
  GET  {host}/accurate/api/delivery-order/detail.do

Credentials: ACCURATE_API_TOKEN + ACCURATE_DATABASE_ID only.
Never reuse ERP V1 secrets or databases.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import GatewaySettings
from app.normalize import (
    normalize_delivery_note,
    normalize_receipt,
    normalize_sales_order,
    normalize_sales_order_list_item,
)

logger = logging.getLogger("accurate_gateway.upstream")

_MAX_ATTEMPTS = 3
_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class AccurateUpstreamError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AccurateClient:
    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._host: str | None = None
        self._session_id: str | None = None

    def configured(self) -> bool:
        return bool(
            (self._settings.accurate_api_token or "").strip()
            and (self._settings.accurate_database_id or "").strip()
        )

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        if self._host and self._session_id:
            return
        token = self._settings.accurate_api_token.strip()
        db_id = self._settings.accurate_database_id.strip()
        if not token or not db_id:
            raise AccurateUpstreamError(
                "accurate_credentials_missing",
                "ACCURATE_API_TOKEN dan ACCURATE_DATABASE_ID wajib untuk mode live",
                status_code=503,
            )
        # Official Accurate Online: open-db.do with Bearer token + database id.
        # Prefer GET; fall back to POST if tenant rejects GET.
        url = f"{self._settings.accurate_account_base.rstrip('/')}/oauth/open-db.do"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = None
        last_exc: Exception | None = None
        for method in ("GET", "POST"):
            try:
                resp = await client.request(
                    method,
                    url,
                    params={"id": db_id},
                    headers=headers,
                )
            except httpx.RequestError as exc:
                last_exc = exc
                continue
            if resp.status_code < 400:
                break
            last_exc = AccurateUpstreamError(
                "accurate_open_db_rejected",
                f"open-db HTTP {resp.status_code}",
                status_code=502,
            )
            resp = None
        if resp is None:
            if isinstance(last_exc, AccurateUpstreamError):
                raise last_exc
            raise AccurateUpstreamError(
                "accurate_open_db_unreachable",
                f"open-db gagal: {last_exc}",
                status_code=502,
            ) from last_exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AccurateUpstreamError(
                "accurate_open_db_invalid",
                "open-db response bukan JSON",
                status_code=502,
            ) from exc
        if isinstance(payload, dict) and payload.get("s") is False:
            raise AccurateUpstreamError(
                "accurate_open_db_business_reject",
                str(payload.get("d") or payload.get("message") or "open-db s=false"),
                status_code=502,
            )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        host = (
            payload.get("host")
            or data.get("host")
            or payload.get("hostName")
            or data.get("hostName")
        )
        # Never treat boolean s=true as host.
        if isinstance(host, bool):
            host = None
        session = (
            payload.get("session")
            or payload.get("sessionId")
            or data.get("session")
            or data.get("sessionId")
            or resp.headers.get("X-Session-ID")
        )
        if not host or not session:
            raise AccurateUpstreamError(
                "accurate_session_incomplete",
                "open-db tidak mengembalikan host/session",
                status_code=502,
            )
        self._host = str(host).rstrip("/")
        if not self._host.startswith("http"):
            self._host = f"https://{self._host}"
        self._session_id = str(session)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._settings.accurate_api_token.strip()
        last_error: AccurateUpstreamError | None = None
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    await self._ensure_session(client)
                    assert self._host and self._session_id
                    url = f"{self._host}{path}"
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-Session-ID": self._session_id,
                            "Accept": "application/json",
                        },
                    )
                except AccurateUpstreamError:
                    raise
                except httpx.RequestError as exc:
                    last_error = AccurateUpstreamError(
                        "accurate_unreachable",
                        f"upstream unreachable: {exc}",
                        status_code=502,
                    )
                    continue
                if resp.status_code in _RETRYABLE and attempt < _MAX_ATTEMPTS:
                    last_error = AccurateUpstreamError(
                        "accurate_retryable",
                        f"HTTP {resp.status_code}",
                        status_code=502,
                    )
                    if resp.status_code in (401, 403):
                        self._host = None
                        self._session_id = None
                    continue
                if resp.status_code == 404:
                    raise AccurateUpstreamError(
                        "accurate_not_found",
                        "dokumen tidak ditemukan di Accurate",
                        status_code=404,
                    )
                if resp.status_code >= 400:
                    raise AccurateUpstreamError(
                        "accurate_http_error",
                        f"Accurate HTTP {resp.status_code}",
                        status_code=502,
                    )
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise AccurateUpstreamError(
                        "accurate_invalid_json",
                        "response Accurate bukan JSON",
                        status_code=502,
                    ) from exc
                if isinstance(data, dict) and data.get("s") is False:
                    msg = data.get("d") or data.get("message") or "Accurate s=false"
                    raise AccurateUpstreamError(
                        "accurate_business_reject",
                        str(msg),
                        status_code=502,
                    )
                return data if isinstance(data, dict) else {"d": data}
            assert last_error is not None
            raise last_error

    async def list_sales_orders(
        self,
        *,
        customer: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "fields": "id,number,statusName,status,customer,customerId,branch,branchId,transDate,totalAmount",
            "sp.pageSize": max(1, min(limit, 200)),
        }
        # Accurate filter keywords vary by tenant; pass soft filters when provided.
        if customer:
            params["filter.keywords.op"] = "CONTAIN"
            params["filter.keywords.val"] = customer
        data = await self._request("GET", "/accurate/api/sales-order/list.do", params=params)
        rows = data.get("d") or data.get("data") or []
        if not isinstance(rows, list):
            raise AccurateUpstreamError(
                "accurate_list_shape",
                "sales-order/list shape tidak dikenali",
                status_code=502,
            )
        out = [normalize_sales_order_list_item(r) for r in rows if isinstance(r, dict)]
        if branch:
            needle = branch.lower()
            out = [
                r
                for r in out
                if needle in str(r.get("branch", {}).get("name", "")).lower()
                or needle == str(r.get("branch", {}).get("id", "")).lower()
            ]
        if status:
            out = [r for r in out if str(r.get("status", "")).upper() == status.upper()]
        return out

    async def get_sales_order(self, number: str) -> dict[str, Any]:
        data = await self._request(
            "GET",
            "/accurate/api/sales-order/detail.do",
            params={"number": number},
        )
        row = data.get("d") or data.get("data") or data
        if not isinstance(row, dict):
            raise AccurateUpstreamError(
                "accurate_detail_shape",
                "sales-order/detail shape tidak dikenali",
                status_code=502,
            )
        return normalize_sales_order(row)

    async def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        # Prefer id; Accurate also accepts number on some tenants.
        params: dict[str, Any]
        if str(receipt_id).isdigit():
            params = {"id": int(receipt_id)}
        else:
            params = {"number": receipt_id}
        data = await self._request(
            "GET",
            "/accurate/api/sales-receipt/detail.do",
            params=params,
        )
        row = data.get("d") or data.get("data") or data
        if not isinstance(row, dict):
            raise AccurateUpstreamError(
                "accurate_receipt_shape",
                "sales-receipt/detail shape tidak dikenali",
                status_code=502,
            )
        return normalize_receipt(row)

    async def get_delivery_note(self, dn_id: str) -> dict[str, Any]:
        params: dict[str, Any]
        if str(dn_id).isdigit():
            params = {"id": int(dn_id)}
        else:
            params = {"number": dn_id}
        data = await self._request(
            "GET",
            "/accurate/api/delivery-order/detail.do",
            params=params,
        )
        row = data.get("d") or data.get("data") or data
        if not isinstance(row, dict):
            raise AccurateUpstreamError(
                "accurate_delivery_shape",
                "delivery-order/detail shape tidak dikenali",
                status_code=502,
            )
        return normalize_delivery_note(row)
