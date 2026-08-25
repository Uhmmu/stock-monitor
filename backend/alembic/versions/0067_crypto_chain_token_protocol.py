"""add chain, token and protocol crypto identities

Revision ID: 0067_crypto_chain_token_protocol
Revises: 0066_crypto_identity_assets

WP 1.2: chains, chain-scoped token deployments and protocols are separate
from economic assets. ``crypto_provider_mappings`` gains token/protocol
target columns; the single-target and type-match checks are replaced so a
mapping still points at exactly one typed object. Downgrade deletes only
new-domain mapping rows (token/protocol targets) before restoring the
asset-only checks; no equity data is touched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0067_crypto_chain_token_protocol"
down_revision = "0066_crypto_identity_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blockchains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("namespace", sa.String(32), nullable=False),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.Column("native_asset_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_blockchains_slug"),
        sa.UniqueConstraint("namespace", "reference", name="uq_blockchains_namespace_reference"),
        sa.ForeignKeyConstraint(
            ["native_asset_id"], ["crypto_assets.id"], ondelete="SET NULL", name="fk_blockchains_native_asset"
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_blockchains_status"),
    )
    op.create_index("ix_blockchains_native_asset_id", "blockchains", ["native_asset_id"])

    op.create_table(
        "crypto_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("normalized_address", sa.String(128), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=True),
        sa.Column("bridged_from_token_id", sa.Integer(), nullable=True),
        sa.Column("verification_status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chain_id", "normalized_address", name="uq_crypto_tokens_chain_address"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chain_id"], ["blockchains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bridged_from_token_id"], ["crypto_tokens.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'mismatch')",
            name="ck_crypto_tokens_verification",
        ),
    )
    op.create_index("ix_crypto_tokens_asset", "crypto_tokens", ["asset_id"])
    op.create_index("ix_crypto_tokens_chain", "crypto_tokens", ["chain_id"])
    op.create_index("ix_crypto_tokens_bridged_from_token_id", "crypto_tokens", ["bridged_from_token_id"])

    op.create_table(
        "crypto_protocols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("website", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_crypto_protocols_slug"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_crypto_protocols_status"),
    )
    op.create_index("ix_crypto_protocols_category", "crypto_protocols", ["category"])

    op.create_table(
        "crypto_protocol_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("protocol_id", "asset_id", "role", name="uq_crypto_protocol_assets_role"),
        sa.ForeignKeyConstraint(["protocol_id"], ["crypto_protocols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role <> ''", name="ck_crypto_protocol_assets_role_nonempty"),
    )
    op.create_index("ix_crypto_protocol_assets_protocol_id", "crypto_protocol_assets", ["protocol_id"])
    op.create_index("ix_crypto_protocol_assets_asset_id", "crypto_protocol_assets", ["asset_id"])

    # provider mappings gain token/protocol targets; checks are replaced so a
    # mapping still carries exactly one typed target. batch mode keeps this
    # runnable on SQLite test databases and plain ALTER on PostgreSQL.
    with op.batch_alter_table("crypto_provider_mappings") as batch_op:
        batch_op.add_column(sa.Column("token_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("protocol_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_crypto_provider_mappings_token", "crypto_tokens", ["token_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_crypto_provider_mappings_protocol", "crypto_protocols", ["protocol_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_constraint("ck_crypto_provider_mappings_single_target", type_="check")
        batch_op.drop_constraint("ck_crypto_provider_mappings_asset_type_match", type_="check")
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
    op.create_index("ix_crypto_provider_mappings_token", "crypto_provider_mappings", ["token_id"])
    op.create_index("ix_crypto_provider_mappings_protocol", "crypto_provider_mappings", ["protocol_id"])


def downgrade() -> None:
    # new-domain mapping rows cannot satisfy the restored asset-only checks
    op.execute("DELETE FROM crypto_provider_mappings WHERE object_type IN ('token', 'protocol')")
    # indexes must be dropped inside the batch: the rebuild would otherwise
    # try to recreate indexes on columns that are being removed
    with op.batch_alter_table("crypto_provider_mappings") as batch_op:
        batch_op.drop_index("ix_crypto_provider_mappings_token")
        batch_op.drop_index("ix_crypto_provider_mappings_protocol")
        batch_op.drop_constraint("ck_crypto_provider_mappings_single_target", type_="check")
        batch_op.drop_constraint("ck_crypto_provider_mappings_type_match", type_="check")
        batch_op.create_check_constraint(
            "ck_crypto_provider_mappings_single_target",
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_crypto_provider_mappings_asset_type_match",
            "(object_type = 'asset') = (asset_id IS NOT NULL)",
        )
        batch_op.drop_constraint("fk_crypto_provider_mappings_protocol", type_="foreignkey")
        batch_op.drop_constraint("fk_crypto_provider_mappings_token", type_="foreignkey")
        batch_op.drop_column("protocol_id")
        batch_op.drop_column("token_id")

    op.drop_index("ix_crypto_protocol_assets_asset_id", table_name="crypto_protocol_assets")
    op.drop_index("ix_crypto_protocol_assets_protocol_id", table_name="crypto_protocol_assets")
    op.drop_table("crypto_protocol_assets")
    op.drop_index("ix_crypto_protocols_category", table_name="crypto_protocols")
    op.drop_table("crypto_protocols")
    op.drop_index("ix_crypto_tokens_bridged_from_token_id", table_name="crypto_tokens")
    op.drop_index("ix_crypto_tokens_chain", table_name="crypto_tokens")
    op.drop_index("ix_crypto_tokens_asset", table_name="crypto_tokens")
    op.drop_table("crypto_tokens")
    op.drop_index("ix_blockchains_native_asset_id", table_name="blockchains")
    op.drop_table("blockchains")
