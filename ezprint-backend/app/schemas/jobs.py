from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

JobStatus = Literal[
    "AwaitingUpload",
    "Queued",
    "Printing",
    "Completed",
    "Failed",
    "Cancelled",
]


class JobCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=16)
    file_size: int = Field(ge=0)
    copies: int = Field(ge=1, le=999, default=1)
    page_size: str = "A4"
    orientation: str = "Portrait"
    print_side: Literal["Single", "Double"] = "Single"
    color_mode: Literal["Color", "Black & White"] = "Black & White"
    layout_pages: int = 1
    layout_type: str = "normal"
    page_range: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class JobCreateResponse(BaseModel):
    job_id: str
    tenant_id: str
    object_key: str
    upload_url: str
    upload_url_expires_in: int
    upload_method: str = "PUT"


class JobFinalizeResponse(BaseModel):
    job_id: str
    status: JobStatus
    total_pages: int
    color_pages: int
    amount: float


class JobStatusUpdate(BaseModel):
    status: JobStatus
    printer_name: Optional[str] = None
    error_message: Optional[str] = None
    printed_pages: Optional[int] = None


class JobSummary(BaseModel):
    job_id: str
    filename: str
    file_type: str
    file_size: int
    status: JobStatus
    total_pages: Optional[int] = None
    color_pages: Optional[int] = None
    copies: int
    page_size: Optional[str] = None
    orientation: Optional[str] = None
    print_side: str
    color_mode: str
    layout_pages: Optional[int] = None
    layout_type: Optional[str] = None
    amount: Optional[float] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    jobs: List[JobSummary]
    total_count: int
    limit: int
    offset: int


class JobFileUrlResponse(BaseModel):
    job_id: str
    url: str
    expires_in: int
    filename: str
