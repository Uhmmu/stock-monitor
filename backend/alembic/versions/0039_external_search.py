"""add Exa external search modes and durable deep runs

Revision ID: 0039_external_search
Revises: 0038_journal_portfolio_sync
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_external_search"
down_revision = "0038_journal_portfolio_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_search_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_run_id", sa.String(256), nullable=True),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("effort", sa.String(16), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("query_preview_safe", sa.String(240), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("termination_reason", sa.String(32), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column(
            "output_structured",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("grounding", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("cost_estimated", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message_safe", sa.String(500), nullable=True),
        sa.Column("last_event_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','queued','running','completed','failed','cancelled')", name="ck_external_search_runs_status"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_external_search_runs_idempotency_key"),
        sa.UniqueConstraint("provider", "provider_run_id", name="uq_external_search_runs_provider_id"),
    )
    for name, columns in (
        ("ix_external_search_runs_public_id", ["public_id"]),
        ("ix_external_search_runs_user_id", ["user_id"]),
        ("ix_external_search_runs_conversation_id", ["conversation_id"]),
        ("ix_external_search_runs_user_message_id", ["user_message_id"]),
        ("ix_external_search_runs_assistant_message_id", ["assistant_message_id"]),
        ("ix_external_search_runs_user_status", ["user_id", "status"]),
        ("ix_external_search_runs_conversation_created", ["conversation_id", "created_at"]),
    ):
        op.create_index(name, "external_search_runs", columns, unique=name == "ix_external_search_runs_public_id")

    op.create_table(
        "external_search_run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("safe_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["external_search_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "provider_event_id", name="uq_external_search_run_events_provider"),
    )
    op.create_index("ix_external_search_run_events_run_id", "external_search_run_events", ["run_id"])
    op.create_index("ix_external_search_run_events_run_created", "external_search_run_events", ["run_id", "created_at"])

    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.add_column(sa.Column("web_access_mode", sa.String(24), nullable=False, server_default="off"))
    with op.batch_alter_table("ai_messages") as batch_op:
        batch_op.add_column(sa.Column("web_access_mode", sa.String(24), nullable=False, server_default="off"))
        batch_op.add_column(sa.Column("external_search_call_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("deep_search_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("external_search_cost_usd", sa.Numeric(12, 6), nullable=True))
        batch_op.create_foreign_key("fk_ai_messages_deep_search_run", "external_search_runs", ["deep_search_run_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_ai_messages_deep_search_run_id", ["deep_search_run_id"])
    with op.batch_alter_table("ai_tool_call_records") as batch_op:
        batch_op.add_column(sa.Column("external_provider", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("external_request_id", sa.String(256), nullable=True))
        batch_op.add_column(sa.Column("external_run_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True))
        batch_op.add_column(sa.Column("cost_estimated", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("ai_tool_call_records") as batch_op:
        for name in ("cost_estimated", "cost_usd", "external_run_id", "external_request_id", "external_provider"):
            batch_op.drop_column(name)
    with op.batch_alter_table("ai_messages") as batch_op:
        batch_op.drop_index("ix_ai_messages_deep_search_run_id")
        batch_op.drop_constraint("fk_ai_messages_deep_search_run", type_="foreignkey")
        for name in ("external_search_cost_usd", "deep_search_run_id", "external_search_call_count", "web_access_mode"):
            batch_op.drop_column(name)
    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.drop_column("web_access_mode")
    op.drop_index("ix_external_search_run_events_run_created", table_name="external_search_run_events")
    op.drop_index("ix_external_search_run_events_run_id", table_name="external_search_run_events")
    op.drop_table("external_search_run_events")
    for name in (
        "ix_external_search_runs_conversation_created", "ix_external_search_runs_user_status",
        "ix_external_search_runs_assistant_message_id", "ix_external_search_runs_user_message_id",
        "ix_external_search_runs_conversation_id", "ix_external_search_runs_user_id",
        "ix_external_search_runs_public_id",
    ):
        op.drop_index(name, table_name="external_search_runs")
    op.drop_table("external_search_runs")
