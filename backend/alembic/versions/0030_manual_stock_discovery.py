"""make stock discovery manual-only

Revision ID: 0030_manual_discovery
Revises: 0029_discovery_model
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_manual_discovery"
down_revision = "0029_discovery_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table(
        "stock_discovery_settings",
        sa.column("auto_update_enabled", sa.Boolean()),
    )
    runs = sa.table(
        "stock_discovery_runs",
        sa.column("next_scheduled_at", sa.DateTime(timezone=True)),
    )
    op.execute(settings.update().values(auto_update_enabled=False))
    op.execute(runs.update().values(next_scheduled_at=None))
    with op.batch_alter_table(
        "stock_discovery_settings", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.alter_column(
            "auto_update_enabled",
            existing_type=sa.Boolean(),
            server_default=sa.false(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Restore the schema default without silently re-enabling paid requests for
    # users whose rows were disabled by the manual-only migration.
    with op.batch_alter_table(
        "stock_discovery_settings", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.alter_column(
            "auto_update_enabled",
            existing_type=sa.Boolean(),
            server_default=sa.true(),
            existing_nullable=False,
        )
