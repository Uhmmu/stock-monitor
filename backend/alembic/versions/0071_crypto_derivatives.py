"""add crypto funding events and typed derivatives snapshots

Revision ID: 0071_crypto_derivatives
Revises: 0070_market_candles

WP 4.3 keeps funding events on their provider event clock and stores the
compatible periodic derivatives fields in one wide, typed row.  Missing
provider fields stay NULL; no ratio or price is inferred by the database.
"""

from alembic import op
import sqlalchemy as sa


revision = "0071_crypto_derivatives"
down_revision = "0070_market_candles"
branch_labels = None
depends_on = None


NUMERIC = sa.Numeric(38, 18)


def upgrade() -> None:
    op.create_table(
        "crypto_funding_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("funding_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding_rate", NUMERIC, nullable=False),
        sa.Column("predicted_rate", NUMERIC, nullable=True),
        sa.Column("mark_price", NUMERIC, nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "instrument_id", "funding_time", "provider",
            name="uq_crypto_funding_rates_key",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_crypto_funding_rates_revision"),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_crypto_funding_rates_instrument_time",
        "crypto_funding_rates",
        ["instrument_id", "funding_time"],
    )
    op.create_index(
        "ix_crypto_funding_rates_provider_time",
        "crypto_funding_rates",
        ["provider", "funding_time"],
    )

    op.create_table(
        "crypto_derivatives_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mark_price", NUMERIC, nullable=True),
        sa.Column("index_price", NUMERIC, nullable=True),
        sa.Column("basis", NUMERIC, nullable=True),
        sa.Column("basis_rate", NUMERIC, nullable=True),
        sa.Column("premium", NUMERIC, nullable=True),
        sa.Column("mark_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_interest_base", NUMERIC, nullable=True),
        sa.Column("open_interest_quote", NUMERIC, nullable=True),
        sa.Column("open_interest_usd", NUMERIC, nullable=True),
        sa.Column("long_short_ratio", NUMERIC, nullable=True),
        sa.Column("top_trader_account_ratio", NUMERIC, nullable=True),
        sa.Column("top_trader_position_ratio", NUMERIC, nullable=True),
        sa.Column("taker_buy_sell_ratio", NUMERIC, nullable=True),
        sa.Column("taker_buy_volume", NUMERIC, nullable=True),
        sa.Column("taker_sell_volume", NUMERIC, nullable=True),
        sa.Column("futures_volume_base", NUMERIC, nullable=True),
        sa.Column("futures_volume_quote", NUMERIC, nullable=True),
        sa.Column("futures_volume_usd", NUMERIC, nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "instrument_id", "interval", "observed_at", "provider",
            name="uq_crypto_derivatives_metrics_key",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_crypto_derivatives_metrics_revision"),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_crypto_derivatives_metrics_instrument_interval_time",
        "crypto_derivatives_metrics",
        ["instrument_id", "interval", "observed_at"],
    )
    op.create_index(
        "ix_crypto_derivatives_metrics_provider_time",
        "crypto_derivatives_metrics",
        ["provider", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crypto_derivatives_metrics_provider_time",
        table_name="crypto_derivatives_metrics",
    )
    op.drop_index(
        "ix_crypto_derivatives_metrics_instrument_interval_time",
        table_name="crypto_derivatives_metrics",
    )
    op.drop_table("crypto_derivatives_metrics")
    op.drop_index(
        "ix_crypto_funding_rates_provider_time",
        table_name="crypto_funding_rates",
    )
    op.drop_index(
        "ix_crypto_funding_rates_instrument_time",
        table_name="crypto_funding_rates",
    )
    op.drop_table("crypto_funding_rates")
