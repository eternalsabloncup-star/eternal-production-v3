"""Step 113 — sanitized stage diagnostics for four-field live probe."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "slice90_four_field_live_probe.py"

FORBIDDEN = [
    "Bearer ",
    "Traceback (most recent",
    "PO/12/11/2026/",
    "GAYO",
    "/etc/epv3/gateway.env",
    "secret-token",
]


def _load():
    spec = importlib.util.spec_from_file_location("slice90_probe_113", PROBE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeUpstream(Exception):
    def __init__(self, code: str, message: str = "SECRET leak path=/x?token=1") -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def test_syntax_check():
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--syntax-check-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["ok"] is True


def test_failure_load_config_missing_env():
    mod = _load()
    slice1l = mod._load_slice1l()
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="load_config",
        exc=FileNotFoundError("env file missing SECRET"),
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "load_config"
    assert fail["blocker"] == "env_file_missing"
    assert fail["error"]["message"] == "redacted"
    blob = json.dumps(fail)
    assert "SECRET" not in blob
    assert "SO/SYN" not in blob
    for marker in FORBIDDEN:
        assert marker not in blob


def test_failure_init_client_unknown():
    mod = _load()
    slice1l = mod._load_slice1l()
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="init_client",
        exc=RuntimeError("cannot build client token=secret-token"),
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "init_client"
    assert fail["blocker"] == "probe_runtime_error"
    assert fail["error"]["code"] == "probe_runtime_error"
    assert "secret-token" not in json.dumps(fail)


def test_failure_resolve_so_preserves_allowlisted_code():
    mod = _load()
    slice1l = mod._load_slice1l()
    # Mimic AccurateUpstreamError name for sanitize type allowlist via code attr only.
    exc = _FakeUpstream("accurate_not_found")
    # Force type name into sanitize by subclassing with correct name if needed.
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="resolve_so",
        exc=exc,
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "resolve_so"
    assert fail["blocker"] == "accurate_not_found"
    assert fail["error"]["code"] == "accurate_not_found"
    assert "SECRET" not in json.dumps(fail)


def test_failure_fetch_detail_http_error_code_kept():
    mod = _load()
    slice1l = mod._load_slice1l()
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="fetch_detail",
        exc=_FakeUpstream("accurate_http_error", "url=https://x/detail?id=1"),
        mode="verify",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "fetch_detail"
    assert fail["blocker"] == "accurate_http_error"
    assert "https://" not in json.dumps(fail)
    assert fail["error"]["message"] == "redacted"


def test_failure_normalize_unknown():
    mod = _load()
    slice1l = mod._load_slice1l()
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="normalize_four_fields",
        exc=TypeError("bad shape"),
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "normalize_four_fields"
    assert fail["blocker"] == "probe_runtime_error"
    assert "bad shape" not in json.dumps(fail)


def test_failure_unknown_exception_still_staged():
    mod = _load()
    slice1l = mod._load_slice1l()

    class WeirdBoom(Exception):
        pass

    fail = mod.failure_report(
        slice1l=slice1l,
        stage="fetch_detail",
        exc=WeirdBoom("token=abc customer=ACME"),
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["stage"] == "fetch_detail"
    assert fail["blocker"] == "probe_runtime_error"
    assert fail["error"]["type"] == "ProbeError"
    assert fail["error"]["message"] == "redacted"
    blob = json.dumps(fail)
    assert "token=abc" not in blob
    assert "ACME" not in blob


def test_classify_blocker_permission():
    mod = _load()
    codes = mod._load_slice1l()._SAFE_ERROR_CODES
    assert (
        mod.classify_blocker(PermissionError("x"), "load_config", codes)
        == "env_file_unreadable"
    )


def test_http_methods_included_on_failure_without_bodies():
    mod = _load()
    slice1l = mod._load_slice1l()
    slice1l._HTTP_METHODS_EXECUTED.clear()
    slice1l._record_executed("GET /accurate/api/sales-order/list.do")
    fail = mod.failure_report(
        slice1l=slice1l,
        stage="resolve_so",
        exc=_FakeUpstream("accurate_identity_ambiguous"),
        mode="discover",
        so_number="SO/SYN/113",
    )
    assert fail["http"]["executed_methods"] == [
        "GET /accurate/api/sales-order/list.do"
    ]
    assert "body" not in json.dumps(fail).lower() or "request_body" not in fail
