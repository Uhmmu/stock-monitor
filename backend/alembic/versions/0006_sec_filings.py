"""add sec_filings table

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sec_filings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("form", sa.String(length=16), nullable=False),
        sa.Column("form_label", sa.String(length=64), nullable=False),
        sa.Column("items", sa.String(length=128), nullable=True),
        sa.Column("event_labels", sa.JSON(), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False, server_default="normal"),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("primary_document", sa.Text(), nullable=True),
        sa.Column("filing_url", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "accession_number"),
    )
    op.create_index("ix_sec_filings_ticker", "sec_filings", ["ticker"])
    op.create_index("ix_sec_filings_form", "sec_filings", ["form"])
    op.create_index("ix_sec_filings_priority", "sec_filings", ["priority"])
    op.create_index("ix_sec_filings_filing_date", "sec_filings", ["filing_date"])


def downgrade():
    op.drop_index("ix_sec_filings_filing_date", table_name="sec_filings")
    op.drop_index("ix_sec_filings_priority", table_name="sec_filings")
    op.drop_index("ix_sec_filings_form", table_name="sec_filings")
    op.drop_index("ix_sec_filings_ticker", table_name="sec_filings")
    op.drop_table("sec_filings")
