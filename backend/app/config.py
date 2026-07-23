from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 全应用统一版本号。所有新的分析元数据（技术信号、价格区间、到达估计等）都引用它，
# 而不是各处硬编码字符串。analyzer / parameter_set / analysis_engine 三个版本目前都等于
# APP_VERSION，但在数据库里分开存储，方便将来单独演进。
APP_VERSION = "v0.4"
ANALYZER_VERSION = APP_VERSION
PARAMETER_SET_VERSION = APP_VERSION
ANALYSIS_ENGINE_VERSION = APP_VERSION


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://stock:stock@postgres:5432/stock_monitor"
    redis_url: str = "redis://redis:6379/0"
    tavily_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_simple: str = "gpt-5.4-mini"
    model_medium: str = "gpt-5.6-luna"
    model_important: str = "gpt-5.6-sol"
    translation_api_key: str = ""
    translation_base_url: str = "https://www.right.codes/claude-aws/v1"
    translation_model: str = "claude-haiku-4-5-20251001"
    translation_batch_size: int = 20
    translation_max_attempts: int = 3
    market_timezone: str = "America/New_York"
    price_poll_minutes: int = 5
    default_threshold_20m: float = 5.0
    default_threshold_1h: float = 5.0
    default_threshold_day: float = 5.0
    alert_cooldown_minutes: int = 60
    investigation_interval_minutes: int = 20
    investigation_duration_minutes: int = 120
    earnings_lookahead_days: int = 7
    finnhub_mcp_url: str = "http://finnhub-mcp:8125/mcp"
    finnhub_api_key: str = ""
    archive_dir: str = "/data/archive"
    news_poll_minutes: int = 15
    news_relevance_threshold: float = 0.15
    marketaux_api_key: str = ""
    marketaux_enabled: bool = True
    marketaux_max_requests_per_day: int = 100
    marketaux_batch_size: int = 5
    market_news_enabled: bool = True
    finnhub_market_news_enabled: bool = True
    marketaux_market_news_enabled: bool = True
    market_news_poll_minutes: int = 60
    marketaux_market_requests_reserve: int = 12
    market_news_max_items: int = 20
    fmp_enabled: bool = True
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    fmp_news_batch_size: int = 10
    fmp_news_interval_seconds: int = 7200
    fmp_request_timeout_seconds: int = 15
    fmp_daily_call_limit: int = 200
    # FMP is restricted to cached company profiles and historical EOD prices.
    # Quota accounting resets on the UTC calendar day.
    fmp_daily_request_limit: int = 150
    fmp_request_reserve: int = 10
    fmp_sync_enabled: bool = True
    fmp_profile_sync_enabled: bool = True
    fmp_price_sync_enabled: bool = True
    fmp_translation_enabled: bool = True
    fmp_profile_refresh_days: int = 180
    technical_chart_dir: str = "/data/technical-charts"
    sec_user_agent: str = "stockMonitor/1.0 self-hosted@example.com"
    edgar_local_data_dir: str = "/data/edgar"
    sec_insider_heavy_sell_value: float = 1_000_000.0
    # 13F ticker→CUSIP 手动兜底覆盖，形如 "IREN:45840M108,ABC:012345678"
    sec_13f_cusip_overrides: str = ""
    # 13F 数据集下载页（运行时解析真实 zip 链接，避免猜文件命名）
    sec_13f_index_url: str = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
    # Low-frequency Perplexity Agent API discovery. User-editable, non-secret
    # defaults live in StockDiscoverySettings; the key and endpoint stay server-only.
    perplexity_api_key: str = ""
    perplexity_agent_url: str = "https://api.perplexity.ai/v1/agent"
    perplexity_agent_model: str = "openai/gpt-5.4"
    perplexity_max_steps: int = 5
    perplexity_max_output_tokens: int = 12000
    perplexity_enable_web_search: bool = True
    perplexity_discovery_interval_days: int = 3
    perplexity_max_monthly_budget_usd: float = 10.0
    perplexity_max_run_cost_usd: float = 1.0
    perplexity_request_timeout_seconds: int = 240
    perplexity_manual_refresh_cooldown_seconds: int = 60
    perplexity_evaluation_budget_usd: float = 2.0
    perplexity_live_evaluation_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
