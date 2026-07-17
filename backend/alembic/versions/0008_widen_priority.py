"""widen sec_filings.priority / sec_events.priority to VARCHAR(16)

'important' (9 chars) overflowed the original VARCHAR(8).

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("sec_filings", "priority", type_=sa.String(length=16))
    op.alter_column("sec_events", "priority", type_=sa.String(length=16))


def downgrade():
    op.alter_column("sec_filings", "priority", type_=sa.String(length=8))
    op.alter_column("sec_events", "priority", type_=sa.String(length=8))
