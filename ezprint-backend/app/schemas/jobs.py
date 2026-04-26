from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

JobStatus = Literal[
    "AwaitingUpload",
    "Queued",
    "Processing",
    "Printing",
    "Completed",
    "Failed",
    "Cancelled",
]


class JobDocumentCreate(BaseModel):
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


class JobCreateRequest(BaseModel):
    filename: Optional[str] = Field(default=None, min_length=1, max_length=255)
    file_type: Optional[str] = Field(default=None, min_length=1, max_length=16)
    file_size: Optional[int] = Field(default=None, ge=0)
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
    files: Optional[List[JobDocumentCreate]] = None

    @model_validator(mode="after")
    def require_legacy_file_or_files(self) -> "JobCreateRequest":
        if self.files:
            return self
        if self.filename and self.file_type and self.file_size is not None:
            return self
        raise ValueError("Either files or filename/file_type/file_size is required")


class JobDocumentUploadSlot(BaseModel):
    file_id: str
    filename: str
    file_type: str
    file_size: int
    object_key: str
    upload_url: str
    upload_url_expires_in: int
    upload_method: str = "PUT"


class JobCreateResponse(BaseModel):
    job_id: str
    tenant_id: str
    object_key: str
    upload_url: str
    upload_url_expires_in: int
    upload_method: str = "PUT"
    files: List[JobDocumentUploadSlot] = Field(default_factory=list)


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


class JobDocumentSummary(BaseModel):
    file_id: str
    filename: str
    file_type: str
    file_size: int
    sort_order: int
    copies: int
    page_size: str
    orientation: str
    print_side: str
    color_mode: str
    layout_pages: int
    layout_type: str
    page_range: Optional[str] = None
    total_pages: Optional[int] = None
    color_pages: Optional[int] = None
    amount: Optional[float] = None


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
    page_range: Optional[str] = None
    amount: Optional[float] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    document_count: int = 1
    files: List[JobDocumentSummary] = Field(default_factory=list)


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


class JobDocumentFileUrl(BaseModel):
    file_id: str
    filename: str
    file_type: str
    file_size: int
    sort_order: int
    url: str
    expires_in: int
    copies: int
    page_size: str
    orientation: str
    print_side: str
    color_mode: str
    layout_pages: int
    layout_type: str
    page_range: Optional[str] = None


class JobFilesUrlResponse(BaseModel):
    job_id: str
    files: List[JobDocumentFileUrl]
