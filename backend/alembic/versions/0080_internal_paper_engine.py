"""extend Goal 5 into a persistent internal paper execution engine

Revision ID: 0080_internal_paper
Revises: 0079_execution_test

Existing PAPER history is retained in one legacy run per account.  Goal 6
TEST tables and the standalone Demo executor are deliberately untouched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0080_internal_paper"
down_revision = "0079_execution_test"
branch_labels = None
depends_on = None

NUMERIC = sa.Numeric(38, 18)
JSON = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "paper_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("initial_equity", NUMERIC, nullable=False),
        sa.Column("ending_equity", NUMERIC, nullable=True),
        sa.Column("peak_equity", NUMERIC, nullable=False),
        sa.Column("max_drawdown", NUMERIC, nullable=False, server_default="0"),
        sa.Column("configuration", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("strategy_metadata", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'completed')", name="ck_paper_runs_status"),
    )
    op.create_index("ix_paper_runs_account_id", "paper_runs", ["account_id"])
    op.create_index("ix_paper_runs_user_id", "paper_runs", ["user_id"])
    op.create_index("ix_paper_runs_account_started", "paper_runs", ["account_id", "started_at"])

    for column in (
        sa.Column("account_key", sa.String(64), nullable=False, server_default="default"),
        sa.Column("name", sa.String(96), nullable=False, server_default="Paper Account"),
        sa.Column("locked_cash", NUMERIC, nullable=False, server_default="0"),
        sa.Column("maker_fee_bps", NUMERIC, nullable=False, server_default="2"),
        sa.Column("maintenance_margin_ratio", NUMERIC, nullable=False, server_default="0.005"),
        sa.Column("liquidation_fee_bps", NUMERIC, nullable=False, server_default="50"),
        sa.Column("current_run_id", sa.Integer(), nullable=True),
    ):
        op.add_column("paper_accounts", column)
    op.create_foreign_key(
        "fk_paper_accounts_current_run_id", "paper_accounts", "paper_runs",
        ["current_run_id"], ["id"], ondelete="SET NULL", use_alter=True,
    )
    op.create_index("ix_paper_accounts_current_run_id", "paper_accounts", ["current_run_id"])
    op.drop_constraint("uq_paper_accounts_user_env", "paper_accounts", type_="unique")
    op.create_unique_constraint(
        "uq_paper_accounts_user_env_key", "paper_accounts", ["user_id", "environment", "account_key"]
    )

    op.execute(sa.text(
        "INSERT INTO paper_runs "
        "(account_id, user_id, status, initial_equity, peak_equity, configuration, strategy_metadata, started_at) "
        "SELECT id, user_id, 'active', initial_cash, initial_cash, '{}', '{}', created_at FROM paper_accounts"
    ))
    op.execute(sa.text(
        "UPDATE paper_accounts SET current_run_id = "
        "(SELECT id FROM paper_runs WHERE paper_runs.account_id = paper_accounts.id ORDER BY id LIMIT 1)"
    ))

    for table in ("paper_orders", "paper_fills", "paper_funding_entries", "paper_positions", "paper_reconciliations"):
        op.add_column(table, sa.Column("run_id", sa.Integer(), nullable=True))
        op.execute(sa.text(
            f"UPDATE {table} SET run_id = (SELECT current_run_id FROM paper_accounts "
            f"WHERE paper_accounts.id = {table}.account_id)"
        ))
        op.alter_column(table, "run_id", existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(
            f"fk_{table}_run_id", table, "paper_runs", ["run_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_run_id", table, ["run_id"])

    op.drop_constraint("ck_paper_orders_market_only", "paper_orders", type_="check")
    op.add_column("paper_orders", sa.Column("market_type", sa.String(12), nullable=False, server_default="futures"))
    op.add_column("paper_orders", sa.Column("position_side", sa.String(8), nullable=False, server_default="BOTH"))
    op.add_column("paper_orders", sa.Column("limit_price", NUMERIC, nullable=True))
    op.add_column("paper_orders", sa.Column("leverage", NUMERIC, nullable=False, server_default="1"))
    op.add_column("paper_orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_paper_orders_type", "paper_orders", "order_type IN ('market', 'limit')")
    op.create_check_constraint("ck_paper_orders_market_type", "paper_orders", "market_type IN ('spot', 'futures')")
    op.create_check_constraint(
        "ck_paper_orders_position_side", "paper_orders", "position_side IN ('BOTH', 'LONG', 'SHORT')"
    )

    op.add_column("paper_fills", sa.Column("event_key", sa.String(128), nullable=True))
    op.add_column("paper_fills", sa.Column("liquidity", sa.String(8), nullable=False, server_default="taker"))
    op.add_column("paper_fills", sa.Column("mark_price", NUMERIC, nullable=True))
    op.add_column("paper_fills", sa.Column("reason", sa.String(32), nullable=True))
    op.execute(sa.text("UPDATE paper_fills SET event_key = 'legacy-fill-' || CAST(id AS VARCHAR)"))
    op.alter_column("paper_fills", "event_key", existing_type=sa.String(128), nullable=False)
    op.create_unique_constraint("uq_paper_fills_event_key", "paper_fills", ["event_key"])
    op.create_check_constraint("ck_paper_fills_liquidity", "paper_fills", "liquidity IN ('maker', 'taker')")

    op.drop_constraint("uq_paper_funding_entries_boundary", "paper_funding_entries", type_="unique")
    op.create_unique_constraint(
        "uq_paper_funding_entries_run_boundary", "paper_funding_entries",
        ["run_id", "instrument_id", "boundary"],
    )

    op.drop_constraint("uq_paper_positions_account_instrument", "paper_positions", type_="unique")
    for column in (
        sa.Column("locked_quantity", NUMERIC, nullable=False, server_default="0"),
        sa.Column("leverage", NUMERIC, nullable=False, server_default="1"),
        sa.Column("margin_used", NUMERIC, nullable=False, server_default="0"),
        sa.Column("mark_price", NUMERIC, nullable=True),
        sa.Column("unrealized_pnl", NUMERIC, nullable=False, server_default="0"),
        sa.Column("liquidation_price", NUMERIC, nullable=True),
    ):
        op.add_column("paper_positions", column)
    op.create_unique_constraint(
        "uq_paper_positions_run_instrument", "paper_positions", ["run_id", "instrument_id"]
    )

    op.create_table(
        "paper_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("available", NUMERIC, nullable=False, server_default="0"),
        sa.Column("locked", NUMERIC, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "asset", name="uq_paper_balances_run_asset"),
        sa.CheckConstraint("CAST(available AS NUMERIC) >= 0", name="ck_paper_balances_available"),
        sa.CheckConstraint("CAST(locked AS NUMERIC) >= 0", name="ck_paper_balances_locked"),
    )
    op.create_index("ix_paper_balances_account_id", "paper_balances", ["account_id"])
    op.create_index("ix_paper_balances_run_id", "paper_balances", ["run_id"])
    op.execute(sa.text(
        "INSERT INTO paper_balances (account_id, run_id, asset, available, locked) "
        "SELECT id, current_run_id, base_currency, cash, locked_cash FROM paper_accounts"
    ))

    op.create_table(
        "paper_ledger_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fill_id", sa.Integer(), sa.ForeignKey("paper_fills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset", sa.String(16), nullable=False, server_default="USDT"),
        sa.Column("cash_delta", NUMERIC, nullable=False, server_default="0"),
        sa.Column("quantity_delta", NUMERIC, nullable=False, server_default="0"),
        sa.Column("amount", NUMERIC, nullable=False, server_default="0"),
        sa.Column("metadata_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_key", name="uq_paper_ledger_events_event_key"),
        sa.CheckConstraint(
            "event_type IN ('INITIAL_DEPOSIT', 'ORDER_FILL', 'TRADING_FEE', 'REALIZED_PNL', "
            "'FUNDING', 'LIQUIDATION', 'MANUAL_RESET')",
            name="ck_paper_ledger_events_type",
        ),
    )
    for column in ("account_id", "run_id", "instrument_id", "order_id", "fill_id"):
        op.create_index(f"ix_paper_ledger_events_{column}", "paper_ledger_events", [column])
    op.create_index("ix_paper_ledger_events_run_time", "paper_ledger_events", ["run_id", "event_time"])
    op.execute(sa.text(
        "INSERT INTO paper_ledger_events "
        "(account_id, run_id, event_key, event_type, asset, cash_delta, amount, metadata_json, event_time) "
        "SELECT id, current_run_id, 'initial-' || CAST(current_run_id AS VARCHAR), 'INITIAL_DEPOSIT', "
        "base_currency, initial_cash, initial_cash, '{}', created_at FROM paper_accounts"
    ))
    op.execute(sa.text(
        "INSERT INTO paper_ledger_events "
        "(account_id, run_id, event_key, event_type, instrument_id, order_id, fill_id, asset, "
        "cash_delta, quantity_delta, amount, metadata_json, event_time) "
        "SELECT account_id, run_id, 'fill-' || CAST(id AS VARCHAR), 'ORDER_FILL', instrument_id, order_id, id, "
        "'USDT', 0, CASE WHEN side = 'buy' THEN quantity ELSE -quantity END, quantity * price, '{}', fill_time "
        "FROM paper_fills"
    ))
    op.execute(sa.text(
        "INSERT INTO paper_ledger_events "
        "(account_id, run_id, event_key, event_type, instrument_id, order_id, fill_id, asset, "
        "cash_delta, amount, metadata_json, event_time) "
        "SELECT account_id, run_id, 'fee-' || CAST(id AS VARCHAR), 'TRADING_FEE', instrument_id, order_id, id, "
        "'USDT', -fee, fee, '{}', fill_time FROM paper_fills WHERE fee <> 0"
    ))
    op.execute(sa.text(
        "INSERT INTO paper_ledger_events "
        "(account_id, run_id, event_key, event_type, instrument_id, order_id, fill_id, asset, "
        "cash_delta, amount, metadata_json, event_time) "
        "SELECT account_id, run_id, 'pnl-' || CAST(id AS VARCHAR), 'REALIZED_PNL', instrument_id, order_id, id, "
        "'USDT', realized_pnl, ABS(realized_pnl), '{}', fill_time FROM paper_fills WHERE realized_pnl <> 0"
    ))
    op.execute(sa.text(
        "INSERT INTO paper_ledger_events "
        "(account_id, run_id, event_key, event_type, instrument_id, asset, cash_delta, amount, metadata_json, event_time) "
        "SELECT account_id, run_id, 'funding-' || CAST(id AS VARCHAR), 'FUNDING', instrument_id, 'USDT', "
        "cash_delta, ABS(cash_delta), '{}', boundary FROM paper_funding_entries"
    ))


def downgrade() -> None:
    op.drop_table("paper_ledger_events")
    op.drop_table("paper_balances")

    op.drop_constraint("uq_paper_positions_run_instrument", "paper_positions", type_="unique")
    for name in ("liquidation_price", "unrealized_pnl", "mark_price", "margin_used", "leverage", "locked_quantity"):
        op.drop_column("paper_positions", name)
    op.create_unique_constraint(
        "uq_paper_positions_account_instrument", "paper_positions", ["account_id", "instrument_id"]
    )

    op.drop_constraint("uq_paper_funding_entries_run_boundary", "paper_funding_entries", type_="unique")
    op.create_unique_constraint(
        "uq_paper_funding_entries_boundary", "paper_funding_entries", ["account_id", "instrument_id", "boundary"]
    )
    op.drop_constraint("ck_paper_fills_liquidity", "paper_fills", type_="check")
    op.drop_constraint("uq_paper_fills_event_key", "paper_fills", type_="unique")
    for name in ("reason", "mark_price", "liquidity", "event_key"):
        op.drop_column("paper_fills", name)

    for constraint in ("ck_paper_orders_position_side", "ck_paper_orders_market_type", "ck_paper_orders_type"):
        op.drop_constraint(constraint, "paper_orders", type_="check")
    for name in ("cancelled_at", "leverage", "limit_price", "position_side", "market_type"):
        op.drop_column("paper_orders", name)
    op.create_check_constraint("ck_paper_orders_market_only", "paper_orders", "order_type = 'market'")

    for table in ("paper_reconciliations", "paper_positions", "paper_funding_entries", "paper_fills", "paper_orders"):
        op.drop_index(f"ix_{table}_run_id", table_name=table)
        op.drop_constraint(f"fk_{table}_run_id", table, type_="foreignkey")
        op.drop_column(table, "run_id")

    op.drop_constraint("uq_paper_accounts_user_env_key", "paper_accounts", type_="unique")
    op.create_unique_constraint("uq_paper_accounts_user_env", "paper_accounts", ["user_id", "environment"])
    op.drop_index("ix_paper_accounts_current_run_id", table_name="paper_accounts")
    op.drop_constraint("fk_paper_accounts_current_run_id", "paper_accounts", type_="foreignkey")
    for name in (
        "current_run_id", "liquidation_fee_bps", "maintenance_margin_ratio", "maker_fee_bps",
        "locked_cash", "name", "account_key",
    ):
        op.drop_column("paper_accounts", name)
    op.drop_table("paper_runs")
