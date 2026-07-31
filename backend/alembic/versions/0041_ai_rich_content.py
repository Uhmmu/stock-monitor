"""add versioned rich content to AI messages

Revision ID: 0041_ai_rich_content
Revises: 0040_ai_memory_decisions
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041_ai_rich_content"
down_revision = "0040_ai_memory_decisions"
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # Both columns remain nullable so existing messages need no table-wide
    # rewrite or backfill and continue to render as Markdown.
    op.add_column(
        "ai_messages",
        sa.Column("content_schema_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_messages",
        sa.Column("content_parts", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_messages", "content_parts")
    op.drop_column("ai_messages", "content_schema_version")
