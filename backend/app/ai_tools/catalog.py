from __future__ import annotations

import math
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.config import get_settings
from app.research.exceptions import ResearchError
from app.research.security import normalize_symbol
from app.research.service import ResearchGateway

from .adapters.base import BaseToolAdapter, from_research
from .schemas import (
    AdapterResult,
    SymbolArguments,
    ToolArguments,
    ToolDefinition,
    ToolExecutionResult,
)


def _symbols(values: list[str]) -> list[str]:
    if len(values) > 20: raise ValueError("at most 20 symbols are allowed")
    result = []
    for value in values:
        try: symbol = normalize_symbol(value)
        except ResearchError as exc: raise ValueError(exc.message) from exc
        if symbol not in result: result.append(symbol)
    return result


def _symbol(value: str | None) -> str | None:
    if value is None: return None
    try: return normalize_symbol(value)
    except ResearchError as exc: raise ValueError(exc.message) from exc


class SymbolsArguments(ToolArguments):
    symbols: list[str] = Field(min_length=1, max_length=20)
    @field_validator("symbols")
    @classmethod
    def clean(cls, value): return _symbols(value)


class PortfolioArguments(ToolArguments): portfolio_id: int | None = Field(None, gt=0)
class PortfolioPositionsArguments(PortfolioArguments):
    symbols: list[str] = Field(default_factory=list, max_length=20)
    sort_by: Literal["symbol", "symbol_desc", "updated_at", "quantity"] = "symbol"
    limit: int = Field(20, ge=1, le=50)
    @field_validator("symbols")
    @classmethod
    def clean(cls, value): return _symbols(value)
class PositionArguments(SymbolArguments): portfolio_id: int | None = Field(None, gt=0)
class DateArguments(ToolArguments):
    start_date: date | None = None; end_date: date | None = None
    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date: raise ValueError("start_date must not be after end_date")
        return self
class PortfolioDateArguments(DateArguments):
    portfolio_id: int | None = Field(None, gt=0)
class SymbolDateArguments(SymbolArguments):
    start_date: date | None = None; end_date: date | None = None
    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date: raise ValueError("start_date must not be after end_date")
        return self
class TradeArguments(DateArguments):
    symbol: str | None = Field(None, max_length=32); portfolio_id: int | None = Field(None, gt=0)
    transaction_type: Literal["buy", "sell", "dividend", "fee", "split", "transfer"] | None = None
    limit: int = Field(20, ge=1, le=100)
    @field_validator("symbol")
    @classmethod
    def clean(cls, value): return _symbol(value)
class CompanySnapshotArguments(SymbolArguments):
    include_position: bool = True; include_price: bool = True; include_valuation: bool = True; include_technical: bool = True
class PeersArguments(SymbolArguments): include_excluded: bool = False
class PriceHistoryArguments(SymbolDateArguments):
    start_date: date | None = None; end_date: date | None = None; interval: Literal["1d"] = "1d"; limit: int = Field(365, ge=1, le=2500)
    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date: raise ValueError("invalid date range")
        return self
class ComparePriceArguments(SymbolsArguments):
    symbols: list[str] = Field(min_length=2, max_length=10); start_date: date | None = None; end_date: date | None = None
    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date: raise ValueError("invalid date range")
        return self
class NewsArguments(DateArguments):
    symbol: str | None = Field(None, max_length=32); symbols: list[str] = Field(default_factory=list, max_length=20)
    days: int = Field(30, ge=1, le=365); provider: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=192); event_type: str | None = Field(None, max_length=32)
    sentiment: str | None = Field(None, max_length=16); min_importance: int | None = Field(None, ge=0, le=100)
    include_market_news: bool = False; limit: int = Field(20, ge=1, le=50)
    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value): return _symbol(value)
    @field_validator("symbols")
    @classmethod
    def clean_symbols(cls, value): return _symbols(value)
class SearchNewsArguments(DateArguments):
    query: str = Field(min_length=1, max_length=500); symbols: list[str] = Field(default_factory=list, max_length=20)
    provider: str | None = Field(None, max_length=100); industry: str | None = Field(None, max_length=192)
    event_type: str | None = Field(None, max_length=32); sentiment: str | None = Field(None, max_length=16)
    min_importance: int | None = Field(None, ge=0, le=100); limit: int = Field(20, ge=1, le=50)
    @field_validator("symbols")
    @classmethod
    def clean(cls, value): return _symbols(value)
class IdArguments(ToolArguments): news_id: int = Field(gt=0)
class CryptoResearchContextArguments(ToolArguments):
    instrument_id: int | None = Field(None, gt=0)
    provider: Literal["binance_spot", "binance_usdm"] | None = None
    provider_id: str | None = Field(None, min_length=3, max_length=64, pattern=r"^[A-Z0-9_-]+$")

    @model_validator(mode="after")
    def require_exact_scope(self):
        by_id = self.instrument_id is not None
        by_provider = self.provider is not None or self.provider_id is not None
        if by_id == by_provider or (by_provider and not (self.provider and self.provider_id)):
            raise ValueError("provide instrument_id or exact provider + provider_id")
        return self

class CryptoNewsArguments(ToolArguments):
    asset_id: int = Field(gt=0)
    instrument_id: int | None = Field(None, gt=0)
    limit: int = Field(20, ge=1, le=20)

class CryptoReportsArguments(ToolArguments):
    asset_id: int | None = Field(None, gt=0)
    instrument_id: int | None = Field(None, gt=0)
    limit: int = Field(20, ge=1, le=20)

    @model_validator(mode="after")
    def require_scope(self):
        if self.asset_id is None and self.instrument_id is None:
            raise ValueError("asset_id or instrument_id is required")
        return self

class FilingIdArguments(ToolArguments): filing_id: int = Field(gt=0)
class EventIdArguments(ToolArguments): event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$")
class ArchiveArguments(SymbolDateArguments):
    period: Literal["daily", "weekly"] = "daily"; start_date: date | None = None; end_date: date | None = None; limit: int = Field(20, ge=1, le=50)
class SecFilingsArguments(SymbolDateArguments):
    form_types: list[str] = Field(default_factory=list, max_length=10); start_date: date | None = None; end_date: date | None = None; limit: int = Field(20, ge=1, le=50)
    @field_validator("form_types")
    @classmethod
    def forms(cls, values):
        result=[]
        for value in values:
            clean=value.strip().upper()
            if not clean or len(clean)>20 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- /" for c in clean): raise ValueError("invalid SEC form type")
            if clean not in result: result.append(clean)
        return result
class SecEventsArguments(SymbolDateArguments):
    event_types: list[str] = Field(default_factory=list, max_length=10); start_date: date | None = None; end_date: date | None = None; limit: int = Field(20, ge=1, le=50)
    @field_validator("event_types")
    @classmethod
    def events(cls, values):
        if any(not value.strip() or len(value)>80 for value in values): raise ValueError("invalid event type")
        return list(dict.fromkeys(v.strip() for v in values))
FINANCIAL_METRICS = {"revenue", "operating_income", "net_income", "gross_profit", "eps", "eps_basic", "eps_diluted", "free_cash_flow", "operating_cash_flow", "gross_margin", "net_margin", "cash", "total_debt", "shares_outstanding"}
SEC_CONCEPTS = {"revenue", "net_income", "operating_income", "gross_profit", "eps_basic", "eps_diluted", "cash_and_equivalents", "total_debt", "shares_outstanding", "operating_cash_flow"}
class SecFactsArguments(SymbolDateArguments):
    concepts: list[str] = Field(default_factory=list, max_length=20); period_type: Literal["annual", "quarterly"] | None = None
    start_date: date | None = None; end_date: date | None = None; limit: int = Field(25, ge=1, le=100)
    @field_validator("concepts")
    @classmethod
    def concepts_allowed(cls, values):
        if any(v not in SEC_CONCEPTS for v in values): raise ValueError("unsupported financial concept")
        return list(dict.fromkeys(values))
class InsiderArguments(SymbolDateArguments):
    start_date: date | None = None; end_date: date | None = None; transaction_type: str | None = Field(None, max_length=16); limit: int = Field(20, ge=1, le=50)
class InstitutionalArguments(SymbolArguments):
    report_period: date | None = None; institution: str | None = Field(None, max_length=200); limit: int = Field(20, ge=1, le=50)
class OwnershipArguments(SymbolDateArguments):
    start_date: date | None = None; end_date: date | None = None; include_insiders: bool = True; include_institutions: bool = True; include_share_statistics: bool = True
class FinancialSummaryArguments(SymbolArguments): period_type: Literal["annual", "quarterly"] | None = None; periods: int = Field(8, ge=1, le=20)
class StatementArguments(SymbolArguments): statement: Literal["income", "balance_sheet", "cash_flow"]; period_type: Literal["annual", "quarterly"] = "annual"; periods: int = Field(4, ge=1, le=20)
class FinancialCompareArguments(SymbolsArguments):
    symbols: list[str] = Field(min_length=2, max_length=10); metrics: list[str] = Field(min_length=1, max_length=20); period_type: Literal["annual", "quarterly"] = "quarterly"; periods: int = Field(4, ge=1, le=12)
    @field_validator("metrics")
    @classmethod
    def metrics_allowed(cls, values):
        if any(v not in FINANCIAL_METRICS for v in values): raise ValueError("unsupported financial metric")
        return list(dict.fromkeys(values))
class FinancialTrendsArguments(SymbolArguments):
    metrics: list[str] = Field(min_length=1, max_length=20)
    period_type: Literal["annual", "quarterly"] = "quarterly"
    periods: int = Field(8, ge=2, le=20)

    @field_validator("metrics")
    @classmethod
    def metrics_allowed(cls, values):
        if any(v not in FINANCIAL_METRICS for v in values): raise ValueError("unsupported financial metric")
        return list(dict.fromkeys(values))

class CompareTechnicalArguments(SymbolsArguments):
    symbols: list[str] = Field(min_length=2, max_length=10)

class ValuationHistoryArguments(SymbolDateArguments): limit: int = Field(30, ge=1, le=100)
class CompareValuationsArguments(SymbolsArguments):
    symbols: list[str] = Field(min_length=2, max_length=10)
    models: list[Literal["graham", "dcf", "relative", "reverse_dcf", "dividend_discount"]] = Field(default_factory=list, max_length=5)
class TechnicalLevelsArguments(SymbolArguments): include_support: bool = True; include_resistance: bool = True
class CalendarArguments(DateArguments):
    symbol: str | None = Field(None, max_length=32); symbols: list[str] = Field(default_factory=list, max_length=20); event_types: list[str] = Field(default_factory=list, max_length=10); limit: int = Field(20, ge=1, le=100)
    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value): return _symbol(value)
    @field_validator("symbols")
    @classmethod
    def clean_symbols(cls, value): return _symbols(value)
class DiscoveryRunsArguments(DateArguments): status: str | None = Field(None, max_length=32); limit: int = Field(20, ge=1, le=50)
class RunIdArguments(ToolArguments): run_id: int = Field(gt=0); include_candidates: bool = True; include_market_context: bool = True; include_exposures: bool = True; include_flows: bool = True
class CandidateArguments(ToolArguments): run_id: int = Field(gt=0); group: str | None = Field(None, max_length=80); status: str | None = Field(None, max_length=32); sort_by: Literal["rank"] = "rank"; limit: int = Field(20, ge=1, le=50)
class CongressArguments(DateArguments):
    symbol: str | None = Field(None, max_length=32); person: str | None = Field(None, max_length=200); party: str | None = Field(None, max_length=16); chamber: str | None = Field(None, max_length=32); limit: int = Field(20, ge=1, le=100)
    @field_validator("symbol")
    @classmethod
    def clean(cls, value): return _symbol(value)
class FiguresArguments(ToolArguments): query: str | None = Field(None, max_length=200); limit: int = Field(20, ge=1, le=100)
class FigurePositionsArguments(ToolArguments):
    figure_id: int = Field(gt=0)
    symbol: str | None = Field(None, max_length=32)

    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value): return _symbol(value)

class FigureActivityArguments(DateArguments): figure_id: int = Field(gt=0)


def _merge(responses: list, data: Any, summary: str, *, partial=False) -> AdapterResult:
    partial=partial or any(str(getattr(r.freshness,"status",None)) in {"stale","expired"} for r in responses)
    partial=partial or any(getattr(w,"code",None) in {"DATA_INCOMPLETE","SOURCE_STALE"} for r in responses for w in r.warnings)
    return AdapterResult(data=data, summary=summary, sources=[s for r in responses for s in r.sources],
        freshness=next((r.freshness for r in responses if r.freshness), None), warnings=[w for r in responses for w in r.warnings], partial=partial)


def _count_summary(noun: str, response, returned: int | None = None) -> str:
    total = response.meta.total if response.meta.total is not None else (len(response.data) if isinstance(response.data, list) else (1 if response.data else 0))
    returned = returned if returned is not None else (len(response.data) if isinstance(response.data, list) else (1 if response.data else 0))
    return f"Found {total} {noun}; {returned} returned from already stored research data."


def _filtered(response, data: list[dict], id_field: str, summary: str) -> AdapterResult:
    identifiers={str(item.get(id_field)) for item in data if item.get(id_field) is not None}
    sources=[item for item in response.sources if str(item.source_id).split(":",1)[-1] in identifiers]
    partial=str(getattr(response.freshness,"status",None)) in {"stale","expired"} or any(getattr(w,"code",None) in {"DATA_INCOMPLETE","SOURCE_STALE"} for w in response.warnings)
    return AdapterResult(data=data,summary=summary,sources=sources,freshness=response.freshness,warnings=response.warnings,partial=partial)


def dispatch(name: str, args: ToolArguments, gw: ResearchGateway) -> AdapterResult:
    today = datetime.now(UTC).date()
    if name == "list_research_capabilities": return from_research(gw.capabilities(), "Listed the current read-only Research Gateway capabilities.")
    if name in {"get_portfolio_summary", "get_portfolio_overview"}: return from_research(gw.portfolio_summary(args.portfolio_id), "Returned the current user's unified authoritative portfolio overview with explicit account and market sources.")
    if name in {"get_portfolio_performance", "get_portfolio_equity_curve", "get_portfolio_drawdown"}:
        return from_research(gw.portfolio_performance(args.portfolio_id,args.start_date,args.end_date), "Returned cash-flow-adjusted IBKR account performance; deposits are not counted as investment return.")
    if name == "get_portfolio_return_attribution":
        return from_research(gw.portfolio_attribution(args.portfolio_id,args.start_date,args.end_date), "Returned position-level attribution from IBKR facts and project-derived daily performance.")
    if name in {"get_dividend_history","get_fee_and_tax_summary","get_cash_flow_summary","get_trade_statistics"}:
        r=gw.trades(args.portfolio_id,None,args.start_date,args.end_date,1,100)
        rows=list(r.data)
        if name=="get_dividend_history": data=[row for row in rows if row.get("event_type")=="dividend"]
        elif name=="get_fee_and_tax_summary":
            relevant=[row for row in rows if row.get("event_type") in {"commission","withholding_tax","broker_fee","margin_interest"}]
            by_currency={}
            for row in relevant:
                item=by_currency.setdefault(row.get("currency") or "UNKNOWN",{"currency":row.get("currency"),"fees":0.0,"taxes":0.0,"events":0})
                item["fees"]+=float(row.get("commission") or (abs(row.get("net_amount") or 0) if row.get("event_type")!="withholding_tax" else 0));item["taxes"]+=float(row.get("tax") or (abs(row.get("net_amount") or 0) if row.get("event_type")=="withholding_tax" else 0));item["events"]+=1
            data=list(by_currency.values())
        elif name=="get_cash_flow_summary":
            external=[row for row in rows if row.get("event_type") in {"deposit","withdrawal"}]
            data={"events":external,"net_by_currency":{currency:sum(float(row.get("net_amount") or 0) for row in external if (row.get("currency") or "UNKNOWN")==currency) for currency in {row.get("currency") or "UNKNOWN" for row in external}}}
        else:
            trades=[row for row in rows if row.get("event_type") in {"buy","sell"}]
            data={"trade_count":len(trades),"buy_count":sum(row.get("event_type")=="buy" for row in trades),"sell_count":sum(row.get("event_type")=="sell" for row in trades),"symbols":sorted({row.get("symbol") for row in trades if row.get("symbol")}),"fees":sum(float(row.get("commission") or 0) for row in trades)}
        return from_research(r,f"Returned {name.replace('_',' ')} from the unified authoritative ledger.").model_copy(update={"data":data})
    if name == "get_currency_exposure":
        r=gw.portfolio_summary(args.portfolio_id); data=r.data
        positions=gw.portfolio_positions(args.portfolio_id,1,50,"symbol").data
        grouped={}
        for row in positions:
            currency=row.get("currency") or "UNKNOWN";grouped[currency]=grouped.get(currency,0)+float(row.get("base_currency_market_value") or 0)
        return from_research(r,"Returned current currency exposure using authoritative quantities and project market valuation.").model_copy(update={"data":{"base_currency":data.get("base_currency"),"position_market_value_by_currency":grouped,"cash":data.get("cash"),"source_types":["IBKR fact","project market","project derived"]}})
    if name == "get_portfolio_positions":
        r=gw.portfolio_positions(args.portfolio_id,1,args.limit,args.sort_by); data=[x for x in r.data if not args.symbols or x.get("symbol") in args.symbols]; return from_research(r,_count_summary("portfolio positions",r,len(data))).model_copy(update={"data":data})
    if name == "get_position_detail": return from_research(gw.portfolio_position(args.symbol,args.portfolio_id),f"Returned the persisted portfolio position for {args.symbol}.")
    if name == "get_position_performance": return from_research(gw.position_ledger_section(args.symbol,args.portfolio_id,"performance_curve"),f"Returned the user's personal investment performance curve for {args.symbol}, not the security price curve.")
    if name == "get_position_transaction_timeline": return from_research(gw.position_ledger_section(args.symbol,args.portfolio_id,"timeline"),f"Returned the authoritative transaction and dividend timeline for {args.symbol}.")
    if name == "get_position_open_lots": return from_research(gw.position_ledger_section(args.symbol,args.portfolio_id,"open_lots"),f"Returned open broker tax lots or manual lots for {args.symbol}.")
    if name == "get_completed_trades": return from_research(gw.position_ledger_section(args.symbol,args.portfolio_id,"completed_trades"),f"Returned completed FIFO round trips for {args.symbol}.")
    if name == "get_trade_history":
        r=gw.trades(args.portfolio_id,args.symbol,args.start_date or today-timedelta(days=365),args.end_date or today,1,args.limit); data=[x for x in r.data if not args.transaction_type or x.get("event_type")==args.transaction_type]; return from_research(r,_count_summary("authoritative trade transactions",r,len(data))).model_copy(update={"data":data})
    if name == "get_portfolio_risk_analysis":
        r=gw.portfolio_analysis(args.portfolio_id,10); return from_research(r,_count_summary("persisted portfolio analysis runs",r))
    if name == "get_company_profile": return from_research(gw.company_profile(args.symbol),f"Returned the persisted company profile for {args.symbol}.")
    if name == "get_company_peers":
        r=gw.peers(args.symbol); data=dict(r.data); data["excluded"]=data.get("excluded",[]) if args.include_excluded else []; return from_research(r,f"Returned persisted peer relationships for {args.symbol}.").model_copy(update={"data":data})
    if name == "get_company_snapshot":
        responses=[]; data={}; missing=[]; section_freshness={}
        calls=[("profile",True,gw.company_profile),("position",args.include_position,lambda s:gw.portfolio_position(s,None)),("price",args.include_price,gw.price_latest),("valuation",args.include_valuation,gw.valuation),("technical",args.include_technical,gw.technical)]
        for key,enabled,fn in calls:
            if not enabled: continue
            try:
                r=fn(args.symbol); responses.append(r); data[key]=r.data
                section_freshness[key]=r.freshness.model_dump(mode="json") if hasattr(r.freshness,"model_dump") else r.freshness
            except ResearchError: missing.append(key); data[key]=None
        if not responses: raise RuntimeError("all company snapshot sections were unavailable")
        data["section_freshness"]=section_freshness
        result=_merge(responses,data,f"Returned {len(responses)} available sections for {args.symbol}; {len(missing)} sections were unavailable.",partial=bool(missing))
        if missing: result.warnings.append({"code":"DATA_INCOMPLETE","message":f"Unavailable snapshot sections: {', '.join(missing)}","severity":"warning"})
        return result
    if name == "get_latest_price":
        return from_research(
            gw.price_latest(args.symbol),
            f"Returned the latest persisted market snapshot for {args.symbol}; no live provider request was made.",
        )
    if name == "get_price_history":
        r=gw.price_history(args.symbol,args.start_date or today-timedelta(days=365),args.end_date or today,args.interval,args.limit); return from_research(r,_count_summary(f"daily price rows for {args.symbol}",r))
    if name == "compare_price_performance":
        responses=[]; rows=[]; missing=[]
        for symbol in args.symbols:
            try:
                r=gw.price_history(symbol,args.start_date or today-timedelta(days=365),args.end_date or today,"1d",2500); responses.append(r); series=sorted(r.data,key=lambda x:str(x.get("date")))
                closes=[float(x["close"]) for x in series if x.get("close") is not None]
                if len(closes)<2: missing.append(symbol); continue
                returns=[closes[i]/closes[i-1]-1 for i in range(1,len(closes)) if closes[i-1]]; peak=closes[0]; drawdown=0.0
                for close in closes: peak=max(peak,close); drawdown=min(drawdown,close/peak-1)
                rows.append({"symbol":symbol,"start":closes[0],"end":closes[-1],"return_percent":round((closes[-1]/closes[0]-1)*100,4),"max_drawdown_percent":round(drawdown*100,4),"annualized_volatility_percent":round(statistics.pstdev(returns)*math.sqrt(252)*100,4) if len(returns)>1 else None,"authority":"derived"})
            except ResearchError: missing.append(symbol)
        result=_merge(responses,rows,f"Compared persisted daily prices for {len(rows)} of {len(args.symbols)} requested symbols.",partial=bool(missing))
        if missing: result.warnings.append({"code":"DATA_INCOMPLETE","message":f"Insufficient prices for: {', '.join(missing)}","severity":"warning"})
        return result
    if name == "get_market_context": return from_research(gw.market_context(),"Returned the latest persisted last-good market context; no refresh was triggered.")
    if name in {"get_latest_news","search_news"}:
        if name=="get_latest_news": syms=list(dict.fromkeys(([args.symbol] if args.symbol else [])+args.symbols)); start=args.start_date or today-timedelta(days=args.days); query=None; include=args.include_market_news
        else: syms=args.symbols; start=args.start_date or today-timedelta(days=30); query=args.query; include=False
        r=gw.news(syms,query,start,args.end_date or today,args.provider,include,1,args.limit,
                  getattr(args,"industry",None),getattr(args,"event_type",None),
                  getattr(args,"sentiment",None),getattr(args,"min_importance",None))
        return from_research(r,_count_summary("stored news items",r))
    if name == "get_news_detail": return from_research(gw.news_detail(args.news_id),f"Returned stored metadata and bounded detail for news item {args.news_id}.")
    if name == "get_news_archives":
        r=gw.archives(args.symbol,args.period,args.start_date,args.end_date,1,args.limit); return from_research(r,_count_summary("persisted news archives",r))
    if name == "get_sec_filings":
        r=gw.sec_filings(args.symbol,args.form_types or None,args.start_date or today-timedelta(days=730),args.end_date or today,1,args.limit); data=r.data[:args.limit]; return _filtered(r,data,"filing_id",f"Found {len(data)} stored SEC filings for {args.symbol}; {len(data)} returned.")
    if name == "get_sec_filing_detail": return from_research(gw.sec_filing(args.filing_id),f"Returned safe stored metadata for SEC filing {args.filing_id}; no document body was read.")
    if name == "get_sec_events":
        r=gw.sec_events(args.symbol,args.event_types or None,args.start_date or today-timedelta(days=730),args.end_date or today,1,args.limit); data=r.data[:args.limit]; return _filtered(r,data,"event_id",f"Found {len(data)} stored SEC events for {args.symbol}; {len(data)} returned.")
    if name == "get_sec_financial_facts":
        r=gw.sec_periods(args.symbol,None,args.period_type,args.start_date,args.end_date,args.limit); data=[]
        for item in r.data:
            row=dict(item); row["metrics"]={key:value for key,value in (row.get("metrics") or {}).items() if not args.concepts or key in args.concepts}; data.append(row)
        return _filtered(r,data,"period_id",f"Returned {len(data)} normalized SEC financial periods for {args.symbol}.")
    if name == "get_insider_trades":
        r=gw.insider_trades(args.symbol,args.start_date or today-timedelta(days=365),args.end_date or today,args.transaction_type,1,args.limit); return from_research(r,_count_summary("stored insider trades",r))
    if name == "get_institutional_holdings":
        r=gw.institutional_holdings(args.symbol,args.report_period,args.institution,1,args.limit); return from_research(r,_count_summary("stored institutional holdings",r))
    if name == "get_company_ownership_activity":
        responses=[]; data={}; missing=[]
        if args.include_insiders:
            try: r=gw.insider_trades(args.symbol,args.start_date or today-timedelta(days=730),args.end_date or today,None,1,30); responses.append(r); data["insider_trades"]=r.data
            except ResearchError: missing.append("insider_trades")
        if args.include_institutions:
            try: r=gw.institutional_holdings(args.symbol,None,None,1,30); responses.append(r); data["institutional_holdings"]=r.data
            except ResearchError: missing.append("institutional_holdings")
        if args.include_share_statistics:
            try:
                r=gw.financial_summary(args.symbol); responses.append(r); data["share_statistics"]=[{"period":x.get("period"),"shares_outstanding":(x.get("metrics") or {}).get("shares_outstanding")} for x in r.data.get("periods",[]) if (x.get("metrics") or {}).get("shares_outstanding")]
                if not data["share_statistics"]: missing.append("share_statistics")
            except ResearchError: missing.append("share_statistics")
        if not responses: raise RuntimeError("all ownership activity sections were unavailable")
        result=_merge(responses,data,f"Returned {len(data)} available ownership sections for {args.symbol}.",partial=bool(missing))
        if missing: result.warnings.append({"code":"DATA_INCOMPLETE","message":f"Unavailable ownership sections: {', '.join(missing)}","severity":"warning"})
        return result
    if name == "get_financial_summary":
        r=gw.financial_summary(args.symbol); periods=[x for x in r.data.get("periods",[]) if not args.period_type or x.get("period_type")==args.period_type][:args.periods]; data=dict(r.data); data["periods"]=periods; return from_research(r,f"Returned {len(periods)} persisted financial periods for {args.symbol}.").model_copy(update={"data":data})
    if name == "get_financial_statements":
        r=gw.financial_statements(args.symbol,args.statement,args.period_type,args.periods); return from_research(r,_count_summary(f"{args.statement} statement periods",r))
    if name in {"compare_financial_metrics","get_financial_trends"}:
        symbols=args.symbols if name=="compare_financial_metrics" else [args.symbol]; responses=[]; output=[]
        for symbol in symbols:
            try:
                r=gw.financial_summary(symbol); responses.append(r); periods=[p for p in r.data.get("periods",[]) if p.get("period_type")==args.period_type][:args.periods]
                series=[{"period":p.get("period"),"metrics":{m:(p.get("metrics") or {}).get(m) for m in args.metrics if (p.get("metrics") or {}).get(m) is not None}} for p in periods]
                item={"symbol":symbol,"series":series,"authority":"source_and_deterministic_reformat"}
                if name=="get_financial_trends":
                    trends={}
                    for metric in args.metrics:
                        points=[(row["metrics"].get(metric) or {}).get("value") for row in series]
                        points=[float(value) for value in points if value is not None]
                        if len(points)>=2:
                            newest,oldest=points[0],points[-1]; change=((newest-oldest)/abs(oldest)*100) if oldest else None
                            trends[metric]={"latest":newest,"oldest":oldest,"change_percent":round(change,4) if change is not None else None,"direction":"up" if newest>oldest else ("down" if newest<oldest else "flat"),"authority":"derived"}
                    item["trends"]=trends
                output.append(item)
            except ResearchError: pass
        if not responses: raise RuntimeError("all financial comparison queries were unavailable")
        return _merge(responses,output,f"Prepared persisted financial metric series for {len(output)} of {len(symbols)} symbols.",partial=len(output)<len(symbols))
    if name == "get_latest_valuation": return from_research(gw.valuation(args.symbol),f"Returned the latest persisted valuation snapshot for {args.symbol}.")
    if name == "get_valuation_history":
        r=gw.valuation_history(args.symbol,args.start_date,args.end_date,args.limit); return from_research(r,_count_summary("valuation snapshots",r))
    if name == "compare_valuations":
        responses=[]; data=[]; missing=[]
        for symbol in args.symbols:
            try:
                r=gw.valuation(symbol); responses.append(r); item=dict(r.data)
                if args.models:
                    valuation=dict(item.get("valuation") or {}); item["valuation"]={key:value for key,value in valuation.items() if key not in {"graham","dcf","relative","reverse_dcf","dividend_discount"} or key in args.models}; item["requested_models"]=args.models
                data.append(item)
            except ResearchError: missing.append(symbol)
        if not responses: raise RuntimeError("all valuation comparison queries were unavailable")
        return _merge(responses,data,f"Compared latest available persisted valuation snapshots for {len(data)} of {len(args.symbols)} requested symbols.",partial=bool(missing))
    if name in {"get_technical_analysis","get_technical_levels","get_technical_chart_reference"}:
        r=gw.technical(args.symbol)
        if name=="get_technical_analysis":
            data=dict(r.data)
            data["indicator_reference_close"]=data.pop("latest_close",None)
            try:
                quote=gw.price_latest(args.symbol)
                data["latest_price_snapshot"]=quote.data
                return _merge(
                    [quote,r],
                    data,
                    f"Returned persisted technical indicators for {args.symbol} plus the latest persisted market snapshot. indicator_reference_close is not the latest persisted price.",
                )
            except ResearchError:
                data["latest_price_snapshot"]=None
                result=from_research(r,f"Returned persisted technical analysis for {args.symbol}; no persisted market snapshot was available.",partial=True).model_copy(update={"data":data})
                result.warnings.append({"code":"DATA_INCOMPLETE","message":"No persisted market snapshot was available; indicator_reference_close is only the historical close used to calculate the indicators.","severity":"warning"})
                return result
        if name=="get_technical_levels": data={k:r.data.get(k) for k in ("symbol","trend","moving_averages","generated_at","data_through")}; data["support_levels"]=r.data.get("support_levels") if args.include_support else []; data["resistance_levels"]=r.data.get("resistance_levels") if args.include_resistance else []
        else:
            image_format=str(r.data.get("image_format") or "webp").lower(); mime={"webp":"image/webp","png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg"}.get(image_format)
            data={"symbol":args.symbol,"chart_available":r.data.get("image_available",False),"locator":r.data.get("chart_url"),"mime_type":mime if r.data.get("image_available") else None,"generated_at":r.data.get("generated_at"),"analysis_version":r.data.get("analysis_version")}
        return from_research(r,f"Returned safe persisted technical {'levels' if name.endswith('levels') else 'chart reference'} for {args.symbol}.").model_copy(update={"data":data})
    if name == "compare_technical_signals":
        responses=[]; data=[]
        for symbol in args.symbols:
            try: r=gw.technical(symbol); responses.append(r); data.append({k:r.data.get(k) for k in ("symbol","status","trend","rsi_14","macd","generated_at","data_through")})
            except ResearchError: pass
        if not responses: raise RuntimeError("all technical comparison queries were unavailable")
        return _merge(responses,data,f"Compared persisted technical signals for {len(data)} of {len(args.symbols)} requested symbols.",partial=len(data)<len(args.symbols))
    if name == "get_calendar_events":
        syms=list(dict.fromkeys(([args.symbol] if args.symbol else [])+args.symbols)); r=gw.calendar_events(syms,args.event_types or None,args.start_date,args.end_date,1,args.limit); data=r.data[:args.limit]; return _filtered(r,data,"event_id",f"Returned {len(data)} persisted calendar events.")
    if name == "get_calendar_event_detail": return from_research(gw.calendar_event(args.event_id),f"Returned persisted event {args.event_id} and bounded source evidence.")
    if name == "get_discovery_runs":
        r=gw.discovery_runs(args.status,args.start_date,args.end_date,1,args.limit); return from_research(r,_count_summary("user-owned discovery runs",r))
    if name == "get_discovery_run":
        r=gw.discovery_run(args.run_id); responses=[r]; data=dict(r.data)
        if args.include_candidates:
            candidates=gw.discovery_candidates(args.run_id,None,None,1,50); responses.append(candidates); data["candidates"]=candidates.data
        else: data.pop("candidates",None)
        if not args.include_market_context: data.pop("market_context",None)
        if not args.include_exposures: data.pop("exposures",None)
        if not args.include_flows: data.pop("flow_directions",None)
        return _merge(responses,data,f"Returned persisted user-owned discovery run {args.run_id}; no new run was started.")
    if name == "get_discovery_candidates":
        r=gw.discovery_candidates(args.run_id,args.group,args.status,1,args.limit); return from_research(r,_count_summary("stored discovery candidates",r))
    if name == "get_congress_trades":
        r=gw.congress_trades(args.symbol,args.person,args.party,args.chamber,args.start_date,args.end_date,1,args.limit); return from_research(r,_count_summary("public transaction disclosures",r))
    if name == "get_tracked_figures":
        r=gw.tracked_figures(args.query,1,args.limit); return from_research(r,_count_summary("tracked public figures",r))
    if name == "get_figure_positions": return from_research(gw.figure_positions(args.figure_id,args.symbol),f"Returned persisted positions for tracked figure {args.figure_id}.")
    if name == "get_public_figure_activity": return from_research(gw.public_figure_activity(args.figure_id,args.start_date,args.end_date),f"Returned persisted public activity for tracked figure {args.figure_id}.")
    if name == "get_crypto_research_context":
        response = (
            gw.crypto_research_context(args.instrument_id)
            if args.instrument_id is not None
            else gw.crypto_research_context_by_provider(args.provider, args.provider_id)
        )
        return from_research(
            response,
            "Returned persisted crypto market, technical, derivatives, fundamental and regime context for an exact instrument identity; no provider fetch or execution was performed.",
        )
    if name == "get_crypto_news":
        return from_research(
            gw.crypto_news(args.asset_id, args.instrument_id, args.limit),
            f"Returned persisted crypto news for asset {args.asset_id}; no provider fetch or execution was performed.",
        )
    if name == "get_crypto_reports":
        return from_research(
            gw.crypto_reports(args.asset_id, args.instrument_id, args.limit),
            "Returned persisted crypto research reports; no provider fetch, signal, or order was submitted.",
        )
    raise RuntimeError(f"unimplemented registered tool: {name}")


class GatewayToolAdapter(BaseToolAdapter):
    def __init__(self, definition: ToolDefinition, arguments_model: type[ToolArguments]): self.definition=definition; self.arguments_model=arguments_model
    async def execute(self,args,context,gateway): return dispatch(self.definition.name,args,gateway)


TOOL_SPECS: list[tuple[str,str,str,type[ToolArguments],bool,int,int|None,int|None]] = [
    ("list_research_capabilities","system","Research capabilities",ToolArguments,False,600,None,None),
    ("get_portfolio_summary","portfolio","Portfolio summary",PortfolioArguments,True,30,None,None),("get_portfolio_positions","portfolio","Portfolio positions",PortfolioPositionsArguments,True,30,50,None),("get_position_detail","portfolio","Position detail",PositionArguments,True,30,None,None),("get_trade_history","portfolio","Trade history",TradeArguments,True,30,100,3660),("get_portfolio_risk_analysis","portfolio","Portfolio risk analysis",PortfolioArguments,True,30,20,None),
    ("get_portfolio_overview","portfolio","Unified portfolio overview",PortfolioArguments,True,30,None,None),("get_portfolio_performance","portfolio","Cash-flow-adjusted portfolio performance",PortfolioDateArguments,True,30,100,3660),("get_portfolio_equity_curve","portfolio","Portfolio equity curve",PortfolioDateArguments,True,30,100,3660),("get_portfolio_drawdown","portfolio","Portfolio drawdown",PortfolioDateArguments,True,30,100,3660),("get_portfolio_return_attribution","portfolio","Portfolio return attribution",PortfolioDateArguments,True,30,100,3660),("get_position_performance","portfolio","Personal position performance",PositionArguments,True,30,100,None),("get_position_transaction_timeline","portfolio","Position transaction timeline",PositionArguments,True,30,100,None),("get_position_open_lots","portfolio","Position open lots",PositionArguments,True,30,100,None),("get_completed_trades","portfolio","Completed position trades",PositionArguments,True,30,100,None),
    ("get_trade_statistics","portfolio","Trade statistics",PortfolioDateArguments,True,30,100,3660),("get_dividend_history","portfolio","Dividend history",PortfolioDateArguments,True,30,100,3660),("get_fee_and_tax_summary","portfolio","Fee and tax summary",PortfolioDateArguments,True,30,100,3660),("get_cash_flow_summary","portfolio","External cash flow summary",PortfolioDateArguments,True,30,100,3660),("get_currency_exposure","portfolio","Currency exposure",PortfolioArguments,True,30,50,None),
    ("get_company_profile","company","Company profile",SymbolArguments,False,600,None,None),("get_company_snapshot","company","Company snapshot",CompanySnapshotArguments,True,30,None,None),("get_company_peers","company","Company peers",PeersArguments,False,600,100,None),
    ("get_latest_price","market","Latest persisted market snapshot",SymbolArguments,False,30,None,None),("get_price_history","market","Price history",PriceHistoryArguments,False,60,100,3660),("compare_price_performance","market","Compare price performance",ComparePriceArguments,False,60,10,3660),("get_market_context","market","Market context",ToolArguments,True,120,None,None),
    ("get_latest_news","news","Latest stored news",NewsArguments,False,120,50,365),("search_news","news","Search stored news",SearchNewsArguments,False,120,50,3650),("get_news_detail","news","News detail",IdArguments,False,120,None,None),("get_news_archives","news","News archives",ArchiveArguments,False,120,50,3660),
    ("get_sec_filings","sec","SEC filings",SecFilingsArguments,False,600,50,3660),("get_sec_filing_detail","sec","SEC filing detail",FilingIdArguments,False,600,None,None),("get_sec_events","sec","SEC events",SecEventsArguments,False,600,50,3660),("get_sec_financial_facts","sec","SEC financial facts",SecFactsArguments,False,600,100,3660),("get_insider_trades","sec","Insider trades",InsiderArguments,False,600,50,3660),("get_institutional_holdings","sec","Institutional holdings",InstitutionalArguments,False,600,50,None),("get_company_ownership_activity","ownership","Company ownership activity",OwnershipArguments,False,600,100,3660),
    ("get_financial_summary","financials","Financial summary",FinancialSummaryArguments,False,600,20,None),("get_financial_statements","financials","Financial statements",StatementArguments,False,600,20,None),("compare_financial_metrics","financials","Compare financial metrics",FinancialCompareArguments,False,600,10,None),("get_financial_trends","financials","Financial trends",FinancialTrendsArguments,False,600,20,None),
    ("get_latest_valuation","valuation","Latest valuation",SymbolArguments,False,300,None,None),("get_valuation_history","valuation","Valuation history",ValuationHistoryArguments,False,300,100,3660),("compare_valuations","valuation","Compare valuations",CompareValuationsArguments,False,300,10,None),
    ("get_technical_analysis","technical","Technical analysis with persisted market snapshot",SymbolArguments,False,30,None,None),("get_technical_levels","technical","Technical levels",TechnicalLevelsArguments,False,300,None,None),("compare_technical_signals","technical","Compare technical signals",CompareTechnicalArguments,False,300,10,None),("get_technical_chart_reference","technical","Technical chart reference",SymbolArguments,False,300,None,None),
    ("get_calendar_events","calendar","Calendar events",CalendarArguments,False,120,100,730),("get_calendar_event_detail","calendar","Calendar event detail",EventIdArguments,False,120,None,None),
    ("get_discovery_runs","discovery","Discovery runs",DiscoveryRunsArguments,True,120,50,3660),("get_discovery_run","discovery","Discovery run",RunIdArguments,True,120,None,None),("get_discovery_candidates","discovery","Discovery candidates",CandidateArguments,True,120,50,None),
    ("get_congress_trades","ownership","Congress trades",CongressArguments,False,600,100,3660),("get_tracked_figures","ownership","Tracked figures",FiguresArguments,False,600,100,None),("get_figure_positions","ownership","Figure positions",FigurePositionsArguments,False,600,100,None),("get_public_figure_activity","ownership","Public figure activity",FigureActivityArguments,False,600,100,3660),
    ("get_crypto_research_context","crypto","Crypto research context",CryptoResearchContextArguments,False,60,None,None),
    ("get_crypto_news","crypto","Crypto news",CryptoNewsArguments,False,120,20,30),
    ("get_crypto_reports","crypto","Crypto research reports",CryptoReportsArguments,False,300,20,None),
]


def build_adapters(disabled: set[str] | None = None) -> list[GatewayToolAdapter]:
    disabled=disabled or set(); adapters=[]; settings=get_settings()
    maximum_timeout=min(max(settings.ai_tools_max_timeout_seconds,.1),30.0)
    default_timeout=min(max(settings.ai_tools_default_timeout_seconds,.1),maximum_timeout)
    for name,domain,title,args_model,private,ttl,max_items,max_days in TOOL_SPECS:
        description=(f"Use this tool to retrieve {title.lower()} already stored in stock-monitor. It returns bounded structured data with sources and freshness. "
                     f"Do not use it for real-time data that may not have synchronized yet. It {'contains current-user private data' if private else 'does not expose another user’s private data'}. "
                     "It is read-only and never searches the public web, calls a model, refreshes a provider, triggers paid work, emits signals, or submits paper/test/live orders.")
        definition=ToolDefinition(name=name,domain=domain,title=title,description=description,input_schema=args_model.model_json_schema(),
            output_schema=ToolExecutionResult.model_json_schema(),contains_private_data=private,enabled=name not in disabled,cache_ttl_seconds=ttl,max_items=max_items,max_date_range_days=max_days,
            default_timeout_seconds=default_timeout,max_timeout_seconds=maximum_timeout,tags=[domain,"read-only","stored-data"])
        adapters.append(GatewayToolAdapter(definition,args_model))
    return adapters
