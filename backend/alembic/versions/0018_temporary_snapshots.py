"""temporary section snapshots

Revision ID: 0018_temporary_snapshots
Revises: 0017_financial_statement_snapshots
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_temporary_snapshots"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "temporary_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section", sa.String(length=24), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("section", "ticker"),
    )
    op.create_index("ix_temporary_snapshots_section", "temporary_snapshots", ["section"])
    op.create_index("ix_temporary_snapshots_ticker", "temporary_snapshots", ["ticker"])
    op.create_index("ix_temporary_snapshots_expires_at", "temporary_snapshots", ["expires_at"])


def downgrade():
    op.drop_table("temporary_snapshots")
