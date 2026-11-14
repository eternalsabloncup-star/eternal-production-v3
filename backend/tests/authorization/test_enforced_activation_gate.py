"""Production-safe enforced gate + Director status. Never activates Live."""
import pytest
from types import SimpleNamespace

from app.authorization.catalog import CATALOG, MAPPING_REVIEW_REQUIRED
from app.authorization.evaluator import Access, Resource, evaluate
from app.authorization.mode import authorization_status, enforced_startup_allowed
from app.authorization.owner_policy import (
    AUTOMATIC_GRANT_IMPORT_ALLOWED,
    MAPPING_OWNER_RESOLUTIONS,
    policy_invariants,
)
from app.core.config import get_settings
from app.main import create_app
from tests.authorization.test_foundation import db  # noqa: F401 — required by runtime
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
    assert payload["mapping_review_required"]["production.job.read"]["impact"]
    assert payload["activation_recommended"] is False
    assert payload["owner_policy"]["automatic_grant_import_allowed"] is False
    assert payload["inventory_audit"]["conclusion"] == "blocked"


def test_owner_policy_invariants_and_director_full_access():
    assert AUTOMATIC_GRANT_IMPORT_ALLOWED is False
    inv = policy_invariants()
    assert inv["director_full_access"] is True
    assert inv["manual_user_creation_only"] is True
    assert inv["no_silent_legacy_account_mutation"] is True
    assert set(MAPPING_REVIEW_REQUIRED) == set(MAPPING_OWNER_RESOLUTIONS)
    for key, detail in MAPPING_OWNER_RESOLUTIONS.items():
        assert "manual_only" in detail["status"]
        assert detail["impact"] and detail["recommendation"] and detail["owner_decision"]
    # Director Full Access: every catalog capability allowed across branches.
    director = Access(user_id=1, active=True, director=True, grants=(), revision=1)
    for code, cap in CATALOG.items():
        resource = Resource() if cap.scope == "global" else Resource("ANY-BRANCH")
        assert evaluate(director, code, resource).allowed, code
    # Empty grants: non-director default deny.
    employee = Access(user_id=3, active=True, director=False, grants=(), revision=1)
    assert evaluate(employee, "job.read", Resource("A")).allowed is False


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
    assert body["owner_policy"]["director_full_access"] is True
    assert set(body["mapping_review_required"]) == set(MAPPING_REVIEW_REQUIRED)
    assert body["mapping_review_required"]["production.tracking.read"]["recommendation"]
    assert body["inventory_audit"]["writes_performed"] is False
