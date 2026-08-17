"""add deterministic AI Mood snapshots

Revision ID: 0059_ai_mood_engine
Revises: 0058_options_analytics
"""

from alembic import op
import sqlalchemy as sa


revision = "0059_ai_mood_engine"
down_revision = "0058_options_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mood_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(192), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("candidate_state", sa.String(32)),
        sa.Column("previous_state", sa.String(32)),
        sa.Column("direction", sa.String(16)),
        sa.Column("phase", sa.String(32)),
        sa.Column("regime", sa.String(32)),
        sa.Column("mood_score", sa.Float()),
        sa.Column("agreement_score", sa.Float()),
        sa.Column("agreement_level", sa.String(16)),
        sa.Column("confidence", sa.Float()),
        sa.Column("quality", sa.Float()),
        sa.Column("coverage", sa.Float()),
        sa.Column("freshness_status", sa.String(24)),
        sa.Column("state_started_on", sa.Date()),
        sa.Column("duration_sessions", sa.Integer()),
        sa.Column("calculation_version", sa.String(32), nullable=False, server_default="mood_v1"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("signals", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("divergences", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("transition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("missing_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("stale_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("input_manifest", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint(
            "scope_type", "scope_key", "trading_date", "calculation_version",
            name="uq_mood_snapshots_scope_date_version",
        ),
        sa.CheckConstraint("mood_score IS NULL OR (mood_score >= 0 AND mood_score <= 100)", name="ck_mood_snapshots_score"),
        sa.CheckConstraint("agreement_score IS NULL OR (agreement_score >= 0 AND agreement_score <= 1)", name="ck_mood_snapshots_agreement"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_mood_snapshots_confidence"),
        sa.CheckConstraint("quality IS NULL OR (quality >= 0 AND quality <= 1)", name="ck_mood_snapshots_quality"),
        sa.CheckConstraint("coverage IS NULL OR (coverage >= 0 AND coverage <= 1)", name="ck_mood_snapshots_coverage"),
    )
    op.create_index("ix_mood_snapshots_scope_date", "mood_snapshots", ["scope_type", "scope_key", "trading_date"])
    op.create_index("ix_mood_snapshots_trading_date", "mood_snapshots", ["trading_date"])
    op.create_index("ix_mood_snapshots_state", "mood_snapshots", ["state"])
    op.create_index("ix_mood_snapshots_input_hash", "mood_snapshots", ["input_hash"])


def downgrade() -> None:
    for index in (
        "ix_mood_snapshots_input_hash",
        "ix_mood_snapshots_state",
        "ix_mood_snapshots_trading_date",
        "ix_mood_snapshots_scope_date",
    ):
        op.drop_index(index, table_name="mood_snapshots")
    op.drop_table("mood_snapshots")
