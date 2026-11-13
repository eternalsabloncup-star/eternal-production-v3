"""Effective payment status from local verified evidence; never trust the mirror.

Reads do not write/commit or call Accurate. Revalidation is an explicit mutation.
A single SQL statement evaluates receipts and bypasses in the same snapshot.
"""
from sqlalchemy import case, exists, select
from app.models.production.job import ProductionJob
from app.models.production.payment import PaymentBypass, PaymentReceiptRef


def status_expression():
    receipt = exists().where(
        PaymentReceiptRef.job_id == ProductionJob.id,
        PaymentReceiptRef.status == 'valid',
        PaymentReceiptRef.evidence_verified.is_(True),
        PaymentReceiptRef.amount > 0,
    )
    bypass = exists().where(
        PaymentBypass.job_id == ProductionJob.id,
        PaymentBypass.active.is_(True),
    )
    return case((receipt, 'approved'), (bypass, 'bypassed'), else_='pending')


async def effective_statuses(session, job_ids):
    if not job_ids:
        return {}
    rows = await session.execute(select(ProductionJob.id, status_expression()).where(ProductionJob.id.in_(job_ids)))
    return dict(rows.all())


async def effective_status(session, job_id):
    return (await effective_statuses(session, [job_id])).get(job_id, 'pending')
