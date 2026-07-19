"""add daily valuation snapshots

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("ai_opinion", sa.Text(), nullable=True),
        sa.Column("ai_model", sa.String(128), nullable=True),
        sa.Column("source_version", sa.String(32), nullable=False, server_default="cross-model-v3"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "snapshot_date"),
    )
    op.create_index("ix_valuation_snapshots_ticker", "valuation_snapshots", ["ticker"])
    op.create_index("ix_valuation_snapshots_snapshot_date", "valuation_snapshots", ["snapshot_date"])


def downgrade():
    op.drop_index("ix_valuation_snapshots_snapshot_date", table_name="valuation_snapshots")
    op.drop_index("ix_valuation_snapshots_ticker", table_name="valuation_snapshots")
    op.drop_table("valuation_snapshots")
