"""Add market-news scope, deterministic ranking metadata and scope-aware uniqueness.

Revision ID: 0024_market_news
Revises: 0023_fmp_technical
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0024_market_news"
down_revision: str | None = "0023_fmp_technical"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("news_items", sa.Column("scope", sa.String(length=16), nullable=False, server_default="company"))
    op.add_column("news_items", sa.Column("topic", sa.String(length=64), nullable=True))
    op.add_column("news_items", sa.Column("importance_score", sa.Float(), nullable=True))
    op.add_column("news_items", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("news_items", sa.Column("cluster_key", sa.String(length=64), nullable=True))
    # Existing Marketaux unique indexes were global, preventing one relevant
    # article from appearing in both its company and market contexts.
    op.drop_index("uq_news_items_marketaux_external_id", table_name="news_items")
    op.drop_index("uq_news_items_marketaux_normalized_url", table_name="news_items")
    op.create_index("uq_news_items_marketaux_external_id", "news_items", ["scope", "external_id"], unique=True, postgresql_where=sa.text("provider = 'marketaux'"))
    op.create_index("uq_news_items_marketaux_normalized_url", "news_items", ["scope", "normalized_url"], unique=True, postgresql_where=sa.text("provider = 'marketaux'"))
    op.drop_constraint("uq_news_items_fingerprint", "news_items", type_="unique")
    op.create_unique_constraint("uq_news_items_scope_fingerprint", "news_items", ["scope", "fingerprint"])
    op.create_index("ix_news_items_scope_published", "news_items", ["scope", "published_at"])
    op.create_index("ix_news_items_ticker_published", "news_items", ["ticker", "published_at"])
    op.create_index("ix_news_items_cluster_key", "news_items", ["cluster_key"])

def downgrade() -> None:
    op.drop_index("ix_news_items_cluster_key", table_name="news_items")
    op.drop_index("ix_news_items_ticker_published", table_name="news_items")
    op.drop_index("ix_news_items_scope_published", table_name="news_items")
    op.drop_constraint("uq_news_items_scope_fingerprint", "news_items", type_="unique")
    op.drop_index("uq_news_items_marketaux_normalized_url", table_name="news_items")
    op.drop_index("uq_news_items_marketaux_external_id", table_name="news_items")
    op.create_index("uq_news_items_marketaux_external_id", "news_items", ["external_id"], unique=True, postgresql_where=sa.text("provider = 'marketaux'"))
    op.create_index("uq_news_items_marketaux_normalized_url", "news_items", ["normalized_url"], unique=True, postgresql_where=sa.text("provider = 'marketaux'"))
    op.create_unique_constraint("uq_news_items_fingerprint", "news_items", ["fingerprint"])
    for name in ("cluster_key", "quality_score", "importance_score", "topic", "scope"):
        op.drop_column("news_items", name)
