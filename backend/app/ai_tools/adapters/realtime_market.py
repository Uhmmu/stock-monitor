"""Read-only semantic AI tools for server-owned realtime market state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator
from sqlalchemy import select

from app.api.market_routes import realtime_value
from app.models import Portfolio
from app.research.security import normalize_symbol
from app.services.intraday_market import bar_out, event_out, intraday_bars, intraday_summary, monitor_events
from app.services.portfolio.performance import build_summary

from ..schemas import AdapterResult, SymbolArguments, ToolArguments, ToolDefinition, ToolExecutionResult
from .base import BaseToolAdapter


class RealtimeSymbolsArguments(ToolArguments):
    symbols: list[str] = Field(min_length=1, max_length=20)

    @field_validator("symbols")
    @classmethod
    def clean(cls, values):
        return list(dict.fromkeys(normalize_symbol(value) for value in values))


class IntradayArguments(SymbolArguments):
    interval: Literal["1m", "5m", "15m"] = "1m"
    period: Literal["1d", "5d"] = "1d"
    limit: int = Field(500, ge=1, le=2000)


class MarketEventsArguments(ToolArguments):
    symbols: list[str] = Field(default_factory=list, max_length=20)
    since: datetime | None = None
    limit: int = Field(100, ge=1, le=500)

    @field_validator("symbols")
    @classmethod
    def clean(cls, values):
        return list(dict.fromkeys(normalize_symbol(value) for value in values))


class RealtimeToolAdapter(BaseToolAdapter):
    def __init__(self, definition: ToolDefinition, arguments_model, action: str):
        self.definition = definition
        self.arguments_model = arguments_model
        self.action = action

    async def execute(self, args, context, gateway):
        db = gateway.db
        if self.action == "quote":
            value = realtime_value(db, args.symbol)
            return _quote_result(args.symbol, value)
        if self.action == "quotes":
            values = {symbol: realtime_value(db, symbol) for symbol in args.symbols}
            return AdapterResult(
                data={"quotes": values, "missing": [key for key, value in values.items() if value is None]},
                summary=f"Returned server-owned realtime state for {sum(value is not None for value in values.values())} of {len(values)} symbols.",
                sources=_quote_sources([value for value in values.values() if value]),
                partial=any(value is None or value.get("stale") for value in values.values()),
            )
        if self.action == "bars":
            now = datetime.now(UTC); start = now - timedelta(days=5 if args.period == "5d" else 1)
            rows = intraday_bars(db, args.symbol, interval=args.interval, start=start, end=now, limit=args.limit)
            return AdapterResult(
                data={"symbol": args.symbol, "interval": args.interval, "period": args.period, "bars": [bar_out(row) for row in rows]},
                summary=f"Returned {len(rows)} persisted {args.interval} intraday bars for {args.symbol}.",
                sources=[{"provider": row.provider, "feed": row.feed, "source_type": "intraday_bar"} for row in rows[-3:]],
                partial=not bool(rows),
            )
        if self.action == "summary":
            value = intraday_summary(db, args.symbol)
            return AdapterResult(data=value, summary=f"Returned persisted intraday summary for {args.symbol}.", partial=not value.get("available"))
        if self.action in {"state", "anomalies"}:
            quote = realtime_value(db, args.symbol)
            summary = intraday_summary(db, args.symbol)
            rows = monitor_events(db, symbols=[args.symbol], since=datetime.now(UTC) - timedelta(days=1), limit=100)
            data = {"symbol": args.symbol, "quote": quote, "intraday_summary": summary, "events": [event_out(row) for row in rows]}
            if self.action == "anomalies":
                data = {"symbol": args.symbol, "events": data["events"], "through": datetime.now(UTC)}
            return AdapterResult(
                data=data, summary=f"Returned persisted intraday {'anomalies' if self.action == 'anomalies' else 'market state'} for {args.symbol}.",
                sources=_quote_sources([quote] if quote else []) + [{"source_type": "market_monitor_event", "authority": "deterministic"}],
                partial=quote is None or bool(quote and quote.get("stale")),
            )
        if self.action == "events":
            rows = monitor_events(db, symbols=args.symbols, since=args.since, limit=args.limit)
            return AdapterResult(
                data={"events": [event_out(row) for row in rows], "count": len(rows)},
                summary=f"Returned {len(rows)} persisted deterministic market monitor events.",
                sources=[{"source_type": "market_monitor_event", "authority": "deterministic"}],
            )
        if self.action == "portfolio":
            portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == context.user_id, Portfolio.slug == "default").limit(1))
            if portfolio is None:
                return AdapterResult(data={"available": False, "reason": "portfolio_not_found"}, summary="No default portfolio exists for the current user.", partial=True)
            value = build_summary(db, portfolio, cached_fx_only=True)
            return AdapterResult(
                data=value, summary="Returned current-user portfolio valuation using realtime state when fresh and persisted fallbacks otherwise.",
                sources=[{"source_type": "realtime_quote_or_persisted_fallback", "authority": "market_price"}, {"source_type": "portfolio_positions", "authority": "quantity_and_cost"}],
                partial=value.get("has_unpriced_positions", False) or value.get("has_unconverted_positions", False),
            )
        raise RuntimeError("unknown realtime tool action")


def _quote_sources(values):
    result = []
    for value in values:
        quote = (value or {}).get("authoritative_quote") or {}
        item = {"provider": quote.get("provider"), "feed": quote.get("feed"), "source_type": (value or {}).get("source_type")}
        if item not in result:
            result.append(item)
        for alt in (value or {}).get("alternate_quotes") or []:
            ref = {"provider": alt.get("provider"), "feed": alt.get("feed"), "source_type": "realtime_reference"}
            if ref not in result:
                result.append(ref)
    return result


def _quote_result(symbol, value):
    warnings = []
    quote = (value or {}).get("authoritative_quote") or {}
    if value and value.get("stale"):
        warnings.append({"code": "SOURCE_STALE", "message": "Realtime state is stale; treat it as a fallback, not a live quote.", "severity": "warning"})
    if quote.get("is_delayed"):
        warnings.append({"code": "SOURCE_DELAYED", "message": "The provider marks this quote as delayed.", "severity": "warning"})
    return AdapterResult(
        data=value or {"symbol": symbol, "available": False},
        summary=f"Returned server-owned realtime market state for {symbol}." if value else f"No realtime or persisted quote was available for {symbol}.",
        sources=_quote_sources([value] if value else []), warnings=warnings,
        partial=value is None or bool(value and value.get("stale")),
    )


def build_realtime_market_adapters(disabled: set[str] | None = None):
    disabled = disabled or set()
    specs = [
        ("get_realtime_quote", "Realtime quote with provider provenance and delayed/stale flags", SymbolArguments, "quote", False, 2),
        ("get_realtime_quotes", "Realtime quotes for a bounded list with independent provider fallbacks", RealtimeSymbolsArguments, "quotes", False, 2),
        ("get_intraday_bars", "Persisted normalized intraday OHLCV bars without live provider calls", IntradayArguments, "bars", False, 10),
        ("get_intraday_summary", "Deterministic summary calculated from persisted normalized intraday bars", SymbolArguments, "summary", False, 10),
        ("get_intraday_market_state", "Combined quote, persisted intraday summary, and deterministic monitor events", SymbolArguments, "state", False, 5),
        ("get_intraday_anomalies", "Cooldown-controlled deterministic intraday anomaly and crossover events", SymbolArguments, "anomalies", False, 5),
        ("get_market_monitor_events", "Persisted monitor events filtered by symbols and optional timestamp", MarketEventsArguments, "events", False, 5),
        ("get_realtime_portfolio_state", "Current-user positions valued by market prices without changing IBKR authority", ToolArguments, "portfolio", True, 2),
    ]
    output = []
    for name, title, args_model, action, private, ttl in specs:
        definition = ToolDefinition(
            name=name, domain="portfolio" if private else "market", title=title,
            description=f"Use this read-only tool to retrieve {title.lower()} from stock-monitor. It never exposes provider credentials, changes portfolio authority, places trades, or triggers paid provider work; unavailable fields remain null.",
            input_schema=args_model.model_json_schema(), output_schema=ToolExecutionResult.model_json_schema(),
            contains_private_data=private, enabled=name not in disabled, cache_ttl_seconds=ttl,
            default_timeout_seconds=5, max_timeout_seconds=10, max_items=100 if action in {"bars", "events"} else None,
            tags=["market", "realtime", "read-only"],
        )
        output.append(RealtimeToolAdapter(definition, args_model, action))
    return output
