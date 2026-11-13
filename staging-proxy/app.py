"""Eternal V3 staging/live edge proxy (VPS: /opt/epv3/staging-proxy/app.py).

Routes:
  /api/v1/*  → backend :8100  (unchanged)
  /t/*       → backend :8100  (customer portal; BEFORE StaticFiles)
  /*         → StaticFiles(frontend dist)

Preserves method, path, query, body, and upstream status.
Does not follow redirects. Adds no-store / no-referrer / security headers.
"""

from __future__ import annotations

import os
from typing import Iterable

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

BACKEND_BASE = os.environ.get("EPV3_BACKEND_BASE", "http://127.0.0.1:8100").rstrip("/")
FRONTEND_ROOT = os.environ.get(
    "EPV3_FRONTEND_ROOT",
    "/var/www/epv3/frontend/dist",
)
PROXY_TIMEOUT = float(os.environ.get("EPV3_PROXY_TIMEOUT_SEC", "30"))

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _filter_request_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        out[key] = value
    return out


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk == "content-encoding":
            # Body already decoded by httpx when we use .content.
            continue
        out[key] = value
    out.update(_SECURITY_HEADERS)
    return out


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


async def _proxy_to_backend(request: Request) -> Response:
    """Forward GET/POST (and other methods) to backend without rewriting path/body."""
    target = f"{BACKEND_BASE}{request.url.path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    body = await request.body()
    headers = _filter_request_headers(request.headers.items())
    try:
        async with httpx.AsyncClient(
            timeout=PROXY_TIMEOUT,
            follow_redirects=False,
        ) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=headers,
                content=body,
            )
    except httpx.RequestError:
        return JSONResponse(
            {"detail": "Backend unavailable"},
            status_code=502,
            headers=dict(_SECURITY_HEADERS),
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


def create_app(
    *,
    frontend_root: str | None = None,
    mount_static: bool = True,
) -> FastAPI:
    application = FastAPI(title="EPV3 Staging Proxy", docs_url=None, redoc_url=None)
    application.add_middleware(SecurityHeadersMiddleware)

    @application.api_route(
        "/api/v1",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    @application.api_route(
        "/api/v1/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_api(request: Request, path: str = "") -> Response:
        return await _proxy_to_backend(request)

    # Customer portal — must be registered BEFORE StaticFiles mount.
    @application.api_route(
        "/t/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_customer_portal(request: Request, path: str) -> Response:
        return await _proxy_to_backend(request)

    root = frontend_root or FRONTEND_ROOT
    if mount_static and root and os.path.isdir(root):
        application.mount(
            "/",
            StaticFiles(directory=root, html=True),
            name="frontend",
        )

    return application


app = create_app()
