"""add sec_events, sec_financial_periods, sec_insider_trades tables

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sec_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("form", sa.String(length=16), nullable=False),
        sa.Column("item_code", sa.String(length=8), nullable=False),
        sa.Column("item_label", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False, server_default="normal"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("filing_url", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("accession_number", "item_code"),
    )
    op.create_index("ix_sec_events_ticker", "sec_events", ["ticker"])
    op.create_index("ix_sec_events_priority", "sec_events", ["priority"])
    op.create_index("ix_sec_events_filing_date", "sec_events", ["filing_date"])

    op.create_table(
        "sec_financial_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("form", sa.String(length=16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("filed_at", sa.Date(), nullable=True),
        sa.Column("accession_number", sa.String(length=32), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("net_income", sa.Float(), nullable=True),
        sa.Column("operating_income", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("eps_basic", sa.Float(), nullable=True),
        sa.Column("eps_diluted", sa.Float(), nullable=True),
        sa.Column("cash_and_equivalents", sa.Float(), nullable=True),
        sa.Column("total_debt", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.Float(), nullable=True),
        sa.Column("operating_cash_flow", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="sec_edgar"),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "fiscal_year", "fiscal_period", "form"),
    )
    op.create_index("ix_sec_financial_periods_ticker", "sec_financial_periods", ["ticker"])
    op.create_index("ix_sec_financial_periods_period_end", "sec_financial_periods", ["period_end"])

    op.create_table(
        "sec_insider_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("insider_name", sa.String(length=128), nullable=False),
        sa.Column("insider_title", sa.String(length=128), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("transaction_code", sa.String(length=8), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("shares_owned_after", sa.Float(), nullable=True),
        sa.Column("flag", sa.String(length=16), nullable=True),
        sa.Column("filing_url", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "accession_number", "insider_name", "transaction_date", "transaction_code", "shares"
        ),
    )
    op.create_index("ix_sec_insider_trades_ticker", "sec_insider_trades", ["ticker"])
    op.create_index("ix_sec_insider_trades_accession_number", "sec_insider_trades", ["accession_number"])
    op.create_index("ix_sec_insider_trades_transaction_date", "sec_insider_trades", ["transaction_date"])


def downgrade():
    op.drop_index("ix_sec_insider_trades_transaction_date", table_name="sec_insider_trades")
    op.drop_index("ix_sec_insider_trades_accession_number", table_name="sec_insider_trades")
    op.drop_index("ix_sec_insider_trades_ticker", table_name="sec_insider_trades")
    op.drop_table("sec_insider_trades")
    op.drop_index("ix_sec_financial_periods_period_end", table_name="sec_financial_periods")
    op.drop_index("ix_sec_financial_periods_ticker", table_name="sec_financial_periods")
    op.drop_table("sec_financial_periods")
    op.drop_index("ix_sec_events_filing_date", table_name="sec_events")
    op.drop_index("ix_sec_events_priority", table_name="sec_events")
    op.drop_index("ix_sec_events_ticker", table_name="sec_events")
    op.drop_table("sec_events")
