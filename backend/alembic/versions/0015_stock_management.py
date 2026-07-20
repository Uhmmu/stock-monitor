"""add stock management and manual peers

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "stock_profiles",
        sa.Column("ticker", sa.String(16), primary_key=True),
        sa.Column("company_name", sa.String(256)),
        sa.Column("official_sector", sa.String(128)),
        sa.Column("official_industry", sa.String(192)),
        sa.Column("source", sa.String(32), nullable=False, server_default="yfinance"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_stock_profiles_official_sector", "stock_profiles", ["official_sector"])
    op.create_index("ix_stock_profiles_official_industry", "stock_profiles", ["official_industry"])
    op.add_column("watchlist_items", sa.Column("alert_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("watchlist_items", sa.Column("user_group_id", sa.Integer(), nullable=True))
    op.add_column("watchlist_items", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_watchlist_group", "watchlist_items", "stock_groups", ["user_group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_watchlist_items_user_group_id", "watchlist_items", ["user_group_id"])
    op.create_table(
        "peer_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_ticker", sa.String(16), nullable=False),
        sa.Column("peer_ticker", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("base_ticker", "peer_ticker"),
        sa.CheckConstraint("base_ticker <> peer_ticker", name="ck_peer_relation_not_self"),
    )
    op.create_index("ix_peer_relations_base_ticker", "peer_relations", ["base_ticker"])
    op.create_index("ix_peer_relations_peer_ticker", "peer_relations", ["peer_ticker"])
    op.create_index("ix_peer_relations_source", "peer_relations", ["source"])
    op.create_table(
        "peer_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_ticker", sa.String(16), nullable=False),
        sa.Column("peer_ticker", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("base_ticker", "peer_ticker"),
        sa.CheckConstraint("base_ticker <> peer_ticker", name="ck_peer_exclusion_not_self"),
    )
    op.create_index("ix_peer_exclusions_base_ticker", "peer_exclusions", ["base_ticker"])
    op.create_index("ix_peer_exclusions_peer_ticker", "peer_exclusions", ["peer_ticker"])


def downgrade():
    op.drop_table("peer_exclusions")
    op.drop_table("peer_relations")
    op.drop_index("ix_watchlist_items_user_group_id", table_name="watchlist_items")
    op.drop_constraint("fk_watchlist_group", "watchlist_items", type_="foreignkey")
    op.drop_column("watchlist_items", "display_order")
    op.drop_column("watchlist_items", "user_group_id")
    op.drop_column("watchlist_items", "alert_enabled")
    op.drop_table("stock_profiles")
    op.drop_table("stock_groups")
