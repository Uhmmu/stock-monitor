"""add paper trading account, orders, fills, funding and reconciliation

Revision ID: 0078_quant_paper
Revises: 0077_quant_signals

Goal 5 WP 12.1/WP 12.2: a separate risk/order boundary converts paper signals
into virtual orders and fills.  Fills plus funding entries are the durable
ledger; positions and cash are derived caches reconciled from that ledger.
No PortfolioPosition, TradeTransaction or IBKR state is touched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0078_quant_paper"
down_revision = "0077_quant_signals"
branch_labels = None
depends_on = None


NUMERIC = sa.Numeric(38, 18)
JSON = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="paper"),
        sa.Column("base_currency", sa.String(8), nullable=False, server_default="USDT"),
        sa.Column("initial_cash", NUMERIC, nullable=False),
        sa.Column("cash", NUMERIC, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("taker_fee_bps", NUMERIC, nullable=False, server_default="5"),
        sa.Column("spread_bps", NUMERIC, nullable=False, server_default="2"),
        sa.Column("slippage_bps", NUMERIC, nullable=False, server_default="2"),
        sa.Column("leverage_cap", NUMERIC, nullable=False, server_default="1"),
        sa.Column("fill_policy", sa.String(24), nullable=False, server_default="paper-fill-v1"),
        sa.Column("last_funding_boundary", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "environment", name="uq_paper_accounts_user_env"),
        sa.CheckConstraint("environment = 'paper'", name="ck_paper_accounts_paper_only"),
        sa.CheckConstraint("status IN ('active', 'paused')", name="ck_paper_accounts_status"),
        sa.CheckConstraint("CAST(initial_cash AS NUMERIC) > 0", name="ck_paper_accounts_initial_cash_positive"),
        sa.CheckConstraint(
            "CAST(leverage_cap AS NUMERIC) >= 1 AND CAST(leverage_cap AS NUMERIC) <= 3",
            name="ck_paper_accounts_leverage_bounds",
        ),
    )
    op.create_index("ix_paper_accounts_status", "paper_accounts", ["status"])
    op.create_index("ix_paper_accounts_user_id", "paper_accounts", ["user_id"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("quant_signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(12), nullable=False, server_default="market"),
        sa.Column("intended_quantity", NUMERIC, nullable=False),
        sa.Column("filled_quantity", NUMERIC, nullable=False, server_default="0"),
        sa.Column("reference_price", NUMERIC, nullable=False),
        sa.Column("avg_fill_price", NUMERIC, nullable=True),
        sa.Column("fee", NUMERIC, nullable=False, server_default="0"),
        sa.Column("spread_cost", NUMERIC, nullable=False, server_default="0"),
        sa.Column("slippage_cost", NUMERIC, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_order_id", name="uq_paper_orders_client_order_id"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_paper_orders_side"),
        sa.CheckConstraint("order_type = 'market'", name="ck_paper_orders_market_only"),
        sa.CheckConstraint(
            "status IN ('pending', 'partially_filled', 'filled', 'rejected', 'expired', 'cancelled')",
            name="ck_paper_orders_status",
        ),
        sa.CheckConstraint("CAST(intended_quantity AS NUMERIC) > 0", name="ck_paper_orders_quantity_positive"),
    )
    op.create_index("ix_paper_orders_account_created", "paper_orders", ["account_id", "created_at"])
    op.create_index("ix_paper_orders_user_created", "paper_orders", ["user_id", "created_at"])
    op.create_index("ix_paper_orders_user_id", "paper_orders", ["user_id"])
    op.create_index("ix_paper_orders_account_id", "paper_orders", ["account_id"])
    op.create_index("ix_paper_orders_signal_id", "paper_orders", ["signal_id"])
    op.create_index("ix_paper_orders_instrument_id", "paper_orders", ["instrument_id"])

    op.create_table(
        "paper_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", NUMERIC, nullable=False),
        sa.Column("price", NUMERIC, nullable=False),
        sa.Column("fee", NUMERIC, nullable=False, server_default="0"),
        sa.Column("spread_cost", NUMERIC, nullable=False, server_default="0"),
        sa.Column("slippage_cost", NUMERIC, nullable=False, server_default="0"),
        sa.Column("realized_pnl", NUMERIC, nullable=False, server_default="0"),
        sa.Column("fill_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_paper_fills_side"),
        sa.CheckConstraint("CAST(quantity AS NUMERIC) > 0", name="ck_paper_fills_quantity_positive"),
    )
    op.create_index("ix_paper_fills_account_time", "paper_fills", ["account_id", "fill_time"])
    op.create_index("ix_paper_fills_order", "paper_fills", ["order_id"])
    op.create_index("ix_paper_fills_order_id", "paper_fills", ["order_id"])
    op.create_index("ix_paper_fills_account_id", "paper_fills", ["account_id"])
    op.create_index("ix_paper_fills_user_id", "paper_fills", ["user_id"])
    op.create_index("ix_paper_fills_instrument_id", "paper_fills", ["instrument_id"])

    op.create_table(
        "paper_funding_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boundary", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate", NUMERIC, nullable=False),
        sa.Column("quantity", NUMERIC, nullable=False),
        sa.Column("price", NUMERIC, nullable=False),
        sa.Column("cash_delta", NUMERIC, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "instrument_id", "boundary", name="uq_paper_funding_entries_boundary"),
    )
    op.create_index("ix_paper_funding_entries_account_boundary", "paper_funding_entries", ["account_id", "boundary"])
    op.create_index("ix_paper_funding_entries_account_id", "paper_funding_entries", ["account_id"])
    op.create_index("ix_paper_funding_entries_user_id", "paper_funding_entries", ["user_id"])
    op.create_index("ix_paper_funding_entries_instrument_id", "paper_funding_entries", ["instrument_id"])

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", NUMERIC, nullable=False, server_default="0"),
        sa.Column("avg_entry_price", NUMERIC, nullable=False, server_default="0"),
        sa.Column("realized_pnl", NUMERIC, nullable=False, server_default="0"),
        sa.Column("total_fees", NUMERIC, nullable=False, server_default="0"),
        sa.Column("last_fill_id", sa.Integer(), sa.ForeignKey("paper_fills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "instrument_id", name="uq_paper_positions_account_instrument"),
    )
    op.create_index("ix_paper_positions_account", "paper_positions", ["account_id"])
    op.create_index("ix_paper_positions_account_id", "paper_positions", ["account_id"])
    op.create_index("ix_paper_positions_instrument_id", "paper_positions", ["instrument_id"])
    op.create_index("ix_paper_positions_last_fill_id", "paper_positions", ["last_fill_id"])

    op.create_table(
        "paper_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("funding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cash_from_ledger", NUMERIC, nullable=False, server_default="0"),
        sa.Column("cash_cached", NUMERIC, nullable=False, server_default="0"),
        sa.Column("mismatches", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("warnings", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ok', 'mismatch', 'repaired')", name="ck_paper_reconciliations_status"),
    )
    op.create_index("ix_paper_reconciliations_account_created", "paper_reconciliations", ["account_id", "created_at"])
    op.create_index("ix_paper_reconciliations_account_id", "paper_reconciliations", ["account_id"])


def downgrade() -> None:
    op.drop_table("paper_reconciliations")
    op.drop_table("paper_positions")
    op.drop_table("paper_funding_entries")
    op.drop_table("paper_fills")
    op.drop_table("paper_orders")
    op.drop_table("paper_accounts")
