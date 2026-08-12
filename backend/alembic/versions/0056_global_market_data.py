"""add shared daily market-data freshness state

Revision ID: 0056_global_market_data
Revises: 0055_industry_seed_registry
"""

from alembic import op
import sqlalchemy as sa


revision = "0056_global_market_data"
down_revision = "0055_industry_seed_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("historical_prices", sa.Column("adjusted_close", sa.Numeric(20, 6), nullable=True))
    op.create_table(
        "market_data_sync_states",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("priority", sa.String(2), nullable=False, server_default="P2"),
        sa.Column("latest_market_date", sa.Date(), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(16), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_status", sa.String(32), nullable=False, server_default="MISSING"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority IN ('P0', 'P1', 'P2')", name="ck_market_data_sync_states_priority"),
        sa.CheckConstraint("failure_count >= 0", name="ck_market_data_sync_states_failure_count"),
    )
    for column in ("security_id", "priority", "latest_market_date", "next_refresh_at", "freshness_status"):
        op.create_index(f"ix_market_data_sync_states_{column}", "market_data_sync_states", [column])


def downgrade() -> None:
    for column in ("freshness_status", "next_refresh_at", "latest_market_date", "priority", "security_id"):
        op.drop_index(f"ix_market_data_sync_states_{column}", table_name="market_data_sync_states")
    op.drop_table("market_data_sync_states")
    op.drop_column("historical_prices", "adjusted_close")
