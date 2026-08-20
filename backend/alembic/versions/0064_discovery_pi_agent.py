"""pi agent discovery engine: funnel stats and agent events

Revision ID: 0064_discovery_pi_agent
Revises: 0063_valuation_history
"""

from alembic import op
import sqlalchemy as sa


revision = "0064_discovery_pi_agent"
down_revision = "0063_valuation_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_discovery_runs",
        sa.Column("funnel_stats", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "stock_discovery_agent_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_stock_discovery_agent_events_run", "stock_discovery_agent_events", ["run_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_stock_discovery_agent_events_run", table_name="stock_discovery_agent_events")
    op.drop_table("stock_discovery_agent_events")
    op.drop_column("stock_discovery_runs", "funnel_stats")
