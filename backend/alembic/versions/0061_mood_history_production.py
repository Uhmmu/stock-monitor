"""add Mood history provenance and daily runs

Revision ID: 0061_mood_history_production
Revises: 0060_mood_validation_lab
"""

from alembic import op
import sqlalchemy as sa


revision = "0061_mood_history_production"
down_revision = "0060_mood_validation_lab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mood_snapshots") as batch_op:
        batch_op.add_column(sa.Column("snapshot_type", sa.String(16), nullable=False, server_default="INTRADAY"))
        batch_op.add_column(sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.drop_constraint("uq_mood_snapshots_scope_date_version", type_="unique")
        batch_op.create_unique_constraint(
            "uq_mood_snapshots_scope_date_version_type",
            ["scope_type", "scope_key", "trading_date", "calculation_version", "snapshot_type"],
        )

    op.create_table(
        "mood_daily_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("calculation_version", sa.String(32), nullable=False, server_default="mood_v1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("completed_scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("insufficient_scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("failed_scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("readiness", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("health", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("trading_date", "calculation_version", name="uq_mood_daily_runs_date_version"),
    )
    op.create_index("ix_mood_daily_runs_trading_date", "mood_daily_runs", ["trading_date"])
    op.create_index("ix_mood_daily_runs_status", "mood_daily_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mood_daily_runs_status", table_name="mood_daily_runs")
    op.drop_index("ix_mood_daily_runs_trading_date", table_name="mood_daily_runs")
    op.drop_table("mood_daily_runs")

    with op.batch_alter_table("mood_snapshots") as batch_op:
        batch_op.drop_constraint("uq_mood_snapshots_scope_date_version_type", type_="unique")
        batch_op.create_unique_constraint(
            "uq_mood_snapshots_scope_date_version",
            ["scope_type", "scope_key", "trading_date", "calculation_version"],
        )
        batch_op.drop_column("warnings")
        batch_op.drop_column("input_cutoff")
        batch_op.drop_column("snapshot_type")
