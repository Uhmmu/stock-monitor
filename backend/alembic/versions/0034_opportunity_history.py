"""add opportunity discovery history

Revision ID: 0034_opportunity_history
Revises: 0033_user_price_alerts
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_opportunity_history"
down_revision = "0033_user_price_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_discovery_settings",
        sa.Column("discovery_mode", sa.String(length=32), server_default="search_local", nullable=False),
    )
    op.add_column(
        "stock_discovery_runs",
        sa.Column("discovery_mode", sa.String(length=32), server_default="search_local", nullable=False),
    )
    op.create_table(
        "opportunity_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("query_context", sa.JSON(), nullable=False),
        sa.Column("market_condition", sa.Text(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("search_source", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["stock_discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_opportunity_history_user_created",
        "opportunity_history",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_opportunity_history_user_id", "opportunity_history", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_opportunity_history_user_id", table_name="opportunity_history")
    op.drop_index("ix_opportunity_history_user_created", table_name="opportunity_history")
    op.drop_table("opportunity_history")
    op.drop_column("stock_discovery_runs", "discovery_mode")
    op.drop_column("stock_discovery_settings", "discovery_mode")
