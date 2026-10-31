"""add durable ingestion jobs and deleting document state

Revision ID: 0004_ingestion_jobs
Revises: 0003_documents
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_ingestion_jobs"
down_revision = "0003_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("ck_documents_status", type_="check")
        batch.create_check_constraint(
            "ck_documents_status",
            "status IN ('uploaded', 'queued', 'processing', 'completed', 'failed', 'deleting')",
        )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed')", name="ck_ingestion_jobs_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ingestion_jobs_attempt_count"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_ingestion_jobs_document_id"),
        sa.UniqueConstraint("task_id", name="uq_ingestion_jobs_task_id"),
    )
    op.create_index("ix_ingestion_jobs_owner_id", "ingestion_jobs", ["owner_id"], unique=False)
    op.create_index("ix_ingestion_jobs_status_dispatch", "ingestion_jobs", ["status", "dispatched_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status_dispatch", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_owner_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("ck_documents_status", type_="check")
        batch.create_check_constraint(
            "ck_documents_status", "status IN ('uploaded', 'processing', 'completed', 'failed')"
        )
