from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PrinterCapabilities(BaseModel):
    supports_color: Optional[bool] = None
    supports_duplex: Optional[bool] = None


class PrinterRegisterRequest(BaseModel):
    printer_id: str = Field(min_length=1, max_length=120)
    printer_name: str = Field(min_length=1, max_length=120)
    is_default: bool = False
    capabilities: PrinterCapabilities = PrinterCapabilities()


class PrinterOut(BaseModel):
    printer_id: str
    printer_name: str
    is_default: bool
    is_active: bool
    is_online: bool
    last_heartbeat: Optional[datetime] = None
    supports_color: Optional[bool] = None
    supports_duplex: Optional[bool] = None
    created_at: datetime


class PrinterListResponse(BaseModel):
    printers: List[PrinterOut]
