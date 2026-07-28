"""add unified portfolio analysis run history

Revision ID: 0036_portfolio_analysis_runs
Revises: 0035_calendar_sync_runs
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_portfolio_analysis_runs"
down_revision = "0035_calendar_sync_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("analysis_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("price_data_start_date", sa.Date(), nullable=True),
        sa.Column("price_data_end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_analysis_runs_portfolio_id", "portfolio_analysis_runs", ["portfolio_id"])
    op.create_index("ix_portfolio_analysis_runs_analysis_type", "portfolio_analysis_runs", ["analysis_type"])
    op.create_index("ix_portfolio_analysis_runs_status", "portfolio_analysis_runs", ["status"])
    op.create_index("ix_portfolio_analysis_runs_created_at", "portfolio_analysis_runs", ["created_at"])
    op.create_index("ix_portfolio_analysis_runs_portfolio_type_created", "portfolio_analysis_runs", ["portfolio_id", "analysis_type", "created_at"])


def downgrade() -> None:
    op.drop_table("portfolio_analysis_runs")
