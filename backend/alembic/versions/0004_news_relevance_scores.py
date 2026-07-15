"""add news relevance and sentiment scores

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("news_items", sa.Column("relevance_score", sa.Float(), nullable=True))
    op.add_column("news_items", sa.Column("sentiment_score", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("news_items", "sentiment_score")
    op.drop_column("news_items", "relevance_score")
