"""add canonical crypto assets and provider mappings

Revision ID: 0066_crypto_identity_assets
Revises: 0065_admin_user_management

WP 1.1 of the crypto/quant program: canonical crypto identity is a new
additive graph; equity ``securities`` rows are untouched. Provider
namespaces carry the market (binance_spot/binance_usdm) and one provider id
maps to exactly one typed target. Target columns for token/protocol/
instrument objects arrive with migrations 0067/0068; until then the
single-target check rejects every non-asset mapping, fail closed.
"""

from alembic import op
import sqlalchemy as sa


revision = "0066_crypto_identity_assets"
down_revision = "0065_admin_user_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("asset_kind", sa.String(16), nullable=False, server_default="coin"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("wraps_asset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_crypto_assets_slug"),
        sa.ForeignKeyConstraint(["wraps_asset_id"], ["crypto_assets.id"], ondelete="SET NULL"),
        sa.CheckConstraint("asset_kind IN ('coin', 'token')", name="ck_crypto_assets_kind"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'delisted')", name="ck_crypto_assets_status"),
        sa.CheckConstraint("id <> wraps_asset_id", name="ck_crypto_assets_no_self_wrap"),
    )
    op.create_index("ix_crypto_assets_symbol", "crypto_assets", ["symbol"])
    op.create_index("ix_crypto_assets_status", "crypto_assets", ["status"])
    op.create_index("ix_crypto_assets_wraps_asset_id", "crypto_assets", ["wraps_asset_id"])

    op.create_table(
        "crypto_symbol_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol", name="uq_crypto_symbol_aliases_symbol"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_crypto_symbol_aliases_asset_id", "crypto_symbol_aliases", ["asset_id"])

    op.create_table(
        "crypto_provider_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(16), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "object_type", "provider_id", name="uq_crypto_provider_mappings_key"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "object_type IN ('asset', 'token', 'protocol', 'instrument')",
            name="ck_crypto_provider_mappings_object_type",
        ),
        sa.CheckConstraint(
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_crypto_provider_mappings_single_target",
        ),
        sa.CheckConstraint(
            "(object_type = 'asset') = (asset_id IS NOT NULL)",
            name="ck_crypto_provider_mappings_asset_type_match",
        ),
    )
    op.create_index("ix_crypto_provider_mappings_asset", "crypto_provider_mappings", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_crypto_provider_mappings_asset", table_name="crypto_provider_mappings")
    op.drop_table("crypto_provider_mappings")
    op.drop_index("ix_crypto_symbol_aliases_asset_id", table_name="crypto_symbol_aliases")
    op.drop_table("crypto_symbol_aliases")
    op.drop_index("ix_crypto_assets_wraps_asset_id", table_name="crypto_assets")
    op.drop_index("ix_crypto_assets_status", table_name="crypto_assets")
    op.drop_index("ix_crypto_assets_symbol", table_name="crypto_assets")
    op.drop_table("crypto_assets")
