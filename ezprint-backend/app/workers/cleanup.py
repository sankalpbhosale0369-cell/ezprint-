"""Periodic asset cleanup — safety net for the state machine.

Immediate MinIO cleanup happens synchronously inside
`app.services.jobs.transition()` whenever a job reaches a terminal state.
This worker exists only to cover two residual cases:

    1. MinIO was momentarily unavailable during that synchronous call,
       so the job is flagged `assets_delete_scheduled=True` and needs a retry.
    2. A customer created a job but never uploaded: `AwaitingUpload` older
       than `ABANDON_AFTER_HOURS` is transitioned to `Cancelled`
       (which itself runs cleanup via the state machine).

It intentionally does NOT delete files for Completed jobs after 24h —
that path is now owned by `transition()` at the moment of completion.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta
from typing import List

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.core.logging import configure_logging
from app.db import models
from app.db.session import SessionLocal
from app.services.jobs import _cleanup_assets, transition

logger = logging.getLogger(__name__)


BATCH_SIZE = 20
SLEEP_SECONDS = 300  # 5 min
ABANDON_AFTER_HOURS = 1


# ------------------------------------------------------------------ retry path
def _find_retry_candidates(db) -> List[models.PrintJob]:
    """Jobs whose immediate cleanup failed and still needs another attempt."""
    stmt = (
        select(models.PrintJob)
        .where(
            and_(
                models.PrintJob.assets_deleted.is_(False),
                models.PrintJob.assets_delete_scheduled.is_(True),
                models.PrintJob.status.in_(["Completed", "Failed", "Cancelled"]),
            )
        )
        .limit(BATCH_SIZE)
    )
    return list(db.scalars(stmt).all())


# ------------------------------------------------------------ abandonment path
def _find_abandoned_uploads(db) -> List[models.PrintJob]:
    """AwaitingUpload jobs older than the abandonment threshold."""
    cutoff = datetime.utcnow() - timedelta(hours=ABANDON_AFTER_HOURS)
    stmt = (
        select(models.PrintJob)
        .where(
            and_(
                models.PrintJob.status == "AwaitingUpload",
                models.PrintJob.created_at < cutoff,
            )
        )
        .limit(BATCH_SIZE)
    )
    return list(db.scalars(stmt).all())


# ----------------------------------------------------------------- main sweep
def _sweep_once() -> dict:
    db = SessionLocal()
    retried = 0
    abandoned = 0
    errors = 0
    try:
        for job in _find_retry_candidates(db):
            try:
                _cleanup_assets(db, job)
                if job.assets_deleted:
                    retried += 1
            except Exception:
                errors += 1
                logger.exception("retry cleanup failed for job=%s", job.job_id)

        for job in _find_abandoned_uploads(db):
            try:
                transition(
                    db, job, "Cancelled",
                    error_message=f"Upload abandoned (>{ABANDON_AFTER_HOURS}h)",
                )
                abandoned += 1
            except HTTPException as exc:
                logger.warning(
                    "skip abandoned job=%s: %s", job.job_id, exc.detail
                )
            except Exception:
                errors += 1
                logger.exception("abandon cleanup failed for job=%s", job.job_id)
    finally:
        db.close()
    return {"retried": retried, "abandoned": abandoned, "errors": errors}


def main() -> None:
    configure_logging()
    logger.info(
        "cleanup worker started (interval=%ss, batch=%s, abandon_after=%sh)",
        SLEEP_SECONDS, BATCH_SIZE, ABANDON_AFTER_HOURS,
    )
    stopping = False

    def _stop(*_args):
        nonlocal stopping
        stopping = True
        logger.info("cleanup worker received stop signal")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping:
        try:
            result = _sweep_once()
            if any(result.values()):
                logger.info("cleanup sweep: %s", result)
        except Exception:
            logger.exception("cleanup sweep crashed")
        for _ in range(SLEEP_SECONDS):
            if stopping:
                break
            time.sleep(1)
    logger.info("cleanup worker exited")


if __name__ == "__main__":
    main()
