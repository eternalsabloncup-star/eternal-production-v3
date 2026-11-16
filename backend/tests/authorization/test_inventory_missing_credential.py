"""Cutover inventory must block users without AccountCredential (Settings path)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.authorization.accounts import AccountCredential
from app.authorization.inventory import build
from app.core.security import hash_password
from app.models.user import User
from tests.authorization.test_foundation import db  # noqa: F401
from tests.authorization.test_runtime import runtime


@pytest.mark.asyncio
async def test_missing_credential_is_blocking(runtime):
    db_factory, _client = runtime
    async with db_factory.begin() as session:
        session.add(
            User(
                username="no.cred",
                display_name="No Cred",
                role="operator",
                password_hash=hash_password("sandbox-runtime-password"),
                permissions=["production.job.read"],
                branch_ids=["A"],
                is_active=True,
            )
        )

    async with db_factory() as session:
        user = await session.scalar(select(User).where(User.username == "no.cred"))
        assert user is not None
        assert await session.get(AccountCredential, user.id) is None
        report = await build(session, declare_readonly=False)
        assert user.id in report["missing_credential_user_ids"]
        row = next(r for r in report["users"] if r["user_id"] == user.id)
        assert row["missing_credential"] is True
        assert row["blocking"] is True
        assert report["cutover_review_clear"] is False
