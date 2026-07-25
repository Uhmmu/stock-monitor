"""add ownership statistics and normalized investment calendar

Revision ID: 0032_ownership_calendar
Revises: 0031_portfolio_benchmark
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_ownership_calendar"
down_revision = "0031_portfolio_benchmark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equity_share_statistics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("shares_outstanding", sa.Float(), nullable=True),
        sa.Column("float_shares", sa.Float(), nullable=True),
        sa.Column("free_float_percent", sa.Float(), nullable=True),
        sa.Column("implied_shares_outstanding", sa.Float(), nullable=True),
        sa.Column("shares_short", sa.Float(), nullable=True),
        sa.Column("shares_short_prior_month", sa.Float(), nullable=True),
        sa.Column("short_percent_of_float", sa.Float(), nullable=True),
        sa.Column("short_percent_of_outstanding", sa.Float(), nullable=True),
        sa.Column("short_ratio", sa.Float(), nullable=True),
        sa.Column("held_percent_insiders", sa.Float(), nullable=True),
        sa.Column("held_percent_institutions", sa.Float(), nullable=True),
        sa.Column("average_volume", sa.Float(), nullable=True),
        sa.Column("average_volume_10d", sa.Float(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("is_estimated", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_equity_share_statistics_symbol"),
    )
    for name, columns in (
        ("ix_equity_share_statistics_security_id", ["security_id"]),
        ("ix_equity_share_statistics_symbol", ["symbol"]),
        ("ix_equity_share_statistics_as_of_date", ["as_of_date"]),
        ("ix_equity_share_statistics_source", ["source"]),
        ("ix_equity_share_statistics_fetched_at", ["fetched_at"]),
    ):
        op.create_index(name, "equity_share_statistics", columns)

    op.create_table(
        "investment_calendar_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("security_id", sa.Integer(), nullable=True),
        sa.Column("company_name", sa.String(length=256), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_status", sa.String(length=24), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("fiscal_period", sa.String(length=16), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("is_estimated", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("impact_level", sa.String(length=16), nullable=False),
        sa.Column("primary_source", sa.String(length=32), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("has_conflict", sa.Boolean(), nullable=False),
        sa.Column("conflict_fields", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_investment_calendar_events_event_type", ["event_type"]),
        ("ix_investment_calendar_events_symbol", ["symbol"]),
        ("ix_investment_calendar_events_security_id", ["security_id"]),
        ("ix_investment_calendar_events_event_date", ["event_date"]),
        ("ix_investment_calendar_events_impact_level", ["impact_level"]),
        ("ix_investment_calendar_events_primary_source", ["primary_source"]),
        ("ix_investment_calendar_events_status", ["status"]),
        ("ix_investment_calendar_events_fetched_at", ["fetched_at"]),
        ("ix_investment_calendar_date_type", ["event_date", "event_type"]),
        ("ix_investment_calendar_symbol_date", ["symbol", "event_date"]),
    ):
        op.create_index(name, "investment_calendar_events", columns)

    op.create_table(
        "investment_calendar_event_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["investment_calendar_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "provider", "source_record_id", name="uq_calendar_event_provider_record"),
    )
    op.create_index("ix_investment_calendar_event_sources_event_id", "investment_calendar_event_sources", ["event_id"])
    op.create_index("ix_calendar_event_sources_provider", "investment_calendar_event_sources", ["provider", "fetched_at"])


def downgrade() -> None:
    op.drop_table("investment_calendar_event_sources")
    op.drop_table("investment_calendar_events")
    op.drop_table("equity_share_statistics")
