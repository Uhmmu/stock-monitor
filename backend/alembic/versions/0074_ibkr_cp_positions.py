"""add Client Portal Gateway current positions

Revision ID: 0074_ibkr_cp_positions
Revises: 0073_crypto_research_enrichment
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0074_ibkr_cp_positions"
down_revision = "0073_crypto_research_enrichment"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ibkr_cp_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_type", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("account_id", sa.String(80)),
        sa.Column("position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("removed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("warnings", JSON_VALUE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_stage", sa.String(24)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ibkr_cp_sync_runs_user_id", "ibkr_cp_sync_runs", ["user_id"])
    op.create_index("ix_ibkr_cp_sync_runs_status", "ibkr_cp_sync_runs", ["status"])
    op.create_index("ix_ibkr_cp_sync_runs_stage", "ibkr_cp_sync_runs", ["stage"])
    op.create_index("ix_ibkr_cp_sync_runs_account_id", "ibkr_cp_sync_runs", ["account_id"])
    op.create_index(
        "ix_ibkr_cp_run_user_completed", "ibkr_cp_sync_runs", ["user_id", "completed_at"],
    )
    op.create_index(
        "uq_ibkr_cp_one_active_user", "ibkr_cp_sync_runs", ["user_id"], unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
        sqlite_where=sa.text("status IN ('queued','running')"),
    )
    op.create_table(
        "ibkr_cp_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(80), nullable=False),
        sa.Column("conid", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(48)),
        sa.Column("asset_class", sa.String(32)),
        sa.Column("currency", sa.String(16)),
        sa.Column("exchange", sa.String(32)),
        sa.Column("quantity", sa.Numeric(38, 12)),
        sa.Column("average_cost", sa.Numeric(38, 12)),
        sa.Column("market_price", sa.Numeric(38, 12)),
        sa.Column("market_value", sa.Numeric(38, 12)),
        sa.Column("unrealized_pnl", sa.Numeric(38, 12)),
        sa.Column("realized_pnl", sa.Numeric(38, 12)),
        sa.Column("source", sa.String(32), nullable=False, server_default="client_portal_gateway"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("raw_payload", JSON_VALUE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_cp_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_run_id", sa.Integer(), sa.ForeignKey("ibkr_cp_sync_runs.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("user_id", "account_id", "conid", name="uq_ibkr_cp_position_key"),
    )
    op.create_index("ix_ibkr_cp_positions_user_id", "ibkr_cp_positions", ["user_id"])
    op.create_index("ix_ibkr_cp_positions_conid", "ibkr_cp_positions", ["conid"])
    op.create_index("ix_ibkr_cp_positions_status", "ibkr_cp_positions", ["status"])
    op.create_index("ix_ibkr_cp_position_user_status", "ibkr_cp_positions", ["user_id", "status"])
    op.create_index("ix_ibkr_cp_position_account", "ibkr_cp_positions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_ibkr_cp_position_account", table_name="ibkr_cp_positions")
    op.drop_index("ix_ibkr_cp_position_user_status", table_name="ibkr_cp_positions")
    op.drop_index("ix_ibkr_cp_positions_status", table_name="ibkr_cp_positions")
    op.drop_index("ix_ibkr_cp_positions_conid", table_name="ibkr_cp_positions")
    op.drop_index("ix_ibkr_cp_positions_user_id", table_name="ibkr_cp_positions")
    op.drop_table("ibkr_cp_positions")
    op.drop_index("uq_ibkr_cp_one_active_user", table_name="ibkr_cp_sync_runs")
    op.drop_index("ix_ibkr_cp_run_user_completed", table_name="ibkr_cp_sync_runs")
    op.drop_index("ix_ibkr_cp_sync_runs_account_id", table_name="ibkr_cp_sync_runs")
    op.drop_index("ix_ibkr_cp_sync_runs_stage", table_name="ibkr_cp_sync_runs")
    op.drop_index("ix_ibkr_cp_sync_runs_status", table_name="ibkr_cp_sync_runs")
    op.drop_index("ix_ibkr_cp_sync_runs_user_id", table_name="ibkr_cp_sync_runs")
    op.drop_table("ibkr_cp_sync_runs")
