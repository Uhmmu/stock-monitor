"""add durable investment calendar sync telemetry

Revision ID: 0035_calendar_sync_runs
Revises: 0034_opportunity_history
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_calendar_sync_runs"
down_revision = "0034_opportunity_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment_calendar_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracked_symbols", sa.Integer(), nullable=False),
        sa.Column("successful_symbols", sa.Integer(), nullable=False),
        sa.Column("events_seen", sa.Integer(), nullable=False),
        sa.Column("active_future_events", sa.Integer(), nullable=False),
        sa.Column("future_symbol_count", sa.Integer(), nullable=False),
        sa.Column("provider_counts", sa.JSON(), nullable=False),
        sa.Column("failures", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investment_calendar_sync_runs_status",
        "investment_calendar_sync_runs",
        ["status"],
    )
    op.create_index(
        "ix_investment_calendar_sync_runs_started_at",
        "investment_calendar_sync_runs",
        ["started_at"],
    )
    op.create_index(
        "ix_calendar_sync_runs_status_started",
        "investment_calendar_sync_runs",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("investment_calendar_sync_runs")
