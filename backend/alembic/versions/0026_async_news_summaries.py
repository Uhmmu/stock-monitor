"""run news AI summaries as persistent background jobs

Revision ID: 0026_async_news_summaries
Revises: 0025_portfolio
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_async_news_summaries"
down_revision = "0025_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_items",
        sa.Column("ai_summary_status", sa.String(length=16), nullable=False, server_default="idle"),
    )
    op.add_column("news_items", sa.Column("ai_summary_request_id", sa.String(length=36), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news_items", sa.Column("ai_summary_last_error", sa.Text(), nullable=True))
    op.create_index("ix_news_items_ai_summary_status", "news_items", ["ai_summary_status"])
    op.create_index("ix_news_items_ai_summary_request_id", "news_items", ["ai_summary_request_id"])
    op.execute("UPDATE news_items SET ai_summary_status = 'completed' WHERE ai_summary IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_news_items_ai_summary_request_id", table_name="news_items")
    op.drop_index("ix_news_items_ai_summary_status", table_name="news_items")
    op.drop_column("news_items", "ai_summary_last_error")
    op.drop_column("news_items", "ai_summary_requested_at")
    op.drop_column("news_items", "ai_summary_request_id")
    op.drop_column("news_items", "ai_summary_status")
