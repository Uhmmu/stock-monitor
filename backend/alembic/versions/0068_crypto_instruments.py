"""add crypto exchange instruments and instrument mapping target

Revision ID: 0068_crypto_instruments
Revises: 0067_crypto_chain_token_protocol

WP 1.3: venue instruments are persisted with exact (venue, provider_symbol,
kind) identity — BTCUSDT spot and perpetual are different rows. Provider
mappings gain the instrument target column; checks become the final 4-way
single-target/type-match pair. Downgrade deletes only instrument-target
mapping rows; no equity data is touched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0068_crypto_instruments"
down_revision = "0067_crypto_chain_token_protocol"
branch_labels = None
depends_on = None


SINGLE_TARGET_4WAY = (
    "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN token_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN protocol_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN instrument_id IS NULL THEN 0 ELSE 1 END) = 1"
)
TYPE_MATCH_4WAY = (
    "((object_type = 'asset') = (asset_id IS NOT NULL))"
    " AND ((object_type = 'token') = (token_id IS NOT NULL))"
    " AND ((object_type = 'protocol') = (protocol_id IS NOT NULL))"
    " AND ((object_type = 'instrument') = (instrument_id IS NOT NULL))"
)


def upgrade() -> None:
    op.create_table(
        "crypto_instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("provider_symbol", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("base_asset_id", sa.Integer(), nullable=False),
        sa.Column("quote_asset_id", sa.Integer(), nullable=False),
        sa.Column("settlement_asset_id", sa.Integer(), nullable=True),
        sa.Column("contract_size", sa.Numeric(38, 12), nullable=True),
        sa.Column("tick_size", sa.Numeric(38, 12), nullable=True),
        sa.Column("step_size", sa.Numeric(38, 12), nullable=True),
        sa.Column("min_notional", sa.Numeric(38, 12), nullable=True),
        sa.Column("price_precision", sa.Integer(), nullable=True),
        sa.Column("quantity_precision", sa.Integer(), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="trading"),
        sa.Column("listing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delisting_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calendar", sa.String(8), nullable=False, server_default="utc"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("venue", "provider_symbol", "kind", name="uq_crypto_instruments_venue_symbol_kind"),
        sa.ForeignKeyConstraint(["base_asset_id"], ["crypto_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quote_asset_id"], ["crypto_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settlement_asset_id"], ["crypto_assets.id"], ondelete="SET NULL"),
        sa.CheckConstraint("kind IN ('spot', 'perpetual', 'future')", name="ck_crypto_instruments_kind"),
        sa.CheckConstraint(
            "market IN ('spot', 'usdm_futures', 'coinm_futures')", name="ck_crypto_instruments_market"
        ),
        sa.CheckConstraint(
            "status IN ('trading', 'halted', 'delisted', 'inactive')", name="ck_crypto_instruments_status"
        ),
        sa.CheckConstraint("calendar = 'utc'", name="ck_crypto_instruments_utc_calendar"),
    )
    op.create_index(
        "ix_crypto_instruments_assets_kind_status",
        "crypto_instruments",
        ["base_asset_id", "quote_asset_id", "kind", "status"],
    )
    op.create_index("ix_crypto_instruments_status", "crypto_instruments", ["status"])
    op.create_index("ix_crypto_instruments_settlement_asset_id", "crypto_instruments", ["settlement_asset_id"])

    with op.batch_alter_table("crypto_provider_mappings") as batch_op:
        batch_op.add_column(sa.Column("instrument_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_crypto_provider_mappings_instrument", "crypto_instruments",
            ["instrument_id"], ["id"], ondelete="CASCADE",
        )
        batch_op.drop_constraint("ck_crypto_provider_mappings_single_target", type_="check")
        batch_op.drop_constraint("ck_crypto_provider_mappings_type_match", type_="check")
        batch_op.create_check_constraint(
            "ck_crypto_provider_mappings_single_target", SINGLE_TARGET_4WAY
        )
        batch_op.create_check_constraint("ck_crypto_provider_mappings_type_match", TYPE_MATCH_4WAY)
    op.create_index(
        "ix_crypto_provider_mappings_instrument", "crypto_provider_mappings", ["instrument_id"]
    )


def downgrade() -> None:
    op.execute("DELETE FROM crypto_provider_mappings WHERE object_type = 'instrument'")
    with op.batch_alter_table("crypto_provider_mappings") as batch_op:
        batch_op.drop_index("ix_crypto_provider_mappings_instrument")
        batch_op.drop_constraint("ck_crypto_provider_mappings_single_target", type_="check")
        batch_op.drop_constraint("ck_crypto_provider_mappings_type_match", type_="check")
        batch_op.create_check_constraint(
            "ck_crypto_provider_mappings_single_target",
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN token_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN protocol_id IS NULL THEN 0 ELSE 1 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_crypto_provider_mappings_type_match",
            "((object_type = 'asset') = (asset_id IS NOT NULL))"
            " AND ((object_type = 'token') = (token_id IS NOT NULL))"
            " AND ((object_type = 'protocol') = (protocol_id IS NOT NULL))",
        )
        batch_op.drop_constraint("fk_crypto_provider_mappings_instrument", type_="foreignkey")
        batch_op.drop_column("instrument_id")

    op.drop_index("ix_crypto_instruments_settlement_asset_id", table_name="crypto_instruments")
    op.drop_index("ix_crypto_instruments_status", table_name="crypto_instruments")
    op.drop_index("ix_crypto_instruments_assets_kind_status", table_name="crypto_instruments")
    op.drop_table("crypto_instruments")
