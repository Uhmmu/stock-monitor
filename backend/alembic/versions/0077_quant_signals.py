"""add expiring quant signals, generation runs and strategy deployments

Revision ID: 0077_quant_signals
Revises: 0076_quant_backtesting

Goal 5 WP 11.1/WP 11.2: strategy outputs become durable desired positions
with non-extendable expiry, dedupe, supersession and audit.  Signals carry no
order side/type and no Binance linkage; the environment is pinned to paper.
"""

from alembic import op
import sqlalchemy as sa


revision = "0077_quant_signals"
down_revision = "0076_quant_backtesting"
branch_labels = None
depends_on = None


NUMERIC = sa.Numeric(38, 18)
JSON = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "quant_strategy_deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="paper"),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("target_exposure", NUMERIC, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="paused"),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "user_id", "environment", "strategy_key", "instrument_id", "interval",
            name="uq_quant_deployments_identity",
        ),
        sa.CheckConstraint("environment = 'paper'", name="ck_quant_deployments_paper_only"),
        sa.CheckConstraint("status IN ('active', 'paused')", name="ck_quant_deployments_status"),
        sa.CheckConstraint(
            "CAST(target_exposure AS NUMERIC) >= 0.25 AND CAST(target_exposure AS NUMERIC) <= 1",
            name="ck_quant_deployments_exposure_bounds",
        ),
    )
    op.create_index("ix_quant_deployments_user_status", "quant_strategy_deployments", ["user_id", "status"])
    op.create_index("ix_quant_deployments_user_id", "quant_strategy_deployments", ["user_id"])
    op.create_index("ix_quant_deployments_instrument_id", "quant_strategy_deployments", ["instrument_id"])

    op.create_table(
        "quant_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("quant_strategy_deployments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="paper"),
        sa.Column("status", sa.String(16), nullable=False, server_default="generated"),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_exposure", NUMERIC, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("feature_value_id", sa.Integer(), sa.ForeignKey("quant_feature_values.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("feature_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_reason", sa.Text(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), sa.ForeignKey("quant_signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_quant_signals_idempotency_key"),
        sa.CheckConstraint("environment = 'paper'", name="ck_quant_signals_paper_only"),
        sa.CheckConstraint(
            "status IN ('generated', 'superseded', 'expired', 'rejected', 'consumed')",
            name="ck_quant_signals_status",
        ),
        sa.CheckConstraint("valid_from < expires_at", name="ck_quant_signals_validity_window"),
        sa.CheckConstraint(
            "CAST(target_exposure AS NUMERIC) >= -1 AND CAST(target_exposure AS NUMERIC) <= 1",
            name="ck_quant_signals_target_bounds",
        ),
    )
    op.create_index("ix_quant_signals_user_status_generated", "quant_signals", ["user_id", "status", "generated_at"])
    op.create_index("ix_quant_signals_status_expires", "quant_signals", ["status", "expires_at"])
    op.create_index("ix_quant_signals_deployment_decision", "quant_signals", ["deployment_id", "decision_time"])
    op.create_index("ix_quant_signals_user_id", "quant_signals", ["user_id"])
    op.create_index("ix_quant_signals_instrument_id", "quant_signals", ["instrument_id"])
    op.create_index("ix_quant_signals_feature_value_id", "quant_signals", ["feature_value_id"])
    op.create_index("ix_quant_signals_superseded_by_id", "quant_signals", ["superseded_by_id"])

    op.create_table(
        "quant_signal_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("quant_strategy_deployments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("boundary", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("feature_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lag_seconds", sa.Integer(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("quant_signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("deployment_id", "boundary", name="uq_quant_signal_runs_deployment_boundary"),
        sa.CheckConstraint(
            "status IN ('signal_created', 'no_signal', 'duplicate', 'stale_data', "
            "'missing_data', 'failed', 'skipped_paused', 'skipped_expired_boundary')",
            name="ck_quant_signal_runs_status",
        ),
    )
    op.create_index("ix_quant_signal_runs_user_created", "quant_signal_runs", ["user_id", "created_at"])
    op.create_index("ix_quant_signal_runs_user_id", "quant_signal_runs", ["user_id"])
    op.create_index("ix_quant_signal_runs_deployment_id", "quant_signal_runs", ["deployment_id"])
    op.create_index("ix_quant_signal_runs_instrument_id", "quant_signal_runs", ["instrument_id"])
    op.create_index("ix_quant_signal_runs_signal_id", "quant_signal_runs", ["signal_id"])


def downgrade() -> None:
    op.drop_table("quant_signal_runs")
    op.drop_table("quant_signals")
    op.drop_table("quant_strategy_deployments")
