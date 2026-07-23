"""add Perplexity-backed stock discovery history

Revision ID: 0028_stock_discovery
Revises: 0027_portfolio_strategy
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_stock_discovery"
down_revision = "0027_portfolio_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_discovery_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auto_update_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("model", sa.String(128), nullable=False, server_default="openai/gpt-5.4-mini"),
        sa.Column("enable_web_search", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="12000"),
        sa.Column("monthly_budget_usd", sa.Float(), nullable=False, server_default="10"),
        sa.Column("max_run_cost_usd", sa.Float(), nullable=False, server_default="1"),
        sa.Column("min_market_cap", sa.Float(), nullable=False, server_default="2000000000"),
        sa.Column("exclude_current_holdings", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exclude_watchlist", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_positive_fcf", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_trailing_pe", sa.Float(), nullable=False, server_default="80"),
        sa.Column("max_forward_pe", sa.Float(), nullable=False, server_default="60"),
        sa.Column("max_price_to_sales", sa.Float(), nullable=False, server_default="25"),
        sa.Column("filter_extreme_momentum", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("missing_data_policy", sa.String(24), nullable=False, server_default="warn"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_stock_discovery_settings_user_id"),
    )
    op.create_index("ix_stock_discovery_settings_user_id", "stock_discovery_settings", ["user_id"])

    op.create_table(
        "stock_discovery_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_successful_run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(48), nullable=False, server_default="preparing_portfolio"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("analysis_date", sa.Date()),
        sa.Column("next_scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("model_requested", sa.String(128), nullable=False),
        sa.Column("model_used", sa.String(128)),
        sa.Column("prompt_version", sa.String(64), nullable=False, server_default="stock-discovery-prompt-v0.4"),
        sa.Column("schema_version", sa.String(64), nullable=False, server_default="stock-discovery-schema-v0.4"),
        sa.Column("filter_version", sa.String(64), nullable=False, server_default="stock-discovery-filter-v0.4"),
        sa.Column("portfolio_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("failure_code", sa.String(48)),
        sa.Column("failure_reason", sa.Text()),
        sa.UniqueConstraint("idempotency_key", name="uq_stock_discovery_runs_idempotency_key"),
    )
    op.create_index("ix_stock_discovery_runs_user_id", "stock_discovery_runs", ["user_id"])
    op.create_index("ix_stock_discovery_runs_portfolio_id", "stock_discovery_runs", ["portfolio_id"])
    op.create_index("ix_stock_discovery_runs_status", "stock_discovery_runs", ["status"])
    op.create_index("ix_stock_discovery_runs_user_requested", "stock_discovery_runs", ["user_id", "requested_at"])

    op.create_table("stock_discovery_portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("context_hash", sa.String(64), nullable=False), sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_stock_discovery_portfolio_snapshots_context_hash", "stock_discovery_portfolio_snapshots", ["context_hash"])
    op.create_table("stock_discovery_market_contexts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""), sa.Column("risk_regime", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("stock_discovery_exposures",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("diagnosis_kind", sa.String(32), nullable=False), sa.Column("exposure_type", sa.String(32)), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="medium"), sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_action", sa.Text(), nullable=False, server_default=""), sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_stock_discovery_exposures_run_kind", "stock_discovery_exposures", ["run_id", "diagnosis_kind"])
    op.create_table("stock_discovery_flow_directions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_type", sa.String(24), nullable=False), sa.Column("direction", sa.String(200), nullable=False),
        sa.Column("strength", sa.String(24), nullable=False, server_default="uncertain"), sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_stock_discovery_flows_run_type", "stock_discovery_flow_directions", ["run_id", "flow_type"])
    op.create_table("stock_discovery_candidate_groups",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.String(80), nullable=False), sa.Column("group_name", sa.String(120), nullable=False), sa.Column("group_type", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""), sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "group_id", name="uq_stock_discovery_groups_run_group"))
    op.create_table("stock_discovery_candidates",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_ticker", sa.String(48), nullable=False), sa.Column("normalized_ticker", sa.String(32)), sa.Column("canonical_key", sa.String(96), nullable=False),
        sa.Column("company_name", sa.String(256), nullable=False, server_default=""), sa.Column("exchange", sa.String(64)), sa.Column("country", sa.String(64)),
        sa.Column("raw_rank", sa.Integer()), sa.Column("final_rank", sa.Integer()), sa.Column("candidate_priority", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("symbol_match_status", sa.String(32), nullable=False, server_default="pending"), sa.Column("symbol_match_reason", sa.Text()),
        sa.Column("filter_status", sa.String(32), nullable=False, server_default="insufficient_data"), sa.Column("display_status", sa.String(32), nullable=False, server_default="insufficient_data"),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="pending"), sa.Column("raw_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("normalized_data", sa.JSON(), nullable=False, server_default="{}"), sa.Column("local_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("researched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "canonical_key", name="uq_stock_discovery_candidates_run_key"))
    op.create_index("ix_stock_discovery_candidates_normalized_ticker", "stock_discovery_candidates", ["normalized_ticker"])
    op.create_index("ix_stock_discovery_candidates_run_status", "stock_discovery_candidates", ["run_id", "display_status"])
    op.create_table("stock_discovery_candidate_group_memberships",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("stock_discovery_candidate_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_reason", sa.Text(), nullable=False, server_default=""), sa.Column("raw_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("candidate_id", "group_id", name="uq_stock_discovery_membership"))
    op.create_table("stock_discovery_candidate_metrics",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False), sa.Column("value", sa.Float()), sa.Column("text_value", sa.Text()), sa.Column("unit", sa.String(32)),
        sa.Column("source", sa.String(32), nullable=False, server_default="unknown"), sa.Column("data_period", sa.String(64)),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("has_discrepancy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("candidate_id", "metric_key", "source", name="uq_stock_discovery_metric_source"))
    op.create_table("stock_discovery_sources",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE")), sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False), sa.Column("source_type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("source_origin", sa.String(32), nullable=False, server_default="perplexity_finance"))
    op.create_index("ix_stock_discovery_sources_run_id", "stock_discovery_sources", ["run_id"])
    op.create_index("ix_stock_discovery_sources_candidate_id", "stock_discovery_sources", ["candidate_id"])
    op.create_table("stock_discovery_filter_results",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("reasons", sa.JSON(), nullable=False, server_default="[]"), sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("filter_version", sa.String(64), nullable=False, server_default="stock-discovery-filter-v0.4"))
    op.create_table("stock_discovery_raw_payloads",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("response_json", sa.JSON(), nullable=False, server_default="{}"), sa.Column("output_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("parsed_json", sa.JSON(), nullable=False, server_default="{}"), sa.Column("tool_results", sa.JSON(), nullable=False, server_default="[]"))
    op.create_table("stock_discovery_usage",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"), sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"), sa.Column("finance_search_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("web_search_calls", sa.Integer(), nullable=False, server_default="0"), sa.Column("tool_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("model_cost_usd", sa.Float(), nullable=False, server_default="0"), sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("raw_usage", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    for table in (
        "stock_discovery_usage", "stock_discovery_raw_payloads", "stock_discovery_filter_results",
        "stock_discovery_sources", "stock_discovery_candidate_metrics", "stock_discovery_candidate_group_memberships",
        "stock_discovery_candidates", "stock_discovery_candidate_groups", "stock_discovery_flow_directions",
        "stock_discovery_exposures", "stock_discovery_market_contexts", "stock_discovery_portfolio_snapshots",
        "stock_discovery_runs", "stock_discovery_settings",
    ):
        op.drop_table(table)
