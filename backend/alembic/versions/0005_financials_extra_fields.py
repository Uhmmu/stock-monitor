"""add operating_income and net_margin to quarterly_financials

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("quarterly_financials", sa.Column("operating_income", sa.Float(), nullable=True))
    op.add_column("quarterly_financials", sa.Column("net_margin", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("quarterly_financials", "net_margin")
    op.drop_column("quarterly_financials", "operating_income")
