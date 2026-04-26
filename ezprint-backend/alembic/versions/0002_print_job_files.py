"""Add print job files for multi-document jobs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_job_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("print_job_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("page_range", sa.String(length=50), nullable=True),
        sa.Column("copies", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("page_size", sa.String(length=20), nullable=False, server_default="A4"),
        sa.Column("orientation", sa.String(length=20), nullable=False, server_default="Portrait"),
        sa.Column("print_side", sa.String(length=20), nullable=False, server_default="Single"),
        sa.Column("color_mode", sa.String(length=20), nullable=False, server_default="Black & White"),
        sa.Column("layout_pages", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("layout_type", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("color_pages", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["print_job_id"], ["print_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
        sa.UniqueConstraint("print_job_id", "sort_order", name="uq_print_job_files_order"),
    )
    op.create_index("ix_print_job_files_print_job_id", "print_job_files", ["print_job_id"])
    op.create_index("ix_print_job_files_tenant_id", "print_job_files", ["tenant_id"])
    op.create_index(
        "ix_print_job_files_tenant_job",
        "print_job_files",
        ["tenant_id", "print_job_id"],
    )

    print_jobs = sa.table(
        "print_jobs",
        sa.column("id", sa.Integer),
        sa.column("tenant_id", sa.String),
        sa.column("filename", sa.String),
        sa.column("object_key", sa.String),
        sa.column("file_size", sa.Integer),
        sa.column("file_type", sa.String),
        sa.column("page_range", sa.String),
        sa.column("copies", sa.Integer),
        sa.column("page_size", sa.String),
        sa.column("orientation", sa.String),
        sa.column("print_side", sa.String),
        sa.column("color_mode", sa.String),
        sa.column("layout_pages", sa.Integer),
        sa.column("layout_type", sa.String),
        sa.column("total_pages", sa.Integer),
        sa.column("color_pages", sa.Integer),
        sa.column("amount", sa.Float),
        sa.column("created_at", sa.DateTime),
    )
    files = sa.table(
        "print_job_files",
        sa.column("file_id", sa.String),
        sa.column("print_job_id", sa.Integer),
        sa.column("tenant_id", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("filename", sa.String),
        sa.column("object_key", sa.String),
        sa.column("file_size", sa.Integer),
        sa.column("file_type", sa.String),
        sa.column("page_range", sa.String),
        sa.column("copies", sa.Integer),
        sa.column("page_size", sa.String),
        sa.column("orientation", sa.String),
        sa.column("print_side", sa.String),
        sa.column("color_mode", sa.String),
        sa.column("layout_pages", sa.Integer),
        sa.column("layout_type", sa.String),
        sa.column("total_pages", sa.Integer),
        sa.column("color_pages", sa.Integer),
        sa.column("amount", sa.Float),
        sa.column("uploaded_at", sa.DateTime),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.select(print_jobs)).mappings().all()
    for row in rows:
        if not row["object_key"]:
            continue
        bind.execute(
            files.insert().values(
                file_id=str(uuid.uuid4()),
                print_job_id=row["id"],
                tenant_id=row["tenant_id"],
                sort_order=0,
                filename=row["filename"],
                object_key=row["object_key"],
                file_size=row["file_size"],
                file_type=row["file_type"],
                page_range=row["page_range"],
                copies=row["copies"],
                page_size=row["page_size"],
                orientation=row["orientation"],
                print_side=row["print_side"],
                color_mode=row["color_mode"],
                layout_pages=row["layout_pages"],
                layout_type=row["layout_type"],
                total_pages=row["total_pages"],
                color_pages=row["color_pages"],
                amount=row["amount"],
                uploaded_at=row["created_at"],
            )
        )


def downgrade() -> None:
    op.drop_index("ix_print_job_files_tenant_job", table_name="print_job_files")
    op.drop_index("ix_print_job_files_tenant_id", table_name="print_job_files")
    op.drop_index("ix_print_job_files_print_job_id", table_name="print_job_files")
    op.drop_table("print_job_files")
