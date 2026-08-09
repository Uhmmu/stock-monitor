"""persist normalized news content and structured AI enrichment

Revision ID: 0050_news_enrichment
Revises: 0049_realtime_market_data
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0050_news_enrichment"
down_revision = "0049_realtime_market_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("news_items") as batch_op:
        batch_op.add_column(sa.Column("article_content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("article_content_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("content_final_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("content_fetch_method", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("content_fetch_status", sa.String(length=16), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("content_fetch_quality", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("content_fetched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("content_fetch_error_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("ai_analysis", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("ai_event_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("ai_sentiment", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("ai_importance", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ai_market_impact", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_summary_version", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("ai_summary_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("ai_summary_last_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("ai_summary_next_retry_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("ai_summary_status", server_default="pending", existing_type=sa.String(length=16), existing_nullable=False)
        batch_op.create_index("ix_news_items_article_content_hash", ["article_content_hash"])
        batch_op.create_index("ix_news_items_content_fetch_status", ["content_fetch_status"])
        batch_op.create_index("ix_news_items_ai_event_type", ["ai_event_type"])
        batch_op.create_index("ix_news_items_ai_sentiment", ["ai_sentiment"])
        batch_op.create_index("ix_news_items_ai_importance", ["ai_importance"])
        batch_op.create_index("ix_news_items_ai_summary_next_retry_at", ["ai_summary_next_retry_at"])


def downgrade() -> None:
    with op.batch_alter_table("news_items") as batch_op:
        batch_op.drop_index("ix_news_items_ai_summary_next_retry_at")
        batch_op.drop_index("ix_news_items_ai_importance")
        batch_op.drop_index("ix_news_items_ai_sentiment")
        batch_op.drop_index("ix_news_items_ai_event_type")
        batch_op.drop_index("ix_news_items_content_fetch_status")
        batch_op.drop_index("ix_news_items_article_content_hash")
        batch_op.alter_column("ai_summary_status", server_default="idle", existing_type=sa.String(length=16), existing_nullable=False)
        batch_op.drop_column("ai_summary_next_retry_at")
        batch_op.drop_column("ai_summary_last_attempt_at")
        batch_op.drop_column("ai_summary_attempts")
        batch_op.drop_column("ai_summary_version")
        batch_op.drop_column("ai_market_impact")
        batch_op.drop_column("ai_importance")
        batch_op.drop_column("ai_sentiment")
        batch_op.drop_column("ai_event_type")
        batch_op.drop_column("ai_analysis")
        batch_op.drop_column("content_fetch_error_code")
        batch_op.drop_column("content_fetched_at")
        batch_op.drop_column("content_fetch_quality")
        batch_op.drop_column("content_fetch_status")
        batch_op.drop_column("content_fetch_method")
        batch_op.drop_column("content_final_url")
        batch_op.drop_column("article_content_hash")
        batch_op.drop_column("article_content")
