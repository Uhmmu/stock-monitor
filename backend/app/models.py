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
from sqlalchemy.types import TypeDecorator

from app.database import Base


class PreciseNumeric(TypeDecorator):
    """Numeric(38, 18) that survives SQLite tests without float round-trips.

    PostgreSQL uses the native NUMERIC type; SQLite (tests only) stores the
    decimal as text so precision assertions are exact.
    """

    impl = Numeric(38, 18)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            from sqlalchemy import String

            return dialect.type_descriptor(String(80))
        return dialect.type_descriptor(Numeric(38, 18))

    def process_bind_param(self, value, dialect):
        if dialect.name == "sqlite":
            return str(value) if value is not None else None
        return value

    def process_result_value(self, value, dialect):
        if dialect.name == "sqlite":
            return Decimal(value) if value is not None else None
        return value


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


class SecuritySymbolAlias(Base):
    """Historical provider symbol for an existing security identity."""
    __tablename__ = "security_symbol_aliases"
    __table_args__ = (UniqueConstraint("provider", "symbol", name="uq_security_symbol_aliases_provider_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    change_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    feed: Mapped[str | None] = mapped_column(String(32))
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


class IntradayBar(Base):
    """Normalized intraday OHLCV. Realtime ticks remain ephemeral in Redis."""
    __tablename__ = "intraday_bars"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timestamp", "interval", "provider", "feed",
            name="uq_intraday_bars_source_minute",
        ),
        Index("ix_intraday_bars_symbol_interval_timestamp", "symbol", "interval", "timestamp"),
        CheckConstraint("interval IN ('1m', '5m', '15m')", name="ck_intraday_bars_interval"),
        CheckConstraint("high >= low", name="ck_intraday_bars_high_low"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_intraday_bars_volume"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval: Mapped[str] = mapped_column(String(8), default="1m")
    open: Mapped[float] = mapped_column(Numeric(20, 8))
    high: Mapped[float] = mapped_column(Numeric(20, 8))
    low: Mapped[float] = mapped_column(Numeric(20, 8))
    close: Mapped[float] = mapped_column(Numeric(20, 8))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[float | None] = mapped_column(Numeric(20, 8))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    feed: Mapped[str] = mapped_column(String(32), default="unknown")
    market_session: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketMonitorEvent(Base):
    """Cooldown-controlled deterministic intraday monitor event."""
    __tablename__ = "market_monitor_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_market_monitor_events_event_key"),
        Index("ix_market_monitor_events_symbol_timestamp", "symbol", "timestamp"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    feed: Mapped[str | None] = mapped_column(String(32))
    market_session: Mapped[str] = mapped_column(String(16), default="unknown")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    canonical_story_id: Mapped[str | None] = mapped_column(String(64), index=True)
    provider_sources: Mapped[list | None] = mapped_column(JSON)
    provider_metadata: Mapped[dict | None] = mapped_column(JSON)
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
    article_content: Mapped[str | None] = mapped_column(Text)
    article_content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    content_final_url: Mapped[str | None] = mapped_column(Text)
    content_fetch_method: Mapped[str | None] = mapped_column(String(32))
    content_fetch_status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    content_fetch_quality: Mapped[float | None] = mapped_column(Float)
    content_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_fetch_error_code: Mapped[str | None] = mapped_column(String(32))
    image_url: Mapped[str | None] = mapped_column(Text)
    symbols: Mapped[list | None] = mapped_column(JSON)
    news_type: Mapped[str] = mapped_column(String(32), default="article", server_default="article")
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_event_type: Mapped[str | None] = mapped_column(String(32), index=True)
    ai_sentiment: Mapped[str | None] = mapped_column(String(16), index=True)
    ai_importance: Mapped[int | None] = mapped_column(Integer, index=True)
    ai_market_impact: Mapped[str | None] = mapped_column(Text)
    ai_summary_model: Mapped[str | None] = mapped_column(String(128))
    ai_summary_version: Mapped[str | None] = mapped_column(String(32))
    ai_summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_summary_status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    ai_summary_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ai_summary_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_summary_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
    adjusted_close: Mapped[float | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change_percent: Mapped[float | None] = mapped_column(Numeric(16, 6))
    source: Mapped[str] = mapped_column(String(16), default="fmp")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketDataSyncState(Base):
    """Freshness/checkpoint state for the shared daily-price repository."""
    __tablename__ = "market_data_sync_states"
    __table_args__ = (
        CheckConstraint("priority IN ('P0', 'P1', 'P2')", name="ck_market_data_sync_states_priority"),
        CheckConstraint("failure_count >= 0", name="ck_market_data_sync_states_failure_count"),
    )

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    priority: Mapped[str] = mapped_column(String(2), default="P2", index=True)
    latest_market_date: Mapped[date | None] = mapped_column(Date, index=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(16))
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    freshness_status: Mapped[str] = mapped_column(String(32), default="MISSING", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
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


class SecEpsFact(Base):
    """SEC XBRL companyconcept 的 diluted EPS 事实（point-in-time）。

    同一 (period_start, period_end) 会在多份 filing 里重复出现（原始 + 后续比较期），
    这里只保留「首次公开」的那一条：eps 为首次披露值，first_filed 是其生效日期，
    用于历史估值的 as-of join，杜绝 look-ahead bias。
    """
    __tablename__ = "sec_eps_facts"
    __table_args__ = (
        UniqueConstraint("ticker", "period_start", "period_end"),
        Index("ix_sec_eps_facts_ticker_filed", "ticker", "first_filed"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    duration_days: Mapped[int] = mapped_column(Integer)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    form: Mapped[str] = mapped_column(String(16))
    accession_number: Mapped[str | None] = mapped_column(String(32))
    first_filed: Mapped[date] = mapped_column(Date)
    eps: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="sec_xbrl_companyconcept")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockSplit(Base):
    """拆股历史（yfinance 采集；FMP EOD 价格已是复权口径，用于把 as-reported EPS 换算到当前股本）。"""
    __tablename__ = "stock_splits"
    __table_args__ = (UniqueConstraint("symbol", "ex_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    ex_date: Mapped[date] = mapped_column(Date)
    ratio: Mapped[float] = mapped_column(Float)  # 1 旧股 = ratio 新股
    source: Mapped[str] = mapped_column(String(16), default="yfinance")
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
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """Server-side refresh-token session; only the sha256 hash is stored."""
    __tablename__ = 'auth_sessions'
    __table_args__ = (
        Index('ix_auth_sessions_user_revoked', 'user_id', 'revoked_at'),
        Index('ix_auth_sessions_family', 'family_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36))
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    funnel_stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default="{}")
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


class StockDiscoveryAgentEvent(Base):
    """Lightweight research-funnel event reported by the Pi Agent sidecar.

    Only observable milestones are stored (theme discovered, candidate
    screened, ...), never model chain-of-thought.
    """
    __tablename__ = "stock_discovery_agent_events"
    __table_args__ = (Index("ix_stock_discovery_agent_events_run", "run_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stock_discovery_runs.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class IndustryPulseNode(Base):
    """Persisted canonical industry/theme taxonomy node.

    Provider labels remain evidence only; this table is the application's
    stable taxonomy and graph identity.  ``taxonomy`` distinguishes the base
    industry tree from the AI/theme graph while ``parent_id`` supports both
    hierarchies without introducing a second node table.
    """

    __tablename__ = "industry_pulse_nodes"
    __table_args__ = (
        UniqueConstraint("taxonomy", "node_key", name="uq_industry_pulse_nodes_taxonomy_key"),
        Index("ix_industry_pulse_nodes_taxonomy_parent", "taxonomy", "parent_id"),
        Index("ix_industry_pulse_nodes_enabled", "enabled"),
        CheckConstraint("taxonomy IN ('base', 'ai')", name="ck_industry_pulse_nodes_taxonomy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    taxonomy: Mapped[str] = mapped_column(String(16), default="base")
    node_key: Mapped[str] = mapped_column(String(192))
    slug: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(192))
    name_zh: Mapped[str | None] = mapped_column(String(192))
    level: Mapped[str] = mapped_column(String(24), default="leaf")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustryPulseRelation(Base):
    """Directed AI-chain/theme edge between persisted taxonomy nodes."""

    __tablename__ = "industry_pulse_relations"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_industry_pulse_relations_edge"),
        Index("ix_industry_pulse_relations_source_node_id", "source_node_id"),
        Index("ix_industry_pulse_relations_target_node_id", "target_node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"))
    target_node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(32), default="downstream")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndustryPulseInstrument(Base):
    """ETF/security proxy mapping for a taxonomy node.

    A mapping is intentionally many-to-many.  ``role`` controls aggregation;
    benchmarks and references are stored for comparison but excluded from
    effective sector weights by the calculator.
    """

    __tablename__ = "industry_pulse_instruments"
    __table_args__ = (
        UniqueConstraint("node_id", "ticker", "role", name="uq_industry_pulse_instruments_node_ticker_role"),
        Index("ix_industry_pulse_instruments_node_enabled", "node_id", "enabled"),
        Index("ix_industry_pulse_instruments_ticker", "ticker"),
        Index("ix_industry_pulse_instruments_node_pulse", "node_id", "enabled_for_pulse"),
        CheckConstraint("mapping_type IN ('etf_proxy', 'primary_industry', 'secondary_industry', 'theme_exposure')", name="ck_industry_pulse_instruments_mapping_type"),
        CheckConstraint("role IN ('primary', 'secondary', 'reference', 'benchmark')", name="ck_industry_pulse_instruments_role"),
        CheckConstraint("purity >= 0 AND purity <= 1", name="ck_industry_pulse_instruments_purity"),
        CheckConstraint("exposure >= 0 AND exposure <= 1", name="ck_industry_pulse_instruments_exposure"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_industry_pulse_instruments_confidence"),
        CheckConstraint("liquidity >= 0 AND liquidity <= 1", name="ck_industry_pulse_instruments_liquidity"),
        CheckConstraint("classification_source IN ('MANUAL_CURATED_SEED', 'MANUAL', 'ETF_HOLDING', 'AI_CLASSIFIED', 'PROVIDER', 'INHERITED')", name="ck_industry_pulse_instruments_classification_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"))
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"))
    ticker: Mapped[str] = mapped_column(String(32))
    instrument_type: Mapped[str] = mapped_column(String(16), default="etf")
    mapping_type: Mapped[str] = mapped_column(String(24), default="etf_proxy", index=True)
    role: Mapped[str] = mapped_column(String(24), default="primary", index=True)
    purity: Mapped[float] = mapped_column(Float, default=1.0)
    exposure: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    liquidity: Mapped[float] = mapped_column(Float, default=1.0)
    provider_symbol: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    classification_source: Mapped[str] = mapped_column(String(24), default="PROVIDER", index=True)
    seed_version: Mapped[int | None] = mapped_column(Integer, index=True)
    slot: Mapped[int | None] = mapped_column(Integer)
    basket_quality: Mapped[str | None] = mapped_column(String(16))
    source_etf: Mapped[str | None] = mapped_column(String(32))
    constituent_role: Mapped[str | None] = mapped_column(String(24))
    enabled_for_pulse: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    health_status: Mapped[str] = mapped_column(String(32), default="UNAVAILABLE")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_trading_date: Mapped[date | None] = mapped_column(Date)
    data_quality: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustrySeedReplacementReview(Base):
    __tablename__ = "industry_seed_replacement_reviews"
    __table_args__ = (UniqueConstraint("seed_version", "leaf_code", "old_symbol", name="uq_industry_seed_replacement_review"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_version: Mapped[int] = mapped_column(Integer, index=True)
    leaf_code: Mapped[str] = mapped_column(String(16), index=True)
    leaf_name: Mapped[str] = mapped_column(String(256))
    old_symbol: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    last_valid_date: Mapped[date | None] = mapped_column(Date)
    remaining_constituents: Mapped[list] = mapped_column(JSON, default=list)
    suggested_candidates: Mapped[list] = mapped_column(JSON, default=list)
    suggestion_reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustrySyntheticIndex(Base):
    """Transparent equal-weight daily index for one canonical base leaf."""
    __tablename__ = "industry_synthetic_indexes"
    __table_args__ = (
        UniqueConstraint("node_id", "trading_date", name="uq_industry_synthetic_indexes_node_date"),
        Index("ix_industry_synthetic_indexes_node_date", "node_id", "trading_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    index_value: Mapped[float | None] = mapped_column(Float)
    daily_return: Mapped[float | None] = mapped_column(Float)
    valid_constituents: Mapped[int] = mapped_column(Integer)
    expected_constituents: Mapped[int] = mapped_column(Integer, default=5)
    coverage_quality: Mapped[float] = mapped_column(Float)
    calculation_status: Mapped[str] = mapped_column(String(32), index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    methodology_version: Mapped[str] = mapped_column(String(32), default="equal_weight_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustryPulseClassificationCache(Base):
    """Idempotency cache for bounded Luna candidate classification."""

    __tablename__ = "industry_pulse_classification_cache"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    metadata_hash: Mapped[str] = mapped_column(String(64), index=True)
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustryPulseSnapshot(Base):
    """Point-in-time deterministic pulse for one node and trading date."""

    __tablename__ = "industry_pulse_snapshots"
    __table_args__ = (
        UniqueConstraint("node_id", "trading_date", name="uq_industry_pulse_snapshots_node_date"),
        Index("ix_industry_pulse_snapshots_node_date", "node_id", "trading_date"),
        Index("ix_industry_pulse_snapshots_date", "trading_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    pulse: Mapped[float | None] = mapped_column(Float)
    trend_score: Mapped[float | None] = mapped_column(Float)
    relative_strength_score: Mapped[float | None] = mapped_column(Float)
    volume_score: Mapped[float | None] = mapped_column(Float)
    momentum_score: Mapped[float | None] = mapped_column(Float)
    breadth_score: Mapped[float | None] = mapped_column(Float)
    consensus_score: Mapped[float | None] = mapped_column(Float)
    heat: Mapped[float | None] = mapped_column(Float)
    risk: Mapped[float | None] = mapped_column(Float)
    change_1d: Mapped[float | None] = mapped_column(Float)
    change_5d: Mapped[float | None] = mapped_column(Float)
    change_20d: Mapped[float | None] = mapped_column(Float)
    mood: Mapped[str | None] = mapped_column(String(32))
    regime: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str | None] = mapped_column(String(24))
    data_quality: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    coverage_quality: Mapped[float | None] = mapped_column(Float)
    proxy_based_on_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark_json: Mapped[dict] = mapped_column(JSON, default=dict)
    calculation_version: Mapped[str] = mapped_column(String(32), default="v1")
    source: Mapped[str] = mapped_column(String(32), default="yahoo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndustryPulseFocusSignal(Base):
    """Persisted deterministic focus/ranking signal for one node/date."""

    __tablename__ = "industry_pulse_focus_signals"
    __table_args__ = (
        UniqueConstraint("node_id", "trading_date", "signal_type", name="uq_industry_pulse_focus_node_date_type"),
        Index("ix_industry_pulse_focus_date_type", "trading_date", "signal_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    signal_type: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndustryPulseSyncRun(Base):
    """Durable telemetry for the daily/due Industry Pulse task."""

    __tablename__ = "industry_pulse_sync_runs"
    __table_args__ = (Index("ix_industry_pulse_sync_runs_started", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    trigger_type: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    etf_total: Mapped[int] = mapped_column(Integer, default=0)
    yfinance_success: Mapped[int] = mapped_column(Integer, default=0)
    finnhub_fallback: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    sector_calculated: Mapped[int] = mapped_column(Integer, default=0)
    sector_unavailable: Mapped[int] = mapped_column(Integer, default=0)
    focus_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_summaries_generated: Mapped[int] = mapped_column(Integer, default=0)
    luna_calls: Mapped[int] = mapped_column(Integer, default=0)
    sol_calls: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)


class IndustryPulseNarrative(Base):
    """Optional cached Luna explanation, isolated from numeric snapshots."""

    __tablename__ = "industry_pulse_narratives"
    __table_args__ = (
        UniqueConstraint("node_id", "trading_date", name="uq_industry_pulse_narratives_node_date"),
        Index("ix_industry_pulse_narratives_date", "trading_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="CASCADE"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OptionsSnapshot(Base):
    """Bounded daily options analytics; filtered contracts live in payload, not a contract ledger."""

    __tablename__ = "options_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "trading_date", name="uq_options_snapshots_symbol_date"),
        Index("ix_options_snapshots_symbol_date", "symbol", "trading_date"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="ck_options_snapshots_quality"),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_options_snapshots_coverage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), index=True)
    sector_node_id: Mapped[int | None] = mapped_column(ForeignKey("industry_pulse_nodes.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(16), default="yfinance")
    underlying_price: Mapped[float | None] = mapped_column(Float)
    nearest_expiration: Mapped[date | None] = mapped_column(Date)
    next_expiration: Mapped[date | None] = mapped_column(Date)
    days_to_expiration: Mapped[int | None] = mapped_column(Integer)
    active_contracts: Mapped[int] = mapped_column(Integer, default=0)
    call_volume: Mapped[int | None] = mapped_column(BigInteger)
    put_volume: Mapped[int | None] = mapped_column(BigInteger)
    call_open_interest: Mapped[int | None] = mapped_column(BigInteger)
    put_open_interest: Mapped[int | None] = mapped_column(BigInteger)
    put_call_volume_ratio: Mapped[float | None] = mapped_column(Float)
    put_call_oi_ratio: Mapped[float | None] = mapped_column(Float)
    atm_iv: Mapped[float | None] = mapped_column(Float)
    near_term_iv: Mapped[float | None] = mapped_column(Float)
    next_term_iv: Mapped[float | None] = mapped_column(Float)
    iv_change: Mapped[float | None] = mapped_column(Float)
    downside_skew: Mapped[float | None] = mapped_column(Float)
    upside_skew: Mapped[float | None] = mapped_column(Float)
    activity_score: Mapped[float | None] = mapped_column(Float)
    activity_status: Mapped[str] = mapped_column(String(32), default="insufficient_history")
    quality_score: Mapped[float] = mapped_column(Float, default=0)
    coverage: Mapped[float] = mapped_column(Float, default=0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OptionsChainCache(Base):
    """Short-lived, bounded provider evidence for detail views and provider debugging."""

    __tablename__ = "options_chain_cache"
    __table_args__ = (UniqueConstraint("symbol", "expiration", name="uq_options_chain_cache_symbol_expiration"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    expiration: Mapped[date] = mapped_column(Date, index=True)
    provider: Mapped[str] = mapped_column(String(16), default="yfinance")
    calls_json: Mapped[list] = mapped_column(JSON, default=list)
    puts_json: Mapped[list] = mapped_column(JSON, default=list)
    contract_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OptionsSyncRun(Base):
    __tablename__ = "options_sync_runs"
    __table_args__ = (Index("ix_options_sync_runs_started", "started_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    trigger_type: Mapped[str] = mapped_column(String(24), default="scheduled")
    symbols_requested: Mapped[int] = mapped_column(Integer, default=0)
    symbols_success: Mapped[int] = mapped_column(Integer, default=0)
    symbols_failed: Mapped[int] = mapped_column(Integer, default=0)
    contracts_received: Mapped[int] = mapped_column(Integer, default=0)
    contracts_filtered: Mapped[int] = mapped_column(Integer, default=0)
    low_quality_symbols: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MoodSnapshot(Base):
    """Deterministic, persisted AI Mood state for one scope and trading day.

    The JSON columns intentionally retain the evidence contract while the
    scalar columns make the latest state cheap to query and index.  A
    calculation version is part of the identity so history can be rebuilt
    without destroying older methodology results.
    """

    __tablename__ = "mood_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_key", "trading_date", "calculation_version", "snapshot_type",
            name="uq_mood_snapshots_scope_date_version_type",
        ),
        Index("ix_mood_snapshots_scope_date", "scope_type", "scope_key", "trading_date"),
        Index("ix_mood_snapshots_trading_date", "trading_date"),
        Index("ix_mood_snapshots_state", "state"),
        Index("ix_mood_snapshots_input_hash", "input_hash"),
        CheckConstraint("mood_score IS NULL OR (mood_score >= 0 AND mood_score <= 100)", name="ck_mood_snapshots_score"),
        CheckConstraint("agreement_score IS NULL OR (agreement_score >= 0 AND agreement_score <= 1)", name="ck_mood_snapshots_agreement"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_mood_snapshots_confidence"),
        CheckConstraint("quality IS NULL OR (quality >= 0 AND quality <= 1)", name="ck_mood_snapshots_quality"),
        CheckConstraint("coverage IS NULL OR (coverage >= 0 AND coverage <= 1)", name="ck_mood_snapshots_coverage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(24))
    scope_key: Mapped[str] = mapped_column(String(192))
    trading_date: Mapped[date] = mapped_column(Date)
    snapshot_type: Mapped[str] = mapped_column(String(16), default="INTRADAY")
    state: Mapped[str] = mapped_column(String(32))
    candidate_state: Mapped[str | None] = mapped_column(String(32))
    previous_state: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str | None] = mapped_column(String(16))
    phase: Mapped[str | None] = mapped_column(String(32))
    regime: Mapped[str | None] = mapped_column(String(32))
    mood_score: Mapped[float | None] = mapped_column(Float)
    agreement_score: Mapped[float | None] = mapped_column(Float)
    agreement_level: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float | None] = mapped_column(Float)
    freshness_status: Mapped[str | None] = mapped_column(String(24))
    state_started_on: Mapped[date | None] = mapped_column(Date)
    duration_sessions: Mapped[int | None] = mapped_column(Integer)
    calculation_version: Mapped[str] = mapped_column(String(32), default="mood_v1")
    input_hash: Mapped[str] = mapped_column(String(64))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    signals: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    divergences: Mapped[list] = mapped_column(JSON, default=list)
    transition: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_sources: Mapped[list] = mapped_column(JSON, default=list)
    stale_sources: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    input_manifest: Mapped[dict] = mapped_column(JSON, default=dict)


class MoodDailyRun(Base):
    """Durable daily Mood materialization run and coverage summary."""

    __tablename__ = "mood_daily_runs"
    __table_args__ = (
        UniqueConstraint("trading_date", "calculation_version", name="uq_mood_daily_runs_date_version"),
        Index("ix_mood_daily_runs_trading_date", "trading_date"),
        Index("ix_mood_daily_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date)
    calculation_version: Mapped[str] = mapped_column(String(32), default="mood_v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_scopes: Mapped[list] = mapped_column(JSON, default=list)
    completed_scopes: Mapped[list] = mapped_column(JSON, default=list)
    insufficient_scopes: Mapped[list] = mapped_column(JSON, default=list)
    failed_scopes: Mapped[list] = mapped_column(JSON, default=list)
    readiness: Mapped[dict] = mapped_column(JSON, default=dict)
    health: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)


class MoodValidationRun(Base):
    """Reproducible, append-only validation of persisted Mood history."""

    __tablename__ = "mood_validation_runs"
    __table_args__ = (
        Index("ix_mood_validation_runs_created", "created_at"),
        Index("ix_mood_validation_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    engine_version: Mapped[str] = mapped_column(String(64))
    calculation_version: Mapped[str] = mapped_column(String(32))
    validation_version: Mapped[str] = mapped_column(String(64))
    parameter_set: Mapped[dict] = mapped_column(JSON, default=dict)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    scope_filter: Mapped[list] = mapped_column(JSON, default=list)
    benchmark_config: Mapped[dict] = mapped_column(JSON, default=dict)
    forward_horizons: Mapped[list] = mapped_column(JSON, default=list)
    data_cutoff: Mapped[date] = mapped_column(Date)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)


class MoodValidationResult(Base):
    """One generic aggregate or drill-down index produced by a validation run."""

    __tablename__ = "mood_validation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "result_key", name="uq_mood_validation_results_run_key"),
        Index("ix_mood_validation_results_run_study", "run_id", "study_type"),
        Index("ix_mood_validation_results_scope", "run_id", "scope_type", "scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("mood_validation_runs.id", ondelete="CASCADE"), index=True)
    result_key: Mapped[str] = mapped_column(String(64))
    study_type: Mapped[str] = mapped_column(String(40), index=True)
    scope_type: Mapped[str | None] = mapped_column(String(24))
    scope_key: Mapped[str | None] = mapped_column(String(192))
    state: Mapped[str | None] = mapped_column(String(32))
    transition_from: Mapped[str | None] = mapped_column(String(32))
    transition_to: Mapped[str | None] = mapped_column(String(32))
    divergence_type: Mapped[str | None] = mapped_column(String(32))
    bucket: Mapped[str | None] = mapped_column(String(32))
    horizon: Mapped[int | None] = mapped_column(Integer)
    sample_mode: Mapped[str] = mapped_column(String(24), default="daily")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_interval: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[str] = mapped_column(String(24), default="INSUFFICIENT_SAMPLE")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    event_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Crypto canonical identity (crypto/quant program Phase 1).
#
# Deliberately separate from equity `Security`: one economic asset can have
# many chain deployments, protocols and venue products, and crypto symbols
# are never unique (see backend/tests/fixtures/crypto/identity_cases.json and
# docs/plans/crypto-quant-architecture-assessment.md ADR-02). Provider
# namespaces carry the market (binance_spot vs binance_usdm); a raw venue
# symbol such as BTCUSDT is ambiguous across markets by design.
# ---------------------------------------------------------------------------


class CryptoAsset(Base):
    """Canonical economic crypto asset; BTC and WBTC are distinct rows."""

    __tablename__ = "crypto_assets"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_crypto_assets_slug"),
        CheckConstraint("asset_kind IN ('coin', 'token')", name="ck_crypto_assets_kind"),
        CheckConstraint("status IN ('active', 'inactive', 'delisted')", name="ck_crypto_assets_status"),
        CheckConstraint("id <> wraps_asset_id", name="ck_crypto_assets_no_self_wrap"),
        Index("ix_crypto_assets_symbol", "symbol"),
        Index("ix_crypto_assets_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(256))
    asset_kind: Mapped[str] = mapped_column(String(16), default="coin")
    status: Mapped[str] = mapped_column(String(16), default="active")
    wraps_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_assets.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoAssetReference(Base):
    """Provider reference metadata attached to a canonical crypto asset.

    CoinGecko is an enrichment source only; the canonical asset remains the
    ``CryptoAsset`` row and provider mappings retain the explicit join
    evidence.  Contract/category/site payloads are bounded JSON because they
    are reference metadata rather than query-critical identity fields.
    """

    __tablename__ = "crypto_asset_references"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_crypto_asset_references_provider_id"),
        UniqueConstraint("asset_id", "provider", name="uq_crypto_asset_references_asset_provider"),
        Index("ix_crypto_asset_references_asset", "asset_id"),
        Index("ix_crypto_asset_references_provider_timestamp", "provider", "provider_timestamp"),
        CheckConstraint("revision >= 0", name="ck_crypto_asset_references_revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(128))
    canonical_name: Mapped[str | None] = mapped_column(String(256))
    symbol: Mapped[str | None] = mapped_column(String(32))
    categories: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    website_urls: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    contract_references: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    reference_metadata: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    source: Mapped[str] = mapped_column(String(32), default="coingecko", server_default="coingecko")
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    freshness_status: Mapped[str] = mapped_column(String(16), default="fresh", server_default="fresh")
    source_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoAssetFundamentalSnapshot(Base):
    """Point-in-time market fundamentals from an optional reference provider.

    Missing provider values stay NULL.  ``coverage`` is the fraction of the
    six primary values present, not an inferred confidence score.
    """

    __tablename__ = "crypto_asset_fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "provider", "observed_at",
            name="uq_crypto_asset_fundamental_snapshots_observation",
        ),
        Index("ix_crypto_asset_fundamental_snapshots_asset_time", "asset_id", "observed_at"),
        Index("ix_crypto_asset_fundamental_snapshots_provider_time", "provider", "observed_at"),
        CheckConstraint("revision >= 0", name="ck_crypto_asset_fundamental_snapshots_revision"),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_crypto_asset_fundamental_snapshots_coverage"),
        CheckConstraint("market_cap_rank IS NULL OR market_cap_rank >= 1", name="ck_crypto_asset_fundamental_snapshots_rank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="coingecko", server_default="coingecko")
    currency: Mapped[str] = mapped_column(String(16), default="usd", server_default="usd")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_cap: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    fully_diluted_valuation: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    circulating_supply: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    total_supply: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    max_supply: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    coverage: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    freshness_status: Mapped[str] = mapped_column(String(16), default="fresh", server_default="fresh")
    quality: Mapped[str] = mapped_column(String(24), default="ok", server_default="ok")
    source_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoSymbolAlias(Base):
    """Historical/alternative ticker explicitly linked to one asset (XBT -> bitcoin)."""

    __tablename__ = "crypto_symbol_aliases"
    __table_args__ = (UniqueConstraint("symbol", name="uq_crypto_symbol_aliases_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CryptoProviderMapping(Base):
    """Vendor namespace id mapped to exactly one typed crypto object.

    The single-target and type-match checks enforce exactly one non-null
    target column matching ``object_type``; provider namespaces carry the
    market (binance_spot vs binance_usdm). Retargeting an existing mapping
    is never implicit; use the explicit service path.
    """

    __tablename__ = "crypto_provider_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "object_type", "provider_id", name="uq_crypto_provider_mappings_key"),
        CheckConstraint(
            "object_type IN ('asset', 'token', 'protocol', 'instrument')",
            name="ck_crypto_provider_mappings_object_type",
        ),
        CheckConstraint(
            "(CASE WHEN asset_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN token_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN protocol_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN instrument_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_crypto_provider_mappings_single_target",
        ),
        CheckConstraint(
            "((object_type = 'asset') = (asset_id IS NOT NULL))"
            " AND ((object_type = 'token') = (token_id IS NOT NULL))"
            " AND ((object_type = 'protocol') = (protocol_id IS NOT NULL))"
            " AND ((object_type = 'instrument') = (instrument_id IS NOT NULL))",
            name="ck_crypto_provider_mappings_type_match",
        ),
        Index("ix_crypto_provider_mappings_asset", "asset_id"),
        Index("ix_crypto_provider_mappings_token", "token_id"),
        Index("ix_crypto_provider_mappings_protocol", "protocol_id"),
        Index("ix_crypto_provider_mappings_instrument", "instrument_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    object_type: Mapped[str] = mapped_column(String(16))
    provider_id: Mapped[str] = mapped_column(String(128))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"))
    token_id: Mapped[int | None] = mapped_column(ForeignKey("crypto_tokens.id", ondelete="CASCADE"))
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("crypto_protocols.id", ondelete="CASCADE"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("crypto_instruments.id", ondelete="CASCADE"))
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(32), default="manual")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Blockchain(Base):
    """Chain identity with a CAIP-2-style namespace/reference and native asset."""

    __tablename__ = "blockchains"
    __table_args__ = (
        UniqueConstraint("namespace", "reference", name="uq_blockchains_namespace_reference"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_blockchains_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    namespace: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(128))
    native_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_assets.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoToken(Base):
    """One deployment of an asset on a chain; native coins have no token row.

    Addresses are stored normalized per chain rule (EVM chains lowercase).
    Wrapped relations live on the asset; bridged origin links token rows.
    """

    __tablename__ = "crypto_tokens"
    __table_args__ = (
        UniqueConstraint("chain_id", "normalized_address", name="uq_crypto_tokens_chain_address"),
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'mismatch')",
            name="ck_crypto_tokens_verification",
        ),
        Index("ix_crypto_tokens_asset", "asset_id"),
        Index("ix_crypto_tokens_chain", "chain_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"))
    chain_id: Mapped[int] = mapped_column(ForeignKey("blockchains.id", ondelete="CASCADE"))
    normalized_address: Mapped[str] = mapped_column(String(128))
    decimals: Mapped[int | None] = mapped_column(Integer)
    bridged_from_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_tokens.id", ondelete="SET NULL"), index=True
    )
    verification_status: Mapped[str] = mapped_column(String(16), default="unverified")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoProtocol(Base):
    """Protocol/project identity separate from any tradable token."""

    __tablename__ = "crypto_protocols"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_crypto_protocols_slug"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_crypto_protocols_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    website: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoProtocolAsset(Base):
    """Many-to-many protocol/asset role such as governance or fee token."""

    __tablename__ = "crypto_protocol_assets"
    __table_args__ = (
        UniqueConstraint("protocol_id", "asset_id", "role", name="uq_crypto_protocol_assets_role"),
        CheckConstraint("role <> ''", name="ck_crypto_protocol_assets_role_nonempty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("crypto_protocols.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CryptoInstrument(Base):
    """Tradable venue product; BTCUSDT spot and perpetual are distinct rows.

    Unique identity is ``(venue, provider_symbol, kind)`` — the WP 0.3
    fixture proves ``(venue, provider_symbol)`` alone collides across
    markets. Inactive/delisted rows are preserved for historical identity.
    """

    __tablename__ = "crypto_instruments"
    __table_args__ = (
        UniqueConstraint("venue", "provider_symbol", "kind", name="uq_crypto_instruments_venue_symbol_kind"),
        CheckConstraint(
            "kind IN ('spot', 'perpetual', 'future')",
            name="ck_crypto_instruments_kind",
        ),
        CheckConstraint(
            "market IN ('spot', 'usdm_futures', 'coinm_futures')",
            name="ck_crypto_instruments_market",
        ),
        CheckConstraint(
            "status IN ('trading', 'halted', 'delisted', 'inactive')",
            name="ck_crypto_instruments_status",
        ),
        CheckConstraint("calendar = 'utc'", name="ck_crypto_instruments_utc_calendar"),
        Index(
            "ix_crypto_instruments_assets_kind_status",
            "base_asset_id",
            "quote_asset_id",
            "kind",
            "status",
        ),
        Index("ix_crypto_instruments_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(16))
    provider_symbol: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    base_asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="RESTRICT"))
    quote_asset_id: Mapped[int] = mapped_column(ForeignKey("crypto_assets.id", ondelete="RESTRICT"))
    settlement_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_assets.id", ondelete="SET NULL"), index=True
    )
    contract_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    step_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    min_notional: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    price_precision: Mapped[int | None] = mapped_column(Integer)
    quantity_precision: Mapped[int | None] = mapped_column(Integer)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="trading")
    listing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delisting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar: Mapped[str] = mapped_column(String(8), default="utc")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoCollectionRun(Base):
    """Durable job claim/status/counts for a crypto provider domain sync."""

    __tablename__ = "crypto_collection_runs"
    __table_args__ = (
        UniqueConstraint("provider", "domain", "bucket", name="uq_crypto_collection_runs_claim"),
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'partial', 'failed')",
            name="ck_crypto_collection_runs_status",
        ),
        Index("ix_crypto_collection_runs_status", "status"),
        Index("ix_crypto_collection_runs_provider_domain", "provider", "domain", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str] = mapped_column(String(64))
    # time bucket for the claim key (UTC date or hour depending on cadence)
    bucket: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class CryptoSyncState(Base):
    """Per instrument/provider/data-kind watermark with due/gap/error state."""

    __tablename__ = "crypto_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "provider", "data_kind", "interval",
            name="uq_crypto_sync_states_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("crypto_instruments.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    data_kind: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8), default="")
    watermark_ms: Mapped[int | None] = mapped_column(BigInteger)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketCandle(Base):
    """Closed UTC OHLCV candle for any crypto instrument and price authority.

    Identity is ``(instrument_id, interval, open_time_ms, provider,
    price_type)``; ``feed`` records how the row arrived (REST backfill is
    history authority, stream rows only supplement). Prices/volumes keep
    high-precision numerics — never floats.
    """

    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "interval", "open_time_ms", "provider", "price_type",
            name="uq_market_candles_key",
        ),
        CheckConstraint("interval IN ('1h', '4h', '1d')", name="ck_market_candles_interval"),
        CheckConstraint("price_type IN ('trade', 'mark', 'index', 'premium')", name="ck_market_candles_price_type"),
        CheckConstraint("feed IN ('rest', 'stream')", name="ck_market_candles_feed"),
        # CAST keeps the comparisons numeric on SQLite's text-backed decimals;
        # on PostgreSQL NUMERIC the cast is a no-op.
        CheckConstraint("CAST(high AS NUMERIC) >= CAST(low AS NUMERIC)", name="ck_market_candles_high_low"),
        CheckConstraint(
            "CAST(high AS NUMERIC) >= CAST(open AS NUMERIC) AND CAST(high AS NUMERIC) >= CAST(close AS NUMERIC)",
            name="ck_market_candles_high_extremes",
        ),
        CheckConstraint(
            "CAST(low AS NUMERIC) <= CAST(open AS NUMERIC) AND CAST(low AS NUMERIC) <= CAST(close AS NUMERIC)",
            name="ck_market_candles_low_extremes",
        ),
        CheckConstraint(
            "CAST(base_volume AS NUMERIC) >= 0 AND CAST(quote_volume AS NUMERIC) >= 0",
            name="ck_market_candles_volume_nonnegative",
        ),
        Index(
            "ix_market_candles_instrument_interval_time",
            "instrument_id", "interval", "open_time_ms",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("crypto_instruments.id", ondelete="CASCADE"))
    interval: Mapped[str] = mapped_column(String(8))
    open_time_ms: Mapped[int] = mapped_column(BigInteger)
    close_time_ms: Mapped[int] = mapped_column(BigInteger)
    price_type: Mapped[str] = mapped_column(String(8), default="trade")
    provider: Mapped[str] = mapped_column(String(16))
    feed: Mapped[str] = mapped_column(String(8), default="rest")
    open: Mapped[Decimal] = mapped_column(PreciseNumeric)
    high: Mapped[Decimal] = mapped_column(PreciseNumeric)
    low: Mapped[Decimal] = mapped_column(PreciseNumeric)
    close: Mapped[Decimal] = mapped_column(PreciseNumeric)
    base_volume: Mapped[Decimal] = mapped_column(PreciseNumeric)
    quote_volume: Mapped[Decimal] = mapped_column(PreciseNumeric)
    taker_buy_base_volume: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    taker_buy_quote_volume: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    trades: Mapped[int | None] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    final: Mapped[bool] = mapped_column(Boolean, default=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoFundingRate(Base):
    """One provider funding event for an exact perpetual instrument.

    Funding events are kept separate from periodic derivatives snapshots: the
    event clock is provider-defined (usually every eight hours), while metric
    snapshots use a configured interval.  Decimal values never pass through a
    binary float, and a changed provider payload increments ``revision`` in
    the repository layer.
    """

    __tablename__ = "crypto_funding_rates"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "funding_time", "provider",
            name="uq_crypto_funding_rates_key",
        ),
        CheckConstraint("revision >= 0", name="ck_crypto_funding_rates_revision"),
        Index("ix_crypto_funding_rates_instrument_time", "instrument_id", "funding_time"),
        Index("ix_crypto_funding_rates_provider_time", "provider", "funding_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(32))
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    funding_rate: Mapped[Decimal] = mapped_column(PreciseNumeric)
    predicted_rate: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    mark_price: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quality: Mapped[str] = mapped_column(String(24), default="ok", server_default="ok")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class CryptoDerivativesMetric(Base):
    """Typed periodic derivatives snapshot.

    The row is intentionally wide for the core research fields.  Metadata
    columns keep each provider definition/scope/unit explicit, while null
    typed fields represent unavailable endpoint data rather than inferred
    values.  Ratios with different denominators have separate columns and
    definitions instead of being silently collapsed.
    """

    __tablename__ = "crypto_derivatives_metrics"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "interval", "observed_at", "provider",
            name="uq_crypto_derivatives_metrics_key",
        ),
        CheckConstraint("revision >= 0", name="ck_crypto_derivatives_metrics_revision"),
        Index(
            "ix_crypto_derivatives_metrics_instrument_interval_time",
            "instrument_id", "interval", "observed_at",
        ),
        Index("ix_crypto_derivatives_metrics_provider_time", "provider", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mark_price: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    index_price: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    basis: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    basis_rate: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    premium: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    mark_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    open_interest_base: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    open_interest_quote: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    open_interest_usd: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    long_short_ratio: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    top_trader_account_ratio: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    top_trader_position_ratio: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    taker_buy_sell_ratio: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    taker_buy_volume: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    taker_sell_volume: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    futures_volume_base: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    futures_volume_quote: Mapped[Decimal | None] = mapped_column(PreciseNumeric)
    futures_volume_usd: Mapped[Decimal | None] = mapped_column(PreciseNumeric)

    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quality: Mapped[str] = mapped_column(String(24), default="ok", server_default="ok")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoNewsAssociation(Base):
    """Evidence-backed association between a stored news item and crypto.

    This is deliberately additive to ``NewsItem``.  Equity ticker/scope
    semantics remain authoritative for existing rows; crypto consumers use
    stable scope keys and explicit evidence in this join table.
    """

    __tablename__ = "crypto_news_associations"
    __table_args__ = (
        UniqueConstraint("association_key", name="uq_crypto_news_associations_key"),
        CheckConstraint(
            "scope_type IN ('crypto_asset', 'crypto_instrument', 'crypto_market')",
            name="ck_crypto_news_associations_scope",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_crypto_news_associations_confidence",
        ),
        CheckConstraint(
            "(scope_type = 'crypto_asset' AND asset_id IS NOT NULL AND instrument_id IS NULL) OR "
            "(scope_type = 'crypto_instrument' AND asset_id IS NULL AND instrument_id IS NOT NULL) OR "
            "(scope_type = 'crypto_market' AND asset_id IS NULL AND instrument_id IS NULL)",
            name="ck_crypto_news_associations_target",
        ),
        Index("ix_crypto_news_associations_news_scope", "news_item_id", "scope_type"),
        Index("ix_crypto_news_associations_asset", "asset_id"),
        Index("ix_crypto_news_associations_instrument", "instrument_id"),
        Index("ix_crypto_news_associations_scope_key", "scope_type", "scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    news_item_id: Mapped[int] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE")
    )
    scope_type: Mapped[str] = mapped_column(String(24))
    scope_key: Mapped[str] = mapped_column(String(192))
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_assets.id", ondelete="CASCADE")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(64))
    provider_entity_type: Mapped[str | None] = mapped_column(String(32))
    provider_entity_id: Mapped[str | None] = mapped_column(String(256))
    evidence_method: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    confidence: Mapped[float] = mapped_column(Float)
    association_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CryptoRegimeSnapshot(Base):
    """Immutable, versioned observational regime evidence for one instrument."""

    __tablename__ = "crypto_regime_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "as_of", "regime_version", "input_hash",
            name="uq_crypto_regime_snapshots_observation",
        ),
        UniqueConstraint("snapshot_key", name="uq_crypto_regime_snapshots_key"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_crypto_regime_snapshots_confidence",
        ),
        CheckConstraint(
            "coverage IS NULL OR (coverage >= 0 AND coverage <= 1)",
            name="ck_crypto_regime_snapshots_coverage",
        ),
        Index("ix_crypto_regime_snapshots_instrument_time", "instrument_id", "as_of"),
        Index("ix_crypto_regime_snapshots_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE")
    )
    regime_version: Mapped[str] = mapped_column(String(64))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(32))
    threshold_hash: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="persisted_derivatives", server_default="persisted_derivatives")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    snapshot_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CryptoRegimeValidationRun(Base):
    """Persisted, observational result/evidence payload for one validation run."""

    __tablename__ = "crypto_regime_validation_runs"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "validation_version", "input_hash",
            name="uq_crypto_regime_validation_runs_identity",
        ),
        UniqueConstraint("run_key", name="uq_crypto_regime_validation_runs_key"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_crypto_regime_validation_runs_status",
        ),
        CheckConstraint("evaluation_count >= 0", name="ck_crypto_regime_validation_runs_count"),
        Index("ix_crypto_regime_validation_runs_instrument_created", "instrument_id", "created_at"),
        Index("ix_crypto_regime_validation_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE")
    )
    validation_version: Mapped[str] = mapped_column(String(64))
    regime_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    horizons: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    evaluation_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str] = mapped_column(String(64))
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    run_key: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CryptoResearchReport(Base):
    """Persisted crypto research report envelope."""

    __tablename__ = "crypto_research_reports"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_crypto_research_reports_idempotency"),
        Index("ix_crypto_research_reports_asset_created", "asset_id", "created_at"),
        Index("ix_crypto_research_reports_instrument_created", "instrument_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_assets.id", ondelete="CASCADE")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    sources: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    evidence_manifest: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    coverage: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Crypto quant research (Goal 4 / WP 9-10).
#
# Quant rows intentionally keep their input/config snapshots in bounded JSON.
# Raw crypto tables remain the source of market truth; these rows are the
# immutable, replayable contract consumed by the later backtest service.
# ---------------------------------------------------------------------------


class QuantStrategyDefinition(Base):
    """Versioned, explicitly registered strategy definition."""

    __tablename__ = "quant_strategy_definitions"
    __table_args__ = (
        UniqueConstraint("strategy_key", "version", name="uq_quant_strategy_definitions_key_version"),
        CheckConstraint("status IN ('experimental', 'released', 'retired')", name="ck_quant_strategy_definitions_status"),
        Index("ix_quant_strategy_definitions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(64))
    # ``name`` is a stable display label, not a lookup key.
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    interval: Mapped[str] = mapped_column(String(8), default="1h", server_default="1h")
    universe: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    parameter_schema: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    default_parameters: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    config: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    config_hash: Mapped[str] = mapped_column(String(64))
    code_version: Mapped[str] = mapped_column(String(64), default="registry-v1", server_default="registry-v1")
    status: Mapped[str] = mapped_column(String(16), default="released", server_default="released")
    strategy_name = synonym("name")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuantFeatureSet(Base):
    """Versioned feature schema and its causal availability policy."""

    __tablename__ = "quant_feature_sets"
    __table_args__ = (
        UniqueConstraint("feature_set_key", "version", name="uq_quant_feature_sets_key_version"),
        CheckConstraint("status IN ('experimental', 'released', 'retired')", name="ck_quant_feature_sets_status"),
        CheckConstraint("availability_policy <> ''", name="ck_quant_feature_sets_policy_nonempty"),
        Index("ix_quant_feature_sets_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    feature_set_key: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    supported_intervals: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    feature_schema: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    input_declarations: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    input_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    availability_policy: Mapped[str] = mapped_column(
        String(32), default="source_causal_v1", server_default="source_causal_v1"
    )
    config_hash: Mapped[str] = mapped_column(String(64))
    code_version: Mapped[str] = mapped_column(String(64), default="features-v1", server_default="features-v1")
    status: Mapped[str] = mapped_column(String(16), default="released", server_default="released")
    key = synonym("feature_set_key")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuantFeatureValue(Base):
    """Append-only feature payload for one instrument/bar/vintage."""

    __tablename__ = "quant_feature_values"
    __table_args__ = (
        UniqueConstraint(
            "feature_set_id", "instrument_id", "interval", "bar_open_time_ms", "input_hash",
            name="uq_quant_feature_values_input_identity",
        ),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_quant_feature_values_coverage"),
        CheckConstraint("available_at >= as_of", name="ck_quant_feature_values_causal_order"),
        Index("ix_quant_feature_values_instrument_time", "instrument_id", "interval", "as_of"),
        Index("ix_quant_feature_values_feature_time", "feature_set_id", "interval", "as_of"),
        Index("ix_quant_feature_values_available_at", "available_at"),
        Index("ix_quant_feature_values_input_hash", "input_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    feature_set_id: Mapped[int] = mapped_column(
        ForeignKey("quant_feature_sets.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE"), index=True
    )
    interval: Mapped[str] = mapped_column(String(8))
    bar_open_time_ms: Mapped[int] = mapped_column(BigInteger)
    open_time_ms = synonym("bar_open_time_ms")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    coverage: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    quality: Mapped[str] = mapped_column(String(24), default="ok", server_default="ok")
    omissions: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    source_causal_version: Mapped[str] = mapped_column(
        String(32), default="source_causal_v1", server_default="source_causal_v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestRun(Base):
    """User-owned immutable manifest and lifecycle for one replay."""

    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'cancel_requested', 'completed', 'failed', 'cancelled')",
            name="ck_backtest_runs_status",
        ),
        CheckConstraint("initial_capital > 0", name="ck_backtest_runs_initial_capital_positive"),
        Index("ix_backtest_runs_user_status_created", "user_id", "status", "created_at"),
        Index("ix_backtest_runs_status_created", "status", "created_at"),
        Index("ix_backtest_runs_manifest_hash", "manifest_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_definition_id: Mapped[int] = mapped_column(
        ForeignKey("quant_strategy_definitions.id", ondelete="RESTRICT"), index=True
    )
    rerun_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    interval: Mapped[str] = mapped_column(String(8))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    config: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    manifest_hash: Mapped[str] = mapped_column(String(64))
    data_hash: Mapped[str] = mapped_column(String(64))
    feature_hash: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    initial_capital: Mapped[Decimal] = mapped_column(PreciseNumeric)
    seed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BacktestEquityPoint(Base):
    """One strategy-interval NAV observation."""

    __tablename__ = "backtest_equity_points"
    __table_args__ = (
        UniqueConstraint("run_id", "timestamp", name="uq_backtest_equity_points_run_time"),
        Index("ix_backtest_equity_points_run_time", "run_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time = synonym("timestamp")
    nav: Mapped[Decimal] = mapped_column(PreciseNumeric)
    cash: Mapped[Decimal] = mapped_column(PreciseNumeric)
    gross_exposure: Mapped[Decimal] = mapped_column(PreciseNumeric)
    drawdown: Mapped[Decimal] = mapped_column(PreciseNumeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestTrade(Base):
    """One deterministic simulated intent/fill with causal timestamps."""

    __tablename__ = "backtest_trades"
    __table_args__ = (
        Index("ix_backtest_trades_run_time", "run_id", "fill_time"),
        Index("ix_backtest_trades_instrument_time", "instrument_id", "fill_time"),
        CheckConstraint("side IN ('buy', 'sell', 'long', 'short')", name="ck_backtest_trades_side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_instruments.id", ondelete="CASCADE"), index=True
    )
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(PreciseNumeric)
    qty = synonym("quantity")
    price: Mapped[Decimal] = mapped_column(PreciseNumeric)
    fee: Mapped[Decimal] = mapped_column(PreciseNumeric, default=0, server_default="0")
    slippage: Mapped[Decimal] = mapped_column(PreciseNumeric, default=0, server_default="0")
    funding: Mapped[Decimal] = mapped_column(PreciseNumeric, default=0, server_default="0")
    realized_pnl: Mapped[Decimal] = mapped_column(PreciseNumeric, default=0, server_default="0")
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="filled", server_default="filled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



# Register integration-owned tables in the same metadata whenever core models
# are imported (tests, application runtime, and Alembic must see one graph).
from app.integrations.ibkr import db_models as _ibkr_db_models  # noqa: E402,F401
