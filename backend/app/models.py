import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base


class InvestigationStatus(str, enum.Enum):
    active = "active"
    reporting = "reporting"
    completed = "completed"
    failed = "failed"


class ReportType(str, enum.Enum):
    premarket = "premarket"
    postmarket = "postmarket"
    movement = "movement"
    earnings_before = "earnings_before"
    earnings_after = "earnings_after"


class Security(Base):
    """Canonical security identity with provider-specific symbols."""
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("yahoo_symbol", name="uq_securities_yahoo_symbol"),
        UniqueConstraint("finnhub_symbol", name="uq_securities_finnhub_symbol"),
        CheckConstraint("yahoo_symbol IS NOT NULL OR finnhub_symbol IS NOT NULL", name="ck_securities_provider_symbol"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    display_symbol: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), index=True)
    local_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange_code: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange_name: Mapped[str | None] = mapped_column(String(128))
    mic_code: Mapped[str | None] = mapped_column(String(16))
    market: Mapped[str | None] = mapped_column(String(32), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    currency: Mapped[str | None] = mapped_column(String(8))
    instrument_type: Mapped[str | None] = mapped_column(String(32), index=True)
    isin: Mapped[str | None] = mapped_column(String(32), index=True)
    ibkr_conid: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    figi: Mapped[str | None] = mapped_column(String(32), index=True)
    cusip: Mapped[str | None] = mapped_column(String(32), index=True)
    yahoo_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    finnhub_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    yahoo_status: Mapped[str] = mapped_column(String(16), default="unknown")
    finnhub_status: Mapped[str] = mapped_column(String(16), default="unknown")
    mapping_confidence: Mapped[float | None] = mapped_column(Float)
    mapping_method: Mapped[str] = mapped_column(String(32), default="unresolved")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_20m: Mapped[float | None] = mapped_column(Float)
    threshold_1h: Mapped[float | None] = mapped_column(Float)
    threshold_day: Mapped[float | None] = mapped_column(Float)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    user_group_id: Mapped[int | None] = mapped_column(ForeignKey("stock_groups.id", ondelete="SET NULL"), index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemporarySnapshot(Base):
    """A short-lived, section-scoped ticker lookup that is not a watchlist item."""
    __tablename__ = "temporary_snapshots"
    __table_args__ = (UniqueConstraint("section", "ticker"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    section: Mapped[str] = mapped_column(String(24), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockProfile(Base):
    """股票基础资料缓存；官方分类与用户显示分组保持分离。"""
    __tablename__ = "stock_profiles"
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(256))
    official_sector: Mapped[str | None] = mapped_column(String(128), index=True)
    official_industry: Mapped[str | None] = mapped_column(String(192), index=True)
    source: Mapped[str] = mapped_column(String(32), default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StockGroup(Base):
    __tablename__ = "stock_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PeerRelation(Base):
    """同行引用缓存；官方结果随估值同步刷新，手动关系由用户维护。"""
    __tablename__ = "peer_relations"
    __table_args__ = (UniqueConstraint("base_ticker", "peer_ticker"), CheckConstraint("base_ticker <> peer_ticker"))
    id: Mapped[int] = mapped_column(primary_key=True)
    peer_security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    base_ticker: Mapped[str] = mapped_column(String(16), index=True)
    peer_ticker: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PeerExclusion(Base):
    __tablename__ = "peer_exclusions"
    __table_args__ = (UniqueConstraint("base_ticker", "peer_ticker"), CheckConstraint("base_ticker <> peer_ticker"))
    id: Mapped[int] = mapped_column(primary_key=True)
    base_ticker: Mapped[str] = mapped_column(String(16), index=True)
    peer_ticker: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_key", name="uq_price_snapshots_snapshot_key"),
        Index(
            "ix_price_snapshots_latest",
            "ticker",
            "quote_time",
            "fetched_at",
            "persisted_at",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # The physical legacy column names are retained for a safe in-place
    # migration; all new Python/API code uses the normalized attribute names.
    symbol: Mapped[str] = mapped_column("ticker", String(16), index=True)
    exchange: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(12))
    source_type: Mapped[str] = mapped_column(String(32), default="price_snapshot")
    provider: Mapped[str] = mapped_column("source", String(32), default="yfinance")
    provider_symbol: Mapped[str | None] = mapped_column(String(32))
    provider_role: Mapped[str | None] = mapped_column(String(32), default="market_data_aggregator")

    last_price: Mapped[float] = mapped_column("price", Float)
    open_price: Mapped[float | None] = mapped_column(Float)
    day_high: Mapped[float | None] = mapped_column(Float)
    day_low: Mapped[float | None] = mapped_column(Float)
    previous_close: Mapped[float | None] = mapped_column(Float)
    price_change: Mapped[float | None] = mapped_column(Float)
    price_change_percent: Mapped[float | None] = mapped_column(Float)

    day_volume: Mapped[int | None] = mapped_column("volume", Integer)
    average_volume_10d: Mapped[float | None] = mapped_column(Float)
    average_volume_20d: Mapped[float | None] = mapped_column(Float)
    relative_volume_20d: Mapped[float | None] = mapped_column(Float)
    relative_volume_basis: Mapped[str | None] = mapped_column(String(32))

    market_timestamp: Mapped[datetime | None] = mapped_column("quote_time", DateTime(timezone=True), index=True)
    trading_date: Mapped[date | None] = mapped_column(Date)
    market_session: Mapped[str] = mapped_column(String(16), default="unknown")
    timestamp_source: Mapped[str | None] = mapped_column(String(32))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    persisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    is_delayed: Mapped[bool | None] = mapped_column(Boolean)
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    snapshot_key: Mapped[str | None] = mapped_column(String(64))

    # Compatibility aliases keep existing alert/portfolio code and historical
    # fixtures readable while new boundaries consistently expose snake_case.
    ticker = synonym("symbol")
    quote_time = synonym("market_timestamp")
    price = synonym("last_price")
    volume = synonym("day_volume")
    source = synonym("provider")


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(128), unique=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    period: Mapped[str] = mapped_column(String(16))
    baseline_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    change_percent: Mapped[float] = mapped_column(Float)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    investigation: Mapped["Investigation | None"] = relationship(back_populates="alert", uselist=False)


class UserPriceAlert(Base):
    """Authenticated user-owned target line evaluated by the existing quote poller."""
    __tablename__ = "user_price_alerts"
    __table_args__ = (
        Index("ix_user_price_alerts_ticker_enabled", "ticker", "enabled"),
        CheckConstraint("target_price > 0", name="ck_user_price_alerts_target_price"),
        CheckConstraint("direction IN ('above', 'below')", name="ck_user_price_alerts_direction"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    target_price: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_price_alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_alerts.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("price_alerts.id"), unique=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_search_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[InvestigationStatus] = mapped_column(Enum(InvestigationStatus), default=InvestigationStatus.active)
    last_error: Mapped[str | None] = mapped_column(Text)
    alert: Mapped[PriceAlert] = relationship(back_populates="investigation")


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("scope", "fingerprint", name="uq_news_items_scope_fingerprint"),
        Index("ix_news_items_scope_published", "scope", "published_at"),
        Index("ix_news_items_ticker_published", "ticker", "published_at"),
        Index("ix_news_items_cluster_key", "cluster_key"),
        Index(
            "uq_news_items_marketaux_external_id",
            "scope", "external_id",
            unique=True,
            postgresql_where=text("provider = 'marketaux'"),
            sqlite_where=text("provider = 'marketaux'"),
        ),
        Index(
            "uq_news_items_marketaux_normalized_url",
            "scope", "normalized_url",
            unique=True,
            postgresql_where=text("provider = 'marketaux'"),
            sqlite_where=text("provider = 'marketaux'"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(ForeignKey("investigations.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str | None] = mapped_column(String(256))
    fingerprint: Mapped[str] = mapped_column(String(64))
    # Market rows use an internal ticker sentinel and are isolated by scope.
    scope: Mapped[str] = mapped_column(String(16), default="company", server_default="company", index=True)
    topic: Mapped[str | None] = mapped_column(String(64), index=True)
    importance_score: Mapped[float | None] = mapped_column(Float, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float)
    cluster_key: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    translated_title: Mapped[str | None] = mapped_column(String(512))
    title_translation_model: Mapped[str | None] = mapped_column(String(128))
    title_translation_input_hash: Mapped[str | None] = mapped_column(String(64))
    title_translated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title_translation_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    title_translation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    title_translation_last_error: Mapped[str | None] = mapped_column(Text)
    title_translation_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    symbols: Mapped[list | None] = mapped_column(JSON)
    news_type: Mapped[str] = mapped_column(String(32), default="article", server_default="article")
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_model: Mapped[str | None] = mapped_column(String(128))
    ai_summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_summary_status: Mapped[str] = mapped_column(String(16), default="idle", server_default="idle", index=True)
    ai_summary_request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    ai_summary_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_summary_last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsProviderState(Base):
    """Persistent scheduler state for quota-limited batch news providers."""

    __tablename__ = "news_provider_states"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="ck_news_provider_states_request_count"),
        CheckConstraint("next_batch_index >= 0", name="ck_news_provider_states_next_batch_index"),
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    quota_utc_date: Mapped[date] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    next_batch_index: Mapped[int] = mapped_column(Integer, default=0)
    last_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_fetch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HistoricalPrice(Base):
    """Validated daily EOD candles. Written by FMP (primary) and yfinance (fallback); distinguished by `source`."""
    __tablename__ = "historical_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "date", "source", name="uq_historical_prices_symbol_date_source"),
        Index("ix_historical_prices_symbol_date", "symbol", "date"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_historical_prices_volume"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Numeric(20, 6))
    high: Mapped[float] = mapped_column(Numeric(20, 6))
    low: Mapped[float] = mapped_column(Numeric(20, 6))
    close: Mapped[float] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change_percent: Mapped[float | None] = mapped_column(Numeric(16, 6))
    source: Mapped[str] = mapped_column(String(16), default="fmp")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyProfile(Base):
    """Long-lived FMP metadata; never replaces StockProfile classification."""
    __tablename__ = "company_profiles"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(256))
    logo_url: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    ceo: Mapped[str | None] = mapped_column(String(256))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(192))
    country: Mapped[str | None] = mapped_column(String(64))
    exchange: Mapped[str | None] = mapped_column(String(32))
    exchange_full_name: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str | None] = mapped_column(String(16))
    ipo_date: Mapped[date | None] = mapped_column(Date)
    employee_count: Mapped[int | None] = mapped_column(BigInteger)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_zh: Mapped[str | None] = mapped_column(Text)
    description_source_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    profile_source: Mapped[str] = mapped_column(String(16), default="fmp")
    profile_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    translation_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    translation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    translation_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    translation_last_error: Mapped[str | None] = mapped_column(Text)
    translation_model: Mapped[str | None] = mapped_column(String(128))
    translation_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FmpSyncState(Base):
    """Durable quota ledger and per-symbol queue checkpoint."""
    __tablename__ = "fmp_sync_states"
    __table_args__ = (
        UniqueConstraint("task_name", "symbol", "sync_type", name="uq_fmp_sync_state_key"),
        CheckConstraint("requests_used >= 0", name="ck_fmp_sync_requests_used"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    sync_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_date: Mapped[date | None] = mapped_column(Date)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(48))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    quota_day: Mapped[date] = mapped_column(Date, index=True)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    cursor_position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TechnicalAnalysis(Base):
    __tablename__ = "technical_analyses"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    structured_hash: Mapped[str | None] = mapped_column(String(64))
    image_path: Mapped[str | None] = mapped_column(Text)
    image_format: Mapped[str | None] = mapped_column(String(8))
    data_through: Mapped[date | None] = mapped_column(Date)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DailyNewsArchive(Base):
    __tablename__ = "daily_news_archives"
    __table_args__ = (UniqueConstraint("ticker", "market_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    market_date: Mapped[date] = mapped_column(Date, index=True)
    content: Mapped[str] = mapped_column(Text)
    included_news_ids: Mapped[list] = mapped_column(JSON, default=list)
    excluded_news_ids: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WeeklyNewsArchive(Base):
    """每周新闻汇总；把当周每日定档的“关键事实归纳”合并成一份周报，
    生成后当周的原始新闻与每日定档会被删除，只保留此汇总作为历史。
    按 ISO 周（周一起）归档。"""
    __tablename__ = "weekly_news_archives"
    __table_args__ = (UniqueConstraint("ticker", "iso_year", "iso_week"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    iso_year: Mapped[int] = mapped_column(Integer, index=True)
    iso_week: Mapped[int] = mapped_column(Integer, index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    content: Mapped[str] = mapped_column(Text)
    included_dates: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QuarterlyFinancial(Base):
    __tablename__ = "quarterly_financials"
    __table_args__ = (UniqueConstraint("ticker", "fiscal_year", "fiscal_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_period: Mapped[str] = mapped_column(String(8))
    period_end: Mapped[date] = mapped_column(Date, index=True)
    filed_at: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(16))
    revenue: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="finnhub")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialStatementSnapshot(Base):
    """Yahoo 三大报表快照；保留每期原始行，供展示和后续指标复算。"""
    __tablename__ = "financial_statement_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "frequency", "period_end"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    frequency: Mapped[str] = mapped_column(String(16), index=True)  # annual / quarterly
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_period: Mapped[str] = mapped_column(String(16))
    period_end: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    income_statement: Mapped[dict] = mapped_column(JSON, default=dict)
    balance_sheet: Mapped[dict] = mapped_column(JSON, default=dict)
    cash_flow: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="yfinance")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ValuationSnapshot(Base):
    """每日多模型估值快照；JSON payload 保留计算证据，便于追溯和扩展模型。"""
    __tablename__ = "valuation_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "snapshot_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_opinion: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(128))
    source_version: Mapped[str] = mapped_column(String(32), default="cross-model-v3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (UniqueConstraint("ticker", "event_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timing: Mapped[str] = mapped_column(String(16), default="unknown")
    confidence: Mapped[str] = mapped_column(String(16), default="estimated")
    source: Mapped[str] = mapped_column(String(32), default="yfinance")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EquityShareStatistic(Base):
    """Normalized, provider-aware share/short-interest snapshot."""
    __tablename__ = "equity_share_statistics"
    __table_args__ = (UniqueConstraint("symbol", name="uq_equity_share_statistics_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str | None] = mapped_column(String(8))
    shares_outstanding: Mapped[float | None] = mapped_column(Float)
    float_shares: Mapped[float | None] = mapped_column(Float)
    free_float_percent: Mapped[float | None] = mapped_column(Float)
    implied_shares_outstanding: Mapped[float | None] = mapped_column(Float)
    shares_short: Mapped[float | None] = mapped_column(Float)
    shares_short_prior_month: Mapped[float | None] = mapped_column(Float)
    short_percent_of_float: Mapped[float | None] = mapped_column(Float)
    short_percent_of_outstanding: Mapped[float | None] = mapped_column(Float)
    short_ratio: Mapped[float | None] = mapped_column(Float)
    held_percent_insiders: Mapped[float | None] = mapped_column(Float)
    held_percent_institutions: Mapped[float | None] = mapped_column(Float)
    average_volume: Mapped[float | None] = mapped_column(Float)
    average_volume_10d: Mapped[float | None] = mapped_column(Float)
    as_of_date: Mapped[date | None] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32), default="yahoo", index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InvestmentCalendarEvent(Base):
    """A provider-neutral event with a deterministic ID and reconciled provenance."""
    __tablename__ = "investment_calendar_events"
    __table_args__ = (
        Index("ix_investment_calendar_date_type", "event_date", "event_type"),
        Index("ix_investment_calendar_symbol_date", "symbol", "event_date"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    company_name: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_status: Mapped[str] = mapped_column(String(24), default="unknown")
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    impact_level: Mapped[str] = mapped_column(String(16), default="low", index=True)
    primary_source: Mapped[str] = mapped_column(String(32), index=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_fields: Mapped[list] = mapped_column(JSON, default=list)
    metadata_payload: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class InvestmentCalendarEventSource(Base):
    """Provider record retained separately so refreshes never erase provenance."""
    __tablename__ = "investment_calendar_event_sources"
    __table_args__ = (
        UniqueConstraint("event_id", "provider", "source_record_id", name="uq_calendar_event_provider_record"),
        Index("ix_calendar_event_sources_provider", "provider", "fetched_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("investment_calendar_events.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(160), default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestmentCalendarSyncRun(Base):
    """Durable calendar-refresh telemetry used for due checks and coverage reporting."""
    __tablename__ = "investment_calendar_sync_runs"
    __table_args__ = (
        Index("ix_calendar_sync_runs_status_started", "status", "started_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracked_symbols: Mapped[int] = mapped_column(Integer, default=0)
    successful_symbols: Mapped[int] = mapped_column(Integer, default=0)
    events_seen: Mapped[int] = mapped_column(Integer, default=0)
    active_future_events: Mapped[int] = mapped_column(Integer, default=0)
    future_symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    failures: Mapped[list] = mapped_column(JSON, default=list)
    error_type: Mapped[str | None] = mapped_column(String(128))


class SecFiling(Base):
    __tablename__ = "sec_filings"
    __table_args__ = (UniqueConstraint("ticker", "accession_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    accession_number: Mapped[str] = mapped_column(String(32))
    form: Mapped[str] = mapped_column(String(16), index=True)
    form_label: Mapped[str] = mapped_column(String(64))
    items: Mapped[str | None] = mapped_column(String(128))
    event_labels: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(16), default="normal", index=True)
    filing_date: Mapped[date] = mapped_column(Date, index=True)
    report_date: Mapped[date | None] = mapped_column(Date)
    primary_document: Mapped[str | None] = mapped_column(Text)
    filing_url: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecEvent(Base):
    """8-K/6-K 重大事件的 Item 正文（edgartools 抽取，一个 filing 多 Item 各一行）。"""
    __tablename__ = "sec_events"
    __table_args__ = (UniqueConstraint("accession_number", "item_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    accession_number: Mapped[str] = mapped_column(String(32))
    form: Mapped[str] = mapped_column(String(16))
    item_code: Mapped[str] = mapped_column(String(8))
    item_label: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), default="normal", index=True)
    text: Mapped[str | None] = mapped_column(Text)
    # Haiku 翻译栈：对 text 做中文翻译+总结（异步状态机，仿 NewsItem 标题翻译）
    summary_zh: Mapped[str | None] = mapped_column(Text)
    summary_model: Mapped[str | None] = mapped_column(String(128))
    summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    summary_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    summary_attempts: Mapped[int] = mapped_column(Integer, default=0)
    summary_last_error: Mapped[str | None] = mapped_column(Text)
    summary_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, index=True)
    filing_url: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecFinancialPeriod(Base):
    """SEC XBRL 财务大表（与 yfinance 的 QuarterlyFinancial 并存，source=sec_edgar）。"""
    __tablename__ = "sec_financial_periods"
    __table_args__ = (UniqueConstraint("ticker", "fiscal_year", "fiscal_period", "form"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_period: Mapped[str] = mapped_column(String(8))
    form: Mapped[str] = mapped_column(String(16))
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    filed_at: Mapped[date | None] = mapped_column(Date)
    accession_number: Mapped[str | None] = mapped_column(String(32))
    revenue: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    eps_basic: Mapped[float | None] = mapped_column(Float)
    eps_diluted: Mapped[float | None] = mapped_column(Float)
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float)
    total_debt: Mapped[float | None] = mapped_column(Float)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="sec_edgar")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecInsiderTrade(Base):
    """Form 4 内部人交易（edgartools 抽取，一份 Form 4 多笔交易各一行）。"""
    __tablename__ = "sec_insider_trades"
    __table_args__ = (
        UniqueConstraint(
            "accession_number", "insider_name", "transaction_date", "transaction_code", "shares"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    accession_number: Mapped[str] = mapped_column(String(32), index=True)
    insider_name: Mapped[str] = mapped_column(String(128))
    insider_title: Mapped[str | None] = mapped_column(String(128))
    transaction_date: Mapped[date | None] = mapped_column(Date, index=True)
    transaction_code: Mapped[str | None] = mapped_column(String(8))
    shares: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    shares_owned_after: Mapped[float | None] = mapped_column(Float)
    flag: Mapped[str | None] = mapped_column(String(16))
    filing_url: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sec13FHolding(Base):
    """13F 机构季度持仓（SEC 全市场 13F 数据集按 CUSIP 反查自选股）。

    一条 = 某机构在某季度对某只自选股的持仓。value_usd 为持仓市值（整美元，SEC 2023 起原始单位）。
    机构季度申报，季度末后约 45 天公布，因此数据天然滞后。
    """
    __tablename__ = "sec_13f_holdings"
    __table_args__ = (UniqueConstraint("ticker", "accession_number", "report_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cusip: Mapped[str] = mapped_column(String(9), index=True)
    manager_name: Mapped[str] = mapped_column(String(200))
    accession_number: Mapped[str] = mapped_column(String(32))
    report_period: Mapped[date] = mapped_column(Date, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date)
    value_usd: Mapped[float | None] = mapped_column(Float)  # SEC 2023 起 VALUE 为整美元
    shares: Mapped[float | None] = mapped_column(Float)
    put_call: Mapped[str | None] = mapped_column(String(8))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecCusipMap(Base):
    """ticker ↔ CUSIP 映射（13F 数据集只用 CUSIP 标识证券，需自建映射）。

    source: manual(.env 覆盖) / edgar(edgartools 公司名匹配) / issuer_match(ZIP 内 NAMEOFISSUER 命中回写)。
    一只 ticker 可能有多个 CUSIP（多股份类别/历史沿革），故不对 ticker 唯一。
    """
    __tablename__ = "sec_cusip_map"
    __table_args__ = (UniqueConstraint("ticker", "cusip"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cusip: Mapped[str] = mapped_column(String(9), index=True)
    issuer_name: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16), default="issuer_match")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType), index=True)
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(128))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class CongressTrade(Base):
    """国会/行政部门政客逐笔交易（kadoa STOCK Act 披露源）。

    一条 = 某政客某笔 PTR 交易。ticker 可能为空（债券/基金）；金额是披露区间。
    source_uid 用 kadoa 的交易 id 去重。
    """
    __tablename__ = "congress_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_uid: Mapped[str] = mapped_column(String(64), unique=True)
    filer_id: Mapped[str] = mapped_column(String(64), index=True)
    filer_name: Mapped[str] = mapped_column(String(128), index=True)
    chamber: Mapped[str | None] = mapped_column(String(16))
    branch: Mapped[str | None] = mapped_column(String(16))
    party: Mapped[str | None] = mapped_column(String(8))
    state: Mapped[str | None] = mapped_column(String(8))
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    asset_name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[str | None] = mapped_column(String(16))
    transaction_type: Mapped[str | None] = mapped_column(String(32))
    transaction_date: Mapped[date | None] = mapped_column(Date, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date)
    amount_low: Mapped[float | None] = mapped_column(Float)
    amount_high: Mapped[float | None] = mapped_column(Float)
    amount_label: Mapped[str | None] = mapped_column(String(64))
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackedFigure(Base):
    """被追踪的名人档案。kind=politician 有 kadoa_filer_id 可拉实时交易；
    fund_manager（木头姐）无国会交易。is_seed=True 的三位有持仓饼图基线。
    """
    __tablename__ = "tracked_figures"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), default="politician")
    kadoa_filer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    photo_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FigurePosition(Base):
    """三位种子人物的持仓（饼图数据）。baseline_value 为种子基线金额，
    adjusted_value 叠加基线日期后的新交易。木头姐用 baseline_value 存 %（不叠加）。
    category: stock/etf/preferred/corp_bond/muni_bond/treasury/option/other
    """
    __tablename__ = "figure_positions"
    __table_args__ = (UniqueConstraint("figure_slug", "ticker", "asset_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    figure_slug: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str | None] = mapped_column(String(16))
    asset_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(24), default="stock")
    baseline_value: Mapped[float] = mapped_column(Float, default=0.0)
    adjusted_value: Mapped[float] = mapped_column(Float, default=0.0)
    is_percent: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default='user')
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIConversation(Base):
    """User-owned conversation metadata; model execution remains stateless."""
    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived','deleted')", name="ck_ai_conversations_status"),
        CheckConstraint("summary_status IN ('none','pending','ready','stale','failed')", name="ck_ai_conversations_summary_status"),
        Index("ix_ai_conversations_user_deleted_last", "user_id", "deleted_at", "last_message_at"),
        Index("ix_ai_conversations_user_status_last", "user_id", "status", "last_message_at"),
        Index("ix_ai_conversations_user_archived", "user_id", "archived_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    title_source: Mapped[str] = mapped_column(String(16), default="generated")
    status: Mapped[str] = mapped_column(String(16), default="active")
    active_symbol: Mapped[str | None] = mapped_column(String(32))
    active_symbols: Mapped[list] = mapped_column(JSON, default=list)
    active_portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id", ondelete="SET NULL"), index=True)
    page_context: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(64))
    response_mode: Mapped[str] = mapped_column(String(16), default="standard")
    web_access_mode: Mapped[str] = mapped_column(String(24), default="off")
    system_prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str] = mapped_column(String(16), default="none")
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_summary_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation_summary_snapshots.id", ondelete="SET NULL"),
        index=True,
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_ai_messages_role"),
        CheckConstraint("status IN ('pending','streaming','completed','partial','failed','cancelled')", name="ck_ai_messages_status"),
        Index("ix_ai_messages_conversation_created", "conversation_id", "created_at", "id"),
        Index("ix_ai_messages_user_conversation", "user_id", "conversation_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    content_format: Mapped[str] = mapped_column(String(16), default="markdown")
    content_schema_version: Mapped[int | None] = mapped_column(Integer)
    content_parts: Mapped[dict | None] = mapped_column(JSON)
    parent_message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_messages.id", ondelete="SET NULL"))
    regenerated_from_message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True)
    generation_index: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    provider_response_id: Mapped[str | None] = mapped_column(String(256))
    system_prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    web_access_mode: Mapped[str] = mapped_column(String(24), default="off")
    external_search_call_count: Mapped[int] = mapped_column(Integer, default=0)
    deep_search_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_search_runs.id", ondelete="SET NULL"), index=True
    )
    external_search_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    summary_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation_summary_snapshots.id", ondelete="SET NULL"),
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_safe: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deep_search_run: Mapped["ExternalSearchRun | None"] = relationship(
        foreign_keys=[deep_search_run_id], post_update=True
    )


class AIMessageCitation(Base):
    __tablename__ = "ai_message_citations"
    __table_args__ = (
        UniqueConstraint("message_id", "citation_key", name="uq_ai_citations_message_key"),
        UniqueConstraint("message_id", "source_id", name="uq_ai_citations_message_source"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    citation_key: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(256))
    source_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(64))
    authority: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locator: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIToolCallRecord(Base):
    __tablename__ = "ai_tool_call_records"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", "tool_call_id", name="uq_ai_tool_calls_message_call"),
        Index("ix_ai_tool_calls_conversation_created", "conversation_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    assistant_message_id: Mapped[int] = mapped_column(ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    result_mode: Mapped[str | None] = mapped_column(String(16))
    normalized_arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    arguments_hash: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(String(500))
    warning_codes: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    original_item_count: Mapped[int | None] = mapped_column(Integer)
    returned_item_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    reused: Mapped[bool] = mapped_column(Boolean, default=False)
    external_provider: Mapped[str | None] = mapped_column(String(32))
    external_request_id: Mapped[str | None] = mapped_column(String(256))
    external_run_id: Mapped[str | None] = mapped_column(String(64))
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cost_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIConversationSummarySnapshot(Base):
    __tablename__ = "ai_conversation_summary_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','completed','failed','superseded')",
            name="ck_ai_conversation_summary_snapshots_status",
        ),
        UniqueConstraint("conversation_id", "version", name="uq_ai_summary_snapshot_version"),
        Index(
            "ix_ai_summary_snapshots_conversation_status",
            "conversation_id",
            "status",
            "version",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    from_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL")
    )
    through_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True
    )
    source_message_count: Mapped[int] = mapped_column(Integer, default=0)
    source_character_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_text: Mapped[str | None] = mapped_column(Text)
    structured_summary: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict
    )
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(32), default="1")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_safe: Mapped[str | None] = mapped_column(String(500))


class AIUserMemoryPreference(Base):
    __tablename__ = "ai_user_memory_preferences"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    use_in_context: Mapped[bool] = mapped_column(Boolean, default=True)
    candidate_extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIUserMemory(Base):
    __tablename__ = "ai_user_memories"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','active','rejected','stale','expired','archived','deleted')",
            name="ck_ai_user_memories_status",
        ),
        CheckConstraint(
            "scope IN ('global','portfolio','symbol','project','page_context')",
            name="ck_ai_user_memories_scope",
        ),
        Index("ix_ai_user_memories_user_status", "user_id", "status"),
        Index(
            "ix_ai_user_memories_user_scope",
            "user_id",
            "scope",
            "scope_key",
            "status",
        ),
        Index(
            "ix_ai_user_memories_signature",
            "user_id",
            "memory_type",
            "scope",
            "scope_key",
            "normalized_content_hash",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    memory_type: Mapped[str] = mapped_column(String(40), index=True)
    scope: Mapped[str] = mapped_column(String(24), default="global")
    scope_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    title: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    structured_value: Mapped[dict | list | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    origin: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    importance: Mapped[int] = mapped_column(Integer, default=50)
    normalized_content_hash: Mapped[str] = mapped_column(String(64))
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"), index=True
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True
    )
    source_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_investment_decisions.id", ondelete="SET NULL"), index=True
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    stale_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_memory_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_user_memories.id", ondelete="SET NULL"), index=True
    )
    conflict_group: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIMemoryEvent(Base):
    __tablename__ = "ai_memory_events"
    __table_args__ = (
        Index("ix_ai_memory_events_memory_created", "memory_id", "created_at"),
        Index("ix_ai_memory_events_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[int] = mapped_column(
        ForeignKey("ai_user_memories.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(24))
    before_value: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    after_value: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIInvestmentDecision(Base):
    __tablename__ = "ai_investment_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','executed','partially_executed','cancelled','invalidated','closed','archived')",
            name="ck_ai_investment_decisions_status",
        ),
        Index("ix_ai_investment_decisions_user_status", "user_id", "status"),
        Index(
            "ix_ai_investment_decisions_user_symbol",
            "user_id",
            "primary_symbol",
            "status",
        ),
        Index(
            "ix_ai_investment_decisions_user_review",
            "user_id",
            "target_review_at",
            "status",
        ),
        UniqueConstraint(
            "user_id", "decision_number", name="uq_ai_decisions_user_number"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    decision_number: Mapped[int] = mapped_column(Integer)
    decision_type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    primary_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="SET NULL"), index=True
    )
    decision_date: Mapped[date] = mapped_column(Date)
    time_horizon: Mapped[str] = mapped_column(String(24), default="unspecified")
    target_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    action: Mapped[str] = mapped_column(Text)
    position_intent: Mapped[str | None] = mapped_column(String(64))
    target_weight: Mapped[float | None] = mapped_column(Numeric(9, 6))
    target_quantity: Mapped[float | None] = mapped_column(Numeric(20, 6))
    target_price_min: Mapped[float | None] = mapped_column(Numeric(20, 6))
    target_price_max: Mapped[float | None] = mapped_column(Numeric(20, 6))
    thesis: Mapped[list] = mapped_column(JSON, default=list)
    catalysts: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    invalidation_conditions: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    structured_conditions: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"), index=True
    )
    source_user_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL")
    )
    source_assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL")
    )
    supersedes_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_investment_decisions.id", ondelete="SET NULL"), index=True
    )
    merged_from_ids: Mapped[list] = mapped_column(JSON, default=list)
    resolution_type: Mapped[str] = mapped_column(String(24), default="standalone")
    executed_trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trade_transactions.id", ondelete="SET NULL"), index=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIInvestmentDecisionEvidence(Base):
    __tablename__ = "ai_investment_decision_evidence"
    __table_args__ = (
        UniqueConstraint(
            "decision_id", "source_id", name="uq_ai_decision_evidence_source"
        ),
        Index("ix_ai_decision_evidence_decision_created", "decision_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_investment_decisions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(String(256))
    source_type: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(64))
    authority: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(String(2000))
    locator: Mapped[str | None] = mapped_column(String(500))
    evidence_summary: Mapped[str] = mapped_column(String(1000))
    evidence_role: Mapped[str] = mapped_column(String(24), default="context")
    freshness_status: Mapped[str] = mapped_column(String(16), default="unknown")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIInvestmentDecisionReview(Base):
    __tablename__ = "ai_investment_decision_reviews"
    __table_args__ = (
        Index("ix_ai_decision_reviews_decision_reviewed", "decision_id", "reviewed_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_investment_decisions.id", ondelete="CASCADE"), index=True
    )
    review_type: Mapped[str] = mapped_column(String(24), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    thesis_status: Mapped[str] = mapped_column(String(24), default="uncertain")
    invalidation_status: Mapped[str] = mapped_column(String(24), default="unknown")
    execution_status: Mapped[str | None] = mapped_column(String(32))
    what_changed: Mapped[str] = mapped_column(Text, default="")
    supporting_changes: Mapped[list] = mapped_column(JSON, default=list)
    contradicting_changes: Mapped[list] = mapped_column(JSON, default=list)
    lessons: Mapped[list] = mapped_column(JSON, default=list)
    next_action: Mapped[str | None] = mapped_column(Text)
    linked_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="SET NULL")
    )
    linked_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIMessageMemoryUsage(Base):
    __tablename__ = "ai_message_memory_usage"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "memory_id", "usage_type", name="uq_ai_message_memory_usage"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[int] = mapped_column(
        ForeignKey("ai_user_memories.id", ondelete="CASCADE"), index=True
    )
    usage_type: Mapped[str] = mapped_column(String(24), default="context")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIMessageDecisionUsage(Base):
    __tablename__ = "ai_message_decision_usage"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "decision_id", name="uq_ai_message_decision_usage"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_investment_decisions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExternalSearchRun(Base):
    __tablename__ = "external_search_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','queued','running','completed','failed','cancelled')",
            name="ck_external_search_runs_status",
        ),
        UniqueConstraint("provider", "provider_run_id", name="uq_external_search_runs_provider_id"),
        UniqueConstraint("idempotency_key", name="uq_external_search_runs_idempotency_key"),
        Index("ix_external_search_runs_user_status", "user_id", "status"),
        Index("ix_external_search_runs_conversation_created", "conversation_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    user_message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True)
    assistant_message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_messages.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="exa")
    provider_run_id: Mapped[str | None] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(24))
    effort: Mapped[str] = mapped_column(String(16))
    query_hash: Mapped[str] = mapped_column(String(64))
    query_preview_safe: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    termination_reason: Mapped[str | None] = mapped_column(String(32))
    output_text: Mapped[str | None] = mapped_column(Text)
    output_structured: Mapped[dict | list | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    grounding: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cost_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_safe: Mapped[str | None] = mapped_column(String(500))
    last_event_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalSearchRunEvent(Base):
    __tablename__ = "external_search_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "provider_event_id", name="uq_external_search_run_events_provider"),
        Index("ix_external_search_run_events_run_created", "run_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("external_search_runs.id", ondelete="CASCADE"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(16))
    safe_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Portfolio(Base):
    """一个用户的持仓组合。当前每个用户自动拥有一个默认组合；模型保留多组合扩展空间。"""
    __tablename__ = "portfolios"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_portfolios_user_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64), default="default")
    name: Mapped[str] = mapped_column(String(120), default="我的持仓")
    base_currency: Mapped[str] = mapped_column(String(8), default="USD")
    cash_balance: Mapped[float] = mapped_column(Float, default=0.0)
    # The user-declared starting point for comparing the whole portfolio with
    # passive market benchmarks.  This deliberately stays separate from
    # transaction-derived performance: deposits, withdrawals and multi-account
    # history cannot yet be treated as a time-weighted return automatically.
    benchmark_start_date: Mapped[date | None] = mapped_column(Date)
    benchmark_portfolio_return_percent: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioStrategyProfile(Base):
    """User-owned interpretation preferences layered over objective portfolio analysis."""
    __tablename__ = "portfolio_strategy_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_portfolio_strategy_profiles_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    strategy_type: Mapped[str] = mapped_column(String(32), default="quality_growth")
    investment_horizon: Mapped[str] = mapped_column(String(24), default="long_term")
    risk_tolerance: Mapped[str] = mapped_column(String(24), default="balanced")
    max_single_position: Mapped[float] = mapped_column(Float, default=25.0)
    max_theme_exposure: Mapped[float] = mapped_column(Float, default=40.0)
    valuation_preference: Mapped[str] = mapped_column(String(24), default="balanced")
    minimum_quality_score: Mapped[float] = mapped_column(Float, default=70.0)
    preferred_regions: Mapped[list] = mapped_column(JSON, default=lambda: ["north_america"])
    preferred_market_caps: Mapped[list] = mapped_column(JSON, default=lambda: ["large", "mid"])
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PortfolioAnalysisRun(Base):
    """Immutable input/result snapshot for deterministic portfolio analyses."""
    __tablename__ = "portfolio_analysis_runs"
    __table_args__ = (
        Index("ix_portfolio_analysis_runs_portfolio_type_created", "portfolio_id", "analysis_type", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    analysis_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assumptions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(64))
    price_data_start_date: Mapped[date | None] = mapped_column(Date)
    price_data_end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class StockDiscoverySettings(Base):
    """Per-user discovery policy. Secrets deliberately never enter this table."""
    __tablename__ = "stock_discovery_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_stock_discovery_settings_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Legacy cadence fields are retained for migration/rollback compatibility.
    # Discovery is manual-only and application code must not read them.
    auto_update_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=3)
    discovery_mode: Mapped[str] = mapped_column(String(32), default="search_local")
    model: Mapped[str] = mapped_column(String(128), default="openai/gpt-5.4")
    enable_web_search: Mapped[bool] = mapped_column(Boolean, default=True)
    max_steps: Mapped[int] = mapped_column(Integer, default=5)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=12000)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=10.0)
    max_run_cost_usd: Mapped[float] = mapped_column(Float, default=1.0)
    min_market_cap: Mapped[float] = mapped_column(Float, default=2_000_000_000.0)
    exclude_current_holdings: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_watchlist: Mapped[bool] = mapped_column(Boolean, default=False)
    require_positive_fcf: Mapped[bool] = mapped_column(Boolean, default=True)
    max_trailing_pe: Mapped[float] = mapped_column(Float, default=80.0)
    max_forward_pe: Mapped[float] = mapped_column(Float, default=60.0)
    max_price_to_sales: Mapped[float] = mapped_column(Float, default=25.0)
    filter_extreme_momentum: Mapped[bool] = mapped_column(Boolean, default=True)
    missing_data_policy: Mapped[str] = mapped_column(String(24), default="warn")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StockDiscoveryRun(Base):
    __tablename__ = "stock_discovery_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_stock_discovery_runs_idempotency_key"),
        Index("ix_stock_discovery_runs_user_requested", "user_id", "requested_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    previous_successful_run_id: Mapped[int | None] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    discovery_mode: Mapped[str] = mapped_column(String(32), default="search_local")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="preparing_portfolio")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_date: Mapped[date | None] = mapped_column(Date)
    next_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_requested: Mapped[str] = mapped_column(String(128))
    model_used: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64), default="stock-discovery-prompt-v0.4")
    schema_version: Mapped[str] = mapped_column(String(64), default="stock-discovery-schema-v0.4")
    filter_version: Mapped[str] = mapped_column(String(64), default="stock-discovery-filter-v0.4")
    portfolio_snapshot_hash: Mapped[str] = mapped_column(String(64))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    failure_code: Mapped[str | None] = mapped_column(String(48))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class StockDiscoveryPortfolioSnapshot(Base):
    __tablename__ = "stock_discovery_portfolio_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), unique=True)
    context_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockDiscoveryMarketContext(Base):
    __tablename__ = "stock_discovery_market_contexts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    risk_regime: Mapped[str] = mapped_column(String(24), default="unknown")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class StockDiscoveryExposure(Base):
    __tablename__ = "stock_discovery_exposures"
    __table_args__ = (Index("ix_stock_discovery_exposures_run_kind", "run_id", "diagnosis_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"))
    diagnosis_kind: Mapped[str] = mapped_column(String(32))
    exposure_type: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(16), default="medium")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class StockDiscoveryFlowDirection(Base):
    __tablename__ = "stock_discovery_flow_directions"
    __table_args__ = (Index("ix_stock_discovery_flows_run_type", "run_id", "flow_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"))
    flow_type: Mapped[str] = mapped_column(String(24))
    direction: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str] = mapped_column(String(24), default="uncertain")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class StockDiscoveryCandidateGroup(Base):
    __tablename__ = "stock_discovery_candidate_groups"
    __table_args__ = (UniqueConstraint("run_id", "group_id", name="uq_stock_discovery_groups_run_group"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"))
    group_id: Mapped[str] = mapped_column(String(80))
    group_name: Mapped[str] = mapped_column(String(120))
    group_type: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class StockDiscoveryCandidate(Base):
    __tablename__ = "stock_discovery_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "canonical_key", name="uq_stock_discovery_candidates_run_key"),
        Index("ix_stock_discovery_candidates_run_status", "run_id", "display_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"))
    raw_ticker: Mapped[str] = mapped_column(String(48))
    normalized_ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    canonical_key: Mapped[str] = mapped_column(String(96))
    company_name: Mapped[str] = mapped_column(String(256), default="")
    exchange: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64))
    raw_rank: Mapped[int | None] = mapped_column(Integer)
    final_rank: Mapped[int | None] = mapped_column(Integer)
    candidate_priority: Mapped[str] = mapped_column(String(16), default="medium")
    symbol_match_status: Mapped[str] = mapped_column(String(32), default="pending")
    symbol_match_reason: Mapped[str | None] = mapped_column(Text)
    filter_status: Mapped[str] = mapped_column(String(32), default="insufficient_data")
    display_status: Mapped[str] = mapped_column(String(32), default="insufficient_data")
    verification_status: Mapped[str] = mapped_column(String(32), default="pending")
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    normalized_data: Mapped[dict] = mapped_column(JSON, default=dict)
    local_data: Mapped[dict] = mapped_column(JSON, default=dict)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    researched: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockDiscoveryCandidateGroupMembership(Base):
    __tablename__ = "stock_discovery_candidate_group_memberships"
    __table_args__ = (UniqueConstraint("candidate_id", "group_id", name="uq_stock_discovery_membership"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"))
    group_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_candidate_groups.id", ondelete="CASCADE"))
    original_reason: Mapped[str] = mapped_column(Text, default="")
    raw_order: Mapped[int] = mapped_column(Integer, default=0)


class StockDiscoveryCandidateMetric(Base):
    __tablename__ = "stock_discovery_candidate_metrics"
    __table_args__ = (UniqueConstraint("candidate_id", "metric_key", "source", name="uq_stock_discovery_metric_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"))
    metric_key: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="unknown")
    data_period: Mapped[str | None] = mapped_column(String(64))
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    has_discrepancy: Mapped[bool] = mapped_column(Boolean, default=False)


class StockDiscoverySource(Base):
    __tablename__ = "stock_discovery_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32), default="other")
    source_origin: Mapped[str] = mapped_column(String(32), default="perplexity_finance")


class StockDiscoveryFilterResult(Base):
    __tablename__ = "stock_discovery_filter_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_candidates.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    filter_version: Mapped[str] = mapped_column(String(64), default="stock-discovery-filter-v0.4")


class StockDiscoveryRawPayload(Base):
    __tablename__ = "stock_discovery_raw_payloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), unique=True)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_text: Mapped[str] = mapped_column(Text, default="")
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_results: Mapped[list] = mapped_column(JSON, default=list)


class StockDiscoveryUsage(Base):
    __tablename__ = "stock_discovery_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), unique=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    finance_search_calls: Mapped[int] = mapped_column(Integer, default=0)
    web_search_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    model_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    raw_usage: Mapped[dict] = mapped_column(JSON, default=dict)


class OpportunityHistory(Base):
    """Immutable user-visible result from one manually triggered discovery run."""
    __tablename__ = "opportunity_history"
    __table_args__ = (Index("ix_opportunity_history_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    query_context: Mapped[dict] = mapped_column(JSON, default=dict)
    market_condition: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(128))
    search_source: Mapped[str] = mapped_column(String(64), default="perplexity_search")


class TradeTransaction(Base):
    """权威的交易历史事实。持仓聚合与批次都是从这里推导出来的派生状态。

    transaction_type 覆盖 buy/sell/dividend/fee/deposit/withdrawal/split/transfer_in/transfer_out；
    首版仅对 buy/sell/dividend/fee 做完整持仓推导，其余类型安全存储、可后续扩展。
    """
    __tablename__ = "trade_transactions"
    __table_args__ = (
        Index("ix_trade_transactions_portfolio_symbol", "portfolio_id", "symbol"),
        UniqueConstraint("source_log_id", "source_log_row_index", name="uq_trade_transactions_journal_row"),
        CheckConstraint("quantity >= 0", name="ck_trade_transactions_quantity"),
        CheckConstraint("price >= 0", name="ck_trade_transactions_price"),
        CheckConstraint("fees >= 0", name="ck_trade_transactions_fees"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    transaction_type: Mapped[str] = mapped_column(String(16), default="buy", index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    account: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual / journal / import
    # Source governance. ``source`` remains for API compatibility; these
    # explicit fields prevent accounting code from inferring authority from a
    # note or display label.
    source_type: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    authority_source: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    authority_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    superseded_by_source: Mapped[str | None] = mapped_column(String(24))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ibkr_flex_sync_runs.id", ondelete="SET NULL"), index=True
    )
    superseded_by_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("ibkr_flex_records.id", ondelete="SET NULL"), index=True
    )
    match_confidence: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(48))
    source_log_id: Mapped[int | None] = mapped_column(ForeignKey("trade_logs.id", ondelete="CASCADE"), index=True)
    source_log_row_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioPosition(Base):
    """聚合持仓：一个派生缓存/查询层，永远可以从 TradeTransaction 重建，不是权威记录。"""
    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_positions_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    average_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    last_transaction_at: Mapped[date | None] = mapped_column(Date)
    authority_source: Mapped[str] = mapped_column(String(24), default="transactions")
    ibkr_sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="SET NULL"), index=True)
    ibkr_conid: Mapped[str | None] = mapped_column(String(32), index=True)
    ibkr_market_price: Mapped[float | None] = mapped_column(Float)
    ibkr_market_value: Mapped[float | None] = mapped_column(Float)
    ibkr_unrealized_pnl: Mapped[float | None] = mapped_column(Float)
    ibkr_fx_rate_to_base: Mapped[float | None] = mapped_column(Float)
    ibkr_report_date: Mapped[date | None] = mapped_column(Date)
    ibkr_details: Mapped[dict] = mapped_column(JSON, default=dict)
    authority_conflicts: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioPositionLot(Base):
    """持仓批次。首版用平均成本法记账，但保留 FIFO/LIFO/指定批次/部分平仓的扩展边界。"""
    __tablename__ = "portfolio_position_lots"
    __table_args__ = (Index("ix_portfolio_position_lots_symbol", "symbol", "portfolio_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    source_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("trade_transactions.id", ondelete="SET NULL"), index=True)
    original_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    allocated_fees: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open / partial / closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TradeLog(Base):
    __tablename__ = 'trade_logs'
    __table_args__ = (
        UniqueConstraint("user_id", "ibkr_sync_run_id", "ibkr_position_id", name="uq_trade_logs_ibkr_position_draft"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    direction: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    table_rows: Mapped[list] = mapped_column(JSON, default=list)
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    source_type: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    objective_facts: Mapped[dict] = mapped_column(JSON, default=dict)
    ibkr_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ibkr_flex_sync_runs.id", ondelete="SET NULL"), index=True
    )
    ibkr_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_positions.id", ondelete="SET NULL"), index=True
    )
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_model: Mapped[str | None] = mapped_column(String(128))
    ai_summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MacroSeries(Base):
    """Metadata for a persisted macroeconomic time series.

    Raw Alpha Vantage series are stored here. Derived metrics are calculated
    from these observations so they can be reproduced whenever the provider
    revises history, rather than being hand-written latest values.
    """
    __tablename__ = "macro_series"
    __table_args__ = (
        UniqueConstraint("provider", "series_key", name="uq_macro_series_provider_key"),
        Index("ix_macro_series_country_category_enabled", "country_code", "category", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_key: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="alpha_vantage", index=True)
    provider_function: Mapped[str] = mapped_column(String(64))
    provider_parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    country_code: Mapped[str] = mapped_column(String(2), default="US", index=True)
    display_name_zh: Mapped[str] = mapped_column(String(128))
    display_name_en: Mapped[str] = mapped_column(String(128))
    description_zh: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    frequency: Mapped[str] = mapped_column(String(16), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    source_name: Mapped[str] = mapped_column(String(128), default="Alpha Vantage")
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MacroObservation(Base):
    """One dated provider observation; observation_date is not fetch time."""
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint("series_id", "observation_date", name="uq_macro_observations_series_date"),
        Index("ix_macro_observations_series_date_desc", "series_id", "observation_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("macro_series.id", ondelete="CASCADE"), index=True)
    observation_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    unit: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32), default="alpha_vantage")
    source_name: Mapped[str | None] = mapped_column(String(128))
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_number: Mapped[int] = mapped_column(Integer, default=0)
    first_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MacroSyncRun(Base):
    __tablename__ = "macro_sync_runs"
    __table_args__ = (Index("ix_macro_sync_runs_provider_started", "provider", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="alpha_vantage", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    requested_series_count: Mapped[int] = mapped_column(Integer, default=0)
    successful_series_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_series_count: Mapped[int] = mapped_column(Integer, default=0)
    api_requests_used: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    trigger_type: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)


class MacroApiUsage(Base):
    __tablename__ = "macro_api_usage"
    __table_args__ = (
        UniqueConstraint("provider", "usage_date_utc", name="uq_macro_api_usage_provider_date"),
        Index("ix_macro_api_usage_provider_date", "provider", "usage_date_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="alpha_vantage")
    usage_date_utc: Mapped[date] = mapped_column(Date, index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    successful_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited_count: Mapped[int] = mapped_column(Integer, default=0)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Register integration-owned tables in the same metadata whenever core models
# are imported (tests, application runtime, and Alembic must see one graph).
from app.integrations.ibkr import db_models as _ibkr_db_models  # noqa: E402,F401
