"""add persisted Alpha Vantage US macroeconomic series

Revision ID: 0048_alpha_vantage_macro
Revises: 0047_ibkr_journal_drafts
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0048_alpha_vantage_macro"
down_revision = "0047_ibkr_journal_drafts"
branch_labels = None
depends_on = None


SERIES = [
    ("us_real_gdp", "REAL_GDP", {}, "实际 GDP", "Real GDP", "currency", "quarterly", "growth"),
    ("us_real_gdp_per_capita", "REAL_GDP_PER_CAPITA", {}, "人均实际 GDP", "Real GDP per Capita", "currency_per_capita", "quarterly", "growth"),
    ("us_treasury_3m", "TREASURY_YIELD", {"interval": "daily", "maturity": "3month"}, "美国 3 个月国债收益率", "US 3-Month Treasury Yield", "percent", "daily", "rates"),
    ("us_treasury_2y", "TREASURY_YIELD", {"interval": "daily", "maturity": "2year"}, "美国 2 年期国债收益率", "US 2-Year Treasury Yield", "percent", "daily", "rates"),
    ("us_treasury_5y", "TREASURY_YIELD", {"interval": "daily", "maturity": "5year"}, "美国 5 年期国债收益率", "US 5-Year Treasury Yield", "percent", "daily", "rates"),
    ("us_treasury_10y", "TREASURY_YIELD", {"interval": "daily", "maturity": "10year"}, "美国 10 年期国债收益率", "US 10-Year Treasury Yield", "percent", "daily", "rates"),
    ("us_treasury_30y", "TREASURY_YIELD", {"interval": "daily", "maturity": "30year"}, "美国 30 年期国债收益率", "US 30-Year Treasury Yield", "percent", "daily", "rates"),
    ("us_federal_funds_rate", "FEDERAL_FUNDS_RATE", {"interval": "daily"}, "联邦基金利率", "Federal Funds Rate", "percent", "daily", "rates"),
    ("us_cpi", "CPI", {"interval": "monthly"}, "消费者价格指数（CPI）", "Consumer Price Index", "index", "monthly", "inflation"),
    ("us_annual_inflation", "INFLATION", {}, "年度通胀率", "Annual Inflation", "percent", "annual", "inflation"),
    ("us_retail_sales", "RETAIL_SALES", {}, "零售销售", "Retail Sales", "currency", "monthly", "consumer"),
    ("us_durable_goods_orders", "DURABLES", {}, "耐用品订单", "Durable Goods Orders", "currency", "monthly", "consumer"),
    ("us_unemployment_rate", "UNEMPLOYMENT", {}, "失业率", "Unemployment Rate", "percent", "monthly", "labor"),
    ("us_nonfarm_payroll_total", "NONFARM_PAYROLL", {}, "非农就业总人数", "Total Nonfarm Payroll", "persons", "monthly", "labor"),
]


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="alpha_vantage"),
        sa.Column("provider_function", sa.String(length=64), nullable=False),
        sa.Column("provider_parameters_json", sa.JSON(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="US"),
        sa.Column("display_name_zh", sa.String(length=128), nullable=False),
        sa.Column("display_name_en", sa.String(length=128), nullable=False),
        sa.Column("description_zh", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False, server_default="Alpha Vantage"),
        sa.Column("is_derived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "series_key", name="uq_macro_series_provider_key"),
    )
    op.create_index("ix_macro_series_series_key", "macro_series", ["series_key"])
    op.create_index("ix_macro_series_provider", "macro_series", ["provider"])
    op.create_index("ix_macro_series_country_code", "macro_series", ["country_code"])
    op.create_index("ix_macro_series_frequency", "macro_series", ["frequency"])
    op.create_index("ix_macro_series_category", "macro_series", ["category"])
    op.create_index("ix_macro_series_enabled", "macro_series", ["enabled"])
    op.create_index("ix_macro_series_country_category_enabled", "macro_series", ["country_code", "category", "enabled"])

    op.create_table(
        "macro_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(24, 10), nullable=False),
        sa.Column("raw_value", sa.Numeric(24, 10), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="alpha_vantage"),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("is_preliminary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["macro_series.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_id", "observation_date", name="uq_macro_observations_series_date"),
    )
    op.create_index("ix_macro_observations_series_id", "macro_observations", ["series_id"])
    op.create_index("ix_macro_observations_observation_date", "macro_observations", ["observation_date"])
    op.create_index("ix_macro_observations_last_fetched_at", "macro_observations", ["last_fetched_at"])
    op.create_index("ix_macro_observations_series_date_desc", "macro_observations", ["series_id", "observation_date"])

    op.create_table(
        "macro_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="alpha_vantage"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("requested_series_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_series_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_series_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_requests_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary_json", sa.JSON(), nullable=False),
        sa.Column("trigger_type", sa.String(length=24), nullable=False, server_default="scheduled"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_macro_sync_runs_provider", "macro_sync_runs", ["provider"])
    op.create_index("ix_macro_sync_runs_started_at", "macro_sync_runs", ["started_at"])
    op.create_index("ix_macro_sync_runs_status", "macro_sync_runs", ["status"])
    op.create_index("ix_macro_sync_runs_trigger_type", "macro_sync_runs", ["trigger_type"])
    op.create_index("ix_macro_sync_runs_provider_started", "macro_sync_runs", ["provider", "started_at"])

    op.create_table(
        "macro_api_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="alpha_vantage"),
        sa.Column("usage_date_utc", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_limited_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "usage_date_utc", name="uq_macro_api_usage_provider_date"),
    )
    op.create_index("ix_macro_api_usage_provider", "macro_api_usage", ["provider"])
    op.create_index("ix_macro_api_usage_usage_date_utc", "macro_api_usage", ["usage_date_utc"])
    op.create_index("ix_macro_api_usage_provider_date", "macro_api_usage", ["provider", "usage_date_utc"])

    rows = []
    for key, function, params, name_zh, name_en, unit, frequency, category in SERIES:
        rows.append({
            "series_key": key,
            "provider": "alpha_vantage",
            "provider_function": function,
            "provider_parameters_json": params,
            "country_code": "US",
            "display_name_zh": name_zh,
            "display_name_en": name_en,
            "description_zh": "美国宏观时间序列；派生变化由项目本地根据历史观察值计算。",
            "unit": unit,
            "frequency": frequency,
            "category": category,
            "source_name": "Alpha Vantage（数据标注的美国官方/FRED序列）",
            "is_derived": False,
            "enabled": True,
        })
    op.bulk_insert(sa.table("macro_series", *[
        sa.column(name, typ) for name, typ in (
            ("series_key", sa.String(64)), ("provider", sa.String(32)), ("provider_function", sa.String(64)),
            ("provider_parameters_json", sa.JSON()), ("country_code", sa.String(2)), ("display_name_zh", sa.String(128)),
            ("display_name_en", sa.String(128)), ("description_zh", sa.Text()), ("unit", sa.String(32)),
            ("frequency", sa.String(16)), ("category", sa.String(32)), ("source_name", sa.String(128)),
            ("is_derived", sa.Boolean()), ("enabled", sa.Boolean()),
        )
    ]), rows)


def downgrade() -> None:
    op.drop_table("macro_api_usage")
    op.drop_table("macro_sync_runs")
    op.drop_table("macro_observations")
    op.drop_table("macro_series")
