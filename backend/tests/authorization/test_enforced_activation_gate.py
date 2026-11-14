"""Production-safe enforced gate + Director status. Never activates Live."""
import pytest
from types import SimpleNamespace

from app.authorization.mode import authorization_status, enforced_startup_allowed
from app.core.config import get_settings
from app.main import create_app
from tests.authorization.test_runtime import runtime, login


def _settings(**kwargs):
    base = dict(
        v3_workflow_authorization="legacy",
        v3_settings_enabled=False,
        app_env="production",
        v3_workflow_enforced_approval_ref="",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_legacy_always_allowed():
    enforced_startup_allowed(_settings())


def test_enforced_requires_settings():
    with pytest.raises(RuntimeError, match="V3_SETTINGS_ENABLED"):
        enforced_startup_allowed(_settings(v3_workflow_authorization="enforced", app_env="test"))


def test_enforced_allowed_in_test_sandbox():
    enforced_startup_allowed(
        _settings(
            v3_workflow_authorization="enforced",
            v3_settings_enabled=True,
            app_env="test",
        )
    )


def test_enforced_blocked_outside_test_without_approval():
    with pytest.raises(RuntimeError, match="V3_WORKFLOW_ENFORCED_APPROVAL_REF"):
        enforced_startup_allowed(
            _settings(
                v3_workflow_authorization="enforced",
                v3_settings_enabled=True,
                app_env="production",
            )
        )


def test_enforced_allowed_with_owner_approval_ref_outside_test():
    enforced_startup_allowed(
        _settings(
            v3_workflow_authorization="enforced",
            v3_settings_enabled=True,
            app_env="production",
            v3_workflow_enforced_approval_ref="DIR-APPROVAL-2026-11-14",
        )
    )


def test_status_never_echoes_approval_ref_and_lists_blockers():
    payload = authorization_status(
        _settings(
            v3_workflow_authorization="legacy",
            v3_settings_enabled=True,
            app_env="production",
            v3_workflow_enforced_approval_ref="SECRET-REF-DO-NOT-ECHO",
        ),
        bootstrapped=True,
        inventory_summary={
            "cutover_review_clear": False,
            "blocking_user_ids": [3],
            "automatic_import_allowed": False,
        },
    )
    raw = str(payload)
    assert "SECRET-REF-DO-NOT-ECHO" not in raw
    assert payload["enforced_approval_ref_configured"] is True
    assert payload["active_now"] is False
    assert payload["automatic_grant_import"] is False
    assert payload["production_endpoints_mapped"] == 61
    assert any("Inventory cutover belum clear" in b for b in payload["blockers"])
    assert "production.job.read" in payload["mapping_review_required"]
    assert payload["activation_recommended"] is False


def test_create_app_still_defaults_to_legacy(monkeypatch):
    monkeypatch.setenv("V3_SETTINGS_ENABLED", "false")
    monkeypatch.setenv("V3_WORKFLOW_AUTHORIZATION", "legacy")
    monkeypatch.delenv("V3_WORKFLOW_ENFORCED_APPROVAL_REF", raising=False)
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.title
    finally:
        get_settings.cache_clear()


def test_create_app_rejects_enforced_without_safeguards(monkeypatch):
    monkeypatch.setenv("V3_SETTINGS_ENABLED", "true")
    monkeypatch.setenv("V3_WORKFLOW_AUTHORIZATION", "enforced")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("V3_WORKFLOW_ENFORCED_APPROVAL_REF", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="V3_WORKFLOW_ENFORCED_APPROVAL_REF"):
            create_app()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_director_status_endpoint_and_operator_denied(runtime):
    _, client = runtime
    director, _ = await login(client)
    operator, data = await login(client, "test-3")
    assert data["system_director"] is False
    denied = await client.get("/api/v1/settings/authorization-status", headers=operator)
    assert denied.status_code == 403
    ok = await client.get("/api/v1/settings/authorization-status", headers=director)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["workflow_authorization"] == "legacy"
    assert body["active_now"] is False
    assert body["automatic_grant_import"] is False
    assert "SECRET" not in str(body)
    assert isinstance(body["blockers"], list) and body["blockers"]
