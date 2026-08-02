"""add broker-generated trading journal drafts

Revision ID: 0047_ibkr_journal_drafts
Revises: 0046_unified_investment_ledger
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_ibkr_journal_drafts"
down_revision = "0046_unified_investment_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trade_logs") as batch:
        batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="published"))
        batch.add_column(sa.Column("source_type", sa.String(24), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("objective_facts", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("ibkr_sync_run_id", sa.Integer(), sa.ForeignKey("ibkr_flex_sync_runs.id", ondelete="SET NULL")))
        batch.add_column(sa.Column("ibkr_position_id", sa.Integer(), sa.ForeignKey("portfolio_positions.id", ondelete="SET NULL")))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.create_unique_constraint("uq_trade_logs_ibkr_position_draft", ["user_id", "ibkr_sync_run_id", "ibkr_position_id"])
    for name, columns in (
        ("ix_trade_logs_status", ["status"]), ("ix_trade_logs_source_type", ["source_type"]),
        ("ix_trade_logs_ibkr_sync_run_id", ["ibkr_sync_run_id"]), ("ix_trade_logs_ibkr_position_id", ["ibkr_position_id"]),
    ):
        op.create_index(name, "trade_logs", columns)


def downgrade() -> None:
    for name in ("ix_trade_logs_ibkr_position_id", "ix_trade_logs_ibkr_sync_run_id", "ix_trade_logs_source_type", "ix_trade_logs_status"):
        op.drop_index(name, table_name="trade_logs")
    with op.batch_alter_table("trade_logs") as batch:
        batch.drop_constraint("uq_trade_logs_ibkr_position_draft", type_="unique")
        for name in ("updated_at", "ibkr_position_id", "ibkr_sync_run_id", "objective_facts", "source_type", "status"):
            batch.drop_column(name)
