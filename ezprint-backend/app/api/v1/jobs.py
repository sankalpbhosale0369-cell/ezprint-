"""Print job API.

Flow (see plan section 4):

    1. Customer (upload-token) -> POST /api/v1/jobs         -> presigned PUT
    2. Customer uploads directly to MinIO
    3. Customer -> POST /api/v1/jobs/{id}/finalize          -> classify + price + notify
    4. Agent   -> GET /api/v1/jobs/{id}/file-url            -> presigned GET
    5. Agent   -> PATCH /api/v1/jobs/{id}/status            -> Printing/Completed/Failed
    6. Shopkeeper dashboard -> GET /api/v1/jobs             -> list with filters
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.jobs import (
    JobCreateRequest,
    JobCreateResponse,
    JobFileUrlResponse,
    JobFinalizeResponse,
    JobListResponse,
    JobStatusUpdate,
    JobSummary,
)
from app.services.billing import JobBillingInputs, PricingRates, calculate_amount
from app.services.file_processor import classify_bytes_for_job
from app.services.jobs import transition
from app.services.notifier import notifier
from app.services.storage import storage
from app.tenancy.deps import (
    Principal,
    require_agent,
    require_customer_upload,
    require_shopkeeper_or_agent,
    require_tenant,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_job_for_tenant(db: Session, job_id: str, tenant_id: str) -> models.PrintJob:
    job = db.scalars(
        select(models.PrintJob).where(
            models.PrintJob.job_id == job_id,
            models.PrintJob.tenant_id == tenant_id,
        )
    ).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


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
        page_size=job.page_size,
        orientation=job.orientation,
        print_side=job.print_side,
        color_mode=job.color_mode,
        layout_pages=job.layout_pages,
        layout_type=job.layout_type,
        page_range=job.page_range,
        amount=job.amount,
        customer_name=job.customer_name,
        customer_phone=job.customer_phone,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )


@router.post("", response_model=JobCreateResponse, status_code=201)
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer_upload),
) -> JobCreateResponse:
    """Customer creates a job; we mint a tenant-scoped presigned PUT URL."""
    job = models.PrintJob(
        tenant_id=principal.tenant_id,
        filename=payload.filename,
        file_type=payload.file_type.lower().lstrip("."),
        file_size=payload.file_size,
        copies=payload.copies,
        page_size=payload.page_size,
        orientation=payload.orientation,
        print_side=payload.print_side,
        color_mode=payload.color_mode,
        layout_pages=payload.layout_pages,
        layout_type=payload.layout_type,
        page_range=payload.page_range,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        status="AwaitingUpload",
        object_key="",  # populated below once we know job.job_id
    )
    db.add(job)
    db.flush()  # get auto-generated job_id

    object_key = storage.original_key(principal.tenant_id, job.job_id, payload.filename)
    job.object_key = object_key
    db.commit()
    db.refresh(job)

    presigned = storage.presign_put(
        principal.tenant_id, object_key, expires_in=900
    )
    return JobCreateResponse(
        job_id=job.job_id,
        tenant_id=principal.tenant_id,
        object_key=object_key,
        upload_url=presigned.url,
        upload_url_expires_in=presigned.expires_in,
    )


@router.post("/{job_id}/upload", status_code=204)
async def upload_job_file_proxy(
    job_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer_upload),
) -> Response:
    """Customer uploads a file via the FastAPI proxy.

    Avoids the need to configure CORS on MinIO for browser-direct uploads.
    The file is streamed through the API into object storage.
    """
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    if job.status != "AwaitingUpload":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is in status {job.status}, cannot upload",
        )
    data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    storage.put_bytes(principal.tenant_id, job.object_key, data, content_type)
    return Response(status_code=204)


@router.post("/{job_id}/finalize", response_model=JobFinalizeResponse)
async def finalize_job(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer_upload),
) -> JobFinalizeResponse:
    """Customer signals upload is complete; we classify, price, and push to the agent."""
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    if job.status != "AwaitingUpload":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is in status {job.status}, cannot finalize",
        )

    # Pull the file back from MinIO just far enough to classify it.
    try:
        head = storage.head(principal.tenant_id, job.object_key)
        actual_size = int(head.get("ContentLength", 0))
        obj = storage.internal_client.get_object(Bucket=storage.bucket, Key=job.object_key)
        data: bytes = obj["Body"].read()
    except Exception as exc:
        logger.exception("finalize_job failed reading object")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload not found in storage: {exc}",
        )

    stats = classify_bytes_for_job(job.file_type, data, job.page_range)

    pricing = db.scalars(
        select(models.ShopPricing).where(models.ShopPricing.tenant_id == principal.tenant_id)
    ).first()
    rates = (
        PricingRates(
            bw_single=pricing.bw_single,
            bw_double=pricing.bw_double,
            color_single=pricing.color_single,
            color_double=pricing.color_double,
        )
        if pricing
        else PricingRates()
    )
    amount = calculate_amount(
        rates,
        JobBillingInputs(
            total_pages=stats.total_pages,
            color_pages=stats.color_pages,
            copies=job.copies,
            color_mode=job.color_mode,
            print_side=job.print_side,
        ),
    )

    job.file_size = actual_size or job.file_size
    job.total_pages = stats.total_pages
    job.color_pages = stats.color_pages
    job.amount = amount
    db.commit()

    # Advance state machine: AwaitingUpload -> Queued. This also broadcasts
    # a `job_status` event on the tenant channel.
    job = transition(db, job, "Queued")

    # Push the agent-facing new_job payload (includes a short-lived presigned GET).
    download_url = storage.presign_get(
        principal.tenant_id, job.object_key, expires_in=1800, download_filename=job.filename
    )
    event = {
        "type": "new_job",
        "data": {
            "job_id": job.job_id,
            "filename": job.filename,
            "file_type": job.file_type,
            "file_size": job.file_size,
            "total_pages": job.total_pages,
            "color_pages": job.color_pages,
            "copies": job.copies,
            "page_size": job.page_size,
            "orientation": job.orientation,
            "print_side": job.print_side,
            "color_mode": job.color_mode,
            "layout_pages": job.layout_pages,
            "layout_type": job.layout_type,
            "page_range": job.page_range,
            "amount": job.amount,
            "customer_name": job.customer_name,
            "customer_phone": job.customer_phone,
            "download_url": download_url,
            "created_at": job.created_at.isoformat(),
        },
    }
    try:
        await notifier.publish(principal.tenant_id, event)
    except Exception:
        logger.exception("notifier.publish failed for job=%s", job.job_id)

    return JobFinalizeResponse(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        total_pages=job.total_pages or 0,
        color_pages=job.color_pages or 0,
        amount=job.amount or 0.0,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    base = select(models.PrintJob).where(models.PrintJob.tenant_id == principal.tenant_id)
    count_base = select(func.count()).select_from(models.PrintJob).where(
        models.PrintJob.tenant_id == principal.tenant_id
    )
    if status_filter:
        base = base.where(models.PrintJob.status == status_filter)
        count_base = count_base.where(models.PrintJob.status == status_filter)

    total = int(db.scalar(count_base) or 0)
    jobs = db.scalars(
        base.order_by(models.PrintJob.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return JobListResponse(
        jobs=[_job_to_summary(j) for j in jobs],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobSummary)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_tenant),
) -> JobSummary:
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    return _job_to_summary(job)


@router.get("/{job_id}/file-url", response_model=JobFileUrlResponse)
def get_job_file_url(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_agent),
    expires_in: int = Query(default=1800, ge=60, le=3600),
) -> JobFileUrlResponse:
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    if job.assets_deleted or not job.object_key:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Job assets have been cleaned up",
        )
    url = storage.presign_get(
        principal.tenant_id,
        job.object_key,
        expires_in=expires_in,
        download_filename=job.filename,
    )
    return JobFileUrlResponse(
        job_id=job.job_id, url=url, expires_in=expires_in, filename=job.filename
    )


@router.patch("/{job_id}/status", response_model=JobSummary)
def update_job_status(
    job_id: str,
    payload: JobStatusUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> JobSummary:
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    job = transition(db, job, payload.status, error_message=payload.error_message)
    return _job_to_summary(job)
