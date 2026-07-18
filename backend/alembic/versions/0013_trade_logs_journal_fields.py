"""extend trade logs for journal entries

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("trade_logs", "ticker", existing_type=sa.String(16), nullable=True)
    op.alter_column("trade_logs", "direction", existing_type=sa.String(8), nullable=True)
    op.alter_column("trade_logs", "quantity", existing_type=sa.Float(), nullable=True)
    op.alter_column("trade_logs", "price", existing_type=sa.Float(), nullable=True)
    op.add_column("trade_logs", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("trade_logs", sa.Column("table_rows", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("trade_logs", sa.Column("photo_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("trade_logs", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column("trade_logs", sa.Column("ai_summary_model", sa.String(128), nullable=True))
    op.add_column("trade_logs", sa.Column("ai_summary_input_hash", sa.String(64), nullable=True))
    op.add_column("trade_logs", sa.Column("ai_summary_created_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("trade_logs", "ai_summary_created_at")
    op.drop_column("trade_logs", "ai_summary_input_hash")
    op.drop_column("trade_logs", "ai_summary_model")
    op.drop_column("trade_logs", "ai_summary")
    op.drop_column("trade_logs", "photo_urls")
    op.drop_column("trade_logs", "table_rows")
    op.drop_column("trade_logs", "content")
    op.alter_column("trade_logs", "price", existing_type=sa.Float(), nullable=False)
    op.alter_column("trade_logs", "quantity", existing_type=sa.Float(), nullable=False)
    op.alter_column("trade_logs", "direction", existing_type=sa.String(8), nullable=False)
    op.alter_column("trade_logs", "ticker", existing_type=sa.String(16), nullable=False)
