"""Second-tier valid-payload coverage in ENFORCED mode: corrections, payment evidence
lifecycle, schedule cancel/transfer, loading cancel, physical-return dual approval, SJ cancel,
design approval link, lookups. Approvals are always performed by a different user (SoD)."""
from datetime import date
import pytest
from tests.authorization.test_foundation import db
from tests.authorization.test_runtime import runtime, login
from tests.authorization.test_workflow_access import enforced
from tests.authorization.test_workflow_completion import ready, grant
from tests.authorization.test_workflow_business import prepare, API, FLOW_CAPS, SO
from tests.production.payment_helpers import mock_receipts
from tests.production.helper_verify_helpers import helper_verify_output
from tests.production.pod_attach_helpers import PNG_1X1

EXTRA_CAPS = ['design.approval_link.create', 'payment.receipt.revalidate', 'payment.receipt.invalidate',
              'schedule.assignment.cancel_remaining', 'schedule.assignment.transfer_remaining', 'output.correct',
              'loading.cancel_confirmation', 'loading.return.request', 'attachment.return.create',
              'delivery.sj.cancel_local', 'loading.authority.read', 'tracking.link.create', 'attachment.delivery.read']


@pytest.mark.parametrize('actor', ['director', 'scoped'])
async def test_secondary_workflow_actions_under_enforced_mode(ready, monkeypatch, actor):
    db, c = ready
    await prepare(monkeypatch)
    mock_receipts(monkeypatch, {'/receipts/RCV-1': {'id': '2101', 'sales_order_number': SO, 'sales_order_id': '2100', 'branch': {'id': 'A'}, 'amount': '1500000'},
                                '/receipts/2101': {'id': '2101', 'sales_order_number': SO, 'sales_order_id': '2100', 'branch': {'id': 'A'}, 'amount': '1500000'},
                                '/receipts/RCV-2': {'id': '2102', 'sales_order_number': SO, 'sales_order_id': '2100', 'branch': {'id': 'A'}, 'amount': '100'}})
    director, _ = await login(c)
    h = director if actor == 'director' else (await login(c, 'test-3'))[0]
    if actor == 'scoped':
        for cap in FLOW_CAPS + EXTRA_CAPS: await grant(db, cap)
    post = lambda path, body, hdr=h: c.post(API + path, headers=hdr, json=body)
    job = (await post('', {'accurate_so_number': SO, 'accurate_id': '2100', 'branch_id': 'A'})).json()['id']
    assert (await c.get(f'{API}/by-so/{SO}', headers=h)).json()['id'] == job
    v = (await post(f'/{job}/design/versions', {'file_name': 'a.pdf', 'storage_key': 'designs/a.pdf'})).json()['id']
    link = await post(f'/{job}/design/versions/{v}/approval-links', {'so_line_id': 'line-1'})
    assert link.status_code == 200 and link.json()['scope'] == 'design_approval', link.text
    assert (await post(f'/design/versions/{v}/decision', {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})).status_code == 200
    rcp = await post(f'/{job}/payment/receipts', {'accurate_receipt_id': 'RCV-1'})
    assert rcp.status_code == 200, rcp.text
    assert (await post(f"/payment/receipts/{rcp.json()['id']}/revalidate", {'reason': 'recheck evidence', 'idempotency_key': 'reval-act-01'})).status_code == 200
    from decimal import Decimal as _D
    from app.models.production.prep import JobLineQty
    async with db() as s:
        s.add(JobLineQty(job_id=job, so_line_id='line-1', po_qty=_D('100'), production_process='print'))
        await s.commit()
    asg = await post(f'/{job}/schedule/assignments', {'so_line_id': 'line-1', 'color_pass': 1, 'operator_name': 'Rizki', 'machine_name': 'M1', 'work_date': str(date.today()), 'qty_planned': '100'})
    assert asg.status_code == 200, asg.text
    aid = asg.json()['id']
    assert (await post(f'/{job}/prep/screener', {'so_line_id': 'line-1', 'qty': '2', 'po_qty': '100', 'screen_size': 'kecil', 'evidence_ref': 's1', 'idempotency_key': 'prep-s-0001', 'assignment_id': aid})).status_code == 200
    assert (await post(f'/{job}/prep/helper', {'so_line_id': 'line-1', 'qty': '80', 'po_qty': '100', 'evidence_ref': 'c1', 'idempotency_key': 'prep-h-0001', 'assignment_id': aid})).status_code == 200
    s = (await post(f'/{job}/samples', {'file_name': 's.jpg', 'storage_key': 'samples/1.jpg', 'assignment_id': aid})).json()['id']
    assert (await post(f'/samples/{s}/decision', {'decision': 'approved', 'bypass': True, 'reason': 'test setup bypass'})).status_code == 200
    out = await post(f'/{job}/outputs', {'assignment_id': aid, 'qty_physical': '40', 'qty_pass_ops': '40', 'color_pass': 1, 'idempotency_key': 'out-act-001', 'lot_code': 'L1'})
    assert out.status_code == 200, out.text
    await helper_verify_output(c, job, out.json()['id'], '40', headers=h, idem='hv-act-0001')
    corr = await post(f'/{job}/outputs/corrections', {'source_event_id': out.json()['id'], 'qty_physical_delta': '-2', 'reason': 'overcount', 'idempotency_key': 'corr-act-01'})
    assert corr.status_code == 200, corr.text
    assert (await post(f'/{job}/packing', {'so_line_id': 'line-1', 'qty_physical': '30', 'idempotency_key': 'pack-act-01', 'lot_code': 'L1'})).status_code == 200
    la = await c.get(f'{API}/{job}/loading-authority', headers=h, params={'accurate_sj_id': 'SJ-1', 'accurate_sj_number': 'SJ-1', 'accurate_sj_line_id': 'SL-1', 'so_line_id': 'line-1'})
    assert la.status_code == 200, la.text
    load = {'accurate_sj_id': 'sj-1', 'accurate_sj_number': 'SJ/001', 'accurate_sj_line_id': 'SL-1', 'so_line_id': 'line-1'}
    e1 = await post(f'/{job}/loading', {**load, 'qty_physical': '20', 'idempotency_key': 'load-act-01'})
    e2 = await post(f'/{job}/loading', {**load, 'qty_physical': '10', 'idempotency_key': 'load-act-02'})
    e3 = await post(f'/{job}/loading', {**load, 'qty_physical': '5', 'idempotency_key': 'load-act-03'})
    assert e1.status_code == e2.status_code == e3.status_code == 200, (e1.text, e2.text, e3.text)
    cancel = await post(f"/{job}/loading/{e3.json()['id']}/cancel", {'qty_physical': '5', 'reason': 'wrong entry', 'idempotency_key': 'lcancel-01'})
    assert cancel.status_code == 200, cancel.text

    async def upload():
        up = await c.post(f'{API}/{job}/attachments', headers=h, data={'accurate_sj_id': 'sj-1', 'purpose': 'loading_return_photo'}, files={'file': ('r.png', PNG_1X1, 'image/png')})
        assert up.status_code == 200, up.text
        return up.json()['id']
    attachment = await upload()
    assert (await c.get(f'/api/v1/production/jobs/attachments/{attachment}', headers=h)).status_code == 200
    req1 = await post(f"/{job}/loading/{e1.json()['id']}/return-requests", {'qty_physical': '5', 'reason': 'goods back', 'idempotency_key': 'ret-act-001', 'evidence_attachment_id': attachment})
    assert req1.status_code == 200, req1.text
    same_user = await post(f"/{job}/loading/return-requests/{req1.json()['id']}/approve", {'idempotency_key': 'ret-act-same'})
    assert same_user.status_code in (403, 409)  # director==requester or scoped lacks approve: never self-approve
    appr = await post(f"/{job}/loading/return-requests/{req1.json()['id']}/approve", {'idempotency_key': 'ret-act-appr', 'reason': 'received'}, director)
    if actor == 'director': assert appr.status_code in (403, 409)  # requester cannot approve own request
    else: assert appr.status_code == 200, appr.text
    attachment2 = await upload()
    req2 = await post(f"/{job}/loading/{e2.json()['id']}/return-requests", {'qty_physical': '5', 'reason': 'goods back 2', 'idempotency_key': 'ret-act-002', 'evidence_attachment_id': attachment2})
    assert req2.status_code == 200, req2.text
    rej = await post(f"/{job}/loading/return-requests/{req2.json()['id']}/reject", {'idempotency_key': 'ret-act-rej', 'reason': 'not received'}, director)
    if actor == 'scoped': assert rej.status_code == 200, rej.text
    sjc = await post(f'/{job}/sj/cancel', {'accurate_sj_id': 'sj-unused', 'reason': 'supersede', 'idempotency_key': 'sjc-act-001'})
    assert sjc.status_code == 200, sjc.text
    tr = await post(f'/schedule/assignments/{aid}/transfer-remaining', {'operator_name': 'Dewi', 'machine_name': 'M2', 'work_date': str(date.today()), 'reason': 'rebalance'})
    assert tr.status_code == 200, tr.text
    new_id = tr.json().get('id', aid)
    cr = await post(f'/schedule/assignments/{new_id}/cancel-remaining', {'reason': 'customer reduce'})
    assert cr.status_code in (200, 409), cr.text
    inv = await post(f"/payment/receipts/{rcp.json()['id']}/invalidate", {'reason': 'reversed in Accurate'})
    assert inv.status_code == 200, inv.text
    assert (await post(f'/{job}/tracking-links', {})).status_code == 200
