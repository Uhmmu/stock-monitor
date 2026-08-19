"""add sec_eps_facts and stock_splits for historical valuation

Revision ID: 0063_valuation_history
Revises: 0062_auth_sessions
"""

from alembic import op
import sqlalchemy as sa


revision = "0063_valuation_history"
down_revision = "0062_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_eps_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(16), nullable=True),
        sa.Column("form", sa.String(16), nullable=False),
        sa.Column("accession_number", sa.String(32), nullable=True),
        sa.Column("first_filed", sa.Date(), nullable=False),
        sa.Column("eps", sa.Float(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="sec_xbrl_companyconcept"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "period_start", "period_end", name="uq_sec_eps_facts_period"),
    )
    op.create_index("ix_sec_eps_facts_ticker", "sec_eps_facts", ["ticker"])
    op.create_index("ix_sec_eps_facts_period_end", "sec_eps_facts", ["period_end"])
    op.create_index("ix_sec_eps_facts_ticker_filed", "sec_eps_facts", ["ticker", "first_filed"])

    op.create_table(
        "stock_splits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="yfinance"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "ex_date", name="uq_stock_splits_symbol_ex_date"),
    )
    op.create_index("ix_stock_splits_symbol", "stock_splits", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_stock_splits_symbol", table_name="stock_splits")
    op.drop_table("stock_splits")
    op.drop_index("ix_sec_eps_facts_ticker_filed", table_name="sec_eps_facts")
    op.drop_index("ix_sec_eps_facts_period_end", table_name="sec_eps_facts")
    op.drop_index("ix_sec_eps_facts_ticker", table_name="sec_eps_facts")
    op.drop_table("sec_eps_facts")
