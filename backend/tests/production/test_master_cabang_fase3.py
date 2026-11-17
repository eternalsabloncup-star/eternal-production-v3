"""Master Cabang CRUD + permission + referential safety (disposable PG via create_all)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models.production.branch import ProductionBranch, ProductionBranchAudit
from app.models.production.job import ProductionJob
from app.models.production.operations import ProductionMachine
from app.models.user import User
from app.services.production import branches as branch_svc
from app.services.production import permissions as P


@pytest.fixture
async def case():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        director = User(
            username="mc-dir",
            display_name="Direktur MC",
            role="Direktur",
            password_hash="unused",
            branch_ids=["BR-JKT"],
            permissions=[P.JOB_READ],
        )
        operator = User(
            username="mc-op",
            display_name="Operator MC",
            role="operator",
            password_hash="unused",
            branch_ids=["BR-JKT"],
            permissions=[P.JOB_READ],
        )
        job = ProductionJob(
            accurate_so_number="SO-MC-001",
            accurate_id="901",
            branch_id="BR-JKT",
            customer_name="PT Master Cabang",
            design_status="bypassed",
        )
        machine = ProductionMachine(
            branch_id="BR-JKT",
            name="Semi Auto MC",
            kind="semi_auto",
            capacity_per_shift=1000,
            shifts_per_day=1,
            active=True,
            created_by=0,
        )
        session.add_all([director, operator, job, machine])
        await session.commit()
        return director.id, operator.id, job.id, machine.id


@pytest.mark.asyncio
async def test_crud_simpan_baca_audit_and_immutable_code(case):
    did, oid, jid, mid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        created = await branch_svc.create_branch(
            session,
            director,
            code="BR-JKT",
            name="Jakarta",
            reason="Daftar cabang existing eksplisit",
            sort_order=1,
        )
        assert created["code"] == "BR-JKT"
        assert created["name"] == "Jakarta"
        assert created["writable"] is True

        listed = await branch_svc.list_branches(session, director)
        assert listed["can_manage"] is True
        assert listed["persistence"] == "production_branches"
        assert listed["manual_grant_branch_manage_allowed"] is False
        master = next(i for i in listed["items"] if i["code"] == "BR-JKT")
        assert master["source"] == "master"
        assert master["references"]["jobs"] >= 1
        assert master["references"]["machines"] >= 1
        assert master["references"]["users"] >= 1

        updated = await branch_svc.update_branch(
            session,
            director,
            code="BR-JKT",
            name="Jakarta Pusat",
            reason="Ubah nama cabang",
            active=True,
        )
        assert updated["name"] == "Jakarta Pusat"

        again = await branch_svc.get_branch(session, director, "BR-JKT")
        assert again["name"] == "Jakarta Pusat"

        audit = await branch_svc.list_branch_audit(session, director, limit=10)
        actions = [a["action"] for a in audit["items"]]
        assert "branch.create" in actions
        assert "branch.update" in actions

        # Existing job / machine ownership unchanged
        job = await session.get(ProductionJob, jid)
        machine = await session.get(ProductionMachine, mid)
        assert job.branch_id == "BR-JKT"
        assert machine.branch_id == "BR-JKT"

        # Duplicate code rejected
        with pytest.raises(HTTPException) as dup:
            await branch_svc.create_branch(
                session, director, code="BR-JKT", name="Dup", reason="duplikat kode"
            )
        assert dup.value.status_code == 409

        # Soft deactivate allowed even with references (no hard delete)
        deactivated = await branch_svc.update_branch(
            session,
            director,
            code="BR-JKT",
            reason="Nonaktif sementara",
            active=False,
        )
        assert deactivated["active"] is False
        assert (await session.get(ProductionJob, jid)).branch_id == "BR-JKT"


@pytest.mark.asyncio
async def test_operator_cannot_manage_legacy(case):
    _did, oid, _jid, _mid = case
    async with get_session_factory()() as session:
        operator = await session.get(User, oid)
        listed = await branch_svc.list_branches(session, operator)
        assert listed["can_manage"] is False
        assert all(not i.get("writable") for i in listed["items"] if i.get("source") == "master")
        with pytest.raises(HTTPException) as exc:
            await branch_svc.create_branch(
                session,
                operator,
                code="BR-NEW",
                name="Baru",
                reason="cobalah buat cabang",
            )
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as audit_exc:
            await branch_svc.list_branch_audit(session, operator)
        assert audit_exc.value.status_code == 403


@pytest.mark.asyncio
async def test_http_endpoints_director_and_operator(case):
    did, oid, _jid, _mid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        operator = await session.get(User, oid)
        dtoken = create_access_token(director)
        otoken = create_access_token(operator)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Operator may read list
        ro = await ac.get(
            "/api/v1/production/settings/branches",
            headers={"Authorization": f"Bearer {otoken}"},
        )
        assert ro.status_code == 200
        assert ro.json()["can_manage"] is False

        # Operator create forbidden
        denied = await ac.post(
            "/api/v1/production/settings/branches",
            headers={"Authorization": f"Bearer {otoken}"},
            json={"code": "BR-X", "name": "X", "reason": "operator coba"},
        )
        assert denied.status_code == 403

        # Director create → read → audit
        created = await ac.post(
            "/api/v1/production/settings/branches",
            headers={"Authorization": f"Bearer {dtoken}"},
            json={
                "code": "BR-SBY",
                "name": "Surabaya",
                "reason": "Cabang baru eksplisit Direktur",
                "sort_order": 2,
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["code"] == "BR-SBY"

        listed = await ac.get(
            "/api/v1/production/settings/branches",
            headers={"Authorization": f"Bearer {dtoken}"},
        )
        assert listed.status_code == 200
        body = listed.json()
        assert body["can_manage"] is True
        assert body["persistence"] == "production_branches"
        assert any(i["code"] == "BR-SBY" for i in body["items"])

        patched = await ac.patch(
            "/api/v1/production/settings/branches/BR-SBY",
            headers={"Authorization": f"Bearer {dtoken}"},
            json={"name": "Surabaya Timur", "reason": "Koreksi nama cabang", "active": True},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Surabaya Timur"

        detail = await ac.get(
            "/api/v1/production/settings/branches/BR-SBY",
            headers={"Authorization": f"Bearer {dtoken}"},
        )
        assert detail.status_code == 200
        assert detail.json()["name"] == "Surabaya Timur"

        audit = await ac.get(
            "/api/v1/production/settings/branches/audit",
            headers={"Authorization": f"Bearer {dtoken}"},
        )
        assert audit.status_code == 200
        assert len(audit.json()["items"]) >= 2

        # No hard-delete route
        deleted = await ac.delete(
            "/api/v1/production/settings/branches/BR-SBY",
            headers={"Authorization": f"Bearer {dtoken}"},
        )
        assert deleted.status_code in {404, 405, 422}


@pytest.mark.asyncio
async def test_orphan_effective_not_auto_seeded(case):
    did, _oid, _jid, _mid = case
    async with get_session_factory()() as session:
        director = await session.get(User, did)
        listed = await branch_svc.list_branches(session, director)
        # Job branch BR-JKT appears as orphan until explicit create
        orphan = next(i for i in listed["items"] if i["code"] == "BR-JKT")
        assert orphan["source"] == "effective_orphan"
        assert orphan["writable"] is False
        assert await session.scalar(select(func.count()).select_from(ProductionBranch)) == 0


@pytest.mark.asyncio
async def test_settings_branch_manage_not_grantable_to_employee():
    from app.authorization.evaluator import validate_grant
    from app.authorization.models import ScopedGrant

    with pytest.raises(ValueError, match="Director-only"):
        validate_grant(
            ScopedGrant(
                group_id=2,
                capability="settings.branch.manage",
                branches=[],
                ownership="all",
                assignments=[],
                active=True,
            )
        )
