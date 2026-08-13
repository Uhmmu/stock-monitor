"""add bounded options analytics history and cache

Revision ID: 0058_options_analytics
Revises: 0057_industry_synthetic_indexes
"""

from alembic import op
import sqlalchemy as sa


revision = "0058_options_analytics"
down_revision = "0057_industry_synthetic_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "options_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL")),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("sector_node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False, server_default="yfinance"),
        sa.Column("underlying_price", sa.Float()),
        sa.Column("nearest_expiration", sa.Date()),
        sa.Column("next_expiration", sa.Date()),
        sa.Column("days_to_expiration", sa.Integer()),
        sa.Column("active_contracts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("call_volume", sa.BigInteger()),
        sa.Column("put_volume", sa.BigInteger()),
        sa.Column("call_open_interest", sa.BigInteger()),
        sa.Column("put_open_interest", sa.BigInteger()),
        sa.Column("put_call_volume_ratio", sa.Float()),
        sa.Column("put_call_oi_ratio", sa.Float()),
        sa.Column("atm_iv", sa.Float()),
        sa.Column("near_term_iv", sa.Float()),
        sa.Column("next_term_iv", sa.Float()),
        sa.Column("iv_change", sa.Float()),
        sa.Column("downside_skew", sa.Float()),
        sa.Column("upside_skew", sa.Float()),
        sa.Column("activity_score", sa.Float()),
        sa.Column("activity_status", sa.String(32), nullable=False, server_default="insufficient_history"),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "trading_date", name="uq_options_snapshots_symbol_date"),
        sa.CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="ck_options_snapshots_quality"),
        sa.CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_options_snapshots_coverage"),
    )
    for column in ("security_id", "symbol", "trading_date", "asset_type", "sector_node_id", "status", "fetched_at"):
        op.create_index(f"ix_options_snapshots_{column}", "options_snapshots", [column])
    op.create_index("ix_options_snapshots_symbol_date", "options_snapshots", ["symbol", "trading_date"])

    op.create_table(
        "options_chain_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False, server_default="yfinance"),
        sa.Column("calls_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("puts_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("contract_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "expiration", name="uq_options_chain_cache_symbol_expiration"),
    )
    for column in ("symbol", "expiration", "expires_at"):
        op.create_index(f"ix_options_chain_cache_{column}", "options_chain_cache", [column])

    op.create_table(
        "options_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("trigger_type", sa.String(24), nullable=False, server_default="scheduled"),
        sa.Column("symbols_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_filtered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_quality_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_options_sync_runs_started_at", "options_sync_runs", ["started_at"])
    op.create_index("ix_options_sync_runs_started", "options_sync_runs", ["started_at"])
    op.create_index("ix_options_sync_runs_status", "options_sync_runs", ["status"])


def downgrade() -> None:
    op.drop_table("options_sync_runs")
    op.drop_table("options_chain_cache")
    op.drop_table("options_snapshots")
