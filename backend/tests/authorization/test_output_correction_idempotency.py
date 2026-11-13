"""Output correction idempotency: first / identical replay / different payload / concurrent / non-duplicate DB error."""
import asyncio
from datetime import date
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.production.event import ProductionEvent
from app.models.production.schedule import ScheduleAssignment
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready
from tests.authorization.test_workflow_business import prepare, API, SO


async def _setup(ready, monkeypatch):
    db, c = ready
    await prepare(monkeypatch)
    h, _ = await login(c)
    post = lambda path, body: c.post(API + path, headers=h, json=body)
    job = (await post('', {'accurate_so_number': SO, 'accurate_id': '2100', 'branch_id': 'A'})).json()['id']
    v = (await post(f'/{job}/design/versions', {'file_name': 'a.pdf', 'storage_key': 'designs/a.pdf'})).json()['id']
    await post(f'/design/versions/{v}/decision', {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})
    from tests.production.payment_helpers import mock_receipts
    mock_receipts(monkeypatch, {'/receipts/RCV-1': {'id': '2101', 'sales_order_number': SO, 'sales_order_id': '2100', 'branch': {'id': 'A'}, 'amount': '1500000'},
                                '/receipts/2101': {'id': '2101', 'sales_order_number': SO, 'sales_order_id': '2100', 'branch': {'id': 'A'}, 'amount': '1500000'}})
    assert (await post(f'/{job}/payment/receipts', {'accurate_receipt_id': 'RCV-1'})).status_code == 200
    aid = (await post(f'/{job}/schedule/assignments', {'so_line_id': 'line-1', 'color_pass': 1, 'operator_name': 'Rizki', 'machine_name': 'M1', 'work_date': str(date.today()), 'qty_planned': '100'})).json()['id']
    await post(f'/{job}/prep/screener', {'so_line_id': 'line-1', 'qty': '2', 'po_qty': '100', 'screen_size': 'kecil', 'evidence_ref': 's1', 'idempotency_key': 'prep-s-0001', 'assignment_id': aid})
    await post(f'/{job}/prep/helper', {'so_line_id': 'line-1', 'qty': '80', 'po_qty': '100', 'evidence_ref': 'c1', 'idempotency_key': 'prep-h-0001', 'assignment_id': aid})
    s = (await post(f'/{job}/samples', {'file_name': 's.jpg', 'storage_key': 'samples/1.jpg', 'assignment_id': aid})).json()['id']
    await post(f'/samples/{s}/decision', {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})
    out = await post(f'/{job}/outputs', {'assignment_id': aid, 'qty_physical': '40', 'qty_pass_ops': '40', 'color_pass': 1, 'idempotency_key': 'out-idem-01', 'lot_code': 'L1'})
    assert out.status_code == 200, out.text
    body = {'source_event_id': out.json()['id'], 'qty_physical_delta': '-2', 'reason': 'overcount', 'idempotency_key': 'corr-idem-01'}
    return db, c, post, job, aid, body


async def _state(db, aid):
    async with db() as s:
        n = await s.scalar(select(func.count()).select_from(ProductionEvent).where(ProductionEvent.event_type == 'output_correction'))
        confirmed = await s.scalar(select(ScheduleAssignment.qty_confirmed).where(ScheduleAssignment.id == aid))
        outs = await s.scalar(select(func.count()).select_from(ProductionEvent).where(ProductionEvent.event_type == 'output_confirmed'))
    return n, confirmed, outs


async def test_first_replay_conflict_and_retry(ready, monkeypatch):
    db, c, post, job, aid, body = await _setup(ready, monkeypatch)
    before = await _state(db, aid)
    first = await post(f'/{job}/outputs/corrections', body)
    assert first.status_code == 200, first.text
    after_first = await _state(db, aid)
    assert after_first[0] == 1 and after_first[1] == before[1] - 2 and after_first[2] == before[2]
    replay = await post(f'/{job}/outputs/corrections', body)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert await _state(db, aid) == after_first
    diff = await post(f'/{job}/outputs/corrections', {**body, 'qty_physical_delta': '-3'})
    assert diff.status_code == 409 and 'tidak cocok' in diff.text
    diff_reason = await post(f'/{job}/outputs/corrections', {**body, 'reason': 'other reason'})
    assert diff_reason.status_code == 409
    assert await _state(db, aid) == after_first
    retry = await post(f'/{job}/outputs/corrections', {**body, 'idempotency_key': 'corr-idem-02', 'qty_physical_delta': '-3'})
    assert retry.status_code == 200 and retry.json()['id'] != first.json()['id']
    assert (await _state(db, aid))[:2] == (2, before[1] - 5)


async def test_concurrent_duplicates_create_one_correction(ready, monkeypatch):
    db, c, post, job, aid, body = await _setup(ready, monkeypatch)
    before = await _state(db, aid)
    rs = await asyncio.gather(*[post(f'/{job}/outputs/corrections', body) for _ in range(6)])
    assert {r.status_code for r in rs} == {200}, [r.text for r in rs]
    assert len({r.json()['id'] for r in rs}) == 1
    n, confirmed, outs = await _state(db, aid)
    assert (n, confirmed, outs) == (1, before[1] - 2, before[2])
    mixed = await asyncio.gather(post(f'/{job}/outputs/corrections', {**body, 'qty_physical_delta': '-9'}),
                                 post(f'/{job}/outputs/corrections', body))
    assert [r.status_code for r in mixed] == [409, 200]


async def test_non_duplicate_database_error_is_not_masked(ready, monkeypatch):
    db, c, post, job, aid, body = await _setup(ready, monkeypatch)
    before = await _state(db, aid)

    class Orig(Exception):
        sqlstate = '23503'

    async def boom(self):
        await self.rollback()
        raise IntegrityError('stmt', {}, Orig('foreign key violation'))
    monkeypatch.setattr(AsyncSession, 'commit', boom)
    with pytest.raises(IntegrityError):
        await post(f'/{job}/outputs/corrections', body)
    monkeypatch.undo()
    assert await _state(db, aid) == before
