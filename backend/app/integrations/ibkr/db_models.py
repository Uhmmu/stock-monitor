from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IbkrFlexSyncRun(Base):
    __tablename__ = "ibkr_flex_sync_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "source_hash", name="uq_ibkr_sync_user_source_hash"),
        Index("ix_ibkr_sync_user_completed", "user_id", "completed_at"),
        Index("uq_ibkr_sync_one_active_user", "user_id", unique=True,
              postgresql_where=text("status IN ('queued','running')"),
              sqlite_where=text("status IN ('queued','running')")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query_type: Mapped[str] = mapped_column(String(32), default="activity_statement")
    account_id: Mapped[str | None] = mapped_column(String(80), index=True)
    report_from_date: Mapped[date | None] = mapped_column(Date)
    report_to_date: Mapped[date | None] = mapped_column(Date)
    report_period: Mapped[str | None] = mapped_column(String(80))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="completed", index=True)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    raw_record_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_record_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    section_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(String(24), default="manual")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage: Mapped[str] = mapped_column(String(24), default="requested", index=True)
    archive_path: Mapped[str | None] = mapped_column(String(512))
    flex_reference_hint: Mapped[str | None] = mapped_column(String(24))
    import_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    reconciliation: Mapped[dict] = mapped_column(JSON, default=dict)
    propagation: Mapped[dict] = mapped_column(JSON, default=dict)
    error_stage: Mapped[str | None] = mapped_column(String(24))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IbkrFlexRecord(Base):
    __tablename__ = "ibkr_flex_records"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "section", "source_id", name="uq_ibkr_record_source"),
        Index("ix_ibkr_record_run_section_date", "sync_run_id", "section", "report_date"),
        Index("ix_ibkr_record_account_section", "account_id", "section"),
        Index("ix_ibkr_record_symbol_section", "symbol", "section"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(48), index=True)
    source_id: Mapped[str] = mapped_column(String(64))
    source_index: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[str | None] = mapped_column(String(80), index=True)
    symbol: Mapped[str | None] = mapped_column(String(48), index=True)
    conid: Mapped[str | None] = mapped_column(String(32), index=True)
    currency: Mapped[str | None] = mapped_column(String(16), index=True)
    asset_category: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    report_date: Mapped[date | None] = mapped_column(Date, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IbkrNormalizedCashFlow(Base):
    __tablename__ = "ibkr_normalized_cash_flows"
    __table_args__ = (
        UniqueConstraint("user_id", "source_record_id", "calculation_version", name="uq_ibkr_cash_flow_source_version"),
        Index("ix_ibkr_cash_flow_user_account_date", "user_id", "account_id", "flow_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(80), index=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_records.id", ondelete="CASCADE"), index=True)
    source_sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    flow_date: Mapped[date | None] = mapped_column(Date, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    normalized_category: Mapped[str] = mapped_column(String(32), index=True)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_rule: Mapped[str] = mapped_column(String(64))
    original_type: Mapped[str | None] = mapped_column(String(128))
    original_description: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    manual_override: Mapped[str | None] = mapped_column(String(32))
    calculation_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IbkrAccountDailyPerformance(Base):
    __tablename__ = "ibkr_account_daily_performance"
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "performance_date", "calculation_version", name="uq_ibkr_daily_perf_account_date_version"),
        Index("ix_ibkr_daily_perf_user_date", "user_id", "performance_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(String(80), index=True)
    performance_date: Mapped[date] = mapped_column(Date, index=True)
    base_currency: Mapped[str | None] = mapped_column(String(16))
    beginning_nav: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    ending_nav: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    beginning_cash: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    ending_cash: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    gross_position_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    external_deposits: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    external_withdrawals: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    net_external_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unrealized_pnl_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    dividend_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    interest_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    commissions: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    other_fees: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    fx_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    investment_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    cumulative_return: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    drawdown: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    max_drawdown_to_date: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    data_completeness: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    source_sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    calculation_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IbkrTradeRoundTrip(Base):
    __tablename__ = "ibkr_trade_round_trips"
    __table_args__ = (
        UniqueConstraint("user_id", "source_key", "calculation_version", name="uq_ibkr_round_trip_source_version"),
        Index("ix_ibkr_round_trip_user_symbol_closed", "user_id", "symbol", "closed_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(80), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    conid: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(48), index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    average_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    average_exit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    commissions: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    holding_days: Mapped[int | None] = mapped_column(Integer)
    matching_method: Mapped[str] = mapped_column(String(32))
    source_key: Mapped[str] = mapped_column(String(96))
    source_sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    calculation_version: Mapped[str] = mapped_column(String(32))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IbkrPositionPerformanceDaily(Base):
    __tablename__ = "ibkr_position_performance_daily"
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "performance_date", "conid", "calculation_version", name="uq_ibkr_position_perf_date_version"),
        Index("ix_ibkr_position_perf_user_date", "user_id", "performance_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(String(80), index=True)
    performance_date: Mapped[date] = mapped_column(Date, index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"), index=True)
    conid: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(48), index=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    opening_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    closing_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    net_trade_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    opening_market_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    closing_market_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    portfolio_weight: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unrealized_pnl_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    dividend_income: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    commissions: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    fx_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    total_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    contribution_to_portfolio_return: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    price_source: Mapped[str | None] = mapped_column(String(32))
    price_as_of: Mapped[date | None] = mapped_column(Date)
    data_completeness: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    source_sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    calculation_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IbkrDividendEvent(Base):
    __tablename__ = "ibkr_dividend_events"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", "calculation_version", name="uq_ibkr_dividend_event_version"),
        Index("ix_ibkr_dividend_user_pay_date", "user_id", "pay_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(80), index=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_records.id", ondelete="CASCADE"), index=True)
    source_sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    conid: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(48), index=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    ex_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date, index=True)
    gross_dividend: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    withholding_tax: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    net_dividend: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    status: Mapped[str] = mapped_column(String(24), index=True)
    event_key: Mapped[str] = mapped_column(String(96))
    calculation_version: Mapped[str] = mapped_column(String(32))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IbkrPortfolioAuthorityAudit(Base):
    __tablename__ = "ibkr_portfolio_authority_audits"
    __table_args__ = (Index("ix_ibkr_authority_audit_user_position", "user_id", "portfolio_position_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_position_id: Mapped[int] = mapped_column(ForeignKey("portfolio_positions.id", ondelete="CASCADE"), index=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("ibkr_flex_sync_runs.id", ondelete="CASCADE"), index=True)
    flex_record_id: Mapped[int | None] = mapped_column(ForeignKey("ibkr_flex_records.id", ondelete="SET NULL"), index=True)
    conflict_type: Mapped[str] = mapped_column(String(32), index=True)
    previous_source: Mapped[str | None] = mapped_column(String(32))
    previous_value: Mapped[str | None] = mapped_column(Text)
    authoritative_value: Mapped[str | None] = mapped_column(Text)
    application_status: Mapped[str] = mapped_column(String(24))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
