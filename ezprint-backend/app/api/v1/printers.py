"""Printer registration + listing.

Online/offline status comes from the WebSocket heartbeat handler in
`app.ws.agent`, not from this REST surface; this module only handles
the tenant's persistent printer config.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.printers import (
    PrinterListResponse,
    PrinterOut,
    PrinterRegisterRequest,
)
from app.tenancy.deps import (
    Principal,
    require_shopkeeper_or_agent,
)

router = APIRouter()


def _to_out(p: models.Printer) -> PrinterOut:
    return PrinterOut(
        printer_id=p.printer_id,
        printer_name=p.printer_name,
        is_default=p.is_default,
        is_active=p.is_active,
        is_online=p.is_online,
        last_heartbeat=p.last_heartbeat,
        supports_color=p.supports_color,
        supports_duplex=p.supports_duplex,
        created_at=p.created_at,
    )


@router.get("", response_model=PrinterListResponse)
def list_printers(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> PrinterListResponse:
    rows = db.scalars(
        select(models.Printer)
        .where(models.Printer.tenant_id == principal.tenant_id)
        .order_by(models.Printer.is_default.desc(), models.Printer.created_at.asc())
    ).all()
    return PrinterListResponse(printers=[_to_out(p) for p in rows])


@router.post("", response_model=PrinterOut, status_code=201)
def register_printer(
    payload: PrinterRegisterRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> PrinterOut:
    existing = db.scalars(
        select(models.Printer).where(
            models.Printer.tenant_id == principal.tenant_id,
            models.Printer.printer_id == payload.printer_id,
        )
    ).first()
    if existing:
        existing.printer_name = payload.printer_name
        existing.is_default = payload.is_default
        existing.supports_color = payload.capabilities.supports_color
        existing.supports_duplex = payload.capabilities.supports_duplex
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return _to_out(existing)

    if payload.is_default:
        # Demote any other default printer for this tenant.
        db.query(models.Printer).filter(
            models.Printer.tenant_id == principal.tenant_id,
            models.Printer.is_default.is_(True),
        ).update({models.Printer.is_default: False})

    printer = models.Printer(
        tenant_id=principal.tenant_id,
        printer_id=payload.printer_id,
        printer_name=payload.printer_name,
        is_default=payload.is_default,
        supports_color=payload.capabilities.supports_color,
        supports_duplex=payload.capabilities.supports_duplex,
    )
    db.add(printer)
    db.commit()
    db.refresh(printer)
    return _to_out(printer)


@router.delete("/{printer_id}", status_code=204)
def delete_printer(
    printer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> None:
    printer = db.scalars(
        select(models.Printer).where(
            models.Printer.tenant_id == principal.tenant_id,
            models.Printer.printer_id == printer_id,
        )
    ).first()
    if not printer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Printer not found")
    db.delete(printer)
    db.commit()
