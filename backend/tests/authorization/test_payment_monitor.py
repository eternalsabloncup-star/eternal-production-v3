"""Per-PO payment monitor: official PaymentReceiptRef/PaymentBypass source, branch scoped, paginated, read-only."""
from decimal import Decimal
from sqlalchemy import event, func, select, update
from app.db.session import get_engine
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant

URL = '/api/v1/production/jobs/payment/receipts'


async def seed(db):
    """SO-M-00..05 branches A/B alternating (one receipt each), SO-M-06 (A) no receipt,
    SO-M-07 (B) three receipts: two partial verified + one invalidated."""
    async with db() as s:
        jobs = [ProductionJob(accurate_so_number=f'SO-M-{i:02d}', branch_id='A' if i % 2 == 0 else 'B', customer_name=f'Cust {i}') for i in range(8)]
        s.add_all(jobs); await s.flush()
        rows = []
        for i, j in enumerate(jobs[:6]):
            rows.append(PaymentReceiptRef(job_id=j.id, accurate_receipt_id=f'RC-{i}', accurate_receipt_number=f'RCP/{i}', amount=Decimal('1000') + i,
                                          evidence_verified=True, status='valid', recorded_by=1, idempotency_key=f'seed-key-{i}'))
        rows[3].amount = None; rows[3].evidence_verified = False
        rows[4].status = 'invalidated'; rows[5].evidence_verified = False
        for n, (amt, status) in enumerate([('400', 'valid'), ('600', 'valid'), ('250', 'invalidated')]):
            rows.append(PaymentReceiptRef(job_id=jobs[7].id, accurate_receipt_id=f'RC-P{n}', accurate_receipt_number=f'RCP/P{n}', amount=Decimal(amt),
                                          evidence_verified=True, status=status, recorded_by=1, idempotency_key=f'part-key-{n}'))
        s.add_all(rows)
        s.add(PaymentBypass(job_id=jobs[5].id, reason='owner bypass', authorized_by=1, active=True))
        await s.commit()


async def snapshot(db):
    async with db() as s:
        return (await s.scalar(select(func.count()).select_from(PaymentReceiptRef)),
                await s.scalar(select(func.count()).select_from(ProductionEvent)),
                await s.scalar(select(func.count()).select_from(PaymentBypass)))


async def test_every_po_is_listed_once_with_official_payment_data(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    before = await snapshot(db)
    body = (await c.get(URL, headers=h, params={'q': 'SO-M-'})).json()
    assert body['total'] == 8 and len(body['items']) == 8
    by = {i['so_number']: i for i in body['items']}
    assert len(by) == 8
    none = by['SO-M-06']
    assert none['receipt_count'] == 0 and none['receipts'] == [] and none['verified_amount'] is None and none['payment_status'] == 'pending'
    assert by['SO-M-00']['payment_status'] == 'approved' and by['SO-M-00']['verified_amount'] == '1000.00'
    assert by['SO-M-03']['receipts'][0]['amount'] is None and by['SO-M-03']['verified_amount'] is None and by['SO-M-03']['payment_status'] == 'pending'
    assert by['SO-M-04']['verified_amount'] is None and by['SO-M-04']['receipts'][0]['receipt_status'] == 'invalidated'
    assert by['SO-M-05']['payment_status'] == 'bypassed' and by['SO-M-05']['bypass_active'] is True and by['SO-M-05']['verified_amount'] is None
    part = by['SO-M-07']
    assert part['receipt_count'] == 3 and len(part['receipts']) == 3 and part['verified_amount'] == '1000.00'
    assert part['payment_status'] == 'approved'
    assert {r['accurate_receipt_id'] for r in part['receipts']} == {'RC-P0', 'RC-P1', 'RC-P2'}
    assert await snapshot(db) == before


async def test_filters_search_and_pagination_without_duplicates(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    get = lambda **p: c.get(URL, headers=h, params={'q': 'SO-M-', **p})
    pages = [(await get(page_size=3, page=n)).json() for n in (1, 2, 3, 4)]
    assert [len(p['items']) for p in pages] == [3, 3, 2, 0]
    assert pages[0]['has_more'] and pages[1]['has_more'] and not pages[2]['has_more'] and pages[0]['total'] == 8
    ids = [i['job_id'] for p in pages for i in p['items']]
    assert len(ids) == len(set(ids)) == 8
    assert (await get(payment_status='approved')).json()['total'] == 4
    assert (await get(payment_status='bypassed')).json()['total'] == 1
    assert (await get(payment_status='pending')).json()['total'] == 3
    assert (await get(receipts='without')).json()['items'][0]['so_number'] == 'SO-M-06'
    assert (await get(receipts='with')).json()['total'] == 7
    assert (await get(receipt_status='invalidated')).json()['total'] == 2
    assert (await get(branch='A')).json()['total'] == 4
    assert (await get(q='SO-M-02')).json()['items'][0]['so_number'] == 'SO-M-02'
    assert (await get(q='rcp/p1')).json()['items'][0]['so_number'] == 'SO-M-07'
    assert (await get(q='%')).json()['total'] == 0
    assert (await get(q='nothing-matches')).json() == {'items': [], 'total': 0, 'page': 1, 'page_size': 25, 'has_more': False}
    assert (await get(payment_status='bogus')).status_code == 422
    assert (await get(receipts='x')).status_code == 422
    assert (await get(page_size=101)).status_code == 422


async def test_query_count_does_not_grow_with_rows(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    seen = []
    listener = lambda conn, cur, stmt, *a: seen.append(stmt)
    event.listen(get_engine().sync_engine, 'before_cursor_execute', listener)
    try:
        await c.get(URL, headers=h, params={'page_size': 1}); small = len(seen); seen.clear()
        await c.get(URL, headers=h, params={'page_size': 8}); large = len(seen)
    finally:
        event.remove(get_engine().sync_engine, 'before_cursor_execute', listener)
    assert small == large


async def test_scoped_user_sees_only_granted_branch_and_needs_capability(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c, 'test-3')
    assert (await c.get(URL, headers=h)).status_code == 403
    await grant(db, 'payment.evidence.read', branches=('A',))
    body = (await c.get(URL, headers=h, params={'q': 'SO-M-'})).json()
    assert body['total'] == 4 and {i['branch_id'] for i in body['items']} == {'A'}
    assert 'SO-M-01' not in {i['so_number'] for i in body['items']}
    assert (await c.get(URL, headers=h, params={'branch': 'B'})).json()['total'] == 0
    assert (await c.get(URL)).status_code in (401, 403)


async def test_status_stays_consistent_with_board_after_a_payment_change(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    async def both(so):
        item = next(i for i in (await c.get(URL, headers=h, params={'q': so})).json()['items'] if i['so_number'] == so)
        board = (await c.get(f"/api/v1/production/jobs/{item['job_id']}/board", headers=h)).json()
        return item, board
    item, board = await both('SO-M-00')
    assert item['payment_status'] == board['job']['payment_status'] == 'approved'
    assert [r['id'] for r in board['payment_receipts']] == [r['receipt_id'] for r in item['receipts']]
    async with db() as s:
        await s.execute(update(PaymentReceiptRef).where(PaymentReceiptRef.accurate_receipt_id == 'RC-0').values(status='invalidated'))
        await s.commit()
    item, board = await both('SO-M-00')
    assert item['payment_status'] == board['job']['payment_status'] == 'pending'
    assert item['verified_amount'] is None
    # partial: one of the two verified receipts invalidated -> still approved by the remaining valid one
    async with db() as s:
        await s.execute(update(PaymentReceiptRef).where(PaymentReceiptRef.accurate_receipt_id == 'RC-P0').values(status='invalidated'))
        await s.commit()
    item, board = await both('SO-M-07')
    assert item['payment_status'] == board['job']['payment_status'] == 'approved' and item['verified_amount'] == '600.00'


async def test_write_methods_are_not_exposed(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    assert (await c.post(URL, headers=h, json={})).status_code in (404, 405, 422)
    assert (await c.delete(URL, headers=h)).status_code in (404, 405)


async def test_reversed_receipt_is_not_counted_and_status_matches_tasks_and_schedule_gate(ready):
    db, c = ready; await seed(db)
    h, _ = await login(c)
    async with db() as s:
        await s.execute(update(PaymentReceiptRef).where(PaymentReceiptRef.accurate_receipt_id == 'RC-1').values(status='reversed'))
        await s.commit()
    get = lambda so: c.get(URL, headers=h, params={'q': so})
    rev = next(i for i in (await get('SO-M-01')).json()['items'] if i['so_number'] == 'SO-M-01')
    assert rev['payment_status'] == 'pending' and rev['verified_amount'] is None and rev['receipts'][0]['receipt_status'] == 'reversed'
    for so in ('SO-M-00', 'SO-M-01', 'SO-M-05'):
        item = next(i for i in (await get(so)).json()['items'] if i['so_number'] == so)
        tasks = (await c.get('/api/v1/production/jobs/tasks', headers=h, params={'so': so})).json()
        reported = {str(j.get('payment_status')) for j in tasks.get('jobs', [])}
        assert reported == {item['payment_status']}, (so, reported, item['payment_status'])
    # schedule gate follows the same backend status: pending job cannot be scheduled
    blocked = next(i for i in (await get('SO-M-01')).json()['items'])
    r = await c.post(f"/api/v1/production/jobs/{blocked['job_id']}/schedule/assignments", headers=h, json={'so_line_id': 'line-1', 'color_pass': 1, 'operator_name': 'Rizki', 'machine_name': 'M1', 'work_date': '2026-11-14', 'qty_planned': '10'})
    assert r.status_code == 409, r.text
