"""add weekly news archives

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "weekly_news_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("included_dates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "iso_year", "iso_week"),
    )
    op.create_index("ix_weekly_news_archives_ticker", "weekly_news_archives", ["ticker"])
    op.create_index("ix_weekly_news_archives_iso_year", "weekly_news_archives", ["iso_year"])
    op.create_index("ix_weekly_news_archives_iso_week", "weekly_news_archives", ["iso_week"])
    op.create_index("ix_weekly_news_archives_week_start", "weekly_news_archives", ["week_start"])


def downgrade():
    op.drop_table("weekly_news_archives")
