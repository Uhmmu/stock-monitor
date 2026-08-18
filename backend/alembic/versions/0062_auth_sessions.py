"""add auth_sessions for refresh-token lifecycle

Revision ID: 0062_auth_sessions
Revises: 0061_mood_history_production
"""

from alembic import op
import sqlalchemy as sa


revision = "0062_auth_sessions"
down_revision = "0061_mood_history_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_user_revoked", "auth_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_auth_sessions_family", "auth_sessions", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_family", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
