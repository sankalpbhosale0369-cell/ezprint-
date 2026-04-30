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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import models
from app.db.session import get_db
from app.schemas.jobs import (
    JobDocumentCreate,
    JobDocumentFileUrl,
    JobDocumentSummary,
    JobDocumentUploadSlot,
    JobCreateRequest,
    JobCreateResponse,
    JobFileUrlResponse,
    JobFilesUrlResponse,
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
        select(models.PrintJob)
        .options(selectinload(models.PrintJob.files))
        .where(
            models.PrintJob.job_id == job_id,
            models.PrintJob.tenant_id == tenant_id,
        )
    ).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _job_to_summary(job: models.PrintJob) -> JobSummary:
    files = [_job_file_to_summary(f) for f in sorted(job.files, key=lambda f: f.sort_order)]
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
        document_count=len(files) or 1,
        files=files,
    )


def _job_file_to_summary(file: models.PrintJobFile) -> JobDocumentSummary:
    return JobDocumentSummary(
        file_id=file.file_id,
        filename=file.filename,
        file_type=file.file_type,
        file_size=file.file_size,
        sort_order=file.sort_order,
        copies=file.copies,
        page_size=file.page_size,
        orientation=file.orientation,
        print_side=file.print_side,
        color_mode=file.color_mode,
        layout_pages=file.layout_pages,
        layout_type=file.layout_type,
        page_range=file.page_range,
        total_pages=file.total_pages,
        color_pages=file.color_pages,
        amount=file.amount,
    )


def _payload_documents(payload: JobCreateRequest) -> list[JobDocumentCreate]:
    if payload.files:
        return payload.files
    return [
        JobDocumentCreate(
            filename=payload.filename or "document",
            file_type=payload.file_type or "pdf",
            file_size=payload.file_size or 0,
            copies=payload.copies,
            page_size=payload.page_size,
            orientation=payload.orientation,
            print_side=payload.print_side,
            color_mode=payload.color_mode,
            layout_pages=payload.layout_pages,
            layout_type=payload.layout_type,
            page_range=payload.page_range,
        )
    ]


def _job_file_object_key(tenant_id: str, job_id: str, order: int, filename: str) -> str:
    return storage.original_key(tenant_id, job_id, f"{order + 1:03d}_{filename}")


def _document_url_response(
    tenant_id: str,
    job_id: str,
    file: models.PrintJobFile,
    expires_in: int,
) -> JobDocumentFileUrl:
    return JobDocumentFileUrl(
        file_id=file.file_id,
        filename=file.filename,
        file_type=file.file_type,
        file_size=file.file_size,
        sort_order=file.sort_order,
        url=storage.presign_get(
            tenant_id,
            file.object_key,
            expires_in=expires_in,
            download_filename=file.filename,
        ),
        expires_in=expires_in,
        copies=file.copies,
        page_size=file.page_size,
        orientation=file.orientation,
        print_side=file.print_side,
        color_mode=file.color_mode,
        layout_pages=file.layout_pages,
        layout_type=file.layout_type,
        page_range=file.page_range,
    )


@router.post("", response_model=JobCreateResponse, status_code=201)
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer_upload),
) -> JobCreateResponse:
    """Customer creates a job; we mint a tenant-scoped presigned PUT URL."""
    documents = _payload_documents(payload)
    first = documents[0]
    job = models.PrintJob(
        tenant_id=principal.tenant_id,
        filename=first.filename,
        file_type=first.file_type.lower().lstrip("."),
        file_size=sum(doc.file_size for doc in documents),
        copies=first.copies,
        page_size=first.page_size,
        orientation=first.orientation,
        print_side=first.print_side,
        color_mode=first.color_mode,
        layout_pages=first.layout_pages,
        layout_type=first.layout_type,
        page_range=first.page_range,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        status="AwaitingUpload",
        object_key="",  # populated below once we know job.job_id
    )
    db.add(job)
    db.flush()  # get auto-generated job_id

    upload_slots: list[JobDocumentUploadSlot] = []
    for idx, doc in enumerate(documents):
        object_key = _job_file_object_key(principal.tenant_id, job.job_id, idx, doc.filename)
        job_file = models.PrintJobFile(
            tenant_id=principal.tenant_id,
            sort_order=idx,
            filename=doc.filename,
            object_key=object_key,
            file_size=doc.file_size,
            file_type=doc.file_type.lower().lstrip("."),
            copies=doc.copies,
            page_size=doc.page_size,
            orientation=doc.orientation,
            print_side=doc.print_side,
            color_mode=doc.color_mode,
            layout_pages=doc.layout_pages,
            layout_type=doc.layout_type,
            page_range=doc.page_range,
        )
        job.files.append(job_file)
        if idx == 0:
            job.object_key = object_key
    db.commit()
    db.refresh(job)

    for job_file in sorted(job.files, key=lambda f: f.sort_order):
        presigned = storage.presign_put(
            principal.tenant_id, job_file.object_key, expires_in=900
        )
        upload_slots.append(
            JobDocumentUploadSlot(
                file_id=job_file.file_id,
                filename=job_file.filename,
                file_type=job_file.file_type,
                file_size=job_file.file_size,
                object_key=job_file.object_key,
                upload_url=presigned.url,
                upload_url_expires_in=presigned.expires_in,
            )
        )
    first_slot = upload_slots[0]
    return JobCreateResponse(
        job_id=job.job_id,
        tenant_id=principal.tenant_id,
        object_key=first_slot.object_key,
        upload_url=first_slot.upload_url,
        upload_url_expires_in=first_slot.upload_url_expires_in,
        files=upload_slots,
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
    job_file = sorted(job.files, key=lambda f: f.sort_order)[0] if job.files else None
    object_key = job_file.object_key if job_file else job.object_key
    storage.put_bytes(principal.tenant_id, object_key, data, content_type)
    if job_file:
        job_file.file_size = len(data)
        job_file.uploaded_at = datetime.utcnow()
        job.file_size = sum(f.file_size for f in job.files)
        db.commit()
    return Response(status_code=204)


@router.post("/{job_id}/files/{file_id}/upload", status_code=204)
async def upload_job_document_proxy(
    job_id: str,
    file_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer_upload),
) -> Response:
    """Customer uploads one document within a multi-document print job."""
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    if job.status != "AwaitingUpload":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is in status {job.status}, cannot upload",
        )
    job_file = next((f for f in job.files if f.file_id == file_id), None)
    if not job_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job document not found")
    data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    storage.put_bytes(principal.tenant_id, job_file.object_key, data, content_type)
    job_file.file_size = len(data)
    job_file.uploaded_at = datetime.utcnow()
    job.file_size = sum(f.file_size for f in job.files)
    db.commit()
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

    job_files = sorted(job.files, key=lambda f: f.sort_order)
    if not job_files:
        job_files = [
            models.PrintJobFile(
                tenant_id=principal.tenant_id,
                sort_order=0,
                filename=job.filename,
                object_key=job.object_key,
                file_size=job.file_size,
                file_type=job.file_type,
                copies=job.copies,
                page_size=job.page_size,
                orientation=job.orientation,
                print_side=job.print_side,
                color_mode=job.color_mode,
                layout_pages=job.layout_pages,
                layout_type=job.layout_type,
                page_range=job.page_range,
            )
        ]
        job.files.extend(job_files)

    total_size = 0
    total_pages = 0
    color_pages = 0
    amount = 0.0
    for job_file in job_files:
        try:
            head = storage.head(principal.tenant_id, job_file.object_key)
            actual_size = int(head.get("ContentLength", 0))
            obj = storage.internal_client.get_object(Bucket=storage.bucket, Key=job_file.object_key)
            data: bytes = obj["Body"].read()
        except Exception as exc:
            logger.exception("finalize_job failed reading object file_id=%s", job_file.file_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Upload not found in storage for {job_file.filename}: {exc}",
            )

        stats = classify_bytes_for_job(job_file.file_type, data, job_file.page_range)
        doc_amount = calculate_amount(
            rates,
            JobBillingInputs(
                total_pages=stats.total_pages,
                color_pages=stats.color_pages,
                copies=job_file.copies,
                color_mode=job_file.color_mode,
                print_side=job_file.print_side,
            ),
        )
        job_file.file_size = actual_size or job_file.file_size
        job_file.total_pages = stats.total_pages
        job_file.color_pages = stats.color_pages
        job_file.amount = doc_amount
        total_size += job_file.file_size
        total_pages += stats.total_pages
        color_pages += stats.color_pages
        amount += doc_amount

    first_file = job_files[0]
    job.filename = first_file.filename if len(job_files) == 1 else f"{len(job_files)} documents"
    job.object_key = first_file.object_key
    job.file_type = first_file.file_type if len(job_files) == 1 else "multi"
    job.file_size = total_size
    job.copies = first_file.copies
    job.page_size = first_file.page_size
    job.orientation = first_file.orientation
    job.print_side = first_file.print_side
    job.color_mode = first_file.color_mode
    job.layout_pages = first_file.layout_pages
    job.layout_type = first_file.layout_type
    job.page_range = first_file.page_range
    job.total_pages = total_pages
    job.color_pages = color_pages
    job.amount = round(amount, 2)
    db.commit()

    # Advance state machine: AwaitingUpload -> Queued. This also broadcasts
    # a `job_status` event on the tenant channel.
    job = transition(db, job, "Queued")

    # Push the agent-facing new_job payload (includes a short-lived presigned GET).
    document_urls = [
        _document_url_response(principal.tenant_id, job.job_id, file, 1800).model_dump()
        for file in sorted(job.files, key=lambda f: f.sort_order)
    ]
    download_url = document_urls[0]["url"] if document_urls else storage.presign_get(
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
            "document_count": len(document_urls) or 1,
            "documents": document_urls,
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
    first_file = sorted(job.files, key=lambda f: f.sort_order)[0] if job.files else None
    object_key = first_file.object_key if first_file else job.object_key
    filename = first_file.filename if first_file else job.filename
    if job.assets_deleted or not object_key:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Job assets have been cleaned up",
        )
    url = storage.presign_get(
        principal.tenant_id,
        object_key,
        expires_in=expires_in,
        download_filename=filename,
    )
    return JobFileUrlResponse(
        job_id=job.job_id, url=url, expires_in=expires_in, filename=filename
    )


@router.get("/{job_id}/files", response_model=JobFilesUrlResponse)
def get_job_files(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_agent),
    expires_in: int = Query(default=1800, ge=60, le=3600),
) -> JobFilesUrlResponse:
    job = _get_job_for_tenant(db, job_id, principal.tenant_id)
    if job.assets_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Job assets have been cleaned up",
        )
    # Explicit query so we always return every row in `print_job_files`, even if
    # the ORM relationship is stale or not loaded the way callers expect.
    files = list(
        db.scalars(
            select(models.PrintJobFile)
            .where(
                models.PrintJobFile.print_job_id == job.id,
                models.PrintJobFile.tenant_id == principal.tenant_id,
            )
            .order_by(models.PrintJobFile.sort_order)
        ).all()
    )
    if not files and job.object_key:
        url = storage.presign_get(
            principal.tenant_id,
            job.object_key,
            expires_in=expires_in,
            download_filename=job.filename,
        )
        return JobFilesUrlResponse(
            job_id=job.job_id,
            files=[
                JobDocumentFileUrl(
                    file_id=job.job_id,
                    filename=job.filename,
                    file_type=job.file_type,
                    file_size=job.file_size,
                    sort_order=0,
                    url=url,
                    expires_in=expires_in,
                    copies=job.copies,
                    page_size=job.page_size,
                    orientation=job.orientation,
                    print_side=job.print_side,
                    color_mode=job.color_mode,
                    layout_pages=job.layout_pages,
                    layout_type=job.layout_type,
                    page_range=job.page_range,
                )
            ],
        )
    return JobFilesUrlResponse(
        job_id=job.job_id,
        files=[
            _document_url_response(principal.tenant_id, job.job_id, file, expires_in)
            for file in files
        ],
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
