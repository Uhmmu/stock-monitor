"""add Mood validation research runs and generic results

Revision ID: 0060_mood_validation_lab
Revises: 0059_ai_mood_engine
"""

from alembic import op
import sqlalchemy as sa


revision = "0060_mood_validation_lab"
down_revision = "0059_ai_mood_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mood_validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("calculation_version", sa.String(32), nullable=False),
        sa.Column("validation_version", sa.String(64), nullable=False),
        sa.Column("parameter_set", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("scope_filter", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("benchmark_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("forward_horizons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("data_cutoff", sa.Date(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_mood_validation_runs_created", "mood_validation_runs", ["created_at"])
    op.create_index("ix_mood_validation_runs_status", "mood_validation_runs", ["status"])
    op.create_index("ix_mood_validation_runs_created_by_user_id", "mood_validation_runs", ["created_by_user_id"])

    op.create_table(
        "mood_validation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("mood_validation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_key", sa.String(64), nullable=False),
        sa.Column("study_type", sa.String(40), nullable=False),
        sa.Column("scope_type", sa.String(24)),
        sa.Column("scope_key", sa.String(192)),
        sa.Column("state", sa.String(32)),
        sa.Column("transition_from", sa.String(32)),
        sa.Column("transition_to", sa.String(32)),
        sa.Column("divergence_type", sa.String(32)),
        sa.Column("bucket", sa.String(32)),
        sa.Column("horizon", sa.Integer()),
        sa.Column("sample_mode", sa.String(24), nullable=False, server_default="daily"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence_interval", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("quality", sa.String(24), nullable=False, server_default="INSUFFICIENT_SAMPLE"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("event_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "result_key", name="uq_mood_validation_results_run_key"),
    )
    op.create_index("ix_mood_validation_results_run_id", "mood_validation_results", ["run_id"])
    op.create_index("ix_mood_validation_results_study_type", "mood_validation_results", ["study_type"])
    op.create_index("ix_mood_validation_results_run_study", "mood_validation_results", ["run_id", "study_type"])
    op.create_index("ix_mood_validation_results_scope", "mood_validation_results", ["run_id", "scope_type", "scope_key"])


def downgrade() -> None:
    op.drop_table("mood_validation_results")
    op.drop_table("mood_validation_runs")
