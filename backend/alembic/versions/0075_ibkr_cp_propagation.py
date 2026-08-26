"""add propagation summary to IBKR CP sync runs

Revision ID: 0075_ibkr_cp_propagation
Revises: 0074_ibkr_cp_positions
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0075_ibkr_cp_propagation"
down_revision = "0074_ibkr_cp_positions"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("ibkr_cp_sync_runs", sa.Column("propagation", JSON_VALUE, nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    op.drop_column("ibkr_cp_sync_runs", "propagation")
