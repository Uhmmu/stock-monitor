"""add crypto news associations and observational regime persistence

Revision ID: 0073_crypto_research_enrichment
Revises: 0072_crypto_asset_fundamentals

The tables are additive.  Equity ``news_items`` rows are not rewritten and
crypto regime evidence remains observational; no Mood snapshot is touched.
"""

from alembic import op
import sqlalchemy as sa


revision = "0073_crypto_research_enrichment"
down_revision = "0072_crypto_asset_fundamentals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_news_associations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_item_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(192), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_entity_type", sa.String(32), nullable=True),
        sa.Column("provider_entity_id", sa.String(256), nullable=True),
        sa.Column("evidence_method", sa.String(32), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("association_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("association_key", name="uq_crypto_news_associations_key"),
        sa.CheckConstraint(
            "scope_type IN ('crypto_asset', 'crypto_instrument', 'crypto_market')",
            name="ck_crypto_news_associations_scope",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_crypto_news_associations_confidence",
        ),
        sa.CheckConstraint(
            "(scope_type = 'crypto_asset' AND asset_id IS NOT NULL AND instrument_id IS NULL) OR "
            "(scope_type = 'crypto_instrument' AND asset_id IS NULL AND instrument_id IS NOT NULL) OR "
            "(scope_type = 'crypto_market' AND asset_id IS NULL AND instrument_id IS NULL)",
            name="ck_crypto_news_associations_target",
        ),
    )
    op.create_index(
        "ix_crypto_news_associations_news_scope",
        "crypto_news_associations",
        ["news_item_id", "scope_type"],
    )
    op.create_index("ix_crypto_news_associations_asset", "crypto_news_associations", ["asset_id"])
    op.create_index("ix_crypto_news_associations_instrument", "crypto_news_associations", ["instrument_id"])
    op.create_index(
        "ix_crypto_news_associations_scope_key",
        "crypto_news_associations",
        ["scope_type", "scope_key"],
    )

    op.create_table(
        "crypto_regime_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("regime_version", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("threshold_hash", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="persisted_derivatives"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("snapshot_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "instrument_id", "as_of", "regime_version", "input_hash",
            name="uq_crypto_regime_snapshots_observation",
        ),
        sa.UniqueConstraint("snapshot_key", name="uq_crypto_regime_snapshots_key"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_crypto_regime_snapshots_confidence",
        ),
        sa.CheckConstraint(
            "coverage IS NULL OR (coverage >= 0 AND coverage <= 1)",
            name="ck_crypto_regime_snapshots_coverage",
        ),
    )
    op.create_index(
        "ix_crypto_regime_snapshots_instrument_time",
        "crypto_regime_snapshots",
        ["instrument_id", "as_of"],
    )
    op.create_index("ix_crypto_regime_snapshots_state", "crypto_regime_snapshots", ["state"])

    op.create_table(
        "crypto_regime_validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("validation_version", sa.String(64), nullable=False),
        sa.Column("regime_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("horizons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evaluation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "instrument_id", "validation_version", "input_hash",
            name="uq_crypto_regime_validation_runs_identity",
        ),
        sa.UniqueConstraint("run_key", name="uq_crypto_regime_validation_runs_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_crypto_regime_validation_runs_status",
        ),
        sa.CheckConstraint("evaluation_count >= 0", name="ck_crypto_regime_validation_runs_count"),
    )
    op.create_index(
        "ix_crypto_regime_validation_runs_instrument_created",
        "crypto_regime_validation_runs",
        ["instrument_id", "created_at"],
    )
    op.create_index(
        "ix_crypto_regime_validation_runs_status",
        "crypto_regime_validation_runs",
        ["status"],
    )

    op.create_table(
        "crypto_research_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("coverage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], ["crypto_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("idempotency_key", name="uq_crypto_research_reports_idempotency"),
    )
    op.create_index(
        "ix_crypto_research_reports_asset_created",
        "crypto_research_reports",
        ["asset_id", "created_at"],
    )
    op.create_index(
        "ix_crypto_research_reports_instrument_created",
        "crypto_research_reports",
        ["instrument_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crypto_research_reports_instrument_created",
        table_name="crypto_research_reports",
    )
    op.drop_index(
        "ix_crypto_research_reports_asset_created",
        table_name="crypto_research_reports",
    )
    op.drop_table("crypto_research_reports")

    op.drop_index("ix_crypto_regime_validation_runs_status", table_name="crypto_regime_validation_runs")
    op.drop_index(
        "ix_crypto_regime_validation_runs_instrument_created",
        table_name="crypto_regime_validation_runs",
    )
    op.drop_table("crypto_regime_validation_runs")

    op.drop_index("ix_crypto_regime_snapshots_state", table_name="crypto_regime_snapshots")
    op.drop_index(
        "ix_crypto_regime_snapshots_instrument_time",
        table_name="crypto_regime_snapshots",
    )
    op.drop_table("crypto_regime_snapshots")

    op.drop_index("ix_crypto_news_associations_scope_key", table_name="crypto_news_associations")
    op.drop_index("ix_crypto_news_associations_instrument", table_name="crypto_news_associations")
    op.drop_index("ix_crypto_news_associations_asset", table_name="crypto_news_associations")
    op.drop_index("ix_crypto_news_associations_news_scope", table_name="crypto_news_associations")
    op.drop_table("crypto_news_associations")
