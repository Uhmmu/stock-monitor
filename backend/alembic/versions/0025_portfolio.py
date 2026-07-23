"""portfolio holdings module

Revision ID: 0025_portfolio
Revises: 0024_market_news
Create Date: 2026-07-23

新增持仓模块的四张表。全部为新增，不修改也不删除既有表，
现有用户数据（自选股、交易日志等）不受影响。
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_portfolio"
down_revision = "0024_market_news"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("name", sa.String(length=120), nullable=False, server_default="我的持仓"),
        sa.Column("base_currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("cash_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "slug", name="uq_portfolios_user_slug"),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])

    op.create_table(
        "trade_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("transaction_type", sa.String(length=16), nullable=False, server_default="buy"),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("account", sa.String(length=80), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("quantity >= 0", name="ck_trade_transactions_quantity"),
        sa.CheckConstraint("price >= 0", name="ck_trade_transactions_price"),
        sa.CheckConstraint("fees >= 0", name="ck_trade_transactions_fees"),
    )
    op.create_index("ix_trade_transactions_portfolio_id", "trade_transactions", ["portfolio_id"])
    op.create_index("ix_trade_transactions_security_id", "trade_transactions", ["security_id"])
    op.create_index("ix_trade_transactions_symbol", "trade_transactions", ["symbol"])
    op.create_index("ix_trade_transactions_transaction_type", "trade_transactions", ["transaction_type"])
    op.create_index("ix_trade_transactions_trade_date", "trade_transactions", ["trade_date"])
    op.create_index("ix_trade_transactions_portfolio_symbol", "trade_transactions", ["portfolio_id", "symbol"])

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("total_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("last_transaction_at", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_positions_symbol"),
    )
    op.create_index("ix_portfolio_positions_portfolio_id", "portfolio_positions", ["portfolio_id"])
    op.create_index("ix_portfolio_positions_security_id", "portfolio_positions", ["security_id"])
    op.create_index("ix_portfolio_positions_symbol", "portfolio_positions", ["symbol"])

    op.create_table(
        "portfolio_position_lots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("source_transaction_id", sa.Integer(), sa.ForeignKey("trade_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("purchase_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("allocated_fees", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_portfolio_position_lots_portfolio_id", "portfolio_position_lots", ["portfolio_id"])
    op.create_index("ix_portfolio_position_lots_symbol", "portfolio_position_lots", ["symbol", "portfolio_id"])


def downgrade() -> None:
    op.drop_table("portfolio_position_lots")
    op.drop_table("portfolio_positions")
    op.drop_table("trade_transactions")
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.drop_table("portfolios")
