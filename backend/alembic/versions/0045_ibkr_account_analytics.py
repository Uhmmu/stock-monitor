"""add IBKR account analytics and observable sync pipeline

Revision ID: 0045_ibkr_account_analytics
Revises: 0044_ibkr_flex_snapshots
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_ibkr_account_analytics"
down_revision = "0044_ibkr_flex_snapshots"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NUM = sa.Numeric(38, 12)


def _json_column(name: str, empty: str = "{}"):
    return sa.Column(name, JSON_VALUE, nullable=False, server_default=sa.text(f"'{empty}'"))


def upgrade() -> None:
    with op.batch_alter_table("ibkr_flex_sync_runs") as batch:
        batch.alter_column("source_hash", existing_type=sa.String(64), nullable=True)
        for column in (
            sa.Column("trigger_type", sa.String(24), nullable=False, server_default="manual"),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("stage", sa.String(24), nullable=False, server_default="requested"),
            sa.Column("archive_path", sa.String(512)),
            sa.Column("flex_reference_hint", sa.String(24)),
            _json_column("import_counts"), _json_column("reconciliation"), _json_column("propagation"),
            sa.Column("error_stage", sa.String(24)), sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        ):
            batch.add_column(column)
    op.create_index("ix_ibkr_flex_sync_runs_stage", "ibkr_flex_sync_runs", ["stage"])
    op.create_index("uq_ibkr_sync_one_active_user", "ibkr_flex_sync_runs", ["user_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued','running')"),
                    sqlite_where=sa.text("status IN ('queued','running')"))

    op.create_table(
        "ibkr_normalized_cash_flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80)),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("ibkr_flex_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_date", sa.Date()), sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("currency", sa.String(16)), sa.Column("amount", NUM),
        sa.Column("normalized_category", sa.String(32), nullable=False),
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("classification_rule", sa.String(64), nullable=False),
        sa.Column("original_type", sa.String(128)), sa.Column("original_description", sa.Text()),
        _json_column("warnings", "[]"), sa.Column("manual_override", sa.String(32)),
        sa.Column("calculation_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "source_record_id", "calculation_version", name="uq_ibkr_cash_flow_source_version"),
    )
    for name, cols in (
        ("ix_ibkr_normalized_cash_flows_user_id", ["user_id"]), ("ix_ibkr_normalized_cash_flows_account_id", ["account_id"]),
        ("ix_ibkr_normalized_cash_flows_source_record_id", ["source_record_id"]), ("ix_ibkr_normalized_cash_flows_source_sync_run_id", ["source_sync_run_id"]),
        ("ix_ibkr_normalized_cash_flows_flow_date", ["flow_date"]), ("ix_ibkr_normalized_cash_flows_normalized_category", ["normalized_category"]),
        ("ix_ibkr_cash_flow_user_account_date", ["user_id", "account_id", "flow_date"]),
    ): op.create_index(name, "ibkr_normalized_cash_flows", cols)

    op.create_table(
        "ibkr_account_daily_performance",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80), nullable=False), sa.Column("performance_date", sa.Date(), nullable=False), sa.Column("base_currency", sa.String(16)),
        *[sa.Column(name, NUM) for name in ("beginning_nav", "ending_nav", "beginning_cash", "ending_cash", "gross_position_value", "external_deposits", "external_withdrawals", "net_external_cash_flow", "realized_pnl", "unrealized_pnl_change", "dividend_income", "interest_income", "commissions", "taxes", "other_fees", "fx_pnl", "investment_pnl")],
        *[sa.Column(name, sa.Numeric(24, 12)) for name in ("daily_return", "cumulative_return", "drawdown", "max_drawdown_to_date")],
        sa.Column("data_completeness", sa.Numeric(8, 6), nullable=False, server_default="0"), _json_column("warnings", "[]"),
        sa.Column("source_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calculation_version", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "account_id", "performance_date", "calculation_version", name="uq_ibkr_daily_perf_account_date_version"),
    )
    for name, cols in (("ix_ibkr_account_daily_performance_user_id", ["user_id"]), ("ix_ibkr_account_daily_performance_account_id", ["account_id"]), ("ix_ibkr_account_daily_performance_performance_date", ["performance_date"]), ("ix_ibkr_account_daily_performance_source_sync_run_id", ["source_sync_run_id"]), ("ix_ibkr_daily_perf_user_date", ["user_id", "performance_date"])): op.create_index(name, "ibkr_account_daily_performance", cols)

    op.create_table(
        "ibkr_trade_round_trips",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80)), sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")),
        sa.Column("conid", sa.String(32)), sa.Column("symbol", sa.String(48)), sa.Column("opened_at", sa.DateTime(timezone=True)), sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("quantity", NUM), sa.Column("average_entry_price", NUM), sa.Column("average_exit_price", NUM), sa.Column("gross_pnl", NUM), sa.Column("commissions", NUM), sa.Column("taxes", NUM), sa.Column("net_pnl", NUM),
        sa.Column("return_pct", sa.Numeric(24, 12)), sa.Column("holding_days", sa.Integer()), sa.Column("matching_method", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(96), nullable=False), sa.Column("source_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calculation_version", sa.String(32), nullable=False), _json_column("warnings", "[]"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "source_key", "calculation_version", name="uq_ibkr_round_trip_source_version"),
    )
    for name, cols in (("ix_ibkr_trade_round_trips_user_id", ["user_id"]), ("ix_ibkr_trade_round_trips_account_id", ["account_id"]), ("ix_ibkr_trade_round_trips_instrument_id", ["instrument_id"]), ("ix_ibkr_trade_round_trips_conid", ["conid"]), ("ix_ibkr_trade_round_trips_symbol", ["symbol"]), ("ix_ibkr_trade_round_trips_closed_at", ["closed_at"]), ("ix_ibkr_trade_round_trips_source_sync_run_id", ["source_sync_run_id"]), ("ix_ibkr_round_trip_user_symbol_closed", ["user_id", "symbol", "closed_at"])): op.create_index(name, "ibkr_trade_round_trips", cols)

    op.create_table(
        "ibkr_position_performance_daily",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80), nullable=False), sa.Column("performance_date", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")), sa.Column("conid", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(48)), sa.Column("currency", sa.String(16)),
        *[sa.Column(name, NUM) for name in ("opening_quantity", "closing_quantity", "net_trade_quantity", "average_cost", "opening_market_value", "closing_market_value", "realized_pnl", "unrealized_pnl_change", "dividend_income", "commissions", "taxes", "fx_pnl", "total_pnl")],
        sa.Column("portfolio_weight", sa.Numeric(24, 12)), sa.Column("contribution_to_portfolio_return", sa.Numeric(24, 12)),
        sa.Column("price_source", sa.String(32)), sa.Column("price_as_of", sa.Date()),
        sa.Column("data_completeness", sa.Numeric(8, 6), nullable=False, server_default="0"), _json_column("warnings", "[]"),
        sa.Column("source_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calculation_version", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "account_id", "performance_date", "conid", "calculation_version", name="uq_ibkr_position_perf_date_version"),
    )
    for name, cols in (("ix_ibkr_position_performance_daily_user_id", ["user_id"]), ("ix_ibkr_position_performance_daily_account_id", ["account_id"]), ("ix_ibkr_position_performance_daily_performance_date", ["performance_date"]), ("ix_ibkr_position_performance_daily_instrument_id", ["instrument_id"]), ("ix_ibkr_position_performance_daily_conid", ["conid"]), ("ix_ibkr_position_performance_daily_symbol", ["symbol"]), ("ix_ibkr_position_performance_daily_source_sync_run_id", ["source_sync_run_id"]), ("ix_ibkr_position_perf_user_date", ["user_id", "performance_date"])): op.create_index(name, "ibkr_position_performance_daily", cols)

    op.create_table(
        "ibkr_dividend_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80)), sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("ibkr_flex_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conid", sa.String(32)), sa.Column("symbol", sa.String(48)), sa.Column("currency", sa.String(16)), sa.Column("ex_date", sa.Date()), sa.Column("pay_date", sa.Date()),
        sa.Column("gross_dividend", NUM), sa.Column("withholding_tax", NUM), sa.Column("net_dividend", NUM), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("event_key", sa.String(96), nullable=False), sa.Column("calculation_version", sa.String(32), nullable=False), _json_column("warnings", "[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "event_key", "calculation_version", name="uq_ibkr_dividend_event_version"),
    )
    for name, cols in (("ix_ibkr_dividend_events_user_id", ["user_id"]), ("ix_ibkr_dividend_events_account_id", ["account_id"]), ("ix_ibkr_dividend_events_source_record_id", ["source_record_id"]), ("ix_ibkr_dividend_events_source_sync_run_id", ["source_sync_run_id"]), ("ix_ibkr_dividend_events_conid", ["conid"]), ("ix_ibkr_dividend_events_symbol", ["symbol"]), ("ix_ibkr_dividend_events_pay_date", ["pay_date"]), ("ix_ibkr_dividend_events_status", ["status"]), ("ix_ibkr_dividend_user_pay_date", ["user_id", "pay_date"])): op.create_index(name, "ibkr_dividend_events", cols)

    op.create_table(
        "ibkr_portfolio_authority_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_position_id", sa.Integer(), sa.ForeignKey("portfolio_positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flex_record_id", sa.Integer(), sa.ForeignKey("ibkr_flex_records.id", ondelete="SET NULL")),
        sa.Column("conflict_type", sa.String(32), nullable=False), sa.Column("previous_source", sa.String(32)),
        sa.Column("previous_value", sa.Text()), sa.Column("authoritative_value", sa.Text()),
        sa.Column("application_status", sa.String(24), nullable=False), _json_column("details"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for name, cols in (("ix_ibkr_portfolio_authority_audits_user_id", ["user_id"]), ("ix_ibkr_portfolio_authority_audits_portfolio_position_id", ["portfolio_position_id"]), ("ix_ibkr_portfolio_authority_audits_sync_run_id", ["sync_run_id"]), ("ix_ibkr_portfolio_authority_audits_flex_record_id", ["flex_record_id"]), ("ix_ibkr_portfolio_authority_audits_conflict_type", ["conflict_type"]), ("ix_ibkr_authority_audit_user_position", ["user_id", "portfolio_position_id", "created_at"])): op.create_index(name, "ibkr_portfolio_authority_audits", cols)


def downgrade() -> None:
    for table in ("ibkr_portfolio_authority_audits", "ibkr_dividend_events", "ibkr_position_performance_daily", "ibkr_trade_round_trips", "ibkr_account_daily_performance", "ibkr_normalized_cash_flows"):
        op.drop_table(table)
    op.drop_index("ix_ibkr_flex_sync_runs_stage", table_name="ibkr_flex_sync_runs")
    op.drop_index("uq_ibkr_sync_one_active_user", table_name="ibkr_flex_sync_runs")
    with op.batch_alter_table("ibkr_flex_sync_runs") as batch:
        for name in ("heartbeat_at", "error_stage", "propagation", "reconciliation", "import_counts", "flex_reference_hint", "archive_path", "stage", "started_at", "trigger_type"):
            batch.drop_column(name)
        batch.alter_column("source_hash", existing_type=sa.String(64), nullable=False)
