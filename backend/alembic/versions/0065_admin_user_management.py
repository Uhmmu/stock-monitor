"""add administrator notes to users

Revision ID: 0065_admin_user_management
Revises: 0064_discovery_pi_agent
"""

from alembic import op
import sqlalchemy as sa


revision = "0065_admin_user_management"
down_revision = "0064_discovery_pi_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "note")
