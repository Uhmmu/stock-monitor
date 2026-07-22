"""Persist Marketaux's independent execution interval.

Revision ID: 0021_marketaux_interval
Revises: 0020_marketaux
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_marketaux_interval"
down_revision: str | None = "0020_marketaux"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "news_provider_states",
        sa.Column("last_execution_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_provider_states", "last_execution_at")
