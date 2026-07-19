import enum
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_20m: Mapped[float | None] = mapped_column(Float)
    threshold_1h: Mapped[float | None] = mapped_column(Float)
    threshold_day: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "quote_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[float] = mapped_column(Float)
    previous_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="yfinance")


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
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(ForeignKey("investigations.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str | None] = mapped_column(String(256))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
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
    source: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_model: Mapped[str | None] = mapped_column(String(128))
    ai_summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class TradeLog(Base):
    __tablename__ = 'trade_logs'
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
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_model: Mapped[str | None] = mapped_column(String(128))
    ai_summary_input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
