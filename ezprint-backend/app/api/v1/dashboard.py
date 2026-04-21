"""Dashboard KPI endpoint.

Replaces the desktop client's local `DashboardKPIWorker` (which used to hit
the shared SQLite/Postgres directly). The shopkeeper .exe and any future
web dashboard both call this; everything is scoped to the caller's tenant.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.dashboard import DashboardKPIs, Period
from app.schemas.jobs import JobSummary
from app.tenancy.deps import Principal, require_shopkeeper_or_agent

router = APIRouter()


def _period_start(period: Period) -> Optional[datetime]:
    now = datetime.utcnow()
    if period == "today":
        return datetime(now.year, now.month, now.day)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None  # "all"


def _job_to_summary(job: models.PrintJob) -> JobSummary:
    return JobSummary(
        job_id=job.job_id,
        filename=job.filename,
        file_type=job.file_type,
        file_size=job.file_size,
        status=job.status,  # type: ignore[arg-type]
        total_pages=job.total_pages,
        color_pages=job.color_pages,
        copies=job.copies,
        print_side=job.print_side,
        color_mode=job.color_mode,
        amount=job.amount,
        customer_name=job.customer_name,
        customer_phone=job.customer_phone,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("", response_model=DashboardKPIs)
def get_dashboard(
    period: Period = Query(default="today"),
    recent_limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> DashboardKPIs:
    tenant_id = principal.tenant_id
    start = _period_start(period)

    base = select(models.PrintJob).where(models.PrintJob.tenant_id == tenant_id)
    if start is not None:
        base = base.where(models.PrintJob.created_at >= start)

    # One query to aggregate counts + revenue. Revenue counts completed only.
    agg = db.execute(
        select(
            func.count(models.PrintJob.id),
            func.sum(
                func.coalesce(
                    func.nullif(models.PrintJob.amount, None), 0.0
                )
            ).filter(models.PrintJob.status == "Completed"),
            func.sum(
                func.case((models.PrintJob.status == "Completed", 1), else_=0)
            ),
            func.sum(
                func.case((models.PrintJob.status == "Failed", 1), else_=0)
            ),
            func.sum(
                func.case((models.PrintJob.status == "Cancelled", 1), else_=0)
            ),
            func.sum(
                func.case(
                    (models.PrintJob.status.in_(("Queued", "Printing")), 1),
                    else_=0,
                )
            ),
            func.sum(
                func.case((models.PrintJob.status == "AwaitingUpload", 1), else_=0)
            ),
        ).where(
            models.PrintJob.tenant_id == tenant_id,
            *([models.PrintJob.created_at >= start] if start is not None else []),
        )
    ).one()

    total_jobs = int(agg[0] or 0)
    total_revenue = float(agg[1] or 0.0)
    completed = int(agg[2] or 0)
    failed = int(agg[3] or 0)
    cancelled = int(agg[4] or 0)
    in_progress = int(agg[5] or 0)
    awaiting = int(agg[6] or 0)
    avg_amount = (total_revenue / completed) if completed else 0.0

    recent_rows = db.scalars(
        base.order_by(models.PrintJob.created_at.desc()).limit(recent_limit)
    ).all()

    return DashboardKPIs(
        period=period,
        total_revenue=round(total_revenue, 2),
        total_jobs=total_jobs,
        completed_jobs=completed,
        failed_jobs=failed,
        cancelled_jobs=cancelled,
        in_progress_jobs=in_progress,
        awaiting_upload_jobs=awaiting,
        avg_amount=round(avg_amount, 2),
        recent=[_job_to_summary(j) for j in recent_rows],
    )
