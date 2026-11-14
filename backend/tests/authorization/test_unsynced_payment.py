"""Monitoring Penerimaan: Accurate POs without a V3 job, read-only."""
from sqlalchemy import func, select
from app.models.production.job import ProductionJob
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant, FakeGateway, gateway_rows

URL = '/api/v1/production/ops/payment/unsynced'


async def jobs(db):
    async with db() as s:
        return await s.scalar(select(func.count()).select_from(ProductionJob))


async def test_unsynced_pos_scoped_exclude_existing_and_create_nothing(ready):
    db, c = ready
    from app.api.production_inbox import get_gateway
    c._transport.app.dependency_overrides[get_gateway] = lambda: FakeGateway(gateway_rows())
    h, _ = await login(c, 'test-3')
    assert (await c.get(URL, headers=h)).status_code == 403
    await grant(db, 'payment.evidence.read')
    async with db() as s:
        s.add(ProductionJob(accurate_so_number='SO-000', branch_id='A', customer_name='X'))
        await s.commit()
    before = await jobs(db)
    r = await c.get(URL, headers=h, params={'page': 1, 'limit': 20})
    assert r.status_code == 200, r.text
    items = r.json()['items']
    numbers = [i['po_number'] for i in items]
    assert 'SO-000' not in numbers and numbers
    assert all(i['branch_id'] == 'A' and i['has_job'] is False and i['receipt_count'] == 0 and i['verified_amount'] is None for i in items)
    assert await jobs(db) == before
