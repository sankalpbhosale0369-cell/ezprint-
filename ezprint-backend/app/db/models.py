"""SQLAlchemy models.

Ported from `shared/database.py` in the original EzPrint repo and extended with
a `tenants` table. Every tenant-owned row carries a `tenant_id` FK and is
indexed by it; application code MUST filter by the tenant resolved from auth
context (never from the request body).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    """One tenant == one print shop."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    shopkeepers: Mapped[list["Shopkeeper"]] = relationship(back_populates="tenant")


class Shopkeeper(Base):
    """Human login for a tenant. (Future: many shopkeepers per tenant.)"""
    __tablename__ = "shopkeepers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    shop_name: Mapped[str] = mapped_column(String(120), nullable=False)
    shop_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shopkeeper_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    qr_code_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="shopkeepers")


class AgentToken(Base):
    """Long-lived provisioning token for a Windows agent.

    Issued once per shop by an admin (or at tenant creation), shown to the
    shopkeeper, then exchanged for a short-lived `agent` JWT at runtime.
    """
    __tablename__ = "agent_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stored as a bcrypt-style hash; the raw token is shown only once to the operator.
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    customer_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # S3 object key inside the ezprint bucket (e.g. tenants/<tid>/jobs/<jid>/original/<filename>)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)

    page_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    page_size: Mapped[str] = mapped_column(String(20), default="A4", nullable=False)
    orientation: Mapped[str] = mapped_column(String(20), default="Portrait", nullable=False)
    print_side: Mapped[str] = mapped_column(String(20), default="Single", nullable=False)
    color_mode: Mapped[str] = mapped_column(String(20), default="Black & White", nullable=False)
    layout_pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    layout_type: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    total_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    color_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="AwaitingUpload", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Lifecycle helpers (used by the cleanup worker)
    assets_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assets_delete_scheduled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assets_delete_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_print_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_print_jobs_created_at", "created_at"),
    )

    files: Mapped[list["PrintJobFile"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="PrintJobFile.sort_order",
    )


class PrintJobFile(Base):
    __tablename__ = "print_job_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    print_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("print_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)

    page_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    page_size: Mapped[str] = mapped_column(String(20), default="A4", nullable=False)
    orientation: Mapped[str] = mapped_column(String(20), default="Portrait", nullable=False)
    print_side: Mapped[str] = mapped_column(String(20), default="Single", nullable=False)
    color_mode: Mapped[str] = mapped_column(String(20), default="Black & White", nullable=False)
    layout_pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    layout_type: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)

    total_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    color_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[PrintJob] = relationship(back_populates="files")

    __table_args__ = (
        UniqueConstraint("print_job_id", "sort_order", name="uq_print_job_files_order"),
        Index("ix_print_job_files_tenant_job", "tenant_id", "print_job_id"),
    )


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    printer_id: Mapped[str] = mapped_column(String(120), nullable=False)
    printer_name: Mapped[str] = mapped_column(String(120), nullable=False)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    supports_color: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    supports_duplex: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    duplex_override: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    color_override: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    bw_single_override: Mapped[Optional[bool]] = mapped_column(Boolean, default=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "printer_id", name="uq_printers_tenant_printer"),
        Index("ix_printers_tenant_active", "tenant_id", "is_active"),
    )


class ShopPricing(Base):
    __tablename__ = "shop_pricing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    bw_single: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    bw_double: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    color_single: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    color_double: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class License(Base):
    __tablename__ = "licenses"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shop_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="trial", nullable=False)
    trial_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    trial_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    component: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
