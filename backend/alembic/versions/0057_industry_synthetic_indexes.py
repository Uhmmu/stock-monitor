"""add equal-weight leaf industry indexes

Revision ID: 0057_industry_synthetic_indexes
Revises: 0056_global_market_data
"""

from alembic import op
import sqlalchemy as sa


revision = "0057_industry_synthetic_indexes"
down_revision = "0056_global_market_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_synthetic_indexes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("index_value", sa.Float(), nullable=True),
        sa.Column("daily_return", sa.Float(), nullable=True),
        sa.Column("valid_constituents", sa.Integer(), nullable=False),
        sa.Column("expected_constituents", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("coverage_quality", sa.Float(), nullable=False),
        sa.Column("calculation_status", sa.String(32), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("methodology_version", sa.String(32), nullable=False, server_default="equal_weight_v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("node_id", "trading_date", name="uq_industry_synthetic_indexes_node_date"),
    )
    op.create_index("ix_industry_synthetic_indexes_node_id", "industry_synthetic_indexes", ["node_id"])
    op.create_index("ix_industry_synthetic_indexes_trading_date", "industry_synthetic_indexes", ["trading_date"])
    op.create_index("ix_industry_synthetic_indexes_calculation_status", "industry_synthetic_indexes", ["calculation_status"])
    op.create_index("ix_industry_synthetic_indexes_node_date", "industry_synthetic_indexes", ["node_id", "trading_date"])


def downgrade() -> None:
    for index in ("ix_industry_synthetic_indexes_node_date", "ix_industry_synthetic_indexes_calculation_status", "ix_industry_synthetic_indexes_trading_date", "ix_industry_synthetic_indexes_node_id"):
        op.drop_index(index, table_name="industry_synthetic_indexes")
    op.drop_table("industry_synthetic_indexes")
