"""add causal crypto quant definitions, features and backtest records

Revision ID: 0076_quant_backtesting
Revises: 0075_ibkr_cp_propagation

Goal 4 keeps strategy/feature inputs versioned and append-only.  The tables
are additive; no equity, crypto identity, candle, or derivatives rows are
rewritten by this migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "0076_quant_backtesting"
down_revision = "0075_ibkr_cp_propagation"
branch_labels = None
depends_on = None


NUMERIC = sa.Numeric(38, 18)
JSON = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "quant_strategy_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("interval", sa.String(8), nullable=False, server_default="1h"),
        sa.Column("universe", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("parameter_schema", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("default_parameters", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False, server_default="registry-v1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="released"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_key", "version", name="uq_quant_strategy_definitions_key_version"),
        sa.CheckConstraint(
            "status IN ('experimental', 'released', 'retired')",
            name="ck_quant_strategy_definitions_status",
        ),
    )
    op.create_index(
        "ix_quant_strategy_definitions_status", "quant_strategy_definitions", ["status"]
    )

    op.create_table(
        "quant_feature_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_set_key", sa.String(96), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("supported_intervals", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("feature_schema", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("parameters", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("input_declarations", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column(
            "availability_policy", sa.String(32), nullable=False,
            server_default="source_causal_v1",
        ),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False, server_default="features-v1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="released"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("feature_set_key", "version", name="uq_quant_feature_sets_key_version"),
        sa.CheckConstraint(
            "status IN ('experimental', 'released', 'retired')",
            name="ck_quant_feature_sets_status",
        ),
        sa.CheckConstraint(
            "availability_policy <> ''", name="ck_quant_feature_sets_policy_nonempty"
        ),
    )
    op.create_index("ix_quant_feature_sets_status", "quant_feature_sets", ["status"])
    op.create_index("ix_quant_feature_sets_input_hash", "quant_feature_sets", ["input_hash"])

    op.create_table(
        "quant_feature_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_set_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("bar_open_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quality", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("omissions", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("warnings", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "source_causal_version", sa.String(32), nullable=False,
            server_default="source_causal_v1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["feature_set_id"], ["quant_feature_sets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "feature_set_id", "instrument_id", "interval", "bar_open_time_ms", "input_hash",
            name="uq_quant_feature_values_input_identity",
        ),
        sa.CheckConstraint(
            "coverage >= 0 AND coverage <= 1", name="ck_quant_feature_values_coverage"
        ),
        sa.CheckConstraint(
            "available_at >= as_of", name="ck_quant_feature_values_causal_order"
        ),
    )
    op.create_index(
        "ix_quant_feature_values_instrument_time", "quant_feature_values",
        ["instrument_id", "interval", "as_of"],
    )
    op.create_index(
        "ix_quant_feature_values_feature_time", "quant_feature_values",
        ["feature_set_id", "interval", "as_of"],
    )
    op.create_index(
        "ix_quant_feature_values_available_at", "quant_feature_values", ["available_at"]
    )
    op.create_index(
        "ix_quant_feature_values_input_hash", "quant_feature_values", ["input_hash"]
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("strategy_definition_id", sa.Integer(), nullable=False),
        sa.Column("rerun_of_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameters", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("manifest", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("feature_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=True),
        sa.Column("initial_capital", NUMERIC, nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["strategy_definition_id"], ["quant_strategy_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rerun_of_id"], ["backtest_runs.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'cancel_requested', 'completed', 'failed', 'cancelled')",
            name="ck_backtest_runs_status",
        ),
        sa.CheckConstraint(
            "initial_capital > 0", name="ck_backtest_runs_initial_capital_positive"
        ),
    )
    op.create_index(
        "ix_backtest_runs_user_status_created", "backtest_runs", ["user_id", "status", "created_at"]
    )
    op.create_index("ix_backtest_runs_status_created", "backtest_runs", ["status", "created_at"])
    op.create_index("ix_backtest_runs_manifest_hash", "backtest_runs", ["manifest_hash"])

    op.create_table(
        "backtest_equity_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nav", NUMERIC, nullable=False),
        sa.Column("cash", NUMERIC, nullable=False),
        sa.Column("gross_exposure", NUMERIC, nullable=False),
        sa.Column("drawdown", NUMERIC, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "timestamp", name="uq_backtest_equity_points_run_time"),
    )
    op.create_index(
        "ix_backtest_equity_points_run_time", "backtest_equity_points", ["run_id", "timestamp"]
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fill_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", NUMERIC, nullable=False),
        sa.Column("price", NUMERIC, nullable=False),
        sa.Column("fee", NUMERIC, nullable=False, server_default="0"),
        sa.Column("slippage", NUMERIC, nullable=False, server_default="0"),
        sa.Column("funding", NUMERIC, nullable=False, server_default="0"),
        sa.Column("realized_pnl", NUMERIC, nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="filled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "side IN ('buy', 'sell', 'long', 'short')", name="ck_backtest_trades_side"
        ),
    )
    op.create_index("ix_backtest_trades_run_time", "backtest_trades", ["run_id", "fill_time"])
    op.create_index(
        "ix_backtest_trades_instrument_time", "backtest_trades", ["instrument_id", "fill_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_instrument_time", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_run_time", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_equity_points_run_time", table_name="backtest_equity_points")
    op.drop_table("backtest_equity_points")
    op.drop_index("ix_backtest_runs_manifest_hash", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_status_created", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_user_status_created", table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_index("ix_quant_feature_values_input_hash", table_name="quant_feature_values")
    op.drop_index("ix_quant_feature_values_available_at", table_name="quant_feature_values")
    op.drop_index("ix_quant_feature_values_feature_time", table_name="quant_feature_values")
    op.drop_index("ix_quant_feature_values_instrument_time", table_name="quant_feature_values")
    op.drop_table("quant_feature_values")
    op.drop_index("ix_quant_feature_sets_status", table_name="quant_feature_sets")
    op.drop_index("ix_quant_feature_sets_input_hash", table_name="quant_feature_sets")
    op.drop_table("quant_feature_sets")
    op.drop_index("ix_quant_strategy_definitions_status", table_name="quant_strategy_definitions")
    op.drop_table("quant_strategy_definitions")
