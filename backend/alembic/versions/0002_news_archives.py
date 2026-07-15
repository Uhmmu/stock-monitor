"""add news archives and quarterly financials

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("news_items_investigation_id_url_key", "news_items", type_="unique")
    op.add_column("news_items", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("news_items", sa.Column("external_id", sa.String(256), nullable=True))
    op.add_column("news_items", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.add_column("news_items", sa.Column("raw_content", sa.Text(), nullable=True))
    op.add_column("news_items", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("news_items", sa.Column("raw_payload", sa.JSON(), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary_model", sa.String(128), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary_input_hash", sa.String(64), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary_created_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE news_items SET provider = COALESCE(source, 'tavily'), fingerprint = md5(ticker || ':' || url) || md5(COALESCE(title, ''))")
    op.alter_column("news_items", "provider", nullable=False)
    op.alter_column("news_items", "fingerprint", nullable=False)
    op.create_index("ix_news_items_provider", "news_items", ["provider"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_unique_constraint("uq_news_items_fingerprint", "news_items", ["fingerprint"])

    op.create_table(
        "daily_news_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("included_news_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_news_ids", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", "market_date"),
    )
    op.create_index("ix_daily_news_archives_ticker", "daily_news_archives", ["ticker"])
    op.create_index("ix_daily_news_archives_market_date", "daily_news_archives", ["market_date"])

    op.create_table(
        "quarterly_financials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(8), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("eps", sa.Float(), nullable=True),
        sa.Column("net_income", sa.Float(), nullable=True),
        sa.Column("gross_margin", sa.Float(), nullable=True),
        sa.Column("operating_cash_flow", sa.Float(), nullable=True),
        sa.Column("free_cash_flow", sa.Float(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", "fiscal_year", "fiscal_period"),
    )
    op.create_index("ix_quarterly_financials_ticker", "quarterly_financials", ["ticker"])
    op.create_index("ix_quarterly_financials_period_end", "quarterly_financials", ["period_end"])


def downgrade():
    op.drop_table("quarterly_financials")
    op.drop_table("daily_news_archives")
    op.drop_constraint("uq_news_items_fingerprint", "news_items", type_="unique")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_provider", table_name="news_items")
    for column in (
        "ai_summary_created_at", "ai_summary_input_hash", "ai_summary_model", "ai_summary",
        "raw_payload", "image_url", "raw_content", "fingerprint", "external_id", "provider",
    ):
        op.drop_column("news_items", column)
    op.create_unique_constraint("news_items_investigation_id_url_key", "news_items", ["investigation_id", "url"])
