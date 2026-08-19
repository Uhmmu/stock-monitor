from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.services.portfolio.investment_ledger import (
    overview as ledger_overview,
    performance_series as ledger_performance,
    position_detail as ledger_position_detail,
    position_summaries as ledger_positions,
    return_attribution as ledger_attribution,
    transaction_events as ledger_transactions,
)
from app.services.portfolio.portfolio_health import build_health
from app.services.price_snapshots import (
    get_latest_persisted_price_snapshot,
    price_snapshot_out,
    snapshot_freshness,
)

from .enums import FreshnessStatus, ResearchErrorCode, SourceAuthority, SourceType, WarningSeverity
from .exceptions import ResearchError
from .freshness import calculate_freshness, unknown_freshness
from .pagination import page_window, validate_date_range
from .repositories import ResearchRepository
from .registry import RESEARCH_DOMAINS, RESEARCH_VERSION
from .schemas import ResearchFreshness, ResearchMeta, ResearchResponse, ResearchWarning
from .security import normalize_symbol, resolve_safe_file, safe_external_url
from .source_factory import source


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (datetime, date)): return value
    return value


def _bounded(value: Any, *, depth: int = 0) -> Any:
    """Bound persisted provider JSON without exposing arbitrary huge payloads."""
    if depth > 4: return None
    if isinstance(value, dict):
        blocked = {"raw_payload", "response_json", "tool_results", "prompt", "credentials", "authorization"}
        return {str(k): _bounded(v, depth=depth + 1) for k, v in list(value.items())[:100] if str(k).lower() not in blocked}
    if isinstance(value, list): return [_bounded(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str): return value[:4000]
    return _json_value(value)


class ResearchGateway:
    def __init__(self, db: Session, user: User, request_id: str | None = None, request: Any | None = None):
        self.db, self.user = db, user
        self.repo = ResearchRepository(db)
        self.request_id = request_id or str(uuid4())
        self.request = request

    def response(self, data: Any, *, sources=None, freshness=None, warnings=None, symbol=None,
                 symbols=None, page=None, page_size=None, total=None) -> ResearchResponse[Any]:
        source_rows, warning_rows = sources or [], warnings or []
        if self.request is not None:
            self.request.state.research_result_count = len(data) if isinstance(data, list) else (0 if data is None else 1)
            self.request.state.research_source_types = sorted({str(item.source_type) for item in source_rows})
            self.request.state.research_warning_codes = [item.code for item in warning_rows]
        return ResearchResponse(
            data=data, sources=source_rows, freshness=freshness or unknown_freshness("no dated source rows"), warnings=warning_rows,
            meta=ResearchMeta(request_id=self.request_id, generated_at=datetime.now(UTC), symbol=symbol,
                              symbols=symbols or ([symbol] if symbol else []), page=page, page_size=page_size, total=total),
        )

    def capabilities(self):
        return self.response(
            {"domains": list(RESEARCH_DOMAINS), "version": RESEARCH_VERSION, "read_only": True},
            sources=[source(SourceType.capability_registry, "v1", "Research Gateway capability registry", authority=SourceAuthority.derived, locator="research://capabilities/v1")],
            freshness=calculate_freshness("capability_registry", datetime.now(UTC), "runtime capability registry"),
        )

    def _portfolio(self, portfolio_id: int | None = None):
        row = self.repo.portfolio(self.user.id, portfolio_id)
        if not row:
            code = ResearchErrorCode.forbidden_resource if portfolio_id is not None else ResearchErrorCode.not_found
            raise ResearchError(code, "portfolio is unavailable", status_code=404)
        return row

    def portfolio_summary(self, portfolio_id: int | None = None):
        portfolio = self._portfolio(portfolio_id)
        summary = ledger_overview(self.db, portfolio, cached_fx_only=True)
        profile = self.repo.strategy_profile(self.user.id)
        positions = summary.pop("positions")
        maximum = max(positions, key=lambda x: x.get("portfolio_weight") or -1, default=None)
        concentration = build_health(self.db, portfolio).get("concentration") or {}
        data = {
            **summary, "portfolio_name": portfolio.name, "cash_balance": portfolio.cash_balance,
            "cash_currency": portfolio.base_currency,
            "largest_position": ({"symbol": maximum["symbol"], "weight_percent": maximum.get("portfolio_weight")} if maximum else None),
            "concentration_summary": {"hhi": concentration.get("hhi"), "top_three_weight_percent": concentration.get("top_three_weight"),
                                      "sector_weights": (concentration.get("sector_weights") or [])[:10]},
            "risk_profile": ({"strategy_type": profile.strategy_type, "investment_horizon": profile.investment_horizon,
                              "risk_tolerance": profile.risk_tolerance, "max_single_position_percent": profile.max_single_position,
                              "max_theme_exposure_percent": profile.max_theme_exposure} if profile else None),
        }
        as_of = max((p.updated_at for p in self.repo.positions(portfolio.id, 0, 100, "updated_at")[0]), default=portfolio.updated_at)
        warnings = []
        if summary.get("has_unconverted_positions"):
            warnings.append(ResearchWarning(code="DATA_INCOMPLETE", message="Some positions lack a cached FX conversion and are excluded from aggregates."))
        return self.response(data, sources=[source(SourceType.portfolio, portfolio.id, portfolio.name, authority=SourceAuthority.user, retrieved_at=as_of, locator=f"research://portfolio/{portfolio.id}")],
                             freshness=calculate_freshness("portfolio_position", as_of, "latest persisted portfolio position update"), warnings=warnings)

    def portfolio_positions(self, portfolio_id: int | None, page: int, page_size: int, sort: str):
        if sort not in {"symbol", "symbol_desc", "updated_at", "quantity"}:
            raise ResearchError(ResearchErrorCode.invalid_parameter, "unsupported position sort", field="sort", status_code=422)
        portfolio = self._portfolio(portfolio_id); offset, limit = page_window(page, page_size)
        rows, total = self.repo.positions(portfolio.id, offset, limit, sort)
        summary_map = {item["symbol"]: item for item in ledger_positions(self.db, portfolio, cached_fx_only=True)}
        data = [summary_map.get(row.symbol, {"symbol": row.symbol, "total_quantity": row.total_quantity,
                "average_cost": row.average_cost, "total_cost": row.total_cost, "currency": row.currency}) for row in rows]
        sources = [source(SourceType.portfolio_position, f"{portfolio.id}:{r.symbol}", f"{r.symbol} portfolio position", symbol=r.symbol, authority=SourceAuthority.user, retrieved_at=r.updated_at, locator=f"research://portfolio/{portfolio.id}/positions/{r.symbol}") for r in rows]
        as_of = max((r.updated_at for r in rows), default=portfolio.updated_at)
        return self.response(data, sources=sources, freshness=calculate_freshness("portfolio_position", as_of, "latest returned position update"), page=page, page_size=page_size, total=total)

    def portfolio_position(self, symbol: str, portfolio_id: int | None):
        symbol = normalize_symbol(symbol); portfolio = self._portfolio(portfolio_id)
        row = self.repo.position(portfolio.id, symbol)
        if not row: raise ResearchError(ResearchErrorCode.not_found, "portfolio position was not found", status_code=404)
        view = ledger_position_detail(self.db, portfolio, symbol) or {}
        view["open_lot_count"] = len(view.get("open_lots", []))
        return self.response(view, sources=[source(SourceType.portfolio_position, f"{portfolio.id}:{symbol}", f"{symbol} portfolio position", symbol=symbol, authority=SourceAuthority.user, retrieved_at=row.updated_at, locator=f"research://portfolio/{portfolio.id}/positions/{symbol}")],
                             freshness=calculate_freshness("portfolio_position", row.updated_at, "persisted position and cached quote"), symbol=symbol)

    def trades(self, portfolio_id: int | None, symbol: str | None, start: date | None, end: date | None, page: int, page_size: int):
        validate_date_range(start, end); portfolio = self._portfolio(portfolio_id); offset, limit = page_window(page, page_size)
        symbol = normalize_symbol(symbol) if symbol else None
        all_rows = ledger_transactions(self.db, portfolio, symbol=symbol, start=start, end=end)
        rows, total = all_rows[offset:offset + limit], len(all_rows)
        sources = [source(
            SourceType.trade_transaction, row["event_id"], f"{row['event_type']} {row.get('symbol') or ''}",
            symbol=row.get("symbol"), provider=row["source_type"],
            authority=SourceAuthority.primary if row["authority_source"] == "ibkr_flex" else SourceAuthority.user,
            published_at=row.get("occurred_at"), locator=f"research://portfolio/{portfolio.id}/ledger/{row['event_id']}",
        ) for row in rows]
        as_of = ledger_overview(self.db, portfolio, cached_fx_only=True).get("latest_sync_at") or portfolio.updated_at
        return self.response(rows, sources=sources, freshness=calculate_freshness(
            "portfolio_position", as_of, "latest unified authoritative investment ledger"
        ), symbol=symbol, page=page, page_size=page_size, total=total)

    def portfolio_performance(self, portfolio_id: int | None, start: date | None, end: date | None):
        portfolio = self._portfolio(portfolio_id)
        data = ledger_performance(self.db, portfolio, start=start, end=end)
        as_of = data.get("latest_sync_at")
        warnings = [ResearchWarning(code="DATA_INCOMPLETE", message=value) for value in data.get("warnings", [])]
        return self.response(data, sources=[source(
            SourceType.portfolio, portfolio.id, "IBKR account performance and cash-flow-adjusted returns",
            provider="IBKR Flex + stock-monitor derived", authority=SourceAuthority.derived,
            retrieved_at=as_of, locator=f"research://portfolio/{portfolio.id}/performance",
        )], freshness=calculate_freshness("portfolio_position", as_of, "latest unified ledger performance"), warnings=warnings)

    def portfolio_attribution(self, portfolio_id: int | None, start: date | None, end: date | None):
        portfolio = self._portfolio(portfolio_id)
        data = ledger_attribution(self.db, portfolio, start=start, end=end)
        as_of = data.get("latest_sync_at")
        return self.response(data, sources=[source(
            SourceType.portfolio, portfolio.id, "Position return attribution",
            provider="IBKR facts + stock-monitor derived", authority=SourceAuthority.derived,
            retrieved_at=as_of, locator=f"research://portfolio/{portfolio.id}/attribution",
        )], freshness=calculate_freshness("portfolio_position", as_of, "latest ledger attribution"))

    def position_ledger_section(self, symbol: str, portfolio_id: int | None, section: str):
        symbol = normalize_symbol(symbol); portfolio = self._portfolio(portfolio_id)
        detail = ledger_position_detail(self.db, portfolio, symbol)
        if detail is None:
            raise ResearchError(ResearchErrorCode.not_found, "portfolio position was not found", status_code=404)
        data = detail if section == "all" else detail.get(section)
        return self.response(data, sources=[source(
            SourceType.portfolio_position, f"{portfolio.id}:{symbol}:{section}", f"{symbol} {section}",
            symbol=symbol, provider="unified investment ledger", authority=SourceAuthority.derived,
            retrieved_at=detail.get("latest_sync_at"), locator=f"research://portfolio/{portfolio.id}/positions/{symbol}/{section}",
        )], freshness=calculate_freshness("portfolio_position", detail.get("latest_sync_at"), "latest position ledger"), symbol=symbol)

    @staticmethod
    def _news_data(r, detail=False):
        data = {"news_id": r.id, "symbol": None if r.scope == "market" else r.ticker, "symbols": r.symbols or [], "scope": r.scope,
                "title": r.title, "translated_title": r.translated_title, "summary": r.summary, "ai_summary": r.ai_summary,
                "published_at": r.published_at, "found_at": r.found_at, "provider": r.provider, "source": r.source, "url": safe_external_url(r.url),
                "topic": r.topic, "news_type": r.news_type, "importance_score": r.importance_score,
                "quality_score": r.quality_score, "relevance_score": r.relevance_score, "sentiment_score": r.sentiment_score,
                "content_fetch_method": r.content_fetch_method, "content_fetch_status": r.content_fetch_status,
                "content_fetch_quality": r.content_fetch_quality, "content_fetched_at": r.content_fetched_at,
                "ai_analysis": _bounded(r.ai_analysis), "ai_event_type": r.ai_event_type,
                "ai_sentiment": r.ai_sentiment, "ai_importance": r.ai_importance,
                "ai_market_impact": _bounded(r.ai_market_impact), "ai_summary_model": r.ai_summary_model,
                "ai_summary_version": r.ai_summary_version, "ai_summary_created_at": r.ai_summary_created_at,
                "ai_summary_generated_at": r.ai_summary_created_at, "ai_summary_requested_at": r.ai_summary_requested_at,
                "ai_summary_last_attempt_at": r.ai_summary_last_attempt_at, "ai_summary_status": r.ai_summary_status}
        if detail:
            data.update({
                "article_content": _bounded(r.article_content),
                "content_final_url": safe_external_url(r.content_final_url),
                "content_fetch_error_code": r.content_fetch_error_code,
            })
            data["metadata"] = _bounded({k: v for k, v in (r.raw_payload or {}).items() if k in {"author", "authors", "language", "category", "categories", "source", "tickers"}})
        return data

    def news(self, symbols: list[str], query: str | None, start: date | None, end: date | None, provider: str | None,
             include_market: bool, page: int, page_size: int, industry: str | None = None,
             event_type: str | None = None, sentiment: str | None = None, min_importance: int | None = None):
        validate_date_range(start, end); clean = list(dict.fromkeys(normalize_symbol(s) for s in symbols)); offset, limit = page_window(page, page_size)
        rows, total = self.repo.news(clean, query, start, end, provider, include_market, offset, limit,
                                     industry, event_type, sentiment, min_importance)
        sources = [source(SourceType.news, r.id, r.title, symbol=None if r.scope == "market" else r.ticker, provider=r.provider,
                          authority=SourceAuthority.secondary, published_at=r.published_at, retrieved_at=r.found_at, url=r.url, locator=f"research://news/{r.id}") for r in rows]
        warnings = [ResearchWarning(code="DATA_INCOMPLETE", message="No persisted news matched the requested filters.", severity=WarningSeverity.info)] if not rows else []
        return self.response([self._news_data(r) for r in rows], sources=sources, freshness=calculate_freshness("news", max((r.found_at for r in rows), default=None), "latest persisted matching news item"), warnings=warnings, symbols=clean, page=page, page_size=page_size, total=total)

    def news_detail(self, news_id: int):
        row = self.repo.news_item(news_id)
        if not row: raise ResearchError(ResearchErrorCode.not_found, "news item was not found", status_code=404)
        symbol = None if row.scope == "market" else row.ticker
        return self.response(self._news_data(row, True), sources=[source(SourceType.news, row.id, row.title, symbol=symbol, provider=row.provider, authority=SourceAuthority.secondary, published_at=row.published_at, retrieved_at=row.found_at, url=row.url, locator=f"research://news/{row.id}")], freshness=calculate_freshness("news", row.found_at, "news retrieval time"), symbol=symbol)

    def archives(self, symbol: str, period: str, start: date | None, end: date | None, page: int, page_size: int):
        if period not in {"daily", "weekly"}: raise ResearchError(ResearchErrorCode.invalid_parameter, "period must be daily or weekly", field="period", status_code=422)
        validate_date_range(start, end); symbol = normalize_symbol(symbol); offset, limit = page_window(page, page_size)
        rows, total = self.repo.archives(symbol, period, start, end, offset, limit)
        data, sources = [], []
        for r in rows:
            item = {"archive_id": r.id, "symbol": r.ticker, "period": period, "content": r.content, "model": r.model, "version": r.version, "updated_at": r.updated_at}
            if period == "daily": item.update({"start_date": r.market_date, "end_date": r.market_date, "included_news_ids": r.included_news_ids})
            else: item.update({"start_date": r.week_start, "end_date": r.week_end, "included_dates": r.included_dates})
            data.append(item); sources.append(source(SourceType.news_archive, f"{period}:{r.id}", f"{symbol} {period} news archive", symbol=symbol, provider=r.model, authority=SourceAuthority.derived, retrieved_at=r.updated_at, locator=f"research://news/archives/{period}/{r.id}"))
        return self.response(data, sources=sources, freshness=calculate_freshness("news", max((r.updated_at for r in rows), default=None), "latest persisted archive update"), symbol=symbol, page=page, page_size=page_size, total=total)

    @staticmethod
    def _filing(r):
        return {"filing_id": r.id, "symbol": r.ticker, "form_type": r.form, "form_label": r.form_label, "filed_at": r.filing_date,
                "accession_number": r.accession_number, "report_period": r.report_date, "title": r.form_label,
                "official_url": safe_external_url(r.filing_url), "items": r.items, "event_labels": r.event_labels, "priority": r.priority,
                "local_parse_status": "available" if r.raw_payload else "metadata_only", "local_cache_available": bool(r.primary_document), "synced_at": r.synced_at}

    def sec_filings(self, symbol, form, start, end, page, page_size):
        validate_date_range(start, end); symbol = normalize_symbol(symbol) if symbol else None; offset, limit = page_window(page, page_size)
        rows, total = self.repo.sec_filings(symbol, form, start, end, offset, limit)
        sources = [source(SourceType.sec_filing, r.id, f"{r.form} {r.ticker} filing", symbol=r.ticker, provider="SEC EDGAR", authority=SourceAuthority.official, published_at=r.filing_date, retrieved_at=r.synced_at, url=r.filing_url, locator=f"research://sec/filings/{r.id}") for r in rows]
        return self.response([self._filing(r) for r in rows], sources=sources, freshness=calculate_freshness("sec_filing", max((r.synced_at for r in rows), default=None), "SEC filings remain authoritative historical records"), symbol=symbol, page=page, page_size=page_size, total=total)

    def sec_filing(self, filing_id: int):
        row = self.repo.sec_filing(filing_id)
        if not row: raise ResearchError(ResearchErrorCode.not_found, "SEC filing was not found", status_code=404)
        data = self._filing(row); data["metadata"] = _bounded({k: v for k, v in (row.raw_payload or {}).items() if k in {"description", "acceptanceDateTime", "size", "isInlineXBRL", "isXBRL"}})
        return self.response(data, sources=[source(SourceType.sec_filing, row.id, f"{row.form} {row.ticker} filing", symbol=row.ticker, provider="SEC EDGAR", authority=SourceAuthority.official, published_at=row.filing_date, retrieved_at=row.synced_at, url=row.filing_url, locator=f"research://sec/filings/{row.id}")], freshness=calculate_freshness("sec_filing", row.synced_at, "SEC filing historical record"), symbol=row.ticker)

    def sec_events(self, symbol, event_type, start, end, page, page_size):
        validate_date_range(start, end); symbol = normalize_symbol(symbol) if symbol else None; offset, limit = page_window(page, page_size)
        rows, total = self.repo.sec_events(symbol, event_type, start, end, offset, limit)
        data = [{"event_id": r.id, "symbol": r.ticker, "event_type": r.item_code, "event_label": r.item_label, "form_type": r.form,
                 "text_summary": (r.text[:2000] if r.text else None), "summary_zh": r.summary_zh, "summary_status": r.summary_status,
                 "accession_number": r.accession_number, "filed_at": r.filing_date, "official_url": safe_external_url(r.filing_url), "priority": r.priority} for r in rows]
        sources = [source(SourceType.sec_event, r.id, f"{r.item_code} {r.ticker} SEC event", symbol=r.ticker, provider="SEC EDGAR", authority=SourceAuthority.official, published_at=r.filing_date, retrieved_at=r.synced_at, url=r.filing_url, locator=f"research://sec/events/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max((r.synced_at for r in rows), default=None), "SEC event historical record"), symbol=symbol, page=page, page_size=page_size, total=total)

    def sec_periods(self, symbol, concept, period_type, start, end, limit):
        validate_date_range(start, end); symbol = normalize_symbol(symbol)
        if period_type not in {None, "annual", "quarterly"}:
            raise ResearchError(ResearchErrorCode.invalid_parameter, "period_type must be annual or quarterly", field="period_type", status_code=422)
        allowed = {"revenue", "net_income", "operating_income", "gross_profit", "eps_basic", "eps_diluted", "cash_and_equivalents", "total_debt", "shares_outstanding", "operating_cash_flow"}
        if concept and concept not in allowed: raise ResearchError(ResearchErrorCode.invalid_parameter, "unsupported financial concept", field="concept", status_code=422)
        rows = self.repo.sec_financial_periods(symbol, concept, period_type, start, end, min(limit, 100))
        data = []
        for r in rows:
            metrics = {key: {"value": getattr(r, key), "unit": "currency" if key not in {"eps_basic", "eps_diluted", "shares_outstanding"} else ("currency_per_share" if key.startswith("eps") else "shares")} for key in allowed if getattr(r, key) is not None}
            if concept: metrics = {concept: metrics[concept]} if concept in metrics else {}
            data.append({"period_id": r.id, "symbol": r.ticker, "fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period,
                         "form_type": r.form, "period_end": r.period_end, "filed_at": r.filed_at, "currency": r.currency,
                         "metrics": metrics, "accession_number": r.accession_number, "source": r.source, "synced_at": r.synced_at})
        sources = [source(SourceType.sec_financial_period, r.id, f"{r.ticker} {r.fiscal_period} SEC financials", symbol=r.ticker, provider="SEC XBRL", authority=SourceAuthority.official, published_at=r.filed_at, retrieved_at=r.synced_at, locator=f"research://sec/financial-periods/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("financial_statement", max((r.synced_at for r in rows), default=None), "latest persisted SEC XBRL period"), symbol=symbol, total=len(rows))

    def insider_trades(self, symbol, start, end, transaction_type, page, page_size):
        validate_date_range(start, end); symbol = normalize_symbol(symbol) if symbol else None; offset, limit = page_window(page, page_size)
        rows, total = self.repo.insider_trades(symbol, transaction_type, start, end, offset, limit)
        data = [{"trade_id": r.id, "symbol": r.ticker, "insider_name": r.insider_name, "insider_title": r.insider_title,
                 "transaction_date": r.transaction_date, "transaction_type": r.transaction_code, "shares": r.shares,
                 "price_usd_per_share": r.price, "value_usd": r.value, "shares_owned_after": r.shares_owned_after,
                 "flag": r.flag, "official_url": safe_external_url(r.filing_url), "synced_at": r.synced_at} for r in rows]
        sources = [source(SourceType.sec_insider_trade, r.id, f"{r.ticker} Form 4 transaction", symbol=r.ticker, provider="SEC EDGAR", authority=SourceAuthority.official, published_at=r.transaction_date, retrieved_at=r.synced_at, url=r.filing_url, locator=f"research://sec/insider-trades/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max((r.synced_at for r in rows), default=None), "Form 4 historical records"), symbol=symbol, page=page, page_size=page_size, total=total)

    def institutional_holdings(self, symbol, report_period, institution, page, page_size):
        symbol = normalize_symbol(symbol) if symbol else None; offset, limit = page_window(page, page_size)
        rows, total = self.repo.institutional_holdings(symbol, report_period, institution, offset, limit)
        data = [{"holding_id": r.id, "symbol": r.ticker, "institution": r.manager_name, "report_period": r.report_period,
                 "filing_date": r.filing_date, "cusip": r.cusip, "value_usd": r.value_usd, "shares": r.shares,
                 "put_call": r.put_call, "accession_number": r.accession_number, "synced_at": r.synced_at} for r in rows]
        sources = [source(SourceType.sec_13f_holding, r.id, f"{r.manager_name} {r.ticker} 13F holding", symbol=r.ticker, provider="SEC 13F", authority=SourceAuthority.official, published_at=r.filing_date, retrieved_at=r.synced_at, locator=f"research://sec/institutional-holdings/{r.id}") for r in rows]
        warnings = [ResearchWarning(code="DELAYED_REGULATORY_DATA", message="13F holdings are quarterly filings and are not real-time positions.", severity=WarningSeverity.info)]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max((r.synced_at for r in rows), default=None), "13F historical filing data"), warnings=warnings, symbol=symbol, page=page, page_size=page_size, total=total)

    def company_profile(self, symbol: str):
        symbol = normalize_symbol(symbol); company, stock, security = self.repo.company(symbol)
        if not any((company, stock, security)):
            raise ResearchError(ResearchErrorCode.not_found, "company profile was not found", status_code=404)
        data = {
            "symbol": symbol,
            "company_name": (company.company_name if company else None) or (stock.company_name if stock else None) or (security.display_name if security else None),
            "website": company.website if company else None, "ceo": company.ceo if company else None,
            "sector": (company.sector if company else None) or (stock.official_sector if stock else None),
            "industry": (company.industry if company else None) or (stock.official_industry if stock else None),
            "country": company.country if company else (security.country_code if security else None),
            "exchange": company.exchange if company else (security.exchange_code if security else None),
            "currency": company.currency if company else (security.currency if security else None),
            "instrument_type": security.instrument_type if security else None, "isin": security.isin if security else None,
            "ipo_date": company.ipo_date if company else None, "employee_count": company.employee_count if company else None,
            "description": (company.description_zh or company.description_en) if company else None,
        }
        as_of = company.profile_fetched_at if company else (stock.updated_at if stock else security.updated_at)
        provider = company.profile_source if company else (stock.source if stock else "security_registry")
        return self.response(data, sources=[source(SourceType.company_profile, symbol, f"{symbol} company profile", symbol=symbol, provider=provider, authority=SourceAuthority.primary, retrieved_at=as_of, locator=f"research://companies/{symbol}/profile")], freshness=calculate_freshness("financial_statement", as_of, "latest persisted company profile"), symbol=symbol)

    def financial_summary(self, symbol: str):
        symbol = normalize_symbol(symbol)
        quarterlies = self.repo.quarterly_financials(symbol)
        sec_rows = self.repo.sec_periods_for_summary(symbol)
        statements = self.repo.statement_snapshots(symbol, "quarterly", 8)
        records = []
        for r in quarterlies:
            records.append({"period": r.period_end, "period_type": "quarterly", "fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period,
                "currency": r.currency, "source": r.source, "as_of": r.synced_at,
                "metrics": {"revenue": {"value": r.revenue, "unit": "currency"}, "operating_income": {"value": r.operating_income, "unit": "currency"},
                    "net_income": {"value": r.net_income, "unit": "currency"}, "eps": {"value": r.eps, "unit": "currency_per_share"},
                    "free_cash_flow": {"value": r.free_cash_flow, "unit": "currency"}, "operating_cash_flow": {"value": r.operating_cash_flow, "unit": "currency"},
                    "gross_margin": {"value": r.gross_margin, "unit": "percent"}, "net_margin": {"value": r.net_margin, "unit": "percent"}}})
        by_period = {(r.fiscal_year, r.fiscal_period): r for r in quarterlies}
        for item in records:
            if item["source"] not in {r.source for r in quarterlies}:
                continue
            prior = by_period.get((item["fiscal_year"] - 1, item["fiscal_period"]))
            current = by_period.get((item["fiscal_year"], item["fiscal_period"]))
            if prior and current:
                for key in ("revenue", "operating_income", "net_income", "eps", "free_cash_flow"):
                    old, new = getattr(prior, key), getattr(current, key)
                    if old not in (None, 0) and new is not None:
                        item["metrics"][f"{key}_yoy"] = {"value": round((new - old) / abs(old) * 100, 4), "unit": "percent"}
        for r in sec_rows:
            records.append({"period": r.period_end, "period_type": "quarterly" if r.fiscal_period != "FY" else "annual", "fiscal_year": r.fiscal_year,
                "fiscal_period": r.fiscal_period, "currency": r.currency, "source": r.source, "as_of": r.synced_at,
                "metrics": {"revenue": {"value": r.revenue, "unit": "currency"}, "operating_income": {"value": r.operating_income, "unit": "currency"},
                    "net_income": {"value": r.net_income, "unit": "currency"}, "eps_basic": {"value": r.eps_basic, "unit": "currency_per_share"},
                    "cash": {"value": r.cash_and_equivalents, "unit": "currency"}, "total_debt": {"value": r.total_debt, "unit": "currency"},
                    "operating_cash_flow": {"value": r.operating_cash_flow, "unit": "currency"}}})
        records.sort(key=lambda x: x["period"] or date.min, reverse=True)
        sources = [source(SourceType.financial_statement, f"quarterly:{r.id}", f"{symbol} {r.fiscal_period} financials", symbol=symbol, provider=r.source, authority=SourceAuthority.primary, published_at=r.filed_at, retrieved_at=r.synced_at, locator=f"research://companies/{symbol}/financials/{r.id}") for r in quarterlies]
        sources += [source(SourceType.sec_financial_period, r.id, f"{symbol} {r.fiscal_period} SEC financials", symbol=symbol, provider="SEC XBRL", authority=SourceAuthority.official, published_at=r.filed_at, retrieved_at=r.synced_at, locator=f"research://sec/financial-periods/{r.id}") for r in sec_rows]
        as_of = max([r.synced_at for r in quarterlies] + [r.synced_at for r in sec_rows] + [r.synced_at for r in statements], default=None)
        warnings = [] if records else [ResearchWarning(code="DATA_INCOMPLETE", message="No persisted financial periods are available for this symbol.")]
        return self.response({"symbol": symbol, "periods": records[:12]}, sources=sources[:24], freshness=calculate_freshness("financial_statement", as_of, "latest persisted financial data; report period also shown per row"), warnings=warnings, symbol=symbol)

    def financial_statements(self, symbol: str, statement: str, period_type: str, limit: int):
        symbol = normalize_symbol(symbol)
        if statement not in {"income", "balance_sheet", "cash_flow"}: raise ResearchError(ResearchErrorCode.invalid_parameter, "statement must be income, balance_sheet, or cash_flow", field="statement", status_code=422)
        if period_type not in {"annual", "quarterly"}: raise ResearchError(ResearchErrorCode.invalid_parameter, "period_type must be annual or quarterly", field="period_type", status_code=422)
        rows = self.repo.statement_snapshots(symbol, period_type, min(limit, 20)); attr = "income_statement" if statement == "income" else statement
        allowed = {
            "income": {"Total Revenue", "Operating Revenue", "Gross Profit", "Operating Income", "Net Income", "Diluted EPS", "Basic EPS", "EBITDA", "Pretax Income", "Tax Provision"},
            "balance_sheet": {"Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Total Assets", "Current Assets", "Total Liabilities Net Minority Interest", "Current Liabilities", "Total Debt", "Stockholders Equity", "Working Capital"},
            "cash_flow": {"Operating Cash Flow", "Free Cash Flow", "Capital Expenditure", "Investing Cash Flow", "Financing Cash Flow", "End Cash Position", "Depreciation And Amortization", "Stock Based Compensation"},
        }[statement]
        data = []
        for r in rows:
            payload = getattr(r, attr) or {}; metrics = {str(k): {"value": _json_value(v), "unit": "currency"} for k, v in payload.items() if str(k) in allowed}
            data.append({"snapshot_id": r.id, "symbol": symbol, "statement": statement, "period_type": period_type,
                         "period": r.period_end, "fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period,
                         "currency": r.currency, "metrics": metrics, "source": r.source, "as_of": r.synced_at})
        sources = [source(SourceType.financial_statement, r.id, f"{symbol} {statement} {r.period_end}", symbol=symbol, provider=r.source, authority=SourceAuthority.primary, published_at=r.period_end, retrieved_at=r.synced_at, locator=f"research://companies/{symbol}/financial-statements/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("financial_statement", max((r.synced_at for r in rows), default=None), "latest persisted statement snapshot; period shown per row"), symbol=symbol, total=len(rows))

    @staticmethod
    def _valuation(r, detail: bool):
        payload = r.payload or {}; keys = {"company", "classification", "price", "currency", "model_signals", "summary", "valuation_range", "confidence", "status"}
        if detail: keys |= {"inputs", "evidence", "health", "weights", "weight_details", "growth", "graham", "dcf", "dcf_scenarios", "relative", "reverse_dcf", "dividend_discount", "valuation", "consensus", "model_conflict"}
        return {"snapshot_id": r.id, "symbol": r.ticker, "snapshot_date": r.snapshot_date,
                "valuation": _bounded({k: payload[k] for k in keys if k in payload}),
                "existing_generated_content": ({"opinion": r.ai_opinion, "model": r.ai_model} if r.ai_opinion else None),
                "data_version": r.source_version, "generated_at": r.updated_at}

    def valuation(self, symbol: str):
        symbol = normalize_symbol(symbol); rows = self.repo.valuations(symbol)
        if not rows: raise ResearchError(ResearchErrorCode.not_found, "valuation snapshot was not found", status_code=404)
        r = rows[0]
        return self.response(self._valuation(r, True), sources=[source(SourceType.valuation_snapshot, r.id, f"{symbol} valuation snapshot {r.snapshot_date}", symbol=symbol, provider=r.source_version, authority=SourceAuthority.derived, published_at=r.snapshot_date, retrieved_at=r.updated_at, locator=f"research://companies/{symbol}/valuation/{r.id}")], freshness=calculate_freshness("valuation_snapshot", r.updated_at, "latest daily valuation snapshot"), symbol=symbol)

    def valuation_history(self, symbol: str, start: date | None, end: date | None, limit: int):
        validate_date_range(start, end); symbol = normalize_symbol(symbol); rows = self.repo.valuations(symbol, start, end, min(limit, 366))
        sources = [source(SourceType.valuation_snapshot, r.id, f"{symbol} valuation snapshot {r.snapshot_date}", symbol=symbol, provider=r.source_version, authority=SourceAuthority.derived, published_at=r.snapshot_date, retrieved_at=r.updated_at, locator=f"research://companies/{symbol}/valuation/{r.id}") for r in rows]
        return self.response([self._valuation(r, False) for r in rows], sources=sources, freshness=calculate_freshness("valuation_snapshot", max((r.updated_at for r in rows), default=None), "latest matching valuation snapshot"), symbol=symbol, total=len(rows))

    def peers(self, symbol: str):
        symbol = normalize_symbol(symbol); rows, excluded = self.repo.peers(symbol)
        data = {"symbol": symbol, "peers": [{"symbol": r.peer_ticker, "source_type": r.source, "enabled": r.enabled, "display_order": r.display_order} for r in rows],
                "excluded": [{"symbol": r.peer_ticker, "reason": "user_excluded"} for r in excluded]}
        sources = [source(SourceType.peer_relation, r.id, f"{symbol} peer {r.peer_ticker}", symbol=symbol, provider=r.source, authority=SourceAuthority.user if r.source == "manual" else SourceAuthority.derived, retrieved_at=r.updated_at, locator=f"research://companies/{symbol}/peers/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("financial_statement", max((r.updated_at for r in rows), default=None), "latest persisted peer relation"), symbol=symbol)

    def price_latest(self, symbol: str):
        symbol = normalize_symbol(symbol); r = get_latest_persisted_price_snapshot(self.db, symbol)
        if not r: raise ResearchError(ResearchErrorCode.not_found, "price snapshot was not found", status_code=404)
        data = price_snapshot_out(r)
        # Realtime provider snapshots can lack the day range; recover it from another
        # same-trading-day snapshot or the persisted daily bar instead of showing a gap.
        if r.trading_date is not None and (data.get("day_high") is None or data.get("day_low") is None):
            day_high, day_low = self.repo.price_day_range(symbol, r.trading_date)
            if data.get("day_high") is None and day_high is not None:
                data["day_high"] = day_high
            if data.get("day_low") is None and day_low is not None:
                data["day_low"] = day_low
        state = snapshot_freshness(r)
        data_status = "stale" if state["is_stale"] else ("delayed" if r.is_delayed else "fresh")
        freshness = ResearchFreshness(
            as_of=r.market_timestamp or r.fetched_at,
            status=FreshnessStatus.stale if state["is_stale"] else FreshnessStatus.live,
            age_seconds=state["age_seconds"],
            ttl_seconds=state["stale_after_seconds"],
            reason="latest persisted market price snapshot; no provider refresh was triggered",
        )
        return self.response(
            data,
            sources=[source(
                SourceType.price_snapshot,
                r.id,
                f"{symbol} 市场价格快照",
                symbol=symbol,
                provider=r.provider,
                authority=SourceAuthority.secondary,
                retrieved_at=r.fetched_at,
                market_timestamp=r.market_timestamp,
                fetched_at=r.fetched_at,
                persisted_at=r.persisted_at,
                market_session=data["market_session"],
                data_status=data_status,
                provider_role=r.provider_role,
                locator=f"research://companies/{symbol}/price/latest",
            )],
            freshness=freshness,
            symbol=symbol,
        )

    def price_history(self, symbol: str, start: date | None, end: date | None, interval: str, limit: int):
        if interval != "1d": raise ResearchError(ResearchErrorCode.invalid_parameter, "only interval=1d is supported", field="interval", status_code=422)
        validate_date_range(start, end, max_days=3660); symbol = normalize_symbol(symbol); rows = self.repo.price_history(symbol, start, end, min(limit, 2500))
        data = [{"date": r.date, "open": _json_value(r.open), "high": _json_value(r.high), "low": _json_value(r.low), "close": _json_value(r.close),
                 "volume_shares": r.volume, "vwap": _json_value(r.vwap), "change": _json_value(r.change), "change_percent": _json_value(r.change_percent), "source": r.source} for r in rows]
        providers = sorted({r.source for r in rows})
        sources = [source(SourceType.historical_price, f"{symbol}:{provider}", f"{symbol} daily price history", symbol=symbol, provider=provider, authority=SourceAuthority.primary, published_at=max((r.date for r in rows if r.source == provider), default=None), locator=f"research://companies/{symbol}/prices/history?source={provider}") for provider in providers]
        return self.response(data, sources=sources, freshness=calculate_freshness("financial_statement", datetime.combine(max((r.date for r in rows), default=date.min), time.min, tzinfo=UTC) if rows else None, "latest persisted daily close"), symbol=symbol, total=len(rows))

    def technical(self, symbol: str):
        symbol = normalize_symbol(symbol); r = self.repo.technical(symbol)
        if not r: raise ResearchError(ResearchErrorCode.not_found, "technical analysis was not found", status_code=404)
        a = r.analysis or {}; indicators = a.get("indicators") or {}
        data = {"symbol": symbol, "status": r.status, "trend": a.get("weeklyTrend"), "latest_close": a.get("latestClose"),
                "support_levels": _bounded(a.get("supportZones") or ([a.get("nearestSupport")] if a.get("nearestSupport") else [])),
                "resistance_levels": _bounded(a.get("resistanceZones") or ([a.get("nearestResistance")] if a.get("nearestResistance") else [])),
                "rsi_14": indicators.get("rsi14"), "macd": {"value": indicators.get("macd"), "signal": indicators.get("macdSignal"), "histogram": indicators.get("macdHistogram")},
                "moving_averages": {k: indicators.get(k) for k in ("ma5", "ma20", "ma60", "ema20", "weeklyMa20", "weeklyMa50")},
                "volatility": {"atr_14": indicators.get("atr14"), "bollinger_low": indicators.get("bollingerLow"), "bollinger_high": indicators.get("bollingerHigh")},
                "signal_summary": _bounded(a.get("confluences") or []), "omitted_reasons": _bounded(a.get("omittedReasons") or []),
                "analysis_version": r.analysis_version, "generated_at": r.generated_at, "data_through": r.data_through,
                "input_hash": r.input_hash, "image_available": bool(r.image_path), "image_format": (r.image_format or "webp") if r.image_path else None,
                "chart_url": f"/api/research/v1/companies/{symbol}/technical/chart" if r.image_path else None}
        return self.response(data, sources=[source(SourceType.technical_analysis, symbol, f"{symbol} technical analysis", symbol=symbol, provider=a.get("source"), authority=SourceAuthority.derived, published_at=r.data_through, retrieved_at=r.generated_at, locator=f"research://companies/{symbol}/technical")], freshness=calculate_freshness("technical_analysis", r.generated_at, "latest persisted technical analysis"), symbol=symbol)

    def technical_chart_path(self, symbol: str):
        symbol = normalize_symbol(symbol); r = self.repo.technical(symbol)
        if not r or not r.image_path: raise ResearchError(ResearchErrorCode.file_not_found, "technical chart was not found", status_code=404)
        if (r.image_format or "webp").lower() not in {"webp", "png", "jpg", "jpeg"}: raise ResearchError(ResearchErrorCode.file_access_denied, "technical chart format is not allowed", status_code=403)
        return resolve_safe_file(__import__("pathlib").Path(get_settings().technical_chart_dir), r.image_path, {".webp", ".png", ".jpg", ".jpeg"})

    @staticmethod
    def _calendar_event(r, include_metadata: bool = False):
        data = {"event_id": r.id, "symbol": r.symbol, "company_name": r.company_name, "event_type": r.event_type,
                "title": r.title, "description": r.description, "event_date": r.event_date, "event_time": r.event_time,
                "time_status": r.time_status, "timezone": r.timezone, "fiscal_period": r.fiscal_period, "fiscal_year": r.fiscal_year,
                "status": r.status, "confidence": r.confidence, "impact_level": r.impact_level, "is_confirmed": r.is_confirmed,
                "is_estimated": r.is_estimated, "primary_source": r.primary_source, "source_count": len(r.sources or []),
                "has_conflict": r.has_conflict, "conflict_fields": r.conflict_fields or [], "fetched_at": r.fetched_at}
        if include_metadata: data["metadata"] = _bounded(r.metadata_payload or {})
        return data

    def calendar_events(self, symbols: list[str], event_type: str | None, start: date | None, end: date | None, page: int, page_size: int):
        validate_date_range(start, end, max_days=730); clean = list(dict.fromkeys(normalize_symbol(s) for s in symbols)); offset, limit = page_window(page, page_size)
        rows, total = self.repo.calendar_events(clean, event_type, start, end, offset, limit)
        sources = [source(SourceType.calendar_event, r.id, r.title, symbol=r.symbol, provider=r.primary_source, authority=SourceAuthority.primary, published_at=r.event_time or r.event_date, retrieved_at=r.fetched_at, locator=f"research://calendar/events/{r.id}") for r in rows]
        return self.response([self._calendar_event(r) for r in rows], sources=sources, freshness=calculate_freshness("calendar_event", max((r.fetched_at for r in rows), default=None), "latest matching calendar event fetch"), symbols=clean, page=page, page_size=page_size, total=total)

    def calendar_event(self, event_id: str):
        event, evidence = self.repo.calendar_event(event_id)
        if not event: raise ResearchError(ResearchErrorCode.not_found, "calendar event was not found", status_code=404)
        data = self._calendar_event(event, True)
        data["source_evidence"] = [{"provider": r.provider, "source_record_id": r.source_record_id, "source_url": safe_external_url(r.source_url),
                                    "fetched_at": r.fetched_at, "metadata": _bounded({k: v for k, v in (r.raw_payload or {}).items() if k in {"date", "time", "estimate", "actual", "currency", "fiscal_period"}})} for r in evidence]
        sources = [source(SourceType.calendar_event, f"{event.id}:{r.id}", f"{event.title} evidence from {r.provider}", symbol=event.symbol, provider=r.provider, authority=SourceAuthority.primary, retrieved_at=r.fetched_at, url=r.source_url, locator=f"research://calendar/events/{event.id}/sources/{r.id}") for r in evidence]
        if not sources: sources = [source(SourceType.calendar_event, event.id, event.title, symbol=event.symbol, provider=event.primary_source, authority=SourceAuthority.primary, retrieved_at=event.fetched_at, locator=f"research://calendar/events/{event.id}")]
        return self.response(data, sources=sources, freshness=calculate_freshness("calendar_event", event.fetched_at, "calendar event source reconciliation time"), symbol=event.symbol)

    @staticmethod
    def _run(r):
        return {"run_id": r.id, "portfolio_id": r.portfolio_id, "status": r.status, "stage": r.stage, "trigger": r.trigger,
                "requested_at": r.requested_at, "started_at": r.started_at, "completed_at": r.completed_at, "analysis_date": r.analysis_date,
                "model_requested": r.model_requested, "model_used": r.model_used, "prompt_version": r.prompt_version,
                "schema_version": r.schema_version, "filter_version": r.filter_version, "warnings": _bounded(r.warnings or []),
                "failure_code": r.failure_code, "failure_reason": r.failure_reason}

    def discovery_runs(self, status: str | None, start: date | None, end: date | None, page: int, page_size: int):
        validate_date_range(start, end); offset, limit = page_window(page, page_size)
        rows, total = self.repo.discovery_runs(self.user.id, status, start, end, offset, limit)
        sources = [source(SourceType.discovery_run, r.id, f"Opportunity discovery run {r.id}", provider=r.model_used or r.model_requested, authority=SourceAuthority.derived, published_at=r.completed_at or r.requested_at, retrieved_at=r.completed_at or r.requested_at, locator=f"research://discovery/runs/{r.id}") for r in rows]
        return self.response([self._run(r) for r in rows], sources=sources, freshness=calculate_freshness("discovery_run", max((r.completed_at or r.requested_at for r in rows), default=None), "latest user-owned discovery run"), page=page, page_size=page_size, total=total)

    def discovery_run(self, run_id: int):
        run = self.repo.discovery_run(self.user.id, run_id)
        if not run: raise ResearchError(ResearchErrorCode.not_found, "discovery run was not found", status_code=404)
        parts = self.repo.discovery_components(run_id); portfolio = parts["portfolio_snapshot"]; market = parts["market_context"]; usage = parts["usage"]
        data = self._run(run)
        data.update({
            "portfolio_snapshot": ({"context_hash": portfolio.context_hash, "created_at": portfolio.created_at,
                                    "summary": _bounded({k: v for k, v in (portfolio.payload or {}).items() if k in {"portfolio", "health", "strategy", "holdings", "exposures"}})} if portfolio else None),
            "market_context": ({"summary": market.summary, "risk_regime": market.risk_regime,
                                "context": _bounded(market.payload)} if market else None),
            "exposures": [{"kind": r.diagnosis_kind, "type": r.exposure_type, "name": r.name, "level": r.level, "reasoning": r.reasoning, "suggested_action": r.suggested_action} for r in parts["exposures"]],
            "flow_directions": [{"type": r.flow_type, "direction": r.direction, "strength": r.strength, "details": _bounded(r.payload)} for r in parts["flows"]],
            "candidate_groups": [{"group_id": r.group_id, "name": r.group_name, "type": r.group_type, "summary": r.summary} for r in parts["groups"]],
            "usage": ({"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "total_tokens": usage.total_tokens,
                       "finance_search_calls": usage.finance_search_calls, "web_search_calls": usage.web_search_calls,
                       "total_cost_usd": usage.total_cost_usd} if usage else None),
            "source_summary": [{"title": r.title, "url": safe_external_url(r.url), "source_type": r.source_type, "source_origin": r.source_origin} for r in parts["sources"][:100]],
            "opportunity_history": ({"history_id": parts["opportunity_history"].id, "created_at": parts["opportunity_history"].created_at,
                                     "market_condition": parts["opportunity_history"].market_condition,
                                     "model_version": parts["opportunity_history"].model_version,
                                     "search_source": parts["opportunity_history"].search_source} if parts["opportunity_history"] else None),
        })
        sources = [source(SourceType.discovery_run, run.id, f"Opportunity discovery run {run.id}", provider=run.model_used or run.model_requested, authority=SourceAuthority.derived, published_at=run.completed_at or run.requested_at, retrieved_at=run.completed_at or run.requested_at, locator=f"research://discovery/runs/{run.id}")]
        return self.response(data, sources=sources, freshness=calculate_freshness("discovery_run", run.completed_at or run.requested_at, "persisted discovery run completion time"))

    def discovery_candidates(self, run_id: int, group_id: str | None, status: str | None, page: int, page_size: int):
        if not self.repo.discovery_run(self.user.id, run_id): raise ResearchError(ResearchErrorCode.not_found, "discovery run was not found", status_code=404)
        offset, limit = page_window(page, page_size); rows, total = self.repo.discovery_candidates(self.user.id, run_id, group_id, status, offset, limit)
        metrics, filters = self.repo.discovery_candidate_components([r.id for r in rows])
        data = [{"candidate_id": r.id, "symbol": r.normalized_ticker, "raw_ticker": r.raw_ticker, "company_name": r.company_name,
                 "exchange": r.exchange, "country": r.country, "raw_rank": r.raw_rank, "final_rank": r.final_rank,
                 "priority": r.candidate_priority, "symbol_match_status": r.symbol_match_status, "filter_status": r.filter_status,
                 "display_status": r.display_status, "verification_status": r.verification_status,
                 "analysis_summary": _bounded({k: v for k, v in (r.normalized_data or {}).items() if k in {"discovery_reason", "portfolio_fit", "investment_thesis", "major_risks", "thesis_breakers", "why_now"}}),
                 "local_validation": _bounded(r.local_data or {}),
                 "metrics": [{"key": metric.metric_key, "value": metric.value, "text_value": metric.text_value, "unit": metric.unit,
                              "source": metric.source, "period": metric.data_period, "preferred": metric.is_preferred,
                              "has_discrepancy": metric.has_discrepancy} for metric in metrics.get(r.id, [])],
                 "filter_result": ({"status": filters[r.id].status, "reasons": _bounded(filters[r.id].reasons),
                                    "details": _bounded(filters[r.id].details), "filter_version": filters[r.id].filter_version} if r.id in filters else None),
                 "created_at": r.created_at, "verified_at": r.verified_at} for r in rows]
        sources = [source(SourceType.discovery_candidate, r.id, f"Discovery candidate {r.normalized_ticker or r.raw_ticker}", symbol=r.normalized_ticker, authority=SourceAuthority.derived, retrieved_at=r.verified_at or r.created_at, locator=f"research://discovery/runs/{run_id}/candidates/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("discovery_run", max((r.verified_at or r.created_at for r in rows), default=None), "latest candidate verification time"), page=page, page_size=page_size, total=total)

    def portfolio_analysis(self, portfolio_id: int | None = None, limit: int = 10):
        portfolio = self._portfolio(portfolio_id)
        rows = self.repo.portfolio_analysis_runs(portfolio.id, min(max(limit, 1), 20))
        data = [{"run_id": r.id, "analysis_type": r.analysis_type, "status": r.status,
                 "result": _bounded(r.result_json), "assumptions": _bounded(r.assumptions_json),
                 "model_version": r.model_version, "price_data_start_date": r.price_data_start_date,
                 "price_data_end_date": r.price_data_end_date, "created_at": r.created_at,
                 "completed_at": r.completed_at} for r in rows]
        sources = [source(SourceType.portfolio_analysis, r.id, f"Portfolio {r.analysis_type} analysis", authority=SourceAuthority.derived,
                          published_at=r.completed_at or r.created_at, retrieved_at=r.completed_at or r.created_at,
                          locator=f"research://portfolio/{portfolio.id}/analysis/{r.id}") for r in rows]
        warnings = [ResearchWarning(code="DATA_INCOMPLETE", message="No persisted portfolio analysis run is available.", severity=WarningSeverity.info)] if not rows else []
        return self.response(data, sources=sources, freshness=calculate_freshness("portfolio_position", max((r.completed_at or r.created_at for r in rows), default=None), "latest persisted analysis run"), warnings=warnings, total=len(rows))

    def market_context(self):
        pair = self.repo.latest_market_context(self.user.id)
        macro_context = None
        try:
            from app.services.macro.context import build_latest_us_macro_context
            macro_context = build_latest_us_macro_context(self.db)
        except Exception:
            # Macro is an optional provider and its migration may be absent on
            # an older database during a rolling deployment.
            macro_context = None
        macro_as_of = None
        if macro_context and macro_context.get("as_of"):
            try:
                macro_as_of = datetime.fromisoformat(str(macro_context["as_of"]).replace("Z", "+00:00"))
            except ValueError:
                macro_as_of = None
        if not pair:
            data = {"us_macro": macro_context} if macro_context else {}
            sources = [source(SourceType.us_macro, "latest", "Latest persisted US macro context", provider="alpha_vantage", authority=SourceAuthority.derived, retrieved_at=macro_as_of, locator="research://macro/us/latest")] if macro_context else []
            return self.response(data, sources=sources, freshness=unknown_freshness("no persisted market context"),
                                 warnings=[ResearchWarning(code="DATA_INCOMPLETE", message="No persisted last-good market context is available.")])
        context, run = pair
        data = {"summary": context.summary, "risk_regime": context.risk_regime, "context": _bounded(context.payload),
                "as_of": run.completed_at or run.requested_at, "source_run_id": run.id}
        sources = [source(SourceType.market_context, context.id, "Persisted market context", authority=SourceAuthority.derived,
            published_at=run.completed_at or run.requested_at, retrieved_at=run.completed_at or run.requested_at,
            locator=f"research://market/context/{context.id}")]
        if macro_context:
            data["us_macro"] = macro_context
            sources.append(source(SourceType.us_macro, "latest", "Latest persisted US macro context", provider="alpha_vantage", authority=SourceAuthority.derived, retrieved_at=macro_as_of, locator="research://macro/us/latest"))
        return self.response(data, sources=sources, freshness=calculate_freshness("discovery_run", run.completed_at or run.requested_at, "persisted discovery market context"))

    @staticmethod
    def _congress_trade(row):
        return {"trade_id": row.id, "person": row.filer_name, "party": row.party, "chamber": row.chamber,
                "branch": row.branch, "state": row.state, "symbol": row.ticker, "asset_name": row.asset_name,
                "asset_type": row.asset_type, "transaction_type": row.transaction_type,
                "transaction_date": row.transaction_date, "filing_date": row.filing_date,
                "amount_low": row.amount_low, "amount_high": row.amount_high, "amount_label": row.amount_label,
                "is_late": row.is_late, "comment": (row.comment[:1000] if row.comment else None)}

    def congress_trades(self, symbol, person, party, chamber, start, end, page, page_size):
        validate_date_range(start, end); symbol = normalize_symbol(symbol) if symbol else None; offset, limit = page_window(page, page_size)
        rows, total = self.repo.congress_trades(symbol, person, party, chamber, start, end, offset, limit)
        sources = [source(SourceType.congress_trade, r.id, f"{r.filer_name} public disclosure", symbol=r.ticker,
            provider="STOCK Act disclosure", authority=SourceAuthority.official, published_at=r.filing_date,
            retrieved_at=r.synced_at, locator=f"research://ownership/congress-trades/{r.id}") for r in rows]
        return self.response([self._congress_trade(r) for r in rows], sources=sources,
            freshness=calculate_freshness("sec_filing", max((r.synced_at for r in rows), default=None), "persisted public disclosure"),
            symbol=symbol, page=page, page_size=page_size, total=total)

    def tracked_figures(self, query: str | None, page: int, page_size: int):
        offset, limit = page_window(page, page_size); rows, total = self.repo.tracked_figures(query, offset, limit)
        data = [{"figure_id": r.id, "slug": r.slug, "display_name": r.display_name, "kind": r.kind,
                 "photo_url": safe_external_url(r.photo_url), "note": r.note, "is_seed": r.is_seed,
                 "created_at": r.created_at} for r in rows]
        sources = [source(SourceType.tracked_figure, r.id, r.display_name, authority=SourceAuthority.secondary,
            retrieved_at=r.created_at, locator=f"research://ownership/figures/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max((r.created_at for r in rows), default=None), "persisted tracked figure registry"), page=page, page_size=page_size, total=total)

    def figure_positions(self, figure_id: int, symbol: str | None = None):
        figure = self.repo.tracked_figure(figure_id)
        if not figure: raise ResearchError(ResearchErrorCode.not_found, "tracked figure was not found", status_code=404)
        symbol = normalize_symbol(symbol) if symbol else None; rows = self.repo.figure_positions(figure.slug, symbol)
        data = [{"position_id": r.id, "figure_id": figure.id, "figure_name": figure.display_name, "symbol": r.ticker,
                 "asset_name": r.asset_name, "category": r.category, "baseline_value": r.baseline_value,
                 "adjusted_value": r.adjusted_value, "is_percent": r.is_percent, "note": r.note,
                 "last_updated": r.last_updated} for r in rows]
        sources = [source(SourceType.figure_position, r.id, f"{figure.display_name} {r.asset_name}", symbol=r.ticker,
            authority=SourceAuthority.secondary, retrieved_at=r.last_updated, locator=f"research://ownership/figures/{figure.id}/positions/{r.id}") for r in rows]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max((r.last_updated for r in rows), default=None), "persisted public figure position"), symbol=symbol, total=len(rows))

    def public_figure_activity(self, figure_id: int, start: date | None, end: date | None):
        validate_date_range(start, end); figure = self.repo.tracked_figure(figure_id)
        if not figure: raise ResearchError(ResearchErrorCode.not_found, "tracked figure was not found", status_code=404)
        positions = self.repo.figure_positions(figure.slug); trades = self.repo.figure_activity(figure.kadoa_filer_id, start, end)
        data = {"figure": {"figure_id": figure.id, "display_name": figure.display_name, "kind": figure.kind},
                "positions": [{"symbol": r.ticker, "asset_name": r.asset_name, "category": r.category,
                               "adjusted_value": r.adjusted_value, "is_percent": r.is_percent, "last_updated": r.last_updated} for r in positions],
                "trades": [self._congress_trade(r) for r in trades]}
        sources = [source(SourceType.figure_position, r.id, f"{figure.display_name} {r.asset_name}", symbol=r.ticker,
            authority=SourceAuthority.secondary, retrieved_at=r.last_updated, locator=f"research://ownership/figures/{figure.id}/positions/{r.id}") for r in positions]
        sources += [source(SourceType.congress_trade, r.id, f"{r.filer_name} public disclosure", symbol=r.ticker,
            provider="STOCK Act disclosure", authority=SourceAuthority.official, published_at=r.filing_date,
            retrieved_at=r.synced_at, locator=f"research://ownership/congress-trades/{r.id}") for r in trades]
        timestamps = [r.last_updated for r in positions] + [r.synced_at for r in trades]
        return self.response(data, sources=sources, freshness=calculate_freshness("sec_filing", max(timestamps, default=None), "persisted public disclosures and positions"))
