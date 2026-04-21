"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "shopkeepers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("shop_name", sa.String(length=120), nullable=False),
        sa.Column("shop_address", sa.String(length=255), nullable=True),
        sa.Column("contact_number", sa.String(length=20), nullable=True),
        sa.Column("shopkeeper_name", sa.String(length=120), nullable=True),
        sa.Column("qr_code_path", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("shop_id", name="uq_shopkeepers_shop_id"),
        sa.UniqueConstraint("username", name="uq_shopkeepers_username"),
        sa.UniqueConstraint("email", name="uq_shopkeepers_email"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_shopkeepers_tenant_id", "shopkeepers", ["tenant_id"])

    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_tokens_tenant_id", "agent_tokens", ["tenant_id"])

    op.create_table(
        "print_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_ip", sa.String(length=45), nullable=True),
        sa.Column("customer_name", sa.String(length=120), nullable=True),
        sa.Column("customer_phone", sa.String(length=40), nullable=True),
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
        sa.Column("status", sa.String(length=20), nullable=False, server_default="AwaitingUpload"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("assets_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assets_delete_scheduled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assets_delete_attempted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("job_id", name="uq_print_jobs_job_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_print_jobs_tenant_id", "print_jobs", ["tenant_id"])
    op.create_index("ix_print_jobs_tenant_status", "print_jobs", ["tenant_id", "status"])
    op.create_index("ix_print_jobs_created_at", "print_jobs", ["created_at"])

    op.create_table(
        "printers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("printer_id", sa.String(length=120), nullable=False),
        sa.Column("printer_name", sa.String(length=120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("supports_color", sa.Boolean(), nullable=True),
        sa.Column("supports_duplex", sa.Boolean(), nullable=True),
        sa.Column("duplex_override", sa.Boolean(), nullable=True),
        sa.Column("color_override", sa.Boolean(), nullable=True),
        sa.Column("bw_single_override", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "printer_id", name="uq_printers_tenant_printer"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_printers_tenant_id", "printers", ["tenant_id"])
    op.create_index("ix_printers_tenant_active", "printers", ["tenant_id", "is_active"])

    op.create_table(
        "shop_pricing",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("bw_single", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("bw_double", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("color_single", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column("color_double", sa.Float(), nullable=False, server_default="8.0"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", name="uq_shop_pricing_tenant"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "licenses",
        sa.Column("device_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("shop_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="trial"),
        sa.Column("trial_start", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_licenses_tenant_id", "licenses", ["tenant_id"])

    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("component", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_system_logs_tenant_id", "system_logs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_system_logs_tenant_id", table_name="system_logs")
    op.drop_table("system_logs")
    op.drop_index("ix_licenses_tenant_id", table_name="licenses")
    op.drop_table("licenses")
    op.drop_table("shop_pricing")
    op.drop_index("ix_printers_tenant_active", table_name="printers")
    op.drop_index("ix_printers_tenant_id", table_name="printers")
    op.drop_table("printers")
    op.drop_index("ix_print_jobs_created_at", table_name="print_jobs")
    op.drop_index("ix_print_jobs_tenant_status", table_name="print_jobs")
    op.drop_index("ix_print_jobs_tenant_id", table_name="print_jobs")
    op.drop_table("print_jobs")
    op.drop_index("ix_agent_tokens_tenant_id", table_name="agent_tokens")
    op.drop_table("agent_tokens")
    op.drop_index("ix_shopkeepers_tenant_id", table_name="shopkeepers")
    op.drop_table("shopkeepers")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
