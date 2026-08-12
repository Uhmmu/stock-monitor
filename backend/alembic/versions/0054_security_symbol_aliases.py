"""add historical provider symbols to canonical securities

Revision ID: 0054_security_symbol_aliases
Revises: 0053_manual_curated_seed
"""

from alembic import op
import sqlalchemy as sa


revision = "0054_security_symbol_aliases"
down_revision = "0053_manual_curated_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_symbol_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("change_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "symbol", name="uq_security_symbol_aliases_provider_symbol"),
    )
    op.create_index("ix_security_symbol_aliases_security_id", "security_symbol_aliases", ["security_id"])


def downgrade() -> None:
    op.drop_index("ix_security_symbol_aliases_security_id", table_name="security_symbol_aliases")
    op.drop_table("security_symbol_aliases")
