"""Valid-payload business flow under ENFORCED authorization on isolated PostgreSQL.

Proves an allow decision never skips existing workflow gates (design/payment,
sample, qty caps, idempotency, helper verification) and that each step still needs
its own capability."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant
from tests.production.payment_helpers import mock_receipts
from tests.production.sj_line_helpers import sj_line_item
from tests.production.helper_verify_helpers import helper_verify_output
from tests.production.pod_attach_helpers import pod_body, upload_pod_bundle

SO = 'SO/BIZ/001'
FLOW_CAPS = ['job.create', 'job.read', 'design.version.create', 'design.decision.record', 'design.bypass.create',
             'payment.receipt.record', 'schedule.assignment.create', 'prep.screener.record', 'prep.helper.record',
             'sample.version.create', 'sample.decision.record', 'output.record', 'output.helper.verify',
             'reject.record', 'reject.verify', 'packing.record', 'loading.record', 'delivery.pod.record',
             'attachment.delivery.create', 'tracking.read', 'payroll.rate.manage', 'payroll.run.create', 'payroll.run.read']
API = '/api/v1/production/jobs'
PAY = '/api/v1/production/payroll'


async def prepare(monkeypatch):
    mock_receipts(monkeypatch, {'/receipts/RCV-1': {'id': '2101', 'sales_order_number': SO, 'sales_order_id': '2100',
                                                    'branch': {'id': 'A'}, 'amount': '1500000'}})

    async def valid_sj(**kw):
        return {'verified': True, 'mode': 'gateway', 'accurate_sj_id': kw['accurate_sj_id'],
                'accurate_sj_number': kw['accurate_sj_number'], 'sales_order_number': SO, 'branch_id': 'A',
                'line_items': [sj_line_item(accurate_sj_line_id='SL-1', so_line_id='line-1', quantity=100)],
                'loading_eligible': True, 'live_verified': False}
    monkeypatch.setattr('app.services.accurate_evidence.require_valid_sj', valid_sj)


@pytest.mark.parametrize('actor', ['director', 'scoped'])
async def test_full_flow_under_enforced_mode_keeps_every_gate(ready, monkeypatch, actor):
    db, c = ready
    await prepare(monkeypatch)
    h, _ = await login(c, 'test-1' if actor == 'director' else 'test-3')
    if actor == 'scoped':
        for cap in FLOW_CAPS: await grant(db, cap)
    post = lambda path, body, hdr=h: c.post(API + path, headers=hdr, json=body)
    r = await post('', {'accurate_so_number': SO, 'accurate_id': '2100', 'branch_id': 'A', 'customer_name': 'Customer A'})
    assert r.status_code == 200, r.text
    job = r.json()['id']
    asg_body = {'so_line_id': 'line-1', 'color_pass': 1, 'operator_name': 'Rizki', 'machine_name': 'Semi Auto 01',
                'work_date': str(date.today()), 'qty_planned': '100'}
    r = await post(f'/{job}/schedule/assignments', asg_body)
    assert r.status_code == 409, r.text  # authorized, still blocked by design/payment gates
    r = await post(f'/{job}/design/versions', {'file_name': 'a.pdf', 'storage_key': 'designs/a.pdf'})
    assert r.status_code == 200, r.text
    r = await post(f"/design/versions/{r.json()['id']}/decision", {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})
    assert r.status_code == 200, r.text
    assert (await post(f'/{job}/payment/receipts', {'accurate_receipt_id': 'RCV-1', 'amount': '1500000'})).status_code == 200
    r = await post(f'/{job}/schedule/assignments', asg_body)
    assert r.status_code == 200, r.text
    aid = r.json()['id']
    assert (await post(f'/{job}/prep/screener', {'so_line_id': 'line-1', 'qty': '2', 'po_qty': '100', 'screen_size': 'kecil',
            'evidence_ref': 'screen-1', 'idempotency_key': 'prep-screen-1', 'assignment_id': aid})).status_code == 200
    assert (await post(f'/{job}/prep/helper', {'so_line_id': 'line-1', 'qty': '80', 'po_qty': '100',
            'evidence_ref': 'cup-1', 'idempotency_key': 'prep-helper-1', 'assignment_id': aid})).status_code == 200
    s = await post(f'/{job}/samples', {'file_name': 's.jpg', 'storage_key': 'samples/1.jpg', 'assignment_id': aid})
    assert s.status_code == 200
    out_body = {'assignment_id': aid, 'qty_physical': '40', 'qty_pass_ops': '40', 'color_pass': 1, 'idempotency_key': 'out-biz-1', 'lot_code': 'L1'}
    assert (await post(f'/{job}/outputs', {'assignment_id': aid, 'qty_physical': '10', 'idempotency_key': 'out-blocked'})).status_code == 409  # sample gate
    assert (await post(f"/samples/{s.json()['id']}/decision", {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})).status_code == 200
    out = await post(f'/{job}/outputs', out_body)
    assert out.status_code == 200, out.text
    # Same-key + identical payload → 200 replay of committed event (no double qty).
    replay = await post(f'/{job}/outputs', out_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()['id'] == out.json()['id']
    outs = [
        e
        for e in (await c.get(f'{API}/{job}/tracking', headers=h)).json()['events']
        if e['event_type'] == 'output_confirmed'
    ]
    assert len(outs) == 1
    assert outs[0]['idempotency_key'] == 'out-biz-1'
    assert outs[0]['qty_physical'] in ('40', '40.000', '40.0')
    # Same key + different payload → 409, still one event.
    mismatch = await post(
        f'/{job}/outputs',
        {**out_body, 'qty_physical': '11', 'lot_code': 'OTHER'},
    )
    assert mismatch.status_code == 409, mismatch.text
    assert 'payload tidak cocok' in mismatch.text
    outs2 = [
        e
        for e in (await c.get(f'{API}/{job}/tracking', headers=h)).json()['events']
        if e['event_type'] == 'output_confirmed'
    ]
    assert len(outs2) == 1
    pack_body = {'so_line_id': 'line-1', 'qty_physical': '35', 'idempotency_key': 'pack-biz-1', 'lot_code': 'L1'}
    assert (await post(f'/{job}/packing', pack_body)).status_code == 409  # not helper-verified yet
    await helper_verify_output(c, job, out.json()['id'], '40', headers=h, idem='hv-biz-0001')
    rej = await post(f'/{job}/rejects', {'assignment_id': aid, 'qty_physical': '5', 'reason': 'misprint', 'idempotency_key': 'rej-biz-1', 'lot_code': 'L1'})
    assert rej.status_code == 200, rej.text
    assert (await post(f"/rejects/{rej.json()['id']}/verify", {'approved_qty': '5'})).status_code == 200
    assert (await post(f'/{job}/packing', pack_body)).status_code == 200
    assert (await post(f'/{job}/packing', {**pack_body, 'qty_physical': '1', 'idempotency_key': 'pack-biz-over'})).status_code == 409
    load = {'accurate_sj_id': 'sj-1', 'accurate_sj_number': 'SJ/001', 'accurate_sj_line_id': 'SL-1', 'so_line_id': 'line-1',
            'qty_physical': '20', 'idempotency_key': 'load-biz-1'}
    early = await upload_pod_bundle(c, job, 'sj-1', headers=h)
    assert (await post(f'/{job}/pod', pod_body('sj-1', '10', 'pod-early-01', early))).status_code == 409  # nothing loaded
    assert (await post(f'/{job}/loading', load)).status_code == 200
    ok = await upload_pod_bundle(c, job, 'sj-1', headers=h)
    r = await post(f'/{job}/pod', pod_body('sj-1', '20', 'pod-biz-01', ok))
    assert r.status_code == 200, r.text
    events = [e['event_type'] for e in (await c.get(f'{API}/{job}/tracking', headers=h)).json()['events']]
    assert {'output_confirmed', 'reject_verified', 'packing_batch', 'loading', 'pod'} <= set(events)
    r = await c.post(f'{PAY}/rates', headers=h, json={'component': 'one', 'amount': '100', 'effective_from': '2026-01-01'})
    assert r.status_code == 200, r.text
    r = await c.post(f'{PAY}/runs', headers=h, json={'period_start': '2026-01-01', 'period_end': '2026-12-31', 'branch_id': 'A', 'idempotency_key': 'biz-run-' + actor})
    assert r.status_code == 200, r.text
    assert (await c.get(f"{PAY}/runs/{r.json()['id']}", headers=h)).status_code == 200
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ProductionJob).where(ProductionJob.accurate_so_number == SO)) == 1
        assert await s.scalar(select(func.count()).select_from(ProductionEvent).where(ProductionEvent.job_id == job, ProductionEvent.event_type == 'output_confirmed')) == 1


@pytest.mark.parametrize('missing', ['output.record', 'packing.record', 'loading.record', 'delivery.pod.record',
                                     'reject.record', 'payment.receipt.record', 'schedule.assignment.create'])
async def test_each_workflow_step_needs_its_own_capability(ready, monkeypatch, missing):
    db, c = ready
    await prepare(monkeypatch)
    director, _ = await login(c); op, _ = await login(c, 'test-3')
    for cap in FLOW_CAPS:
        if cap != missing: await grant(db, cap)
    r = await c.post(API, headers=director, json={'accurate_so_number': SO, 'accurate_id': '2100', 'branch_id': 'A'})
    job = r.json()['id']
    bodies = {'output.record': ('/outputs', {'assignment_id': 1, 'qty_physical': '1', 'idempotency_key': 'xkey-0001'}),
              'packing.record': ('/packing', {'so_line_id': 'line-1', 'qty_physical': '1', 'idempotency_key': 'xkey-0002'}),
              'loading.record': ('/loading', {'accurate_sj_id': 's', 'accurate_sj_number': 's', 'accurate_sj_line_id': 'l', 'so_line_id': 'line-1', 'qty_physical': '1', 'idempotency_key': 'xkey-0003'}),
              'delivery.pod.record': ('/pod', {}), 'reject.record': ('/rejects', {'assignment_id': 1, 'qty_physical': '1', 'reason': 'r', 'idempotency_key': 'xkey-0004'}),
              'payment.receipt.record': ('/payment/receipts', {'accurate_receipt_id': 'RCV-1'}),
              'schedule.assignment.create': ('/schedule/assignments', {'so_line_id': 'line-1', 'operator_name': 'o', 'machine_name': 'm', 'work_date': str(date.today()), 'qty_planned': '1'})}
    path, body = bodies[missing]
    r = await c.post(f'{API}/{job}{path}', headers=op, json=body)
    assert r.status_code == 403, (missing, r.status_code, r.text)
