"""add crypto collection runs and sync states

Revision ID: 0069_crypto_collection_runs
Revises: 0068_crypto_instruments

WP 2.2: durable due-claim run records for crypto provider syncs plus
per-instrument/provider/data-kind watermark state used by candle backfill.
"""

from alembic import op
import sqlalchemy as sa


revision = "0069_crypto_collection_runs"
down_revision = "0068_crypto_instruments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.UniqueConstraint("provider", "domain", "bucket", name="uq_crypto_collection_runs_claim"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'partial', 'failed')",
            name="ck_crypto_collection_runs_status",
        ),
    )
    op.create_index("ix_crypto_collection_runs_status", "crypto_collection_runs", ["status"])
    op.create_index(
        "ix_crypto_collection_runs_provider_domain", "crypto_collection_runs",
        ["provider", "domain", "started_at"],
    )

    op.create_table(
        "crypto_sync_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("data_kind", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False, server_default=""),
        sa.Column("watermark_ms", sa.BigInteger(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "instrument_id", "provider", "data_kind", "interval", name="uq_crypto_sync_states_key"
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["crypto_instruments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_crypto_sync_states_next_due_at", "crypto_sync_states", ["next_due_at"])


def downgrade() -> None:
    op.drop_index("ix_crypto_sync_states_next_due_at", table_name="crypto_sync_states")
    op.drop_table("crypto_sync_states")
    op.drop_index(
        "ix_crypto_collection_runs_provider_domain", table_name="crypto_collection_runs"
    )
    op.drop_index("ix_crypto_collection_runs_status", table_name="crypto_collection_runs")
    op.drop_table("crypto_collection_runs")
