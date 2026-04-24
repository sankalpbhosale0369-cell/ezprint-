"""Print job state machine.

Every status write in the system — whether it comes in over REST
(`PATCH /api/v1/jobs/{id}/status`) or over the agent WebSocket
(`print_started`, `print_completed`, `print_failed`) — MUST go through
`transition()`. That way:

    - Invalid transitions are rejected with HTTP 409 at both entry points.
    - Timestamps (`started_at`, `completed_at`) are set consistently.
    - Terminal states trigger immediate MinIO cleanup of the job's prefix.
    - A `job_status` event is published on the tenant pub/sub channel so
      any listening frontend (or the agent for confirmation) sees the change.

The state machine is intentionally small — see the `ALLOWED` table below.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import models
from app.services.notifier import notifier
from app.services.storage import storage

logger = logging.getLogger(__name__)

TERMINAL: Set[str] = {"Completed", "Failed", "Cancelled"}

# Per-state list of legal next states. Anything not listed is an error.
ALLOWED: dict[str, Set[str]] = {
    "AwaitingUpload": {"Queued", "Cancelled", "Failed"},
    "Queued":         {"Processing", "Printing", "Cancelled", "Failed"},
    "Processing":     {"Printing", "Cancelled", "Failed"},
    "Printing":       {"Completed", "Failed", "Cancelled"},
    # Terminal states accept no further transitions.
    "Completed":      set(),
    "Failed":         set(),
    "Cancelled":      set(),
}


# --------------------------------------------------------------------- cleanup
def _cleanup_assets(db: Session, job: models.PrintJob) -> None:
    """Delete all MinIO objects for a job. Safe to call more than once.

    Falls back to a scheduled retry if storage is momentarily unavailable;
    the worker loop will pick it up. Never raises out of this function — a
    cleanup failure must not fail the user-facing request.
    """
    if job.assets_deleted:
        return
    prefix = storage.job_prefix(job.tenant_id, job.job_id)
    try:
        storage.delete_prefix(job.tenant_id, prefix)
    except Exception:
        logger.exception("immediate cleanup failed; sweeper will retry job=%s", job.job_id)
        job.assets_delete_scheduled = True
        job.assets_delete_attempted_at = datetime.utcnow()
        db.commit()
        return
    job.assets_deleted = True
    job.assets_delete_scheduled = False
    job.object_key = ""
    job.assets_delete_attempted_at = datetime.utcnow()
    db.commit()


# ------------------------------------------------------------------- broadcast
def _publish_status(job: models.PrintJob) -> None:
    """Fire-and-forget `job_status` broadcast on the tenant channel.

    Works whether or not we're inside a running asyncio loop:
    from async code (FastAPI handlers, WS handler) we schedule a task;
    from sync code (the cleanup worker) we spin up a short-lived loop.
    """
    event = {
        "type": "job_status",
        "data": {
            "job_id": job.job_id,
            "status": job.status,
            "amount": job.amount,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
        },
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    async def _do() -> None:
        try:
            await notifier.publish(job.tenant_id, event)
        except Exception:
            logger.exception("status broadcast failed job=%s", job.job_id)

    if loop is not None:
        loop.create_task(_do())
    else:
        try:
            asyncio.run(_do())
        except Exception:
            logger.exception("status broadcast (sync) failed job=%s", job.job_id)


# ------------------------------------------------------------------ transition
def transition(
    db: Session,
    job: models.PrintJob,
    new_status: str,
    *,
    error_message: Optional[str] = None,
) -> models.PrintJob:
    """Move `job` from its current status to `new_status`.

    Idempotent: setting the same status twice is a no-op. Invalid
    transitions raise HTTP 409. Terminal statuses also trigger immediate
    MinIO cleanup and a pub/sub broadcast.
    """
    if job.status == new_status:
        return job

    allowed = ALLOWED.get(job.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transition {job.status} -> {new_status} not allowed",
        )

    now = datetime.utcnow()
    if new_status == "Printing" and not job.started_at:
        job.started_at = now
    if new_status in TERMINAL:
        job.completed_at = now
        if error_message:
            job.error_message = error_message

    job.status = new_status
    db.commit()
    db.refresh(job)

    if new_status in TERMINAL:
        _cleanup_assets(db, job)

    _publish_status(job)
    return job
