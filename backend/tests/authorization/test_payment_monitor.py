"""Cross-PO receipt monitor: official PaymentReceiptRef source, branch scoped, paginated, read-only."""
from decimal import Decimal
from sqlalchemy import func, select
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant

URL = '/api/v1/production/jobs/payment/receipts'


async def seed(db):
    async with db() as s:
        jobs = [ProductionJob(accurate_so_number=f'SO-M-{i:02d}', branch_id='A' if i % 2 == 0 else 'B', customer_name=f'Cust {i}') for i in range(6)]
        s.add_all(jobs); await s.flush()
        rows = []
        for i, j in enumerate(jobs):
            rows.append(PaymentReceiptRef(job_id=j.id, accurate_receipt_id=f'RC-{i}', accurate_receipt_number=f'RCP/{i}', amount=Decimal('1000') + i,
                                          evidence_verified=True, status='valid', recorded_by=1, idempotency_key=f'seed-key-{i}'))
        # unverified amount-less receipt, invalidated receipt, bypass-only job
        rows[3].amount = None; rows[3].evidence_verified = False
        rows[4].status = 'invalidated'; rows[5].evidence_verified = False
        s.add_all(rows)
        s.add(PaymentBypass(job_id=jobs[5].id, reason='owner bypass', authorized_by=1, active=True))
        await s.commit()


async def snapshot(db):
    async with db() as s:
        return (await s.scalar(select(func.count()).select_from(PaymentReceiptRef)),
                await s.scalar(select(func.count()).select_from(ProductionEvent)),
                await s.scalar(select(func.count()).select_from(PaymentBypass)))


async def test_director_sees_all_branches_with_official_status_and_no_fake_zero(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    before = await snapshot(db)
    body = (await c.get(URL, headers=h)).json()
    assert body['total'] == 6 and len(body['items']) == 6
    by = {i['accurate_receipt_id']: i for i in body['items']}
    assert by['RC-0']['payment_status'] == 'approved' and by['RC-0']['amount'] == '1000.00'
    assert by['RC-3']['amount'] is None and by['RC-3']['payment_status'] == 'pending'
    assert by['RC-4']['receipt_status'] == 'invalidated' and by['RC-4']['payment_status'] == 'pending'
    assert by['RC-5']['payment_status'] == 'bypassed' and by['RC-5']['bypass_active'] is True
    assert {'so_number', 'customer_name', 'accurate_receipt_number', 'branch_id', 'evidence_verified', 'recorded_at', 'job_id'} <= set(body['items'][0])
    assert await snapshot(db) == before


async def test_filters_search_and_pagination(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    p1 = (await c.get(URL, headers=h, params={'page_size': 4})).json()
    p2 = (await c.get(URL, headers=h, params={'page_size': 4, 'page': 2})).json()
    p3 = (await c.get(URL, headers=h, params={'page_size': 4, 'page': 3})).json()
    assert (len(p1['items']), len(p2['items']), len(p3['items'])) == (4, 2, 0)
    assert p1['has_more'] is True and p2['has_more'] is False and p1['total'] == p2['total'] == 6
    ids = [i['receipt_id'] for i in p1['items'] + p2['items']]
    assert len(set(ids)) == 6
    get = lambda **p: c.get(URL, headers=h, params=p)
    assert (await get(payment_status='approved')).json()['total'] == 3
    assert (await get(payment_status='bypassed')).json()['total'] == 1
    assert (await get(receipt_status='invalidated')).json()['total'] == 1
    assert (await get(branch='A')).json()['total'] == 3
    assert (await get(q='SO-M-02')).json()['items'][0]['so_number'] == 'SO-M-02'
    assert (await get(q='rcp/1')).json()['total'] == 1
    assert (await get(q='%')).json()['total'] == 0
    assert (await get(q='nothing-matches')).json() == {'items': [], 'total': 0, 'page': 1, 'page_size': 25, 'has_more': False}
    assert (await get(payment_status='bogus')).status_code == 422
    assert (await get(page_size=101)).status_code == 422


async def test_scoped_user_sees_only_granted_branch_and_needs_capability(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c, 'test-3')
    assert (await c.get(URL, headers=h)).status_code == 403
    await grant(db, 'payment.evidence.read', branches=('A',))
    body = (await c.get(URL, headers=h)).json()
    assert body['total'] == 3 and {i['branch_id'] for i in body['items']} == {'A'}
    assert (await c.get(URL, headers=h, params={'branch': 'B'})).json()['total'] == 0
    assert (await c.get(URL)).status_code in (401, 403)


async def test_write_methods_are_not_exposed(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    assert (await c.post(URL, headers=h, json={})).status_code in (404, 405, 422)
    assert (await c.delete(URL, headers=h)).status_code in (404, 405)
