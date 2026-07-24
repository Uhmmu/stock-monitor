"""add portfolio benchmark comparison settings

Revision ID: 0031_portfolio_benchmark
Revises: 0030_manual_stock_discovery
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_portfolio_benchmark"
down_revision = "0030_manual_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portfolios", sa.Column("benchmark_start_date", sa.Date(), nullable=True))
    op.add_column("portfolios", sa.Column("benchmark_portfolio_return_percent", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolios", "benchmark_portfolio_return_percent")
    op.drop_column("portfolios", "benchmark_start_date")
