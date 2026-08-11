"""persist canonical industry taxonomy and daily sector pulse data

Revision ID: 0051_industry_pulse
Revises: 0050_news_enrichment
"""

from alembic import op
import sqlalchemy as sa


revision = "0051_industry_pulse"
down_revision = "0050_news_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_pulse_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("taxonomy", sa.String(length=16), nullable=False, server_default="base"),
        sa.Column("node_key", sa.String(length=192), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=192), nullable=False),
        sa.Column("name_zh", sa.String(length=192), nullable=True),
        sa.Column("level", sa.String(length=24), nullable=False, server_default="leaf"),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("taxonomy", "node_key", name="uq_industry_pulse_nodes_taxonomy_key"),
        sa.CheckConstraint("taxonomy IN ('base', 'ai')", name="ck_industry_pulse_nodes_taxonomy"),
    )
    op.create_index("ix_industry_pulse_nodes_taxonomy", "industry_pulse_nodes", ["taxonomy"])
    op.create_index("ix_industry_pulse_nodes_node_key", "industry_pulse_nodes", ["node_key"])
    op.create_index("ix_industry_pulse_nodes_slug", "industry_pulse_nodes", ["slug"])
    op.create_index("ix_industry_pulse_nodes_level", "industry_pulse_nodes", ["level"])
    op.create_index("ix_industry_pulse_nodes_parent_id", "industry_pulse_nodes", ["parent_id"])
    op.create_index("ix_industry_pulse_nodes_enabled", "industry_pulse_nodes", ["enabled"])
    op.create_index("ix_industry_pulse_nodes_taxonomy_parent", "industry_pulse_nodes", ["taxonomy", "parent_id"])

    op.create_table(
        "industry_pulse_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="downstream"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_industry_pulse_relations_edge"),
    )
    op.create_index("ix_industry_pulse_relations_source_node_id", "industry_pulse_relations", ["source_node_id"])
    op.create_index("ix_industry_pulse_relations_target_node_id", "industry_pulse_relations", ["target_node_id"])

    op.create_table(
        "industry_pulse_instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("instrument_type", sa.String(length=16), nullable=False, server_default="etf"),
        sa.Column("mapping_type", sa.String(length=24), nullable=False, server_default="etf_proxy"),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="primary"),
        sa.Column("purity", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("exposure", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("liquidity", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("provider_symbol", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("health_status", sa.String(length=16), nullable=False, server_default="UNAVAILABLE"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trading_date", sa.Date(), nullable=True),
        sa.Column("data_quality", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_id", "ticker", "role", name="uq_industry_pulse_instruments_node_ticker_role"),
        sa.CheckConstraint("mapping_type IN ('etf_proxy', 'primary_industry', 'secondary_industry', 'theme_exposure')", name="ck_industry_pulse_instruments_mapping_type"),
        sa.CheckConstraint("role IN ('primary', 'secondary', 'reference', 'benchmark')", name="ck_industry_pulse_instruments_role"),
        sa.CheckConstraint("purity >= 0 AND purity <= 1", name="ck_industry_pulse_instruments_purity"),
        sa.CheckConstraint("exposure >= 0 AND exposure <= 1", name="ck_industry_pulse_instruments_exposure"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_industry_pulse_instruments_confidence"),
        sa.CheckConstraint("liquidity >= 0 AND liquidity <= 1", name="ck_industry_pulse_instruments_liquidity"),
    )
    op.create_index("ix_industry_pulse_instruments_node_id", "industry_pulse_instruments", ["node_id"])
    op.create_index("ix_industry_pulse_instruments_security_id", "industry_pulse_instruments", ["security_id"])
    op.create_index("ix_industry_pulse_instruments_ticker", "industry_pulse_instruments", ["ticker"])
    op.create_index("ix_industry_pulse_instruments_mapping_type", "industry_pulse_instruments", ["mapping_type"])
    op.create_index("ix_industry_pulse_instruments_role", "industry_pulse_instruments", ["role"])
    op.create_index("ix_industry_pulse_instruments_enabled", "industry_pulse_instruments", ["enabled"])
    op.create_index("ix_industry_pulse_instruments_node_enabled", "industry_pulse_instruments", ["node_id", "enabled"])

    op.create_table(
        "industry_pulse_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("pulse", sa.Float(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("relative_strength_score", sa.Float(), nullable=True),
        sa.Column("volume_score", sa.Float(), nullable=True),
        sa.Column("momentum_score", sa.Float(), nullable=True),
        sa.Column("breadth_score", sa.Float(), nullable=True),
        sa.Column("consensus_score", sa.Float(), nullable=True),
        sa.Column("heat", sa.Float(), nullable=True),
        sa.Column("risk", sa.Float(), nullable=True),
        sa.Column("change_1d", sa.Float(), nullable=True),
        sa.Column("change_5d", sa.Float(), nullable=True),
        sa.Column("change_20d", sa.Float(), nullable=True),
        sa.Column("mood", sa.String(length=32), nullable=True),
        sa.Column("regime", sa.String(length=32), nullable=True),
        sa.Column("direction", sa.String(length=24), nullable=True),
        sa.Column("data_quality", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("coverage_quality", sa.Float(), nullable=True),
        sa.Column("proxy_based_on_parent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("benchmark_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("calculation_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="yahoo"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_id", "trading_date", name="uq_industry_pulse_snapshots_node_date"),
    )
    op.create_index("ix_industry_pulse_snapshots_node_id", "industry_pulse_snapshots", ["node_id"])
    op.create_index("ix_industry_pulse_snapshots_trading_date", "industry_pulse_snapshots", ["trading_date"])
    op.create_index("ix_industry_pulse_snapshots_node_date", "industry_pulse_snapshots", ["node_id", "trading_date"])

    op.create_table(
        "industry_pulse_focus_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_id", "trading_date", "signal_type", name="uq_industry_pulse_focus_node_date_type"),
    )
    op.create_index("ix_industry_pulse_focus_signals_node_id", "industry_pulse_focus_signals", ["node_id"])
    op.create_index("ix_industry_pulse_focus_signals_trading_date", "industry_pulse_focus_signals", ["trading_date"])
    op.create_index("ix_industry_pulse_focus_signals_signal_type", "industry_pulse_focus_signals", ["signal_type"])
    op.create_index("ix_industry_pulse_focus_date_type", "industry_pulse_focus_signals", ["trading_date", "signal_type"])

    op.create_table(
        "industry_pulse_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("trigger_type", sa.String(length=24), nullable=False, server_default="scheduled"),
        sa.Column("etf_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("yfinance_success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finnhub_fallback", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sector_calculated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sector_unavailable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("focus_signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_summaries_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("luna_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sol_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_industry_pulse_sync_runs_started_at", "industry_pulse_sync_runs", ["started_at"])
    op.create_index("ix_industry_pulse_sync_runs_status", "industry_pulse_sync_runs", ["status"])
    op.create_index("ix_industry_pulse_sync_runs_trigger_type", "industry_pulse_sync_runs", ["trigger_type"])
    op.create_index("ix_industry_pulse_sync_runs_started", "industry_pulse_sync_runs", ["started_at"])

    op.create_table(
        "industry_pulse_narratives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_id", "trading_date", name="uq_industry_pulse_narratives_node_date"),
    )
    op.create_index("ix_industry_pulse_narratives_node_id", "industry_pulse_narratives", ["node_id"])
    op.create_index("ix_industry_pulse_narratives_trading_date", "industry_pulse_narratives", ["trading_date"])
    op.create_index("ix_industry_pulse_narratives_status", "industry_pulse_narratives", ["status"])
    op.create_index("ix_industry_pulse_narratives_date", "industry_pulse_narratives", ["trading_date"])


def downgrade() -> None:
    op.drop_index("ix_industry_pulse_narratives_date", table_name="industry_pulse_narratives")
    op.drop_index("ix_industry_pulse_narratives_status", table_name="industry_pulse_narratives")
    op.drop_index("ix_industry_pulse_narratives_trading_date", table_name="industry_pulse_narratives")
    op.drop_index("ix_industry_pulse_narratives_node_id", table_name="industry_pulse_narratives")
    op.drop_table("industry_pulse_narratives")

    op.drop_index("ix_industry_pulse_sync_runs_started", table_name="industry_pulse_sync_runs")
    op.drop_index("ix_industry_pulse_sync_runs_trigger_type", table_name="industry_pulse_sync_runs")
    op.drop_index("ix_industry_pulse_sync_runs_status", table_name="industry_pulse_sync_runs")
    op.drop_index("ix_industry_pulse_sync_runs_started_at", table_name="industry_pulse_sync_runs")
    op.drop_table("industry_pulse_sync_runs")

    op.drop_index("ix_industry_pulse_focus_date_type", table_name="industry_pulse_focus_signals")
    op.drop_index("ix_industry_pulse_focus_signals_signal_type", table_name="industry_pulse_focus_signals")
    op.drop_index("ix_industry_pulse_focus_signals_trading_date", table_name="industry_pulse_focus_signals")
    op.drop_index("ix_industry_pulse_focus_signals_node_id", table_name="industry_pulse_focus_signals")
    op.drop_table("industry_pulse_focus_signals")

    op.drop_index("ix_industry_pulse_snapshots_node_date", table_name="industry_pulse_snapshots")
    op.drop_index("ix_industry_pulse_snapshots_trading_date", table_name="industry_pulse_snapshots")
    op.drop_index("ix_industry_pulse_snapshots_node_id", table_name="industry_pulse_snapshots")
    op.drop_table("industry_pulse_snapshots")

    op.drop_index("ix_industry_pulse_instruments_node_enabled", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_enabled", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_role", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_ticker", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_mapping_type", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_security_id", table_name="industry_pulse_instruments")
    op.drop_index("ix_industry_pulse_instruments_node_id", table_name="industry_pulse_instruments")
    op.drop_table("industry_pulse_instruments")

    op.drop_index("ix_industry_pulse_relations_target_node_id", table_name="industry_pulse_relations")
    op.drop_index("ix_industry_pulse_relations_source_node_id", table_name="industry_pulse_relations")
    op.drop_table("industry_pulse_relations")

    op.drop_index("ix_industry_pulse_nodes_taxonomy_parent", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_enabled", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_parent_id", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_level", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_slug", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_node_key", table_name="industry_pulse_nodes")
    op.drop_index("ix_industry_pulse_nodes_taxonomy", table_name="industry_pulse_nodes")
    op.drop_table("industry_pulse_nodes")
