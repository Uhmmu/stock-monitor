"""add sec_events summary_* columns (Haiku 中文翻译+总结)

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sec_events", sa.Column("summary_zh", sa.Text(), nullable=True))
    op.add_column("sec_events", sa.Column("summary_model", sa.String(length=128), nullable=True))
    op.add_column("sec_events", sa.Column("summary_input_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "sec_events",
        sa.Column("summary_status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "sec_events",
        sa.Column("summary_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("sec_events", sa.Column("summary_last_error", sa.Text(), nullable=True))
    op.add_column(
        "sec_events",
        sa.Column("summary_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sec_events_summary_status", "sec_events", ["summary_status"])
    op.create_index("ix_sec_events_summary_next_retry_at", "sec_events", ["summary_next_retry_at"])


def downgrade():
    op.drop_index("ix_sec_events_summary_next_retry_at", table_name="sec_events")
    op.drop_index("ix_sec_events_summary_status", table_name="sec_events")
    op.drop_column("sec_events", "summary_next_retry_at")
    op.drop_column("sec_events", "summary_last_error")
    op.drop_column("sec_events", "summary_attempts")
    op.drop_column("sec_events", "summary_status")
    op.drop_column("sec_events", "summary_input_hash")
    op.drop_column("sec_events", "summary_model")
    op.drop_column("sec_events", "summary_zh")
