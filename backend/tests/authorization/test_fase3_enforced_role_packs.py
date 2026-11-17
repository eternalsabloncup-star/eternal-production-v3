"""Enforced HTTP matrix for six operational roles — disposable PG only.

Never activates Production. Never auto-grants existing users outside this sandbox.
"""
from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.authorization.catalog import CATALOG
from app.authorization.models import AccessAudit, AccessGroup, Membership, ScopedGrant
from app.authorization.role_packs import PRIVILEGE_OPTIONS, ROLE_PACKS
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models.production.job import ProductionJob
from app.models.production.schedule import ScheduleAssignment
from tests.authorization.test_foundation import db  # noqa: F401
from tests.authorization.test_runtime import login, runtime


@pytest.fixture
async def enforced(runtime, monkeypatch):
    factory, _ = runtime
    monkeypatch.setenv("V3_WORKFLOW_AUTHORIZATION", "enforced")
    get_settings.cache_clear()
    async with factory.begin() as s:
        await s.run_sync(lambda sync: Base.metadata.create_all(sync.connection()))
        for i, branch in [(1, "A"), (2, "B")]:
            s.add(
                ProductionJob(
                    id=i, accurate_so_number=f"ROLE-{i}", branch_id=branch
                )
            )
        await s.flush()
        for i, job in [(1, 1), (2, 1), (3, 2)]:
            s.add(
                ScheduleAssignment(
                    id=i,
                    job_id=job,
                    branch_id="A" if job == 1 else "B",
                    so_line_id=str(i),
                    operator_name="Hist",
                    machine_name="M1",
                    work_date=date(2026, 11, 13),
                    qty_planned=10,
                    created_by=1,
                )
            )
    app = create_app()

    async def connection():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db_session] = connection
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield factory, c


def test_role_packs_use_catalog_only_and_never_auto_apply():
    assert ROLE_PACKS["driver"]["ownership_default"] == "all"
    assert "delivery.sj.cancel_local" not in ROLE_PACKS["driver"]["capabilities"]
    assert "tracking.link.create" not in ROLE_PACKS["driver"]["capabilities"]
    assert "tracking.link.create" not in ROLE_PACKS["kepala_produksi"]["capabilities"]
    assert "payment.bypass.create" not in ROLE_PACKS["kepala_produksi"]["capabilities"]
    for pack in ROLE_PACKS.values():
        for cap in pack["capabilities"]:
            assert cap in CATALOG, cap
    for key in PRIVILEGE_OPTIONS:
        assert PRIVILEGE_OPTIONS[key]["status"] == "mapped_manual_packs"
        assert PRIVILEGE_OPTIONS[key]["director_decision_needed"] is False


async def _revision(c, headers) -> int:
    body = (await c.get("/api/v1/settings/users", headers=headers)).json()
    return int(body["revision"])


async def _ensure_group_and_grants(c, headers, *, name: str, caps: list[str], branches: list[str], ownership: str):
    rev = await _revision(c, headers)
    g = await c.post(
        "/api/v1/settings/groups",
        headers=headers,
        json={"revision": rev, "reason": f"Buat grup {name}", "name": name},
    )
    assert g.status_code == 201, g.text
    group_id = g.json().get("group_id")
    if group_id is None:
        groups = (await c.get("/api/v1/settings/groups", headers=headers)).json()["items"]
        group_id = next(x["id"] for x in groups if x["name"] == name)
    for cap in caps:
        rev = await _revision(c, headers)
        r = await c.post(
            f"/api/v1/settings/groups/{group_id}/grants",
            headers=headers,
            json={
                "revision": rev,
                "reason": f"Grant {cap} untuk {name}",
                "capability": cap,
                "branches": branches,
                "ownership": ownership,
                "assignments": [],
            },
        )
        assert r.status_code == 201, (cap, r.status_code, r.text)
    return group_id


async def _attach_user(c, headers, *, user_id: int, group_id: int):
    rev = await _revision(c, headers)
    r = await c.post(
        f"/api/v1/settings/users/{user_id}/memberships",
        headers=headers,
        json={
            "revision": rev,
            "reason": f"Membership user {user_id} → grup {group_id}",
            "group_id": group_id,
            "active": True,
        },
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_director_full_access_cross_branch_and_status_packs(enforced):
    _, c = enforced
    director, me = await login(c)
    assert me["system_director"] is True
    for job in (1, 2):
        r = await c.get(f"/api/v1/production/jobs/{job}", headers=director)
        assert r.status_code == 200, r.text
    status = await c.get("/api/v1/settings/authorization-status", headers=director)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["workflow_authorization"] == "enforced"
    assert body["active_now"] is True
    assert body["automatic_grant_import"] is False
    assert body["role_grant_packs"]["automatic_apply_allowed"] is False
    assert set(body["role_grant_packs"]["packs"]) == set(ROLE_PACKS)
    assert body["production_endpoints_mapped"] >= 70
    assert "permission_options" in body["mapping_review_required"]["production.tracking.read"]


@pytest.mark.asyncio
async def test_user_without_grant_denied_and_readonly_branch_scoped(enforced):
    db, c = enforced
    director, _ = await login(c)
    operator, _ = await login(c, "test-3")
    assert (await c.get("/api/v1/production/jobs/1", headers=operator)).status_code == 403
    assert (await c.get("/api/v1/production/ops/schedule", headers=operator)).status_code == 403
    assert (await c.get("/api/v1/production/ops/deliveries", headers=operator)).status_code == 403
    # Read-only job.read on branch A only
    gid = await _ensure_group_and_grants(
        c,
        director,
        name="RO-Branch-A",
        caps=["job.read"],
        branches=["A"],
        ownership="all",
    )
    await _attach_user(c, director, user_id=3, group_id=gid)
    assert (await c.get("/api/v1/production/jobs/1", headers=operator)).status_code == 200
    assert (await c.get("/api/v1/production/jobs/2", headers=operator)).status_code == 403
    # Write still denied
    assert (
        await c.post(
            "/api/v1/production/jobs/1/loading",
            headers=operator,
            json={},
        )
    ).status_code in (403, 422)


@pytest.mark.asyncio
async def test_six_role_packs_http_matrix_and_access_audit(enforced):
    db, c = enforced
    director, _ = await login(c)
    # Create a dedicated user per role via Settings (manual path)
    users = {}
    for key, pack in ROLE_PACKS.items():
        rev = await _revision(c, director)
        uname = f"role-{key}"
        created = await c.post(
            "/api/v1/settings/users",
            headers=director,
            json={
                "revision": rev,
                "reason": f"Sandbox user {key}",
                "username": uname,
                "display_name": pack["label"],
                "password": "sandbox-runtime-password",
            },
        )
        assert created.status_code == 201, created.text
        uid = created.json()["user"]["id"]
        # clear must_change via DB for login convenience
        async with db.begin() as s:
            from app.authorization.accounts import AccountCredential

            cred = await s.get(AccountCredential, uid)
            if cred:
                cred.must_change_password = False
        users[key] = uid
        gid = await _ensure_group_and_grants(
            c,
            director,
            name=f"Grup {pack['label']}",
            caps=list(pack["capabilities"]),
            branches=["A"],
            ownership=pack["ownership_default"],
        )
        await _attach_user(c, director, user_id=uid, group_id=gid)

    # AccessAudit must contain grant.create + membership actions
    async with db() as s:
        actions = list(
            (
                await s.scalars(select(AccessAudit.action).order_by(AccessAudit.id))
            ).all()
        )
    assert "grant.create" in actions
    assert any(a.startswith("user.") or a == "membership.set" or "membership" in a for a in actions)

    async def hdr(key):
        h, _ = await login(c, f"role-{key}")
        return h

    # Designer: may read job A, denied cross-branch; denied loading write
    d = await hdr("designer")
    assert (await c.get("/api/v1/production/jobs/1", headers=d)).status_code == 200
    assert (await c.get("/api/v1/production/jobs/2", headers=d)).status_code == 403
    assert (await c.post("/api/v1/production/jobs/1/loading", headers=d, json={})).status_code in (403, 422)

    # Screener: prep allowed path requires body — permission gate first (403 without grant was baseline)
    s = await hdr("screener")
    assert (await c.get("/api/v1/production/jobs/1", headers=s)).status_code == 200
    assert (await c.post("/api/v1/production/jobs/1/outputs", headers=s, json={})).status_code in (403, 422)

    # Helper: packing capability present → not 403 for missing capability alone may still 422
    h = await hdr("helper")
    assert (await c.get("/api/v1/production/jobs/tasks", headers=h)).status_code == 200

    # Operator: output path; denied payment bypass
    o = await hdr("operator")
    assert (await c.get("/api/v1/production/jobs/1", headers=o)).status_code == 200
    assert (
        await c.post(
            "/api/v1/production/jobs/1/payment/bypass",
            headers=o,
            json={"reason": "should deny"},
        )
    ).status_code == 403

    # Driver: schedule read + denied sj cancel capability
    dr = await hdr("driver")
    assert (await c.get("/api/v1/production/ops/deliveries", headers=dr)).status_code == 200
    assert (await c.get("/api/v1/production/jobs/2", headers=dr)).status_code == 403  # branch B

    # Kepala Produksi: schedule list + denied bypass
    kp = await hdr("kepala_produksi")
    assert (await c.get("/api/v1/production/ops/schedule", headers=kp)).status_code == 200
    assert (
        await c.post(
            "/api/v1/production/jobs/1/payment/bypass",
            headers=kp,
            json={"reason": "kepala no bypass"},
        )
    ).status_code == 403

    # Settings payment approval GET: needs settings.payment_approval.read — not in packs → 403
    assert (
        await c.get("/api/v1/production/settings/payment-approval", headers=kp)
    ).status_code == 403
    # Director can read payment settings
    assert (
        await c.get("/api/v1/production/settings/payment-approval", headers=director)
    ).status_code == 200

    # Master Cabang: packs cannot manage; Director can create; employee grant rejected
    listed_kp = await c.get("/api/v1/production/settings/branches", headers=kp)
    assert listed_kp.status_code in {200, 403}
    if listed_kp.status_code == 200:
        assert listed_kp.json().get("can_manage") is False
    denied_create = await c.post(
        "/api/v1/production/settings/branches",
        headers=kp,
        json={"code": "BR-ENF", "name": "Enforced", "reason": "bukan direktur"},
    )
    assert denied_create.status_code == 403
    created = await c.post(
        "/api/v1/production/settings/branches",
        headers=director,
        json={"code": "BR-ENF", "name": "Enforced", "reason": "Direktur buat cabang sandbox"},
    )
    assert created.status_code == 200, created.text
    grant_reject = await c.post(
        "/api/v1/settings/groups/2/grants",
        headers=director,
        json={
            "revision": await _revision(c, director),
            "reason": "Coba grant branch.manage — harus ditolak",
            "capability": "settings.branch.manage",
            "ownership": "all",
            "branches": [],
            "assignments": [],
        },
    )
    assert grant_reject.status_code in {400, 403, 422}


@pytest.mark.asyncio
async def test_tracking_read_does_not_imply_link_create(enforced):
    _, c = enforced
    director, _ = await login(c)
    gid = await _ensure_group_and_grants(
        c,
        director,
        name="Tracking-RO",
        caps=["job.read", "tracking.read"],
        branches=["A"],
        ownership="all",
    )
    await _attach_user(c, director, user_id=3, group_id=gid)
    op, _ = await login(c, "test-3")
    tr = await c.get("/api/v1/production/jobs/1/tracking", headers=op)
    assert tr.status_code == 200, tr.text
    # link create must stay denied without tracking.link.create
    r = await c.post(
        "/api/v1/production/jobs/1/tracking-links",
        headers=op,
        json={},
    )
    assert r.status_code == 403, r.text
