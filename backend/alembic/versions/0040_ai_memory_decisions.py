"""add conversation summaries, controlled memory, and decision journal

Revision ID: 0040_ai_memory_decisions
Revises: 0039_external_search
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040_ai_memory_decisions"
down_revision = "0039_external_search"
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_conversation_summary_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("from_message_id", sa.Integer(), nullable=True),
        sa.Column("through_message_id", sa.Integer(), nullable=True),
        sa.Column("source_message_count", sa.Integer(), nullable=False),
        sa.Column("source_character_count", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("structured_summary", JSONB, nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message_safe", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','completed','failed','superseded')",
            name="ck_ai_conversation_summary_snapshots_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["from_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["through_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "version", name="uq_ai_summary_snapshot_version"
        ),
    )
    for name, columns in (
        ("ix_ai_conversation_summary_snapshots_user_id", ["user_id"]),
        (
            "ix_ai_conversation_summary_snapshots_conversation_id",
            ["conversation_id"],
        ),
        (
            "ix_ai_conversation_summary_snapshots_through_message_id",
            ["through_message_id"],
        ),
        (
            "ix_ai_summary_snapshots_conversation_status",
            ["conversation_id", "status", "version"],
        ),
    ):
        op.create_index(name, "ai_conversation_summary_snapshots", columns)

    op.create_table(
        "ai_investment_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("decision_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("primary_symbol", sa.String(32), nullable=True),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("time_horizon", sa.String(24), nullable=False),
        sa.Column("target_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("position_intent", sa.String(64), nullable=True),
        sa.Column("target_weight", sa.Numeric(9, 6), nullable=True),
        sa.Column("target_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("target_price_min", sa.Numeric(20, 6), nullable=True),
        sa.Column("target_price_max", sa.Numeric(20, 6), nullable=True),
        sa.Column("thesis", sa.JSON(), nullable=False),
        sa.Column("catalysts", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("invalidation_conditions", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("open_questions", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("source_conversation_id", sa.Integer(), nullable=True),
        sa.Column("source_user_message_id", sa.Integer(), nullable=True),
        sa.Column("source_assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("executed_trade_id", sa.Integer(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','active','executed','partially_executed','cancelled','invalidated','closed','archived')",
            name="ck_ai_investment_decisions_status",
        ),
        sa.ForeignKeyConstraint(
            ["executed_trade_id"], ["trade_transactions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_assistant_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["ai_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_user_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_ai_investment_decisions_user_id", ["user_id"]),
        ("ix_ai_investment_decisions_decision_type", ["decision_type"]),
        ("ix_ai_investment_decisions_primary_symbol", ["primary_symbol"]),
        ("ix_ai_investment_decisions_portfolio_id", ["portfolio_id"]),
        (
            "ix_ai_investment_decisions_source_conversation_id",
            ["source_conversation_id"],
        ),
        ("ix_ai_investment_decisions_executed_trade_id", ["executed_trade_id"]),
        (
            "ix_ai_investment_decisions_user_status",
            ["user_id", "status"],
        ),
        (
            "ix_ai_investment_decisions_user_symbol",
            ["user_id", "primary_symbol", "status"],
        ),
        (
            "ix_ai_investment_decisions_user_review",
            ["user_id", "target_review_at", "status"],
        ),
    ):
        op.create_index(name, "ai_investment_decisions", columns)

    op.create_table(
        "ai_user_memory_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("use_in_context", sa.Boolean(), nullable=False),
        sa.Column("candidate_extraction_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "ai_user_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(40), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_value", JSONB, nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("normalized_content_hash", sa.String(64), nullable=False),
        sa.Column("source_conversation_id", sa.Integer(), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_decision_id", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_memory_id", sa.Integer(), nullable=True),
        sa.Column("conflict_group", sa.String(64), nullable=True),
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
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposed','active','rejected','stale','expired','archived','deleted')",
            name="ck_ai_user_memories_status",
        ),
        sa.CheckConstraint(
            "scope IN ('global','portfolio','symbol','project','page_context')",
            name="ck_ai_user_memories_scope",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["ai_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_decision_id"],
            ["ai_investment_decisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_memory_id"], ["ai_user_memories.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_ai_user_memories_user_id", ["user_id"]),
        ("ix_ai_user_memories_memory_type", ["memory_type"]),
        (
            "ix_ai_user_memories_source_conversation_id",
            ["source_conversation_id"],
        ),
        ("ix_ai_user_memories_source_message_id", ["source_message_id"]),
        ("ix_ai_user_memories_source_decision_id", ["source_decision_id"]),
        ("ix_ai_user_memories_expires_at", ["expires_at"]),
        ("ix_ai_user_memories_stale_after", ["stale_after"]),
        ("ix_ai_user_memories_supersedes_memory_id", ["supersedes_memory_id"]),
        ("ix_ai_user_memories_conflict_group", ["conflict_group"]),
        ("ix_ai_user_memories_user_status", ["user_id", "status"]),
        (
            "ix_ai_user_memories_user_scope",
            ["user_id", "scope", "scope_key", "status"],
        ),
        (
            "ix_ai_user_memories_signature",
            [
                "user_id",
                "memory_type",
                "scope",
                "scope_key",
                "normalized_content_hash",
            ],
        ),
    ):
        op.create_index(name, "ai_user_memories", columns)

    op.create_table(
        "ai_memory_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("before_value", JSONB, nullable=True),
        sa.Column("after_value", JSONB, nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["ai_user_memories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_memory_events_user_id", "ai_memory_events", ["user_id"])
    op.create_index(
        "ix_ai_memory_events_memory_id", "ai_memory_events", ["memory_id"]
    )
    op.create_index(
        "ix_ai_memory_events_memory_created",
        "ai_memory_events",
        ["memory_id", "created_at"],
    )
    op.create_index(
        "ix_ai_memory_events_user_created",
        "ai_memory_events",
        ["user_id", "created_at"],
    )

    op.create_table(
        "ai_investment_decision_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("authority", sa.String(128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("locator", sa.String(500), nullable=True),
        sa.Column("evidence_summary", sa.String(1000), nullable=False),
        sa.Column("evidence_role", sa.String(24), nullable=False),
        sa.Column("freshness_status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["ai_investment_decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_id", "source_id", name="uq_ai_decision_evidence_source"
        ),
    )
    op.create_index(
        "ix_ai_investment_decision_evidence_user_id",
        "ai_investment_decision_evidence",
        ["user_id"],
    )
    op.create_index(
        "ix_ai_investment_decision_evidence_decision_id",
        "ai_investment_decision_evidence",
        ["decision_id"],
    )
    op.create_index(
        "ix_ai_decision_evidence_decision_created",
        "ai_investment_decision_evidence",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "ai_investment_decision_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thesis_status", sa.String(24), nullable=False),
        sa.Column("invalidation_status", sa.String(24), nullable=False),
        sa.Column("execution_status", sa.String(32), nullable=True),
        sa.Column("what_changed", sa.Text(), nullable=False),
        sa.Column("supporting_changes", sa.JSON(), nullable=False),
        sa.Column("contradicting_changes", sa.JSON(), nullable=False),
        sa.Column("lessons", sa.JSON(), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("linked_message_id", sa.Integer(), nullable=True),
        sa.Column("linked_conversation_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["decision_id"], ["ai_investment_decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["linked_conversation_id"],
            ["ai_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_message_id"], ["ai_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_investment_decision_reviews_user_id",
        "ai_investment_decision_reviews",
        ["user_id"],
    )
    op.create_index(
        "ix_ai_investment_decision_reviews_decision_id",
        "ai_investment_decision_reviews",
        ["decision_id"],
    )
    op.create_index(
        "ix_ai_decision_reviews_decision_reviewed",
        "ai_investment_decision_reviews",
        ["decision_id", "reviewed_at"],
    )

    op.create_table(
        "ai_message_memory_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("usage_type", sa.String(24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["ai_user_memories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["ai_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "memory_id",
            "usage_type",
            name="uq_ai_message_memory_usage",
        ),
    )
    for column in ("user_id", "message_id", "memory_id"):
        op.create_index(
            f"ix_ai_message_memory_usage_{column}",
            "ai_message_memory_usage",
            [column],
        )

    op.create_table(
        "ai_message_decision_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["ai_investment_decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["ai_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "decision_id", name="uq_ai_message_decision_usage"
        ),
    )
    for column in ("user_id", "message_id", "decision_id"):
        op.create_index(
            f"ix_ai_message_decision_usage_{column}",
            "ai_message_decision_usage",
            [column],
        )

    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.add_column(
            sa.Column("current_summary_snapshot_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_ai_conversations_current_summary_snapshot",
            "ai_conversation_summary_snapshots",
            ["current_summary_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_ai_conversations_current_summary_snapshot_id",
            ["current_summary_snapshot_id"],
        )
    with op.batch_alter_table("ai_messages") as batch_op:
        batch_op.add_column(
            sa.Column("summary_snapshot_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_ai_messages_summary_snapshot",
            "ai_conversation_summary_snapshots",
            ["summary_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_ai_messages_summary_snapshot_id", ["summary_snapshot_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_messages") as batch_op:
        batch_op.drop_index("ix_ai_messages_summary_snapshot_id")
        batch_op.drop_constraint(
            "fk_ai_messages_summary_snapshot", type_="foreignkey"
        )
        batch_op.drop_column("summary_snapshot_id")
    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.drop_index("ix_ai_conversations_current_summary_snapshot_id")
        batch_op.drop_constraint(
            "fk_ai_conversations_current_summary_snapshot",
            type_="foreignkey",
        )
        batch_op.drop_column("current_summary_snapshot_id")

    op.drop_table("ai_message_decision_usage")
    op.drop_table("ai_message_memory_usage")
    op.drop_table("ai_investment_decision_reviews")
    op.drop_table("ai_investment_decision_evidence")
    op.drop_table("ai_memory_events")
    op.drop_table("ai_user_memories")
    op.drop_table("ai_user_memory_preferences")
    op.drop_table("ai_investment_decisions")
    op.drop_table("ai_conversation_summary_snapshots")
