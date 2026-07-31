"""link trading journal rows to portfolio transactions

Revision ID: 0038_journal_portfolio_sync
Revises: 0037_ai_conversations
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op


revision = "0038_journal_portfolio_sync"
down_revision = "0037_ai_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "trade_transactions", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.add_column(sa.Column("source_log_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("source_log_row_index", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_trade_transactions_source_log_id",
            "trade_logs",
            ["source_log_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_trade_transactions_source_log_id", ["source_log_id"])
        batch_op.create_unique_constraint(
            "uq_trade_transactions_journal_row",
            ["source_log_id", "source_log_row_index"],
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "trade_transactions", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.drop_constraint("uq_trade_transactions_journal_row", type_="unique")
        batch_op.drop_index("ix_trade_transactions_source_log_id")
        batch_op.drop_constraint(
            "fk_trade_transactions_source_log_id", type_="foreignkey"
        )
        batch_op.drop_column("source_log_row_index")
        batch_op.drop_column("source_log_id")
