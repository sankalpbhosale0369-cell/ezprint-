"""Preview conversion API for customer uploads."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.services.document_converter import (
    DocumentConversionError,
    convert_office_bytes_to_pdf,
)
from app.tenancy.deps import Principal, require_customer_upload

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/office-to-pdf")
async def office_to_pdf_preview(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_customer_upload),
) -> Response:
    """Convert a customer Word upload to PDF for preview rendering."""
    del principal  # auth dependency scopes this endpoint to valid upload sessions
    filename = file.filename or "document.docx"
    data = await file.read()
    try:
        pdf = convert_office_bytes_to_pdf(data, filename)
    except DocumentConversionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("office_to_pdf_preview failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document preview conversion failed",
        ) from exc

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )
