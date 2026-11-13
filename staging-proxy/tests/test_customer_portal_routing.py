"""Focused regression: /t/* must proxy to backend before StaticFiles."""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# Import under test (staging-proxy is not a package; load by path).
import importlib.util

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("epv3_staging_proxy", _ROOT / "app.py")
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class _BackendHandler(BaseHTTPRequestHandler):
    """Minimal backend that echoes path/method/body and records hits."""

    hits: list[dict] = []

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.hits.append(
            {
                "method": self.command,
                "path": self.path,
                "body": body,
                "content_type": self.headers.get("Content-Type"),
            }
        )
        # Simulate customer portal HTML / JSON / decision.
        if self.path.endswith("/decision") and self.command == "POST":
            payload = b'{"ok":true,"decision":"approved"}'
            status = 200
            ctype = "application/json"
        elif self.path.endswith(".json"):
            payload = b'{"scope":"design_approval","po_ref":"SO-X"}'
            status = 200
            ctype = "application/json"
        elif self.path.startswith("/t/"):
            # Include a marker that StaticFiles would never serve.
            payload = b"<html><body>BACKEND_PORTAL_OK</body></html>"
            status = 404 if "invalid-token" in self.path else 200
            ctype = "text/html; charset=utf-8"
        elif self.path.startswith("/api/v1/health"):
            payload = b'{"status":"ok"}'
            status = 200
            ctype = "application/json"
        else:
            payload = b'{"detail":"not found"}'
            status = 404
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Upstream", "epv3-backend")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()


@pytest.fixture()
def backend_server(monkeypatch: pytest.MonkeyPatch):
    _BackendHandler.hits = []
    server = HTTPServer(("127.0.0.1", 0), _BackendHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("EPV3_BACKEND_BASE", f"http://127.0.0.1:{port}")
    # Reload module constants that captured env at import — patch attribute.
    monkeypatch.setattr(_mod, "BACKEND_BASE", f"http://127.0.0.1:{port}")
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def static_root(tmp_path: Path) -> Path:
    # Static would 404 /t/... unless a file exists; leave empty so StaticFiles
    # cannot satisfy /t paths (proxy must win).
    (tmp_path / "production.html").write_text("<html>static</html>", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def proxy_client(backend_server, static_root: Path):
    app = _mod.create_app(frontend_root=str(static_root), mount_static=True)
    with TestClient(app) as client:
        yield client


def test_t_get_html_proxied_not_static(proxy_client: TestClient):
    r = proxy_client.get("/t/cust/po-1/valid-token-aaaaaaaa")
    assert r.status_code == 200
    assert "BACKEND_PORTAL_OK" in r.text
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert _BackendHandler.hits[-1]["method"] == "GET"
    assert _BackendHandler.hits[-1]["path"].startswith("/t/cust/po-1/")


def test_t_get_json_and_invalid_status_preserved(proxy_client: TestClient):
    ok = proxy_client.get("/t/cust/po-1/tok.json")
    assert ok.status_code == 200
    assert ok.json()["scope"] == "design_approval"

    bad = proxy_client.get("/t/example/po-example/invalid-token")
    assert bad.status_code == 404
    assert "BACKEND_PORTAL_OK" in bad.text
    # Path and token not rewritten.
    assert "invalid-token" in _BackendHandler.hits[-1]["path"]


def test_t_post_decision_body_and_status_preserved(proxy_client: TestClient):
    body = {"decision": "approved", "note": "ok"}
    r = proxy_client.post(
        "/t/cust/po-1/tok/decision",
        json=body,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    hit = _BackendHandler.hits[-1]
    assert hit["method"] == "POST"
    assert hit["path"] == "/t/cust/po-1/tok/decision"
    assert b'"decision":"approved"' in hit["body"].replace(b" ", b"")


def test_api_v1_still_proxied(proxy_client: TestClient):
    r = proxy_client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_static_still_serves_frontend(proxy_client: TestClient):
    r = proxy_client.get("/production.html")
    assert r.status_code == 200
    assert "static" in r.text
    # No backend hit for pure static.
    assert all(not h["path"].startswith("/production") for h in _BackendHandler.hits)


def test_proxy_does_not_follow_redirects(backend_server, static_root, monkeypatch):
    """Upstream 302 must be returned as-is (follow_redirects=False)."""

    class RedirectHandler(_BackendHandler):
        def _respond(self) -> None:
            self.send_response(302)
            self.send_header("Location", "http://evil.example/leak")
            self.send_header("Content-Length", "0")
            self.end_headers()

    # Spin a redirect-only backend on a new port.
    RedirectHandler.hits = []
    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(_mod, "BACKEND_BASE", f"http://127.0.0.1:{port}")
    app = _mod.create_app(frontend_root=str(static_root), mount_static=True)
    with TestClient(app, follow_redirects=False) as client:
        r = client.get("/t/a/b/c")
        assert r.status_code == 302
        assert r.headers.get("location") == "http://evil.example/leak"
    server.shutdown()
