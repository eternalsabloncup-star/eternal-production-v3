"""Administrative-only bootstrap. No HTTP route and no account creation.

The operator must independently verify Owner identity and supply the approved
existing user ID, exact username and approval reference. This records that
attestation; it is not an identity-verification service. Recovery is unavailable.
"""
from sqlalchemy import select
from fastapi import HTTPException
from app.authorization.accounts import AccountCredential
from app.authorization.models import AccessState, AccessGroup, Membership
from app.authorization.service import atomic_mutation, _audit
from app.models.user import User

@atomic_mutation
async def bootstrap_director(session, *, owner_user_id: int, expected_username: str, approval_reference: str):
    if not approval_reference.strip() or len(approval_reference) > 400:
        raise HTTPException(422, 'Verified Owner approval reference required')
    state = await session.scalar(select(AccessState).where(AccessState.id == 1).with_for_update().execution_options(populate_existing=True))
    if state is None or state.bootstrapped or await session.scalar(select(AccessGroup.id).where(AccessGroup.system_key == 'director')):
        raise HTTPException(409, 'Bootstrap unavailable or already completed')
    owner = await session.get(User, owner_user_id, populate_existing=True)
    if owner is None or not owner.is_active or owner.username != expected_username:
        raise HTTPException(409, 'Explicit Owner identity does not match an active account')
    if await session.get(AccountCredential, owner_user_id) is None:
        raise HTTPException(409, 'Credential migration required')
    group = AccessGroup(name='Direktur', system_key='director', active=True)
    session.add(group); await session.flush()
    session.add(Membership(user_id=owner_user_id, group_id=group.id, active=True))
    state.bootstrapped = True
    await _audit(session, state, owner_user_id, 'director.bootstrap', approval_reference, {},
                 {'owner_user_id': owner_user_id, 'group_id': group.id, 'expected_username': expected_username})
    return group.id

async def _main(args):
    from app.db.session import get_session_factory, dispose_engine
    try:
        async with get_session_factory().begin() as session:
            await bootstrap_director(session, owner_user_id=args.owner_user_id,
                expected_username=args.expected_username, approval_reference=args.approval_reference)
        print('Director bootstrap committed with audit. No recovery enabled.')
    finally:
        await dispose_engine()

if __name__ == '__main__':
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description='Administrative bootstrap; verified Owner identity required.')
    parser.add_argument('--owner-user-id', type=int, required=True)
    parser.add_argument('--expected-username', required=True)
    parser.add_argument('--approval-reference', required=True)
    asyncio.run(_main(parser.parse_args()))
