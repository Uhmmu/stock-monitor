"""add isolated TEST execution control-plane tables

Revision ID: 0079_execution_test
Revises: 0078_quant_paper

Goal 6 deliberately introduces a second, TEST-only authority.  It projects
eligible Goal 5 paper signals into immutable intents, then records machine
leases and agent-reported order/fill/audit events.  No paper row is mutated and
no live/Binance credential is stored here.
"""

from alembic import op
import sqlalchemy as sa


revision = "0079_execution_test"
down_revision = "0078_quant_paper"
branch_labels = None
depends_on = None


NUMERIC = sa.Numeric(38, 18)
JSON = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "execution_test_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(96), nullable=False),
        sa.Column("account_key", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("venue", sa.String(32), nullable=False, server_default="binance_usdm"),
        sa.Column("base_currency", sa.String(12), nullable=False, server_default="USDT"),
        sa.Column("initial_capital", NUMERIC, nullable=False),
        sa.Column("cash", NUMERIC, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "venue", "account_key", name="uq_execution_test_accounts_scope"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_test_accounts_test_only"),
        sa.CheckConstraint("status IN ('active', 'paused', 'revoked')", name="ck_execution_test_accounts_status"),
        sa.CheckConstraint("CAST(initial_capital AS NUMERIC) > 0", name="ck_execution_test_accounts_capital_positive"),
    )
    op.create_index("ix_execution_test_accounts_user_id", "execution_test_accounts", ["user_id"])
    op.create_index("ix_execution_test_accounts_user_status", "execution_test_accounts", ["user_id", "status"])

    op.create_table(
        "execution_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("execution_test_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("quant_signals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("quant_strategy_deployments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("target_exposure", NUMERIC, nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "signal_id", name="uq_execution_intents_account_signal"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_intents_test_only"),
        sa.CheckConstraint("status IN ('pending', 'leased', 'acked', 'rejected', 'consumed', 'expired')", name="ck_execution_intents_status"),
        sa.CheckConstraint("CAST(target_exposure AS NUMERIC) >= -1 AND CAST(target_exposure AS NUMERIC) <= 1", name="ck_execution_intents_target_bounds"),
    )
    op.create_index("ix_execution_intents_account_id", "execution_intents", ["account_id"])
    op.create_index("ix_execution_intents_user_id", "execution_intents", ["user_id"])
    op.create_index("ix_execution_intents_signal_id", "execution_intents", ["signal_id"])
    op.create_index("ix_execution_intents_deployment_id", "execution_intents", ["deployment_id"])
    op.create_index("ix_execution_intents_instrument_id", "execution_intents", ["instrument_id"])
    op.create_index("ix_execution_intents_account_status", "execution_intents", ["account_id", "status", "created_at"])
    op.create_index("ix_execution_intents_signal_expiry", "execution_intents", ["signal_id", "signal_expires_at"])

    op.create_table(
        "execution_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(96), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("scopes", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("account_ids", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("venues", JSON, nullable=False, server_default=sa.text("'[\"binance_usdm\"]'")),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_fingerprint", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "name", name="uq_execution_agents_owner_name"),
        sa.UniqueConstraint("token_hash", name="uq_execution_agents_token_hash"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_agents_test_only"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_execution_agents_status"),
    )
    op.create_index("ix_execution_agents_owner_id", "execution_agents", ["owner_id"])
    op.create_index("ix_execution_agents_owner_status", "execution_agents", ["owner_id", "status"])

    op.create_table(
        "execution_request_nonces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("execution_agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "nonce", name="uq_execution_request_nonces_agent_nonce"),
    )
    op.create_index("ix_execution_request_nonces_agent_id", "execution_request_nonces", ["agent_id"])
    op.create_index("ix_execution_request_nonces_created", "execution_request_nonces", ["created_at"])

    op.create_table(
        "signal_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intent_id", sa.Integer(), sa.ForeignKey("execution_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("execution_agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("lease_token", sa.String(96), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="leased"),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("intent_id", "attempt", name="uq_signal_leases_intent_attempt"),
        sa.UniqueConstraint("lease_token", name="uq_signal_leases_lease_token"),
        sa.CheckConstraint("environment = 'test'", name="ck_signal_leases_test_only"),
        sa.CheckConstraint("status IN ('leased', 'acked', 'rejected', 'expired', 'released')", name="ck_signal_leases_status"),
    )
    op.create_index("ix_signal_leases_intent_id", "signal_leases", ["intent_id"])
    op.create_index("ix_signal_leases_agent_id", "signal_leases", ["agent_id"])
    op.create_index("ix_signal_leases_agent_status", "signal_leases", ["agent_id", "status", "expires_at"])
    op.create_index("ix_signal_leases_expiry", "signal_leases", ["status", "expires_at"])
    op.create_index("ix_signal_leases_expires_at", "signal_leases", ["expires_at"])
    op.create_index(
        "uq_signal_leases_active_intent",
        "signal_leases",
        ["intent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'leased'"),
        sqlite_where=sa.text("status = 'leased'"),
    )

    op.create_table(
        "execution_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("execution_test_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", sa.Integer(), sa.ForeignKey("execution_intents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("signal_leases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("execution_agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("crypto_instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("venue", sa.String(32), nullable=False, server_default="binance_usdm"),
        sa.Column("client_order_id", sa.String(36), nullable=False),
        sa.Column("provider_order_id", sa.String(128), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False, server_default="market"),
        sa.Column("time_in_force", sa.String(16), nullable=True),
        sa.Column("quantity", NUMERIC, nullable=False),
        sa.Column("price", NUMERIC, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="created"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment", "account_id", "venue", "client_order_id", name="uq_execution_orders_client"),
        sa.UniqueConstraint("environment", "account_id", "venue", "provider_order_id", name="uq_execution_orders_provider"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_orders_test_only"),
        sa.CheckConstraint("status IN ('created', 'submitted', 'partially_filled', 'filled', 'cancel_requested', 'cancelled', 'rejected', 'unknown', 'failed')", name="ck_execution_orders_status"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_execution_orders_side"),
        sa.CheckConstraint("CAST(quantity AS NUMERIC) > 0", name="ck_execution_orders_quantity_positive"),
    )
    op.create_index("ix_execution_orders_account_id", "execution_orders", ["account_id"])
    op.create_index("ix_execution_orders_user_id", "execution_orders", ["user_id"])
    op.create_index("ix_execution_orders_intent_id", "execution_orders", ["intent_id"])
    op.create_index("ix_execution_orders_lease_id", "execution_orders", ["lease_id"])
    op.create_index("ix_execution_orders_agent_id", "execution_orders", ["agent_id"])
    op.create_index("ix_execution_orders_instrument_id", "execution_orders", ["instrument_id"])
    op.create_index("ix_execution_orders_account_status", "execution_orders", ["account_id", "status", "created_at"])

    op.create_table(
        "execution_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("execution_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("execution_test_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("execution_agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("venue", sa.String(32), nullable=False, server_default="binance_usdm"),
        sa.Column("provider_trade_id", sa.String(128), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", NUMERIC, nullable=False),
        sa.Column("price", NUMERIC, nullable=False),
        sa.Column("fee", NUMERIC, nullable=False, server_default="0"),
        sa.Column("fee_asset", sa.String(16), nullable=True),
        sa.Column("fill_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment", "account_id", "venue", "provider_trade_id", name="uq_execution_fills_provider_trade"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_fills_test_only"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_execution_fills_side"),
        sa.CheckConstraint("CAST(quantity AS NUMERIC) > 0", name="ck_execution_fills_quantity_positive"),
        sa.CheckConstraint("CAST(price AS NUMERIC) > 0", name="ck_execution_fills_price_positive"),
    )
    op.create_index("ix_execution_fills_order_id", "execution_fills", ["order_id"])
    op.create_index("ix_execution_fills_account_id", "execution_fills", ["account_id"])
    op.create_index("ix_execution_fills_user_id", "execution_fills", ["user_id"])
    op.create_index("ix_execution_fills_agent_id", "execution_fills", ["agent_id"])
    op.create_index("ix_execution_fills_order_time", "execution_fills", ["order_id", "fill_time"])
    op.create_index("ix_execution_fills_account_time", "execution_fills", ["account_id", "fill_time"])

    op.create_table(
        "execution_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_nonce", sa.String(128), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("execution_agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("execution_test_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("intent_id", sa.Integer(), sa.ForeignKey("execution_intents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("signal_leases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("execution_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fill_id", sa.Integer(), sa.ForeignKey("execution_fills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("venue", sa.String(32), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment", "event_id", name="uq_execution_events_event_id"),
        sa.UniqueConstraint("environment", "agent_id", "event_nonce", name="uq_execution_events_agent_nonce"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_events_test_only"),
    )
    op.create_index("ix_execution_events_agent_id", "execution_events", ["agent_id"])
    op.create_index("ix_execution_events_account_id", "execution_events", ["account_id"])
    op.create_index("ix_execution_events_intent_id", "execution_events", ["intent_id"])
    op.create_index("ix_execution_events_lease_id", "execution_events", ["lease_id"])
    op.create_index("ix_execution_events_order_id", "execution_events", ["order_id"])
    op.create_index("ix_execution_events_fill_id", "execution_events", ["fill_id"])
    op.create_index("ix_execution_events_account_time", "execution_events", ["account_id", "received_at"])
    op.create_index("ix_execution_events_type_time", "execution_events", ["event_type", "received_at"])

    op.create_table(
        "risk_policy_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("execution_test_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("limits", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment", "account_id", "version", name="uq_risk_policy_versions_scope_version"),
        sa.CheckConstraint("environment = 'test'", name="ck_risk_policy_versions_test_only"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_risk_policy_versions_status"),
    )
    op.create_index("ix_risk_policy_versions_account_id", "risk_policy_versions", ["account_id"])
    op.create_index("ix_risk_policy_versions_created_by", "risk_policy_versions", ["created_by"])
    op.create_index("ix_risk_policy_versions_approved_by", "risk_policy_versions", ["approved_by"])
    op.create_index("ix_risk_policy_versions_account_status", "risk_policy_versions", ["account_id", "status", "effective_at"])

    op.create_table(
        "execution_kill_switches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        # Global scope uses sentinel 0 so uniqueness does not depend on NULL
        # semantics (PostgreSQL and SQLite treat NULLs differently).
        sa.Column("scope_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("environment", sa.String(12), nullable=False, server_default="test"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment", "scope_type", "scope_id", name="uq_execution_kill_switches_scope"),
        sa.CheckConstraint("environment = 'test'", name="ck_execution_kill_switches_test_only"),
        sa.CheckConstraint("scope_type IN ('global', 'account', 'agent', 'deployment', 'instrument')", name="ck_execution_kill_switches_scope_type"),
    )
    op.create_index("ix_execution_kill_switches_changed_by", "execution_kill_switches", ["changed_by"])
    op.create_index("ix_execution_kill_switches_enabled", "execution_kill_switches", ["environment", "enabled"])


def downgrade() -> None:
    for table in (
        "execution_kill_switches",
        "risk_policy_versions",
        "execution_events",
        "execution_fills",
        "execution_orders",
        "signal_leases",
        "execution_request_nonces",
        "execution_agents",
        "execution_intents",
        "execution_test_accounts",
    ):
        op.drop_table(table)
