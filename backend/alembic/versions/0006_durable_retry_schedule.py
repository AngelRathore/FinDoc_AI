"""Persist ingestion retry eligibility for the PostgreSQL outbox.

Revision ID: 0006_durable_retry_schedule
Revises: 0005_persistent_conversations
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_durable_retry_schedule"
down_revision = "0005_persistent_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_ingestion_jobs_status_next_attempt", "ingestion_jobs", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status_next_attempt", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "next_attempt_at")
