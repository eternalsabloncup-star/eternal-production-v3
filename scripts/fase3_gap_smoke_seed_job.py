"""Seed disposable workflow evidence so Tugas Tim yields real six-role tasks.

Uses DATABASE_URL of the smoke API (must contain 'test'). Does NOT invent
UI-only tasks — advances print workflow far enough that derive_team_tasks_for_job
emits Designer, Kepala Produksi, Screener, Helper, Operator, and Driver rows.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import dispose_engine, get_session_factory
from app.models.production.attachment import ProductionAttachment
from app.models.production.customer_token import CustomerAccessToken
from app.models.production.design import DesignVersion
from app.models.production.event import ProductionEvent
from app.models.production.job import ProductionJob
from app.models.production.operations import DeliveryPlan, DeliveryPlanEvent
from app.models.production.payment import PaymentBypass, PaymentReceiptRef
from app.models.production.prep import JobLineQty, PrepEvent, PrepState
from app.models.production.sample import SampleVersion
from app.models.production.schedule import ScheduleAssignment
from app.models.user import User
from app.services.production import permissions as P

get_settings.cache_clear()

ALL = [
    P.JOB_CREATE,
    P.JOB_READ,
    P.DESIGN_UPLOAD,
    P.DESIGN_APPROVE,
    P.DESIGN_BYPASS,
    P.PAYMENT_RECORD,
    P.PAYMENT_BYPASS,
    P.PAYMENT_REVOKE,
    P.SCHEDULE_MANAGE,
    P.PREP_SCREENER,
    P.PREP_HELPER,
    P.SAMPLE_UPLOAD,
    P.SAMPLE_DECIDE,
    P.OUTPUT_CONFIRM,
    P.REJECT_RECORD,
    P.REJECT_VERIFY,
    P.PACKING_RECORD,
    P.DELIVERY_MANAGE,
    P.TRACKING_READ,
    P.PAYROLL_MANAGE,
    P.PAYROLL_READ,
]

SO = "SO/SMOKE/GAP-SIX"
MODE = (os.environ.get("SMOKE_SEED_MODE") or "populated").strip().lower()


async def ensure_lead(s) -> User:
    lead = await s.scalar(select(User).where(User.username == "smoke.lead"))
    if lead is None:
        lead = User(
            username="smoke.lead",
            display_name="Smoke",
            role="kepala_produksi",
            password_hash=hash_password("secret-pass"),
            permissions=list(ALL),
            branch_ids=["branch-a"],
            is_active=True,
        )
        s.add(lead)
        await s.flush()
    else:
        lead.password_hash = hash_password("secret-pass")
        lead.permissions = list(ALL)
        lead.is_active = True
        lead.branch_ids = ["branch-a"]
    return lead


async def clear_jobs(s) -> int:
    jobs = (await s.scalars(select(ProductionJob))).all()
    n = len(jobs)
    for job in jobs:
        jid = job.id
        # Child tables first (shared test DB may retain pytest leftovers).
        for model in (
            DeliveryPlanEvent,
            DeliveryPlan,
            ProductionAttachment,
            CustomerAccessToken,
            PaymentReceiptRef,
            PaymentBypass,
            PrepEvent,
            PrepState,
            SampleVersion,
            DesignVersion,
            ProductionEvent,
            ScheduleAssignment,
            JobLineQty,
        ):
            await s.execute(delete(model).where(model.job_id == jid))
        await s.delete(job)
    return n


async def seed_populated(s, lead: User) -> int:
    job = await s.scalar(select(ProductionJob).where(ProductionJob.accurate_so_number == SO))
    if job is None:
        job = ProductionJob(
            accurate_so_number=SO,
            accurate_id="smoke-gap-9201",
            branch_id="branch-a",
            customer_name="Smoke Gap Six Role",
            design_status="bypassed",
            payment_status="bypassed",
        )
        s.add(job)
        await s.flush()
        s.add(
            JobLineQty(
                job_id=job.id,
                so_line_id="line-print",
                accurate_item_id="P-SMOKE",
                po_qty=Decimal("100"),
                production_process="print",
            )
        )
        assign = ScheduleAssignment(
            job_id=job.id,
            branch_id="branch-a",
            so_line_id="line-print",
            operator_name="Op Smoke",
            machine_name="M-Smoke",
            work_date=date.today(),
            qty_planned=Decimal("100"),
            created_by=lead.id,
            status="active",
            color_pass=1,
        )
        s.add(assign)
        await s.flush()
        # Prep evidence unlocks Operator sample task (real workflow, not UI fiction).
        s.add(
            PrepState(
                job_id=job.id,
                so_line_id="line-print",
                role="screener",
                qty=Decimal("100"),
                updated_by=lead.id,
                assignment_id=assign.id,
                screen_size="besar",
            )
        )
        s.add(
            PrepState(
                job_id=job.id,
                so_line_id="line-print",
                role="helper",
                qty=Decimal("100"),
                updated_by=lead.id,
                assignment_id=assign.id,
            )
        )
        # Effective payment gate reads PaymentBypass/Receipt — not job.payment_status mirror.
        s.add(
            PaymentBypass(
                job_id=job.id,
                reason="Smoke disposable six-role gate open",
                authorized_by=lead.id,
                active=True,
                gate_before="pending",
                idempotency_key="smoke-gap-six-bypass",
            )
        )
        return job.id

    # Ensure prep + bypass rows exist on re-run
    assign = await s.scalar(
        select(ScheduleAssignment).where(ScheduleAssignment.job_id == job.id).limit(1)
    )
    for role, size in (("screener", "besar"), ("helper", None)):
        existing = await s.scalar(
            select(PrepState).where(
                PrepState.job_id == job.id,
                PrepState.so_line_id == "line-print",
                PrepState.role == role,
            )
        )
        if existing is None:
            s.add(
                PrepState(
                    job_id=job.id,
                    so_line_id="line-print",
                    role=role,
                    qty=Decimal("100"),
                    updated_by=lead.id,
                    assignment_id=assign.id if assign else None,
                    screen_size=size,
                )
            )
        elif Decimal(existing.qty or 0) <= 0:
            existing.qty = Decimal("100")
    bypass = await s.scalar(
        select(PaymentBypass).where(
            PaymentBypass.job_id == job.id,
            PaymentBypass.active.is_(True),
        )
    )
    if bypass is None:
        s.add(
            PaymentBypass(
                job_id=job.id,
                reason="Smoke disposable six-role gate open",
                authorized_by=lead.id,
                active=True,
                gate_before="pending",
                idempotency_key="smoke-gap-six-bypass",
            )
        )
    job.design_status = "bypassed"
    job.payment_status = "bypassed"
    return job.id


async def main() -> None:
    assert "test" in (os.environ.get("DATABASE_URL") or "").lower(), "refusing non-test DB"
    await dispose_engine()
    get_settings.cache_clear()
    factory = get_session_factory()
    async with factory() as s:
        lead = await ensure_lead(s)
        if MODE == "empty":
            cleared = await clear_jobs(s)
            await s.commit()
            print("SEEDED_EMPTY", "cleared_jobs", cleared)
        elif MODE == "populated":
            job_id = await seed_populated(s, lead)
            await s.commit()
            print("SEEDED_POPULATED", job_id, SO)
        else:
            raise SystemExit(f"unknown SMOKE_SEED_MODE={MODE!r}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
