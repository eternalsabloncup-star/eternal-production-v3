"""HTTPS Accurate Online adapter — read-only, API Token 1.0.3 auth.

Auth (every request, freshly signed):
  Authorization: Bearer <ACCURATE_API_TOKEN>
  X-Api-Timestamp / X-Api-Signature (HMAC-SHA256 + Signature Secret)

Bootstrap:
  POST https://account.accurate.id/api/api-token.do
  → database id + host (d.database)

Business GETs on returned host:
  /accurate/api/sales-order/list.do|detail.do
  /accurate/api/sales-receipt/detail.do
  /accurate/api/delivery-order/detail.do

HTTP 308: do not reuse stale signed headers — update host and re-sign.
Never reuse ERP V1 secrets. Never log credentials.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.accurate_auth import auth_headers, normalize_host
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
_API_TOKEN_PATH = "/api/api-token.do"


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
        self._database_id: str | None = None

    def configured(self) -> bool:
        return bool(
            (self._settings.accurate_api_token or "").strip()
            and (self._settings.accurate_signature_secret or "").strip()
        )

    def _signed_headers(self) -> dict[str, str]:
        token = self._settings.accurate_api_token.strip()
        secret = self._settings.accurate_signature_secret.strip()
        if not token or not secret:
            raise AccurateUpstreamError(
                "accurate_credentials_missing",
                "ACCURATE_API_TOKEN dan ACCURATE_SIGNATURE_SECRET wajib untuk mode live",
                status_code=503,
            )
        return auth_headers(api_token=token, signature_secret=secret)

    @staticmethod
    def _extract_database(payload: dict[str, Any]) -> tuple[str | None, str | None]:
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        database = data.get("database") if isinstance(data.get("database"), dict) else {}
        if not database and isinstance(payload.get("database"), dict):
            database = payload["database"]
        host = database.get("host") or data.get("host") or payload.get("host")
        if isinstance(host, bool):
            host = None
        db_id = database.get("id") or data.get("databaseId") or payload.get("databaseId")
        host_n = normalize_host(str(host)) if host else None
        db_s = str(db_id).strip() if db_id is not None and str(db_id).strip() else None
        return host_n, db_s

    async def _resolve_host(self, client: httpx.AsyncClient) -> None:
        if self._host:
            return
        account = self._settings.accurate_account_base.rstrip("/")
        url = f"{account}{_API_TOKEN_PATH}"
        try:
            resp = await client.post(url, headers=self._signed_headers())
        except httpx.RequestError as exc:
            raise AccurateUpstreamError(
                "accurate_api_token_unreachable",
                "api-token.do unreachable",
                status_code=502,
            ) from exc

        # Manual 308 handling with re-signed headers (never auto-follow stale sig).
        if resp.status_code in {301, 302, 307, 308}:
            location = resp.headers.get("Location") or resp.headers.get("location")
            if not location:
                raise AccurateUpstreamError(
                    "accurate_api_token_redirect_missing",
                    f"api-token.do HTTP {resp.status_code} tanpa Location",
                    status_code=502,
                )
            next_url = urljoin(url, location)
            try:
                resp = await client.post(next_url, headers=self._signed_headers())
            except httpx.RequestError as exc:
                raise AccurateUpstreamError(
                    "accurate_api_token_unreachable",
                    "api-token.do redirect unreachable",
                    status_code=502,
                ) from exc
            # If redirect points at a business host, remember it.
            parsed = urlparse(next_url)
            if parsed.netloc and "account.accurate.id" not in parsed.netloc:
                self._host = normalize_host(f"{parsed.scheme}://{parsed.netloc}")

        if resp.status_code == 401:
            raise AccurateUpstreamError(
                "accurate_auth_rejected",
                "api-token.do menolak token/signature",
                status_code=502,
            )
        if resp.status_code >= 400:
            raise AccurateUpstreamError(
                "accurate_api_token_rejected",
                f"api-token.do HTTP {resp.status_code}",
                status_code=502,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AccurateUpstreamError(
                "accurate_api_token_invalid",
                "api-token.do response bukan JSON",
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise AccurateUpstreamError(
                "accurate_api_token_shape",
                "api-token.do shape tidak dikenali",
                status_code=502,
            )
        if payload.get("s") is False:
            raise AccurateUpstreamError(
                "accurate_api_token_business_reject",
                "api-token.do s=false",
                status_code=502,
            )
        host, db_id = self._extract_database(payload)
        if not host:
            raise AccurateUpstreamError(
                "accurate_host_missing",
                "api-token.do tidak mengembalikan database.host",
                status_code=502,
            )
        self._host = host
        self._database_id = db_id
        # Pin: when ACCURATE_DATABASE_ID is set, resolved id must be present and match.
        expected = (self._settings.accurate_database_id or "").strip()
        if expected:
            if not db_id:
                raise AccurateUpstreamError(
                    "accurate_database_id_missing",
                    "api-token.do tidak mengembalikan database.id — pin gagal",
                    status_code=502,
                )
            if expected != str(db_id).strip():
                raise AccurateUpstreamError(
                    "accurate_database_mismatch",
                    "Database id dari api-token.do tidak cocok dengan konfigurasi",
                    status_code=502,
                )
        # Never log token/secret/database credentials — flags only.
        logger.info(
            "accurate host resolved",
            extra={"has_database_id": bool(db_id), "host_set": True, "pin_enforced": bool(expected)},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: AccurateUpstreamError | None = None
        # follow_redirects=False so 308 can be re-signed.
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    await self._resolve_host(client)
                    assert self._host
                    url = f"{self._host}{path}"
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        headers=self._signed_headers(),
                    )
                except AccurateUpstreamError:
                    raise
                except httpx.RequestError as exc:
                    last_error = AccurateUpstreamError(
                        "accurate_unreachable",
                        "upstream unreachable",
                        status_code=502,
                    )
                    continue

                if resp.status_code in {301, 302, 307, 308}:
                    location = resp.headers.get("Location") or resp.headers.get("location")
                    if not location:
                        raise AccurateUpstreamError(
                            "accurate_redirect_missing",
                            f"HTTP {resp.status_code} tanpa Location",
                            status_code=502,
                        )
                    next_url = urljoin(str(resp.request.url), location)
                    parsed = urlparse(next_url)
                    if parsed.scheme and parsed.netloc:
                        self._host = normalize_host(
                            f"{parsed.scheme}://{parsed.netloc}"
                        )
                    retry_url = (
                        next_url
                        if parsed.path and parsed.path != "/"
                        else f"{self._host}{path}"
                    )
                    try:
                        resp = await client.request(
                            method,
                            retry_url,
                            params=params,
                            headers=self._signed_headers(),
                        )
                    except httpx.RequestError as exc:
                        last_error = AccurateUpstreamError(
                            "accurate_unreachable",
                            "upstream redirect unreachable",
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
                        self._database_id = None
                    continue
                if resp.status_code == 401:
                    raise AccurateUpstreamError(
                        "accurate_auth_rejected",
                        "Accurate menolak token/signature",
                        status_code=502,
                    )
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
                    raise AccurateUpstreamError(
                        "accurate_business_reject",
                        "Accurate s=false",
                        status_code=502,
                    )
                return data if isinstance(data, dict) else {"d": data}
            assert last_error is not None
            raise last_error

    @staticmethod
    def _extract_list_total(data: dict[str, Any], page_len: int) -> int | None:
        """Accurate list totals when present — never invent from page length alone."""
        sp = data.get("sp") if isinstance(data.get("sp"), dict) else {}
        for key in ("rowCount", "rowTotal", "totalRows", "totalRow"):
            val = sp.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
        for key in ("rowCount", "total", "totalRows"):
            val = data.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
        return None

    async def list_sales_orders(
        self,
        *,
        customer: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        page_n = max(1, int(page or 1))
        page_size = max(1, min(int(limit or 50), 200))
        params: dict[str, Any] = {
            # List is summary-only (no detailItem). Extra identity fields when Accurate returns them.
            "fields": (
                # Summary-only (no detailItem). Include Owner-approved header CF
                # slots (Slice 1N CF3/4/5) so list can surface zone/status/buffer
                # when Accurate returns them — never invent if absent.
                "id,number,statusName,status,customer,customerId,customerName,"
                "branch,branchId,branchName,transDate,totalAmount,"
                "poNumber,poNo,customerPoNumber,"
                "salesPersonName,salesmanName,salesName,salesPerson,salesmanList,"
                "salesPersonList,createdUserName,inputUserName,"
                "charField3,charField4,charField5,"
                "charField3Name,charField4Name,charField5Name"
            ),
            "sp.pageSize": page_size,
            "sp.page": page_n,
        }
        if customer:
            params["filter.keywords.op"] = "CONTAIN"
            params["filter.keywords.val"] = customer
        # Prefer Accurate-side filters so page totals stay meaningful.
        upstream_status = False
        upstream_branch = False
        if status:
            params["filter.statusName.op"] = "EQUAL"
            params["filter.statusName.val"] = status
            upstream_status = True
        if branch and str(branch).strip().isdigit():
            params["filter.branchId.op"] = "EQUAL"
            params["filter.branchId.val"] = int(str(branch).strip())
            upstream_branch = True
        data = await self._request(
            "GET", "/accurate/api/sales-order/list.do", params=params
        )
        rows = data.get("d") or data.get("data") or []
        if not isinstance(rows, list):
            raise AccurateUpstreamError(
                "accurate_list_shape",
                "sales-order/list shape tidak dikenali",
                status_code=502,
            )
        out = [normalize_sales_order_list_item(r) for r in rows if isinstance(r, dict)]
        filter_incomplete = False
        # Name-based branch cannot be fully expressed upstream — page-local only.
        if branch and not upstream_branch:
            needle = branch.lower()
            before = len(out)
            out = [
                r
                for r in out
                if needle in str((r.get("branch") or {}).get("name", "")).lower()
                or needle == str((r.get("branch") or {}).get("id", "")).lower()
            ]
            if len(out) != before:
                filter_incomplete = True
        # If status still mismatches after upstream filter, narrow page only.
        if status:
            before = len(out)
            out = [
                r for r in out if str(r.get("status", "")).upper() == status.upper()
            ]
            if len(out) != before:
                filter_incomplete = True
            if not upstream_status and before != len(out):
                filter_incomplete = True
        accurate_total = self._extract_list_total(data, len(out))
        return {
            "rows": out,
            "accurate_total": accurate_total,
            "page": page_n,
            "page_size": page_size,
            "filter_incomplete": filter_incomplete,
            "upstream_status_filter": upstream_status,
            "upstream_branch_filter": upstream_branch,
        }

    async def _fetch_so_detail(self, params: dict[str, Any]) -> dict[str, Any]:
        data = await self._request(
            "GET",
            "/accurate/api/sales-order/detail.do",
            params=params,
        )
        row = data.get("d") or data.get("data") or data
        if not isinstance(row, dict):
            raise AccurateUpstreamError(
                "accurate_detail_shape",
                "sales-order/detail shape tidak dikenali",
                status_code=502,
            )
        return normalize_sales_order(row)

    async def _resolve_so_id_by_number(self, so_number: str) -> int:
        """Map Accurate document number → internal id. Never log the number."""
        attempts: list[dict[str, Any]] = [
            {
                "fields": "id,number",
                "sp.pageSize": 20,
                "sp.page": 1,
                "filter.number.op": "EQUAL",
                "filter.number.val": so_number,
            },
            {
                "fields": "id,number",
                "sp.pageSize": 50,
                "sp.page": 1,
                "filter.keywords.op": "EQUAL",
                "filter.keywords.val": so_number,
            },
        ]
        for params in attempts:
            try:
                data = await self._request(
                    "GET", "/accurate/api/sales-order/list.do", params=params
                )
            except AccurateUpstreamError as exc:
                # Unsupported filter variants → try next strategy; never invent detail.
                if exc.status_code in {404, 502}:
                    continue
                raise
            rows = data.get("d") or data.get("data") or []
            if not isinstance(rows, list):
                continue
            exact = [
                r
                for r in rows
                if isinstance(r, dict)
                and str(r.get("number") or r.get("no") or "").strip() == so_number
            ]
            if len(exact) == 1 and exact[0].get("id") is not None:
                try:
                    return int(exact[0]["id"])
                except (TypeError, ValueError) as exc:
                    raise AccurateUpstreamError(
                        "accurate_detail_shape",
                        "sales-order id tidak valid",
                        status_code=502,
                    ) from exc
        raise AccurateUpstreamError(
            "accurate_not_found",
            "dokumen tidak ditemukan di Accurate",
            status_code=404,
        )

    async def get_sales_order(self, number: str) -> dict[str, Any]:
        """Load SO detail.

        Accurate Online ``sales-order/detail.do`` requires the numeric internal
        ``id`` (not document number). Callers may pass either:
        - internal id (digits) → detail.do?id=
        - document number → resolve via list, then detail.do?id=
        """
        key = (number or "").strip()
        if not key:
            raise AccurateUpstreamError(
                "accurate_not_found",
                "dokumen tidak ditemukan di Accurate",
                status_code=404,
            )
        if key.isdigit():
            return await self._fetch_so_detail({"id": int(key)})
        so_id = await self._resolve_so_id_by_number(key)
        return await self._fetch_so_detail({"id": so_id})

    async def get_receipt(self, receipt_id: str) -> dict[str, Any]:
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
