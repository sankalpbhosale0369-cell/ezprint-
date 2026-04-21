"""Dashboard KPIs for the shopkeeper desktop + web."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel

from app.schemas.jobs import JobSummary

Period = Literal["today", "week", "month", "all"]


class DashboardKPIs(BaseModel):
    period: Period
    total_revenue: float
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    in_progress_jobs: int    # Queued + Printing
    awaiting_upload_jobs: int
    avg_amount: float
    recent: List[JobSummary]
