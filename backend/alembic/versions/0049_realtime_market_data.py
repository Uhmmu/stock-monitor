"""add realtime intraday market data and canonical news provenance

Revision ID: 0049_realtime_market_data
Revises: 0048_alpha_vantage_macro
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0049_realtime_market_data"
down_revision = "0048_alpha_vantage_macro"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.add_column(sa.Column("feed", sa.String(length=32), nullable=True))
    op.create_table(
        "intraday_bars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False, server_default="1m"),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("vwap", sa.Numeric(20, 8), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("feed", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("market_session", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("is_backfill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("interval IN ('1m', '5m', '15m')", name="ck_intraday_bars_interval"),
        sa.CheckConstraint("high >= low", name="ck_intraday_bars_high_low"),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name="ck_intraday_bars_volume"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timestamp", "interval", "provider", "feed", name="uq_intraday_bars_source_minute"),
    )
    op.create_index("ix_intraday_bars_symbol", "intraday_bars", ["symbol"])
    op.create_index("ix_intraday_bars_timestamp", "intraday_bars", ["timestamp"])
    op.create_index("ix_intraday_bars_provider", "intraday_bars", ["provider"])
    op.create_index("ix_intraday_bars_market_session", "intraday_bars", ["market_session"])
    op.create_index("ix_intraday_bars_symbol_interval_timestamp", "intraday_bars", ["symbol", "interval", "timestamp"])

    op.create_table(
        "market_monitor_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("feed", sa.String(length=32), nullable=True),
        sa.Column("market_session", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_market_monitor_events_event_key"),
    )
    op.create_index("ix_market_monitor_events_symbol", "market_monitor_events", ["symbol"])
    op.create_index("ix_market_monitor_events_event_type", "market_monitor_events", ["event_type"])
    op.create_index("ix_market_monitor_events_severity", "market_monitor_events", ["severity"])
    op.create_index("ix_market_monitor_events_timestamp", "market_monitor_events", ["timestamp"])
    op.create_index("ix_market_monitor_events_symbol_timestamp", "market_monitor_events", ["symbol", "timestamp"])

    with op.batch_alter_table("news_items") as batch_op:
        batch_op.add_column(sa.Column("canonical_story_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("provider_sources", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("provider_metadata", sa.JSON(), nullable=True))
        batch_op.create_index("ix_news_items_canonical_story_id", ["canonical_story_id"])


def downgrade() -> None:
    with op.batch_alter_table("news_items") as batch_op:
        batch_op.drop_index("ix_news_items_canonical_story_id")
        batch_op.drop_column("provider_metadata")
        batch_op.drop_column("provider_sources")
        batch_op.drop_column("canonical_story_id")
    op.drop_index("ix_market_monitor_events_symbol_timestamp", table_name="market_monitor_events")
    op.drop_index("ix_market_monitor_events_timestamp", table_name="market_monitor_events")
    op.drop_index("ix_market_monitor_events_severity", table_name="market_monitor_events")
    op.drop_index("ix_market_monitor_events_event_type", table_name="market_monitor_events")
    op.drop_index("ix_market_monitor_events_symbol", table_name="market_monitor_events")
    op.drop_table("market_monitor_events")
    op.drop_index("ix_intraday_bars_symbol_interval_timestamp", table_name="intraday_bars")
    op.drop_index("ix_intraday_bars_market_session", table_name="intraday_bars")
    op.drop_index("ix_intraday_bars_provider", table_name="intraday_bars")
    op.drop_index("ix_intraday_bars_timestamp", table_name="intraday_bars")
    op.drop_index("ix_intraday_bars_symbol", table_name="intraday_bars")
    op.drop_table("intraday_bars")
    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.drop_column("feed")
