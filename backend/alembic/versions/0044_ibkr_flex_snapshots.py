"""add normalized IBKR Flex snapshots

Revision ID: 0044_ibkr_flex_snapshots
Revises: 0043_decision_lineage
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_ibkr_flex_snapshots"
down_revision = "0043_decision_lineage"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ibkr_flex_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_type", sa.String(32), nullable=False, server_default="activity_statement"),
        sa.Column("account_id", sa.String(80)),
        sa.Column("report_from_date", sa.Date()), sa.Column("report_to_date", sa.Date()),
        sa.Column("report_period", sa.String(80)), sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
        sa.Column("source_hash", sa.String(64), nullable=False), sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("raw_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normalized_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("section_counts", JSON_VALUE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", JSON_VALUE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("user_id", "source_hash", name="uq_ibkr_sync_user_source_hash"),
    )
    op.create_index("ix_ibkr_flex_sync_runs_user_id", "ibkr_flex_sync_runs", ["user_id"])
    op.create_index("ix_ibkr_sync_user_completed", "ibkr_flex_sync_runs", ["user_id", "completed_at"])
    op.create_index("ix_ibkr_flex_sync_runs_account_id", "ibkr_flex_sync_runs", ["account_id"])
    op.create_index("ix_ibkr_flex_sync_runs_status", "ibkr_flex_sync_runs", ["status"])
    op.create_table(
        "ibkr_flex_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section", sa.String(48), nullable=False), sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False), sa.Column("account_id", sa.String(80)),
        sa.Column("symbol", sa.String(48)), sa.Column("conid", sa.String(32)), sa.Column("currency", sa.String(16)),
        sa.Column("asset_category", sa.String(32)), sa.Column("description", sa.String(512)),
        sa.Column("report_date", sa.Date()), sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("amount", sa.Numeric(38, 12)), sa.Column("quantity", sa.Numeric(38, 12)), sa.Column("price", sa.Numeric(38, 12)),
        sa.Column("raw_payload", JSON_VALUE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sync_run_id", "section", "source_id", name="uq_ibkr_record_source"),
    )
    for name, columns in (
        ("ix_ibkr_flex_records_sync_run_id", ["sync_run_id"]), ("ix_ibkr_flex_records_section", ["section"]),
        ("ix_ibkr_flex_records_account_id", ["account_id"]), ("ix_ibkr_flex_records_symbol", ["symbol"]),
        ("ix_ibkr_flex_records_conid", ["conid"]), ("ix_ibkr_flex_records_currency", ["currency"]),
        ("ix_ibkr_flex_records_asset_category", ["asset_category"]), ("ix_ibkr_flex_records_report_date", ["report_date"]),
        ("ix_ibkr_flex_records_occurred_at", ["occurred_at"]),
        ("ix_ibkr_record_run_section_date", ["sync_run_id", "section", "report_date"]),
        ("ix_ibkr_record_account_section", ["account_id", "section"]),
        ("ix_ibkr_record_symbol_section", ["symbol", "section"]),
    ):
        op.create_index(name, "ibkr_flex_records", columns)
    op.add_column("securities", sa.Column("ibkr_conid", sa.String(32)))
    op.add_column("securities", sa.Column("figi", sa.String(32)))
    op.add_column("securities", sa.Column("cusip", sa.String(32)))
    op.create_unique_constraint("uq_securities_ibkr_conid", "securities", ["ibkr_conid"])
    op.create_index("ix_securities_ibkr_conid", "securities", ["ibkr_conid"])
    op.create_index("ix_securities_figi", "securities", ["figi"])
    op.create_index("ix_securities_cusip", "securities", ["cusip"])
    op.add_column("portfolio_positions", sa.Column("authority_source", sa.String(24), nullable=False, server_default="transactions"))
    op.add_column("portfolio_positions", sa.Column("ibkr_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="SET NULL")))
    op.add_column("portfolio_positions", sa.Column("ibkr_conid", sa.String(32)))
    op.add_column("portfolio_positions", sa.Column("ibkr_market_price", sa.Float()))
    op.add_column("portfolio_positions", sa.Column("ibkr_market_value", sa.Float()))
    op.add_column("portfolio_positions", sa.Column("ibkr_unrealized_pnl", sa.Float()))
    op.add_column("portfolio_positions", sa.Column("ibkr_fx_rate_to_base", sa.Float()))
    op.add_column("portfolio_positions", sa.Column("ibkr_report_date", sa.Date()))
    op.add_column("portfolio_positions", sa.Column("ibkr_details", JSON_VALUE, nullable=False, server_default=sa.text("'{}'")))
    op.add_column("portfolio_positions", sa.Column("authority_conflicts", JSON_VALUE, nullable=False, server_default=sa.text("'[]'")))
    op.create_index("ix_portfolio_positions_ibkr_sync_run_id", "portfolio_positions", ["ibkr_sync_run_id"])
    op.create_index("ix_portfolio_positions_ibkr_conid", "portfolio_positions", ["ibkr_conid"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_positions_ibkr_conid", table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_ibkr_sync_run_id", table_name="portfolio_positions")
    for name in ("authority_conflicts", "ibkr_details", "ibkr_report_date", "ibkr_fx_rate_to_base", "ibkr_unrealized_pnl", "ibkr_market_value", "ibkr_market_price", "ibkr_conid", "ibkr_sync_run_id", "authority_source"):
        op.drop_column("portfolio_positions", name)
    op.drop_index("ix_securities_cusip", table_name="securities")
    op.drop_index("ix_securities_figi", table_name="securities")
    op.drop_index("ix_securities_ibkr_conid", table_name="securities")
    op.drop_constraint("uq_securities_ibkr_conid", "securities", type_="unique")
    for name in ("cusip", "figi", "ibkr_conid"):
        op.drop_column("securities", name)
    op.drop_table("ibkr_flex_records")
    op.drop_table("ibkr_flex_sync_runs")
