"""Security: JWT key and password pepper must stay separate."""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("V3_JWT_SECRET", "v3_test_jwt_secret_not_from_v1")
os.environ.setdefault("V3_PASSWORD_PEPPER", "v3_test_password_pepper_distinct")

from app.core.config import get_settings
from app.core.security import hash_password, require_password_pepper, verify_password


def test_password_hash_uses_dedicated_pepper_format() -> None:
    get_settings.cache_clear()
    hashed = hash_password("secret-pass")
    assert hashed.startswith("pbkdf2_sha256$120000$")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_pepper_must_differ_from_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V3_JWT_SECRET", "same-value-not-allowed")
    monkeypatch.setenv("V3_PASSWORD_PEPPER", "same-value-not-allowed")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        require_password_pepper()
    assert exc.value.status_code == 503
    get_settings.cache_clear()
