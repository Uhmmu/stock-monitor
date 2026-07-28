"""add authenticated user price target alerts

Revision ID: 0033_user_price_alerts
Revises: 0032_ownership_calendar
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_user_price_alerts"
down_revision = "0032_ownership_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_price_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_price_alert_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_price > 0", name="ck_user_price_alerts_target_price"
        ),
        sa.CheckConstraint(
            "direction IN ('above', 'below')",
            name="ck_user_price_alerts_direction",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["triggered_price_alert_id"], ["price_alerts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("triggered_price_alert_id"),
    )
    op.create_index(
        "ix_user_price_alerts_user_id", "user_price_alerts", ["user_id"]
    )
    op.create_index(
        "ix_user_price_alerts_ticker", "user_price_alerts", ["ticker"]
    )
    op.create_index(
        "ix_user_price_alerts_enabled", "user_price_alerts", ["enabled"]
    )
    op.create_index(
        "ix_user_price_alerts_ticker_enabled",
        "user_price_alerts",
        ["ticker", "enabled"],
    )


def downgrade() -> None:
    op.drop_table("user_price_alerts")
