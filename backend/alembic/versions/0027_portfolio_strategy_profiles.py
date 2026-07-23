"""add per-user portfolio strategy profiles

Revision ID: 0027_portfolio_strategy
Revises: 0026_async_news_summaries
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_portfolio_strategy"
down_revision = "0026_async_news_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_strategy_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_type", sa.String(length=32), nullable=False, server_default="quality_growth"),
        sa.Column("investment_horizon", sa.String(length=24), nullable=False, server_default="long_term"),
        sa.Column("risk_tolerance", sa.String(length=24), nullable=False, server_default="balanced"),
        sa.Column("max_single_position", sa.Float(), nullable=False, server_default="25"),
        sa.Column("max_theme_exposure", sa.Float(), nullable=False, server_default="40"),
        sa.Column("valuation_preference", sa.String(length=24), nullable=False, server_default="balanced"),
        sa.Column("minimum_quality_score", sa.Float(), nullable=False, server_default="70"),
        sa.Column("preferred_regions", sa.JSON(), nullable=False, server_default='["north_america"]'),
        sa.Column("preferred_market_caps", sa.JSON(), nullable=False, server_default='["large", "mid"]'),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_portfolio_strategy_profiles_user_id"),
    )
    op.create_index(
        "ix_portfolio_strategy_profiles_user_id",
        "portfolio_strategy_profiles",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_strategy_profiles_user_id", table_name="portfolio_strategy_profiles")
    op.drop_table("portfolio_strategy_profiles")
