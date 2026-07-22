"""Store FMP news metadata.

Revision ID: 0022_fmp_news
Revises: 0021_marketaux_interval
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_fmp_news"
down_revision: str | None = "0021_marketaux_interval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_items", sa.Column("symbols", sa.JSON(), nullable=True))
    op.add_column(
        "news_items",
        sa.Column("news_type", sa.String(length=32), nullable=False, server_default="article"),
    )


def downgrade() -> None:
    op.drop_column("news_items", "news_type")
    op.drop_column("news_items", "symbols")
