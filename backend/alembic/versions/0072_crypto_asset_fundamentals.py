"""add CoinGecko reference metadata and market fundamentals

Revision ID: 0072_crypto_asset_fundamentals
Revises: 0071_crypto_derivatives

WP 5.1/5.2 keep provider enrichment additive.  Canonical crypto identity and
Binance market rows remain untouched; missing CoinGecko values are nullable
facts rather than synthesized estimates.
"""

from alembic import op
import sqlalchemy as sa


revision = "0072_crypto_asset_fundamentals"
down_revision = "0071_crypto_derivatives"
branch_labels = None
depends_on = None
NUMERIC = sa.Numeric(38, 18)


def upgrade() -> None:
    op.create_table(
        "crypto_asset_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("canonical_name", sa.String(256), nullable=True),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("website_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("contract_references", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reference_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source", sa.String(32), nullable=False, server_default="coingecko"),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_status", sa.String(16), nullable=False, server_default="fresh"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_id", name="uq_crypto_asset_references_provider_id"),
        sa.UniqueConstraint("asset_id", "provider", name="uq_crypto_asset_references_asset_provider"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 0", name="ck_crypto_asset_references_revision"),
    )
    op.create_index("ix_crypto_asset_references_asset", "crypto_asset_references", ["asset_id"])
    op.create_index(
        "ix_crypto_asset_references_provider_timestamp",
        "crypto_asset_references",
        ["provider", "provider_timestamp"],
    )

    op.create_table(
        "crypto_asset_fundamental_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="coingecko"),
        sa.Column("currency", sa.String(16), nullable=False, server_default="usd"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_cap", NUMERIC, nullable=True),
        sa.Column("fully_diluted_valuation", NUMERIC, nullable=True),
        sa.Column("circulating_supply", NUMERIC, nullable=True),
        sa.Column("total_supply", NUMERIC, nullable=True),
        sa.Column("max_supply", NUMERIC, nullable=True),
        sa.Column("market_cap_rank", sa.Integer(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("freshness_status", sa.String(16), nullable=False, server_default="fresh"),
        sa.Column("quality", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "asset_id", "provider", "observed_at",
            name="uq_crypto_asset_fundamental_snapshots_observation",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 0", name="ck_crypto_asset_fundamental_snapshots_revision"),
        sa.CheckConstraint(
            "coverage >= 0 AND coverage <= 1",
            name="ck_crypto_asset_fundamental_snapshots_coverage",
        ),
        sa.CheckConstraint(
            "market_cap_rank IS NULL OR market_cap_rank >= 1",
            name="ck_crypto_asset_fundamental_snapshots_rank",
        ),
    )
    op.create_index(
        "ix_crypto_asset_fundamental_snapshots_asset_time",
        "crypto_asset_fundamental_snapshots",
        ["asset_id", "observed_at"],
    )
    op.create_index(
        "ix_crypto_asset_fundamental_snapshots_provider_time",
        "crypto_asset_fundamental_snapshots",
        ["provider", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crypto_asset_fundamental_snapshots_provider_time",
        table_name="crypto_asset_fundamental_snapshots",
    )
    op.drop_index(
        "ix_crypto_asset_fundamental_snapshots_asset_time",
        table_name="crypto_asset_fundamental_snapshots",
    )
    op.drop_table("crypto_asset_fundamental_snapshots")
    op.drop_index(
        "ix_crypto_asset_references_provider_timestamp",
        table_name="crypto_asset_references",
    )
    op.drop_index("ix_crypto_asset_references_asset", table_name="crypto_asset_references")
    op.drop_table("crypto_asset_references")
