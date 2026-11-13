"""No runtime cutover: pure access contracts plus isolated PostgreSQL transactions."""
import asyncio
import os
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.authorization.catalog import CATALOG, LEGACY_MAPPING, compatibility_inventory
from app.authorization.evaluator import Access, Grant, Resource, evaluate, validate_grant
from app.authorization.models import AccessAudit, AccessGroup, AccessState, Membership, ScopedGrant, TABLES
from app.authorization import service
from app.models.user import User
from app.services.production.permissions import PERMISSION_CATALOG


def test_catalog_covers_every_existing_code_without_export_backfill():
    assert set(LEGACY_MAPPING) == {r['code'] for r in PERMISSION_CATALOG} | {'production.inbox.read', 'production.order.read'}
    mapped = {c for values in LEGACY_MAPPING.values() for c in values}
    assert not any(c.endswith(('.export', '.print')) for c in mapped)
    inventory = compatibility_inventory(['production.job.read', 'unexpected'])
    assert inventory['unknown'] == ['unexpected']
    assert inventory['review_required']
    assert not inventory['automatic_import_allowed']

@pytest.mark.parametrize('capability', sorted(CATALOG))
def test_director_all_registered_capabilities_and_ordinary_default_deny(capability):
    assert evaluate(Access(1, True, True), capability, Resource('OTHER', 999, 30)).allowed
    assert not evaluate(Access(1, True), capability).allowed
    assert not evaluate(Access(1, False, True), capability).allowed


def test_unknown_denied_even_director():
    assert not evaluate(Access(1, True, True), 'invented.superpower').allowed


def test_no_cross_product_and_wrong_assignment_denial():
    a = Access(7, True, grants=(Grant(1, 'output.record', frozenset({'A'}), 'own'), Grant(2, 'job.read', frozenset({'B'}))))
    assert evaluate(a, 'output.record', Resource('A', 4, 7)).allowed
    for resource in [Resource('B', 4, 7), Resource('A', 4, 8), Resource('A', None, 7), Resource(None, 4, 7)]:
        assert not evaluate(a, 'output.record', resource).allowed
    b = Access(7, True, grants=(Grant(3, 'output.record', frozenset({'A'}), 'selected', frozenset({4})),))
    assert evaluate(b, 'output.record', Resource('A', 4)).allowed
    assert not evaluate(b, 'output.record', Resource('A', 5)).allowed
    assert not evaluate(b, 'output.record', Resource('B', 4)).allowed


def test_management_does_not_grant_input_approval_or_correction():
    a = Access(7, True, grants=(Grant(1, 'assignment.ownership.manage', frozenset({'A'})),))
    assert evaluate(a, 'assignment.ownership.manage', Resource('A')).allowed
    for code in ['output.record', 'output.correct', 'sample.decision.record', 'output.helper.verify']:
        assert not evaluate(a, code, Resource('A')).allowed

@pytest.mark.parametrize('grant', [
    Grant(1, 'output.record'), Grant(1, 'output.record', frozenset({'*'})),
    Grant(1, 'output.record', frozenset({'A'}), 'selected'),
    Grant(1, 'output.record', frozenset({'A'}), 'own', frozenset({1})),
    Grant(1, 'payroll.rate.read', frozenset({'A'})),
    Grant(1, 'settings.grant.manage'), Grant(1, 'unknown'),
])
def test_malformed_grants_fail_closed(grant):
    with pytest.raises(ValueError):
        validate_grant(grant)
    assert not evaluate(Access(1, True, grants=(grant,)), grant.capability, Resource('A', 1, 1)).allowed


@pytest.fixture
async def db():
    # Stricter than the repository guard: this suite will ONLY use explicit loopback.
    url = os.environ.get('TEST_DATABASE_URL', '')
    parsed = urlsplit(url)
    if parsed.hostname != '127.0.0.1' or not parsed.path.endswith('_test'):
        pytest.skip('Explicit loopback TEST_DATABASE_URL ending _test required')
    engine = create_async_engine(url)
    schema = 'settings_foundation_test'
    scoped = engine.execution_options(schema_translate_map={None: schema})
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
    async with scoped.begin() as conn:
        for table in TABLES:
            await conn.run_sync(lambda c, t=table: t.create(c))
    factory = async_sessionmaker(scoped, expire_on_commit=False)
    async with factory.begin() as s:
        s.add_all([User(id=i, username=f'test-{i}', display_name='Test', role='operator', password_hash='not-a-login', permissions=[], branch_ids=[]) for i in (1, 2, 3)])
        await s.flush()
        s.add_all([AccessState(id=1, revision=0, bootstrapped=True), AccessGroup(name='Protected test group', system_key='director'), AccessGroup(name='Direktur', system_key=None)])
        await s.flush()
        s.add_all([Membership(user_id=1, group_id=1), Membership(user_id=2, group_id=1), Membership(user_id=3, group_id=2)])
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await engine.dispose()

async def test_database_identity_not_role_or_group_label(db):
    async with db.begin() as s:
        user = await s.get(User, 3)
        user.role = 'Direktur'
    async with db.begin() as s:
        assert not (await service.load_access(s, 3)).director
        with pytest.raises(HTTPException) as error:
            await service.create_group(s, actor=3, revision=0, reason='test', name='Escalation')
        assert error.value.status_code == 403

async def test_group_defaults_and_atomic_audit(db):
    async with db.begin() as s:
        gid = await service.create_group(s, actor=1, revision=0, reason='Owner request', name='Empty')
    async with db.begin() as s:
        assert await s.scalar(select(func.count()).select_from(ScopedGrant).where(ScopedGrant.group_id == gid)) == 0
        assert (await s.get(AccessState, 1)).revision == 1
        log = await s.scalar(select(AccessAudit))
        assert log.actor_user_id == 1 and log.after['group_id'] == gid
        assert log.before == {}

async def test_revision_conflict(db):
    async with db.begin() as s:
        await service.create_group(s, actor=1, revision=0, reason='test', name='First')
    with pytest.raises(HTTPException) as error:
        async with db.begin() as s:
            await service.create_group(s, actor=1, revision=0, reason='test', name='Stale')
    assert error.value.status_code == 409

async def test_audit_failure_rolls_back_change_and_revision(db, monkeypatch):
    original = service._audit
    async def fail(session, state, actor, action, reason, before, after):
        # Real FK violation during audit INSERT, after the group INSERT.
        await original(session, state, 9999, action, reason, before, after)
    monkeypatch.setattr(service, '_audit', fail)
    with pytest.raises(IntegrityError):
        async with db.begin() as s:
            await service.create_group(s, actor=1, revision=0, reason='test', name='Must rollback')
    async with db.begin() as s:
        assert await s.scalar(select(AccessGroup).where(AccessGroup.name == 'Must rollback')) is None
        assert (await s.get(AccessState, 1)).revision == 0
        assert await s.scalar(select(func.count()).select_from(AccessAudit)) == 0

async def test_revocation_authoritative_next_transaction(db):
    async with db.begin() as s:
        gid = await service.add_grant(s, actor=1, revision=0, reason='test', group_id=2, grant=Grant(0, 'job.read', frozenset({'A'})))
    async with db.begin() as s:
        assert evaluate(await service.load_access(s, 3), 'job.read', Resource('A')).allowed
    async with db.begin() as s:
        await service.revoke_grant(s, actor=1, revision=1, reason='revoked', grant_id=gid)
    async with db.begin() as s:
        assert not evaluate(await service.load_access(s, 3), 'job.read', Resource('A')).allowed
        assert not (await s.get(ScopedGrant, gid)).active

async def test_last_admin_concurrency_and_retry(db):
    async def remove(user_id):
        try:
            async with db.begin() as s:
                await service.set_membership(s, actor=user_id, revision=0, reason='test', user_id=user_id, group_id=1, active=False)
            return (user_id, 200)
        except HTTPException as exc:
            return (user_id, exc.status_code)
    results = await asyncio.gather(remove(1), remove(2))
    assert sorted(code for _, code in results) == [200, 409]
    remaining = next(uid for uid, status in results if status != 200)
    with pytest.raises(HTTPException) as error:
        async with db.begin() as s:
            await service.set_user_active(s, actor=remaining, revision=1, reason='test', user_id=remaining, active=False)
    assert error.value.status_code == 409
    async with db.begin() as s:
        assert (await service.load_access(s, remaining)).director
        assert (await s.get(User, remaining)).is_active
        assert (await s.get(AccessState, 1)).revision == 1

async def test_shared_authorization_lock_orders_revocation(db):
    reader_ready, finish_reader, writer_started, writer_done = [asyncio.Event() for _ in range(4)]
    async def reader():
        async with db.begin() as s:
            assert (await service.load_access(s, 3)).active
            reader_ready.set()
            await finish_reader.wait()
    async def writer():
        await reader_ready.wait()
        writer_started.set()
        async with db.begin() as s:
            await service.set_user_active(s, actor=1, revision=0, reason='test', user_id=3, active=False)
        writer_done.set()
    r, w = asyncio.create_task(reader()), asyncio.create_task(writer())
    try:
        await asyncio.wait_for(writer_started.wait(), 3)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(writer_done.wait(), .1)
        finish_reader.set()
        await asyncio.wait_for(asyncio.gather(r, w), 3)
        async with db.begin() as s:
            assert not (await service.load_access(s, 3)).active
    finally:
        finish_reader.set()
        await asyncio.gather(r, w, return_exceptions=True)

async def test_unbootstrapped_fails_closed(db):
    async with db.begin() as s:
        (await s.get(AccessState, 1)).bootstrapped = False
    with pytest.raises(HTTPException) as error:
        async with db.begin() as s:
            await service.load_access(s, 1)
    assert error.value.status_code == 503

async def test_system_group_cannot_receive_custom_grants(db):
    with pytest.raises(HTTPException) as error:
        async with db.begin() as s:
            await service.add_grant(s, actor=1, revision=0, reason='test', group_id=1, grant=Grant(0, 'job.read', frozenset({'A'})))
    assert error.value.status_code == 422

async def test_last_admin_error_caught_by_caller_cannot_commit_deactivation(db):
    async with db.begin() as s:
        await service.set_membership(s, actor=1, revision=0, reason='test', user_id=2, group_id=1, active=False)
    async with db.begin() as s:
        with pytest.raises(HTTPException):
            await service.set_user_active(s, actor=1, revision=1, reason='test', user_id=1, active=False)
        # Deliberately commit the outer transaction after catching the rejection.
    async with db.begin() as s:
        assert (await s.get(User, 1)).is_active
        assert (await s.get(AccessState, 1)).revision == 1

async def test_database_rejects_duplicate_system_group_and_grant(db):
    with pytest.raises(IntegrityError):
        async with db.begin() as s:
            s.add(AccessGroup(name='Another system group', system_key='director'))
    async with db.begin() as s:
        await service.add_grant(s, actor=1, revision=0, reason='test', group_id=2, grant=Grant(0, 'job.read', frozenset({'A'})))
    with pytest.raises(IntegrityError):
        async with db.begin() as s:
            await service.add_grant(s, actor=1, revision=1, reason='test', group_id=2, grant=Grant(0, 'job.read', frozenset({'A'})))
    async with db.begin() as s:
        assert (await s.get(AccessState, 1)).revision == 1
