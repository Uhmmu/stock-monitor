"""add unified investment-ledger source governance

Revision ID: 0046_unified_investment_ledger
Revises: 0045_ibkr_account_analytics
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0046_unified_investment_ledger"
down_revision = "0045_ibkr_account_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trade_transactions") as batch:
        batch.add_column(sa.Column("source_type", sa.String(24), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("authority_source", sa.String(24), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("authority_status", sa.String(32), nullable=False, server_default="active"))
        batch.add_column(sa.Column("superseded_by_source", sa.String(24)))
        batch.add_column(sa.Column("superseded_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("superseded_sync_run_id", sa.Integer(), sa.ForeignKey(
            "ibkr_flex_sync_runs.id", name="fk_trade_transactions_superseded_sync_run", ondelete="SET NULL"
        )))
        batch.add_column(sa.Column("superseded_by_record_id", sa.Integer(), sa.ForeignKey(
            "ibkr_flex_records.id", name="fk_trade_transactions_superseded_record", ondelete="SET NULL"
        )))
        batch.add_column(sa.Column("match_confidence", sa.Float()))
        batch.add_column(sa.Column("match_method", sa.String(48)))
    # Preserve the meaning of existing journal/import rows during backfill.
    op.execute("UPDATE trade_transactions SET source_type = source, authority_source = source WHERE source <> 'manual'")
    for name, columns in (
        ("ix_trade_transactions_source_type", ["source_type"]),
        ("ix_trade_transactions_authority_source", ["authority_source"]),
        ("ix_trade_transactions_authority_status", ["authority_status"]),
        ("ix_trade_transactions_superseded_sync_run_id", ["superseded_sync_run_id"]),
        ("ix_trade_transactions_superseded_by_record_id", ["superseded_by_record_id"]),
    ):
        op.create_index(name, "trade_transactions", columns)


def downgrade() -> None:
    with op.batch_alter_table("trade_transactions") as batch:
        for name in (
            "ix_trade_transactions_superseded_by_record_id",
            "ix_trade_transactions_superseded_sync_run_id",
            "ix_trade_transactions_authority_status",
            "ix_trade_transactions_authority_source",
            "ix_trade_transactions_source_type",
        ):
            batch.drop_index(name)
        for name in (
            "match_method", "match_confidence", "superseded_by_record_id",
            "superseded_sync_run_id", "superseded_at", "superseded_by_source",
            "authority_status", "authority_source", "source_type",
        ):
            batch.drop_column(name)
