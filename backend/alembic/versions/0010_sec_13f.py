"""add sec_13f_holdings + sec_cusip_map (13F 机构季度持仓 + ticker↔CUSIP 映射)

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sec_13f_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("cusip", sa.String(length=9), nullable=False),
        sa.Column("manager_name", sa.String(length=200), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("put_call", sa.String(length=8), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "accession_number", "report_period"),
    )
    op.create_index("ix_sec_13f_holdings_ticker", "sec_13f_holdings", ["ticker"])
    op.create_index("ix_sec_13f_holdings_cusip", "sec_13f_holdings", ["cusip"])
    op.create_index("ix_sec_13f_holdings_report_period", "sec_13f_holdings", ["report_period"])

    op.create_table(
        "sec_cusip_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("cusip", sa.String(length=9), nullable=False),
        sa.Column("issuer_name", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="issuer_match"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "cusip"),
    )
    op.create_index("ix_sec_cusip_map_ticker", "sec_cusip_map", ["ticker"])
    op.create_index("ix_sec_cusip_map_cusip", "sec_cusip_map", ["cusip"])


def downgrade():
    op.drop_index("ix_sec_cusip_map_cusip", table_name="sec_cusip_map")
    op.drop_index("ix_sec_cusip_map_ticker", table_name="sec_cusip_map")
    op.drop_table("sec_cusip_map")
    op.drop_index("ix_sec_13f_holdings_report_period", table_name="sec_13f_holdings")
    op.drop_index("ix_sec_13f_holdings_cusip", table_name="sec_13f_holdings")
    op.drop_index("ix_sec_13f_holdings_ticker", table_name="sec_13f_holdings")
    op.drop_table("sec_13f_holdings")
