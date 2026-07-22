"""Add FMP profile/history cache and technical analysis.

Revision ID: 0023_fmp_technical
Revises: 0022_fmp_news
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_fmp_technical"
down_revision = "0022_fmp_news"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("historical_prices",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False), sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False), sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False), sa.Column("volume", sa.BigInteger()),
        sa.Column("vwap", sa.Numeric(20, 6)), sa.Column("change", sa.Numeric(20, 6)),
        sa.Column("change_percent", sa.Numeric(16, 6)), sa.Column("source", sa.String(16), nullable=False, server_default="fmp"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "date", "source", name="uq_historical_prices_symbol_date_source"),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name="ck_historical_prices_volume"))
    op.create_index("ix_historical_prices_symbol_date", "historical_prices", ["symbol", "date"])
    op.create_index("ix_historical_prices_symbol", "historical_prices", ["symbol"])
    op.create_index("ix_historical_prices_date", "historical_prices", ["date"])
    op.create_table("company_profiles",
        sa.Column("symbol", sa.String(32), primary_key=True), sa.Column("company_name", sa.String(256)),
        sa.Column("logo_url", sa.Text()), sa.Column("website", sa.Text()), sa.Column("ceo", sa.String(256)),
        sa.Column("sector", sa.String(128)), sa.Column("industry", sa.String(192)), sa.Column("country", sa.String(64)),
        sa.Column("exchange", sa.String(32)), sa.Column("exchange_full_name", sa.String(128)), sa.Column("currency", sa.String(16)),
        sa.Column("ipo_date", sa.Date()), sa.Column("employee_count", sa.BigInteger()), sa.Column("description_en", sa.Text()),
        sa.Column("description_zh", sa.Text()), sa.Column("description_source_hash", sa.String(64)),
        sa.Column("profile_source", sa.String(16), nullable=False, server_default="fmp"), sa.Column("profile_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("translation_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("translation_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("translation_next_retry_at", sa.DateTime(timezone=True)), sa.Column("translation_last_error", sa.Text()),
        sa.Column("translation_model", sa.String(128)), sa.Column("translation_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_company_profiles_description_source_hash", "company_profiles", ["description_source_hash"])
    op.create_index("ix_company_profiles_translation_status", "company_profiles", ["translation_status"])
    op.create_index("ix_company_profiles_translation_next_retry_at", "company_profiles", ["translation_next_retry_at"])
    op.create_table("fmp_sync_states",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("task_name", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False), sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"), sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("last_successful_date", sa.Date()),
        sa.Column("retry_after", sa.DateTime(timezone=True)), sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(48)), sa.Column("last_error_message", sa.Text()),
        sa.Column("quota_day", sa.Date(), nullable=False), sa.Column("requests_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("task_name", "symbol", "sync_type", name="uq_fmp_sync_state_key"),
        sa.CheckConstraint("requests_used >= 0", name="ck_fmp_sync_requests_used"))
    for col in ("task_name", "symbol", "sync_type", "status", "quota_day", "retry_after"):
        op.create_index(f"ix_fmp_sync_states_{col}", "fmp_sync_states", [col])
    op.create_table("technical_analyses",
        sa.Column("symbol", sa.String(32), primary_key=True), sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("analysis", sa.JSON(), nullable=False), sa.Column("analysis_version", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False), sa.Column("structured_hash", sa.String(64)),
        sa.Column("image_path", sa.Text()), sa.Column("image_format", sa.String(8)), sa.Column("data_through", sa.Date()),
        sa.Column("generated_at", sa.DateTime(timezone=True)), sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_technical_analyses_status", "technical_analyses", ["status"])
    op.create_index("ix_technical_analyses_input_hash", "technical_analyses", ["input_hash"])


def downgrade():
    op.drop_table("technical_analyses")
    op.drop_table("fmp_sync_states")
    op.drop_table("company_profiles")
    op.drop_table("historical_prices")
