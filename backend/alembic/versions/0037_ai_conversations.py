"""add user-owned AI conversations and message evidence

Revision ID: 0037_ai_conversations
Revises: 0036_portfolio_analysis_runs
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_ai_conversations"
down_revision = "0036_portfolio_analysis_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("title_source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("active_symbol", sa.String(32), nullable=True),
        sa.Column("active_symbols", sa.JSON(), nullable=False),
        sa.Column("active_portfolio_id", sa.Integer(), nullable=True),
        sa.Column("page_context", sa.String(32), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("response_mode", sa.String(16), nullable=False),
        sa.Column("system_prompt_version", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_status", sa.String(16), nullable=False),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("completed_message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active','archived','deleted')", name="ck_ai_conversations_status"),
        sa.CheckConstraint("summary_status IN ('none','pending','ready','stale','failed')", name="ck_ai_conversations_summary_status"),
        sa.ForeignKeyConstraint(["active_portfolio_id"], ["portfolios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_index("ix_ai_conversations_active_portfolio_id", "ai_conversations", ["active_portfolio_id"])
    op.create_index("ix_ai_conversations_last_message_at", "ai_conversations", ["last_message_at"])
    op.create_index("ix_ai_conversations_user_deleted_last", "ai_conversations", ["user_id", "deleted_at", "last_message_at"])
    op.create_index("ix_ai_conversations_user_status_last", "ai_conversations", ["user_id", "status", "last_message_at"])
    op.create_index("ix_ai_conversations_user_archived", "ai_conversations", ["user_id", "archived_at"])

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(16), nullable=False),
        sa.Column("parent_message_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("regenerated_from_message_id", sa.Integer(), nullable=True),
        sa.Column("generation_index", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("provider_response_id", sa.String(256), nullable=True),
        sa.Column("system_prompt_version", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message_safe", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_ai_messages_role"),
        sa.CheckConstraint("status IN ('pending','streaming','completed','partial','failed','cancelled')", name="ck_ai_messages_status"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["regenerated_from_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reply_to_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_ai_messages_conversation_id", ["conversation_id"]),
        ("ix_ai_messages_user_id", ["user_id"]),
        ("ix_ai_messages_parent_message_id", ["parent_message_id"]),
        ("ix_ai_messages_regenerated_from_message_id", ["regenerated_from_message_id"]),
        ("ix_ai_messages_conversation_created", ["conversation_id", "created_at", "id"]),
        ("ix_ai_messages_user_conversation", ["user_id", "conversation_id"]),
    ):
        op.create_index(name, "ai_messages", columns)

    op.create_table(
        "ai_message_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("citation_key", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("authority", sa.String(128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locator", sa.String(500), nullable=True),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["ai_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "citation_key", name="uq_ai_citations_message_key"),
        sa.UniqueConstraint("message_id", "source_id", name="uq_ai_citations_message_source"),
    )
    for column in ("message_id", "conversation_id", "user_id"):
        op.create_index(f"ix_ai_message_citations_{column}", "ai_message_citations", [column])

    op.create_table(
        "ai_tool_call_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("assistant_message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(256), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_mode", sa.String(16), nullable=True),
        sa.Column("normalized_arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=True),
        sa.Column("summary", sa.String(500), nullable=True),
        sa.Column("warning_codes", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("original_item_count", sa.Integer(), nullable=True),
        sa.Column("returned_item_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("reused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["ai_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assistant_message_id", "tool_call_id", name="uq_ai_tool_calls_message_call"),
    )
    for column in ("conversation_id", "assistant_message_id", "user_id"):
        op.create_index(f"ix_ai_tool_call_records_{column}", "ai_tool_call_records", [column])
    op.create_index("ix_ai_tool_calls_conversation_created", "ai_tool_call_records", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_tool_call_records")
    op.drop_table("ai_message_citations")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
