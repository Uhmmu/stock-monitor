"""promote the evaluated stock discovery model default

Revision ID: 0029_discovery_model
Revises: 0028_stock_discovery
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_discovery_model"
down_revision = "0028_stock_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "stock_discovery_settings", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.alter_column(
            "model",
            existing_type=sa.String(length=128),
            server_default="openai/gpt-5.4",
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "stock_discovery_settings", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.alter_column(
            "model",
            existing_type=sa.String(length=128),
            server_default="openai/gpt-5.4-mini",
            existing_nullable=False,
        )
