"""expand persisted market price snapshots

Revision ID: 0042_price_market_snapshots
Revises: 0041_ai_rich_content
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042_price_market_snapshots"
down_revision = "0041_ai_rich_content"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _old_unique_constraint_name() -> str | None:
    bind = op.get_bind()
    for constraint in sa.inspect(bind).get_unique_constraints("price_snapshots"):
        if set(constraint.get("column_names") or []) == {"ticker", "quote_time"}:
            return constraint.get("name")
    return None


def upgrade() -> None:
    old_unique = _old_unique_constraint_name()
    if old_unique:
        op.drop_constraint(old_unique, "price_snapshots", type_="unique")

    columns = (
        sa.Column("exchange", sa.String(64), nullable=True),
        sa.Column("currency", sa.String(12), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("provider_symbol", sa.String(32), nullable=True),
        sa.Column("provider_role", sa.String(32), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("day_high", sa.Float(), nullable=True),
        sa.Column("day_low", sa.Float(), nullable=True),
        sa.Column("price_change", sa.Float(), nullable=True),
        sa.Column("price_change_percent", sa.Float(), nullable=True),
        sa.Column("average_volume_10d", sa.Float(), nullable=True),
        sa.Column("average_volume_20d", sa.Float(), nullable=True),
        sa.Column("relative_volume_20d", sa.Float(), nullable=True),
        sa.Column("relative_volume_basis", sa.String(32), nullable=True),
        sa.Column("trading_date", sa.Date(), nullable=True),
        sa.Column("market_session", sa.String(16), nullable=True),
        sa.Column("timestamp_source", sa.String(32), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_delayed", sa.Boolean(), nullable=True),
        sa.Column("delay_seconds", sa.Integer(), nullable=True),
        sa.Column("raw_payload", JSON_VALUE, nullable=True),
        sa.Column("snapshot_key", sa.String(64), nullable=True),
    )
    for column in columns:
        op.add_column("price_snapshots", column)

    # Historical quote_time was populated with datetime.now() by the old
    # fetcher. Preserve it as retrieval time, but do not relabel it as a
    # provider market timestamp.
    op.execute(
        sa.text(
            "UPDATE price_snapshots "
            "SET fetched_at = quote_time, source_type = 'price_snapshot', "
            "provider_role = 'market_data_aggregator', market_session = 'unknown'"
        )
    )
    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.alter_column("quote_time", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column("source_type", existing_type=sa.String(32), nullable=False)
        batch_op.alter_column("market_session", existing_type=sa.String(16), nullable=False)
    op.execute(sa.text("UPDATE price_snapshots SET quote_time = NULL"))

    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.create_unique_constraint(
            "uq_price_snapshots_snapshot_key",
            ["snapshot_key"],
        )
    op.create_index(
        "ix_price_snapshots_latest",
        "price_snapshots",
        ["ticker", "quote_time", "fetched_at", "persisted_at"],
    )
    op.create_index("ix_price_snapshots_fetched_at", "price_snapshots", ["fetched_at"])
    op.create_index("ix_price_snapshots_persisted_at", "price_snapshots", ["persisted_at"])


def downgrade() -> None:
    op.drop_index("ix_price_snapshots_persisted_at", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_fetched_at", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_latest", table_name="price_snapshots")
    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.drop_constraint(
            "uq_price_snapshots_snapshot_key",
            type_="unique",
        )

    # The legacy schema requires quote_time. On downgrade only, fall back to
    # the historical retrieval timestamp so the old application can start.
    op.execute(
        sa.text(
            "UPDATE price_snapshots "
            "SET quote_time = COALESCE(quote_time, fetched_at, persisted_at)"
        )
    )
    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.alter_column("quote_time", existing_type=sa.DateTime(timezone=True), nullable=False)

    for name in (
        "snapshot_key",
        "raw_payload",
        "delay_seconds",
        "is_delayed",
        "persisted_at",
        "fetched_at",
        "timestamp_source",
        "market_session",
        "trading_date",
        "relative_volume_basis",
        "relative_volume_20d",
        "average_volume_20d",
        "average_volume_10d",
        "price_change_percent",
        "price_change",
        "day_low",
        "day_high",
        "open_price",
        "provider_role",
        "provider_symbol",
        "source_type",
        "currency",
        "exchange",
    ):
        op.drop_column("price_snapshots", name)

    with op.batch_alter_table("price_snapshots") as batch_op:
        batch_op.create_unique_constraint(
            "uq_price_snapshots_ticker_quote_time",
            ["ticker", "quote_time"],
        )
