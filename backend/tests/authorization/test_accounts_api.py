"""Isolated account/API tests; runtime router remains unregistered."""
import json
import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.authorization.test_foundation import db
from app.authorization import accounts
from app.authorization.api import router
from app.authorization.models import AccessAudit, AccessState
from app.core.config import get_settings
from app.core.security import hash_password, verify_password, decode_access_token
from app.db.session import get_db_session
from app.models.user import User

PASSWORD = 'isolated-test-password-1'
NEXT_PASSWORD = 'isolated-test-password-2'

@pytest.fixture
async def case(db, monkeypatch):
    monkeypatch.setenv('V3_JWT_SECRET', 'test-only-jwt-secret-long-enough-for-hs256')
    monkeypatch.setenv('V3_PASSWORD_PEPPER', 'test-only-separate-password-pepper')
    get_settings.cache_clear()
    async with db.begin() as s:
        await s.run_sync(lambda sync: accounts.AccountCredential.__table__.create(sync.connection()))
        await s.execute(text("SELECT setval('settings_foundation_test.users_id_seq', 3, true)"))
        for uid in (1, 2, 3):
            (await s.get(User, uid)).password_hash = hash_password(PASSWORD)
            s.add(accounts.AccountCredential(user_id=uid, generation=1, must_change_password=False))
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    async def connection():
        async with db() as session:
            yield session
    app.dependency_overrides[get_db_session] = connection
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        async def login(uid=1, password=PASSWORD, username=None):
            response = await client.post('/api/v1/settings/session/login', json={'username': username or f'test-{uid}', 'password': password})
            assert response.status_code == 200, response.text
            return {'Authorization': 'Bearer ' + response.json()['access_token']}
        yield db, client, login

async def post(client, path, headers, revision=0, **fields):
    return await client.post('/api/v1/settings' + path, headers=headers, json={'revision': revision, 'reason': 'Test owner decision', **fields})

async def test_password_lifecycle(case):
    db, client, login = case
    admin = await login()
    created = await post(client, '/users', admin, username='new-user', display_name='New', password=PASSWORD)
    assert created.status_code == 201
    uid = created.json()['user']['id']
    assert PASSWORD not in created.text and 'password_hash' not in created.text
    initial = await login(username='new-user')
    assert (await client.get('/api/v1/settings/users', headers=initial)).status_code == 403
    changed = await client.post('/api/v1/settings/session/password', headers=initial, json={'current_password': PASSWORD, 'new_password': NEXT_PASSWORD})
    assert changed.status_code == 200 and changed.json() == {'reauthenticate': True}
    assert (await client.get('/api/v1/settings/users', headers=initial)).status_code == 401
    fresh = await login(username='new-user', password=NEXT_PASSWORD)
    assert (await client.get('/api/v1/settings/groups', headers=fresh)).status_code == 403
    assert (await post(client, f'/users/{uid}/password-reset', admin, revision=2, password=PASSWORD)).status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=fresh)).status_code == 401
    async with db.begin() as s:
        user = await s.get(User, uid)
        assert user.permissions == [] and user.branch_ids == []
        assert user.password_hash != PASSWORD and verify_password(PASSWORD, user.password_hash)
        audit = list((await s.scalars(select(AccessAudit))).all())
        serialized = json.dumps([{'before': a.before, 'after': a.after, 'reason': a.reason} for a in audit])
        assert PASSWORD not in serialized and NEXT_PASSWORD not in serialized and 'pbkdf2' not in serialized

async def test_force_change(case):
    _, client, login = case
    admin, target = await login(), await login(2)
    assert (await post(client, '/users/2/password-reset', admin)).status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=target)).status_code == 401
    limited = await login(2)
    assert (await client.get('/api/v1/settings/users', headers=limited)).status_code == 403
    bad = await client.post('/api/v1/settings/session/password', headers=limited, json={'current_password': 'incorrect', 'new_password': NEXT_PASSWORD})
    assert bad.status_code == 401

async def test_deactivation_reactivation(case):
    _, client, login = case
    admin, target = await login(), await login(3)
    assert (await post(client, '/users/3/active', admin, active=False)).status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=target)).status_code == 401
    assert (await post(client, '/users/3/active', admin, revision=1, active=True)).status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=target)).status_code == 401
    assert (await client.post('/api/v1/settings/session/login', json={'username': 'test-3', 'password': PASSWORD})).status_code == 200

@pytest.mark.parametrize('field,value', [('permissions', ['*']), ('role', 'Direktur'), ('actor', 1), ('system_key', 'director')])
async def test_payload_privilege_and_secret_redaction(case, field, value):
    _, client, login = case
    admin = await login()
    result = await client.patch('/api/v1/settings/users/3', headers=admin, json={'revision': 0, 'reason': 'test', 'username': 'test-3', 'display_name': 'Test', field: value})
    assert result.status_code == 422
    response = await client.post('/api/v1/settings/session/login', json={'username': 'test-1', 'password': PASSWORD, 'extra': PASSWORD})
    assert response.status_code == 422 and PASSWORD not in response.text

async def test_direct_api_authorization(case):
    _, client, login = case
    ordinary = await login(3)
    for endpoint in ['/users', '/groups', '/capabilities', '/access-audit', '/users/1/effective-access']:
        assert (await client.get('/api/v1/settings' + endpoint)).status_code == 401
        assert (await client.get('/api/v1/settings' + endpoint, headers=ordinary)).status_code == 403
    assert (await post(client, '/users/3/memberships', ordinary, group_id=1, active=True)).status_code == 403

async def test_membership_scoped_manual_export_and_revoke(case):
    _, client, login = case
    admin = await login()
    group = await post(client, '/groups', admin, name='New group')
    assert group.status_code == 201
    gid = group.json()['group_id']
    assert (await client.get(f'/api/v1/settings/groups/{gid}/grants', headers=admin)).json()['items'] == []
    assert (await post(client, '/users/3/memberships', admin, revision=1, group_id=gid, active=True)).status_code == 200
    grant = await post(client, f'/groups/{gid}/grants', admin, revision=2, capability='task.export', branches=['A'])
    assert grant.status_code == 201
    effective = (await client.get('/api/v1/settings/users/3/effective-access', headers=admin)).json()
    assert effective['grants'][0]['capability'] == 'task.export' and effective['grants'][0]['branches'] == ['A']
    assert (await post(client, f"/grants/{grant.json()['grant_id']}/revoke", admin, revision=3)).status_code == 200
    assert (await client.get('/api/v1/settings/users/3/effective-access', headers=admin)).json()['grants'] == []

async def test_profile_revision_and_duplicate_conflict(case):
    _, client, login = case
    admin = await login()
    payload = {'revision': 0, 'reason': 'Owner', 'username': 'renamed', 'display_name': 'Updated'}
    assert (await client.patch('/api/v1/settings/users/3', headers=admin, json=payload)).status_code == 200
    assert (await client.patch('/api/v1/settings/users/3', headers=admin, json=payload)).status_code == 409
    dupe = await post(client, '/users', admin, revision=1, username='renamed', display_name='Other', password=PASSWORD)
    assert dupe.status_code == 409 and PASSWORD not in dupe.text

async def test_audit_failure_rolls_back_credentials(case, monkeypatch):
    db, _, _ = case
    original = accounts._audit
    async def fail(session, state, actor, action, reason, before, after):
        await original(session, state, 99999, action, reason, before, after)
    monkeypatch.setattr(accounts, '_audit', fail)
    async with db.begin() as s:
        before = (await s.get(User, 3)).password_hash
        with pytest.raises(IntegrityError):
            await accounts.reset_password(s, actor=1, revision=0, reason='test', user_id=3, password=NEXT_PASSWORD)
    async with db.begin() as s:
        assert (await s.get(User, 3)).password_hash == before
        assert (await s.get(accounts.AccountCredential, 3)).generation == 1
        assert (await s.get(AccessState, 1)).revision == 0

async def test_last_admin_api(case):
    _, client, login = case
    admin = await login()
    assert (await post(client, '/users/2/memberships', admin, group_id=1, active=False)).status_code == 200
    assert (await post(client, '/users/1/active', admin, revision=1, active=False)).status_code == 409
    assert (await client.get('/api/v1/settings/users', headers=admin)).status_code == 200

async def test_isolated_token_and_router(case):
    _, _, login = case
    header = await login()
    with pytest.raises(HTTPException) as error:
        decode_access_token(header['Authorization'].split(' ', 1)[1])
    assert error.value.status_code == 401
    from app.main import create_app
    # Isolasi: router akun `/api/v1/settings/*` tetap OFF kecuali V3_SETTINGS_ENABLED.
    # Jangan samakan dengan Settings operasional produksi `/api/v1/production/settings/*`.
    account_settings_paths = [
        getattr(route, 'path', '') or ''
        for route in create_app().routes
        if (getattr(route, 'path', '') or '').startswith('/api/v1/settings')
    ]
    assert account_settings_paths == [], account_settings_paths
    assert any(
        (getattr(route, 'path', '') or '').startswith('/api/v1/production/settings/')
        for route in create_app().routes
    ), 'production operational settings routes must remain registered'

async def test_username_change_revokes_session(case):
    _, client, login = case
    admin, target = await login(), await login(3)
    result = await client.patch('/api/v1/settings/users/3', headers=admin, json={'revision': 0, 'reason': 'Owner', 'username': 'renamed-user', 'display_name': 'Test'})
    assert result.status_code == 200
    assert (await client.get('/api/v1/settings/users', headers=target)).status_code == 401

async def test_concurrent_password_change_only_one_commits(case):
    import asyncio
    _, client, login = case
    target = await login(3)
    async def change(password):
        return await client.post('/api/v1/settings/session/password', headers=target, json={'current_password': PASSWORD, 'new_password': password})
    responses = await asyncio.gather(change(NEXT_PASSWORD), change('different-next-password'))
    assert sorted(r.status_code for r in responses) == [200, 401]

@pytest.mark.parametrize('password', ['short', PASSWORD])
async def test_invalid_reset_preserves_generation(case, password):
    db, client, login = case
    result = await post(client, '/users/3/password-reset', await login(), password=password)
    assert result.status_code == 422
    async with db.begin() as s:
        assert (await s.get(accounts.AccountCredential, 3)).generation == 1
        assert (await s.get(AccessState, 1)).revision == 0

async def test_legacy_session_cannot_bypass_isolated_credential_check(case):
    from app.core.security import create_access_token
    db, client, _ = case
    async with db.begin() as s:
        token = create_access_token(await s.get(User, 1))
    result = await client.get('/api/v1/settings/users', headers={'Authorization': 'Bearer ' + token})
    assert result.status_code == 401

async def test_account_create_audit_failure_leaves_no_user(case, monkeypatch):
    db, _, _ = case
    original = accounts._audit
    async def fail(session, state, actor, action, reason, before, after):
        await original(session, state, 99999, action, reason, before, after)
    monkeypatch.setattr(accounts, '_audit', fail)
    async with db.begin() as s:
        with pytest.raises(IntegrityError):
            await accounts.create_user(s, actor=1, revision=0, reason='test', username='rollback-user', display_name='Test', password=PASSWORD)
    async with db.begin() as s:
        assert await s.scalar(select(User).where(User.username == 'rollback-user')) is None
        assert (await s.get(AccessState, 1)).revision == 0
