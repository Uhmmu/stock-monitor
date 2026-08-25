"""add UTC multi-timeframe market candles

Revision ID: 0070_market_candles
Revises: 0069_crypto_collection_runs

WP 2.3: closed 1h/4h/1d UTC candle store with typed OHLC/volumes at high
numeric precision, provider/price-type/feed provenance and an identity key
that prevents cross-authority overwrites. Equity ``historical_prices`` and
``intraday_bars`` remain untouched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0070_market_candles"
down_revision = "0069_crypto_collection_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_candles",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("open_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("close_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("price_type", sa.String(8), nullable=False, server_default="trade"),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("feed", sa.String(8), nullable=False, server_default="rest"),
        sa.Column("open", sa.Numeric(38, 18), nullable=False),
        sa.Column("high", sa.Numeric(38, 18), nullable=False),
        sa.Column("low", sa.Numeric(38, 18), nullable=False),
        sa.Column("close", sa.Numeric(38, 18), nullable=False),
        sa.Column("base_volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("quote_volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("taker_buy_base_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("taker_buy_quote_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("trades", sa.Integer(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "instrument_id", "interval", "open_time_ms", "provider", "price_type",
            name="uq_market_candles_key",
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
        sa.CheckConstraint("interval IN ('1h', '4h', '1d')", name="ck_market_candles_interval"),
        sa.CheckConstraint("price_type IN ('trade', 'mark', 'index', 'premium')", name="ck_market_candles_price_type"),
        sa.CheckConstraint("feed IN ('rest', 'stream')", name="ck_market_candles_feed"),
        # CAST keeps the comparisons numeric on SQLite's text-backed decimals;
        # on PostgreSQL NUMERIC the cast is a no-op.
        sa.CheckConstraint("CAST(high AS NUMERIC) >= CAST(low AS NUMERIC)", name="ck_market_candles_high_low"),
        sa.CheckConstraint(
            "CAST(high AS NUMERIC) >= CAST(open AS NUMERIC) AND CAST(high AS NUMERIC) >= CAST(close AS NUMERIC)",
            name="ck_market_candles_high_extremes",
        ),
        sa.CheckConstraint(
            "CAST(low AS NUMERIC) <= CAST(open AS NUMERIC) AND CAST(low AS NUMERIC) <= CAST(close AS NUMERIC)",
            name="ck_market_candles_low_extremes",
        ),
        sa.CheckConstraint(
            "CAST(base_volume AS NUMERIC) >= 0 AND CAST(quote_volume AS NUMERIC) >= 0",
            name="ck_market_candles_volume_nonnegative",
        ),
    )
    op.create_index(
        "ix_market_candles_instrument_interval_time",
        "market_candles",
        ["instrument_id", "interval", "open_time_ms"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_candles_instrument_interval_time", table_name="market_candles")
    op.drop_table("market_candles")
