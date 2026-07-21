"""add yfinance financial statement snapshots

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "financial_statement_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("income_statement", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("balance_sheet", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("cash_flow", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(32), nullable=False, server_default="yfinance"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "frequency", "period_end"),
    )
    op.create_index("ix_financial_statement_snapshots_ticker", "financial_statement_snapshots", ["ticker"])
    op.create_index("ix_financial_statement_snapshots_frequency", "financial_statement_snapshots", ["frequency"])
    op.create_index("ix_financial_statement_snapshots_period_end", "financial_statement_snapshots", ["period_end"])


def downgrade():
    op.drop_table("financial_statement_snapshots")
