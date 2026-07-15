from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    default_threshold_20m: float = 2.0
    default_threshold_1h: float = 4.0
    default_threshold_day: float = 6.0
    alert_cooldown_minutes: int = 60
    investigation_interval_minutes: int = 20
    investigation_duration_minutes: int = 120
    earnings_lookahead_days: int = 7
    finnhub_mcp_url: str = "http://finnhub-mcp:8125/mcp"
    archive_dir: str = "/data/archive"
    news_poll_minutes: int = 15
    news_relevance_threshold: float = 0.15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
