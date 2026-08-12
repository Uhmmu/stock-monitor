"""allow canonical manual Industry Pulse seeds and longer health states

Revision ID: 0053_manual_curated_seed
Revises: 0052_industry_pulse_constituents
"""

from alembic import op
import sqlalchemy as sa


revision = "0053_manual_curated_seed"
down_revision = "0052_industry_pulse_constituents"
branch_labels = None
depends_on = None

_TABLE = "industry_pulse_instruments"
_CHECK = "ck_industry_pulse_instruments_classification_source"
_OLD_SOURCE_CHECK = "classification_source IN ('MANUAL', 'ETF_HOLDING', 'AI_CLASSIFIED', 'PROVIDER', 'INHERITED')"
_NEW_SOURCE_CHECK = "classification_source IN ('MANUAL_CURATED_SEED', 'MANUAL', 'ETF_HOLDING', 'AI_CLASSIFIED', 'PROVIDER', 'INHERITED')"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # 0052 intentionally skipped CHECK creation on SQLite; batch mode
        # recreates the table while preserving its existing indexes/columns.
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            batch.alter_column("health_status", existing_type=sa.String(16), type_=sa.String(32))
            batch.create_check_constraint(_CHECK, _NEW_SOURCE_CHECK)
        return
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_CHECK, _TABLE, _NEW_SOURCE_CHECK)
    op.alter_column(_TABLE, "health_status", existing_type=sa.String(16), type_=sa.String(32))


def downgrade() -> None:
    bind = op.get_bind()
    # Do not let the narrower legacy type fail on rows carrying the new
    # diagnostic states; retain a truthful safe fallback for old consumers.
    op.execute(sa.text("UPDATE industry_pulse_instruments SET health_status = 'UNAVAILABLE' WHERE length(health_status) > 16"))
    op.execute(sa.text("UPDATE industry_pulse_instruments SET classification_source = 'MANUAL' WHERE classification_source = 'MANUAL_CURATED_SEED'"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            batch.drop_constraint(_CHECK, type_="check")
            batch.alter_column("health_status", existing_type=sa.String(32), type_=sa.String(16))
        return
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_CHECK, _TABLE, _OLD_SOURCE_CHECK)
    op.alter_column(_TABLE, "health_status", existing_type=sa.String(32), type_=sa.String(16))
