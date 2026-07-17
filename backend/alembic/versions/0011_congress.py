"""add congress_trades + tracked_figures + figure_positions (政客交易/名人持仓)

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "congress_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_uid", sa.String(length=64), nullable=False),
        sa.Column("filer_id", sa.String(length=64), nullable=False),
        sa.Column("filer_name", sa.String(length=128), nullable=False),
        sa.Column("chamber", sa.String(length=16), nullable=True),
        sa.Column("branch", sa.String(length=16), nullable=True),
        sa.Column("party", sa.String(length=8), nullable=True),
        sa.Column("state", sa.String(length=8), nullable=True),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("asset_name", sa.Text(), nullable=True),
        sa.Column("asset_type", sa.String(length=16), nullable=True),
        sa.Column("transaction_type", sa.String(length=32), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("amount_low", sa.Float(), nullable=True),
        sa.Column("amount_high", sa.Float(), nullable=True),
        sa.Column("amount_label", sa.String(length=64), nullable=True),
        sa.Column("is_late", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_uid"),
    )
    op.create_index("ix_congress_trades_filer_id", "congress_trades", ["filer_id"])
    op.create_index("ix_congress_trades_filer_name", "congress_trades", ["filer_name"])
    op.create_index("ix_congress_trades_ticker", "congress_trades", ["ticker"])
    op.create_index("ix_congress_trades_transaction_date", "congress_trades", ["transaction_date"])

    op.create_table(
        "tracked_figures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="politician"),
        sa.Column("kadoa_filer_id", sa.String(length=64), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_seed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tracked_figures_slug", "tracked_figures", ["slug"])
    op.create_index("ix_tracked_figures_kadoa_filer_id", "tracked_figures", ["kadoa_filer_id"])

    op.create_table(
        "figure_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("figure_slug", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=True),
        sa.Column("asset_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False, server_default="stock"),
        sa.Column("baseline_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adjusted_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_percent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("figure_slug", "ticker", "asset_name"),
    )
    op.create_index("ix_figure_positions_figure_slug", "figure_positions", ["figure_slug"])


def downgrade():
    op.drop_index("ix_figure_positions_figure_slug", table_name="figure_positions")
    op.drop_table("figure_positions")
    op.drop_index("ix_tracked_figures_kadoa_filer_id", table_name="tracked_figures")
    op.drop_index("ix_tracked_figures_slug", table_name="tracked_figures")
    op.drop_table("tracked_figures")
    op.drop_index("ix_congress_trades_transaction_date", table_name="congress_trades")
    op.drop_index("ix_congress_trades_ticker", table_name="congress_trades")
    op.drop_index("ix_congress_trades_filer_name", table_name="congress_trades")
    op.drop_index("ix_congress_trades_filer_id", table_name="congress_trades")
    op.drop_table("congress_trades")
