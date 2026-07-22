"""Add persistent Marketaux provider state and URL deduplication.

Revision ID: 0020_marketaux
Revises: 0019_securities
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_marketaux"
down_revision: str | None = "0019_securities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_items", sa.Column("normalized_url", sa.Text(), nullable=True))
    op.create_index(
        "uq_news_items_marketaux_external_id",
        "news_items",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'marketaux'"),
    )
    op.create_index(
        "uq_news_items_marketaux_normalized_url",
        "news_items",
        ["normalized_url"],
        unique=True,
        postgresql_where=sa.text("provider = 'marketaux'"),
    )
    op.create_table(
        "news_provider_states",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("quota_utc_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_batch_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_successful_fetch", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="ck_news_provider_states_request_count"),
        sa.CheckConstraint("next_batch_index >= 0", name="ck_news_provider_states_next_batch_index"),
        sa.PrimaryKeyConstraint("provider"),
    )
    op.execute(
        sa.text(
            "INSERT INTO news_provider_states "
            "(provider, quota_utc_date, request_count, next_batch_index) "
            "VALUES ('marketaux', (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, 0, 0)"
        )
    )


def downgrade() -> None:
    op.drop_table("news_provider_states")
    op.drop_index("uq_news_items_marketaux_normalized_url", table_name="news_items")
    op.drop_index("uq_news_items_marketaux_external_id", table_name="news_items")
    op.drop_column("news_items", "normalized_url")
