"""add news title translations

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("news_items", sa.Column("translated_title", sa.String(512), nullable=True))
    op.add_column("news_items", sa.Column("title_translation_model", sa.String(128), nullable=True))
    op.add_column("news_items", sa.Column("title_translation_input_hash", sa.String(64), nullable=True))
    op.add_column("news_items", sa.Column("title_translated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "news_items",
        sa.Column("title_translation_status", sa.String(16), server_default="pending", nullable=False),
    )
    op.add_column(
        "news_items",
        sa.Column("title_translation_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("news_items", sa.Column("title_translation_last_error", sa.Text(), nullable=True))
    op.add_column(
        "news_items",
        sa.Column("title_translation_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_news_items_title_translation_status", "news_items", ["title_translation_status"])
    op.create_index(
        "ix_news_items_title_translation_next_retry_at",
        "news_items",
        ["title_translation_next_retry_at"],
    )


def downgrade():
    op.drop_index("ix_news_items_title_translation_next_retry_at", table_name="news_items")
    op.drop_index("ix_news_items_title_translation_status", table_name="news_items")
    for column in (
        "title_translation_next_retry_at",
        "title_translation_last_error",
        "title_translation_attempts",
        "title_translation_status",
        "title_translated_at",
        "title_translation_input_hash",
        "title_translation_model",
        "translated_title",
    ):
        op.drop_column("news_items", column)
