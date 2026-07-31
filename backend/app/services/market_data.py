from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import yfinance as yf


@dataclass(frozen=True)
class Quote:
    ticker: str
    quote_time: datetime
    price: float
    previous_close: float | None
    volume: int | None


@dataclass(frozen=True)
class LiveQuote:
    """An on-demand Yahoo chart quote with the provider's market timestamp."""

    ticker: str
    quote_time: datetime
    retrieved_at: datetime
    trading_date: date
    price: float
    regular_market_price: float | None
    previous_close: float | None
    open: float | None
    day_high: float | None
    day_low: float | None
    volume: int | None
    currency: str | None
    exchange: str | None
    average_volume_10d: float | None
    average_volume_20d: float | None
    market_status: str
    quote_session: str
    timestamp_source: str = "provider"
    is_delayed: bool | None = None
    delay_seconds: int | None = None
    raw_payload: dict[str, Any] | None = None
    source: str = "yahoo_chart_1m"


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _epoch(value: Any) -> datetime | None:
    number = _finite_float(value)
    return datetime.fromtimestamp(number, UTC) if number is not None else None


def _quote_session(moment: datetime, periods: dict[str, Any]) -> str:
    timestamp = moment.timestamp()
    has_period = False
    for key, label in (("pre", "pre_market"), ("regular", "regular"), ("post", "after_hours")):
        period = periods.get(key) or {}
        start, end = _finite_float(period.get("start")), _finite_float(period.get("end"))
        if start is not None and end is not None:
            has_period = True
            if start <= timestamp <= end:
                return label
    return "closed" if has_period else "unknown"


def _current_market_status(moment: datetime, periods: dict[str, Any]) -> str:
    session = _quote_session(moment, periods)
    return "open" if session == "regular" else session


def fetch_live_quote(ticker: str) -> LiveQuote:
    """Fetch the latest tradable quote on demand.

    The one-minute Yahoo chart is preferred over ``fast_info`` because its row
    index is the provider's actual quote time. Extended-hours rows are included.
    Callers can therefore distinguish quote time from retrieval time instead of
    presenting a request timestamp as if it were a trade timestamp.
    """
    symbol = ticker.strip().upper()
    stock = yf.Ticker(symbol)
    frame = stock.history(
        period="1d",
        interval="1m",
        prepost=True,
        auto_adjust=False,
        timeout=6,
    )
    retrieved_at = datetime.now(UTC)
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError(f"no live quote rows for {symbol}")
    closes = frame["Close"].dropna()
    if closes.empty:
        raise ValueError(f"no valid live quote price for {symbol}")

    last_index = closes.index[-1]
    trading_date = last_index.date()
    quote_time = last_index.to_pydatetime()
    if quote_time.tzinfo is None:
        quote_time = quote_time.replace(tzinfo=UTC)
    quote_time = quote_time.astimezone(UTC)
    price = _finite_float(closes.iloc[-1])
    if price is None or price <= 0:
        raise ValueError(f"invalid live quote price for {symbol}")

    metadata = stock.history_metadata or {}
    periods = metadata.get("currentTradingPeriod") or {}
    regular_market_time = _epoch(metadata.get("regularMarketTime"))
    regular_price = _finite_float(metadata.get("regularMarketPrice"))
    if regular_market_time and quote_time <= regular_market_time and regular_price is not None:
        price, quote_time = regular_price, regular_market_time

    regular_frame = None
    regular_period = periods.get("regular") or {}
    regular_start = _finite_float(regular_period.get("start"))
    regular_end = _finite_float(regular_period.get("end"))
    if regular_start is not None and regular_end is not None:
        regular_mask = [
            regular_start <= index.to_pydatetime().timestamp() <= regular_end
            for index in frame.index
        ]
        regular_frame = frame.loc[regular_mask]
        if regular_frame.empty:
            regular_frame = None

    def _regular_value(column: str, operation: str) -> float | None:
        if regular_frame is None or column not in regular_frame:
            return None
        values = regular_frame[column].dropna()
        if values.empty:
            return None
        if operation == "first":
            return _finite_float(values.iloc[0])
        if operation == "max":
            return _finite_float(values.max())
        if operation == "min":
            return _finite_float(values.min())
        if operation == "sum":
            return _finite_float(values.sum())
        return None

    open_price = _finite_float(metadata.get("regularMarketOpen"))
    day_high = _finite_float(metadata.get("regularMarketDayHigh"))
    day_low = _finite_float(metadata.get("regularMarketDayLow"))
    volume = _finite_float(metadata.get("regularMarketVolume"))
    open_price = open_price or _regular_value("Open", "first")
    day_high = day_high or _regular_value("High", "max")
    day_low = day_low or _regular_value("Low", "min")
    volume = volume or _regular_value("Volume", "sum")
    daily = stock.history(
        period="1mo",
        interval="1d",
        prepost=False,
        auto_adjust=False,
        timeout=6,
    )
    historical_volumes: list[float] = []
    if daily is not None and not daily.empty and "Volume" in daily:
        for index, value in daily["Volume"].dropna().items():
            point_date = index.date() if hasattr(index, "date") else None
            number = _finite_float(value)
            if point_date != trading_date and number is not None and number > 0:
                historical_volumes.append(number)
    average_10d = (
        sum(historical_volumes[-10:]) / len(historical_volumes[-10:])
        if historical_volumes[-10:]
        else None
    )
    average_20d = (
        sum(historical_volumes[-20:]) / len(historical_volumes[-20:])
        if historical_volumes[-20:]
        else None
    )
    reported_delay = _finite_float(metadata.get("exchangeDataDelayedBy"))
    return LiveQuote(
        ticker=symbol,
        quote_time=quote_time,
        retrieved_at=retrieved_at,
        trading_date=trading_date,
        price=price,
        regular_market_price=regular_price,
        previous_close=_finite_float(metadata.get("previousClose") or metadata.get("chartPreviousClose")),
        open=open_price,
        day_high=day_high,
        day_low=day_low,
        volume=int(volume) if volume is not None else None,
        currency=str(metadata["currency"]) if metadata.get("currency") else None,
        exchange=str(metadata.get("fullExchangeName") or metadata.get("exchangeName") or "") or None,
        average_volume_10d=average_10d,
        average_volume_20d=average_20d,
        market_status=_current_market_status(retrieved_at, periods),
        quote_session=_quote_session(quote_time, periods),
        is_delayed=reported_delay > 0 if reported_delay is not None else None,
        delay_seconds=int(reported_delay * 60) if reported_delay is not None else None,
        raw_payload={
            key: metadata.get(key)
            for key in (
                "currency",
                "symbol",
                "exchangeName",
                "fullExchangeName",
                "regularMarketTime",
                "regularMarketPrice",
                "regularMarketDayHigh",
                "regularMarketDayLow",
                "regularMarketVolume",
                "previousClose",
                "exchangeDataDelayedBy",
            )
            if metadata.get(key) is not None
        },
    )


def fetch_earnings_events(tickers: list[str]) -> list[tuple[str, datetime]]:
    events: list[tuple[str, datetime]] = []
    for ticker in tickers:
        dates = yf.Ticker(ticker).get_earnings_dates(limit=4)
        if dates is None or dates.empty:
            continue
        for value in dates.index:
            moment = value.to_pydatetime()
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            events.append((ticker, moment.astimezone(UTC)))
    return events


_YF_INCOME = {
    "revenue": "Total Revenue", "cost_of_revenue": "Cost Of Revenue",
    "gross_profit": "Gross Profit", "operating_income": "Operating Income",
    "net_income": "Net Income", "eps": "Diluted EPS",
}
_YF_CASHFLOW = {"operating_cash_flow": "Operating Cash Flow", "free_cash_flow": "Free Cash Flow"}

# 同一经济含义在 Yahoo / yfinance 版本和不同行业中可能使用不同名称。
_STATEMENT_FIELDS = {
    "income_statement": {
        "revenue": ("Total Revenue", "Operating Revenue"), "gross_profit": ("Gross Profit",),
        "operating_income": ("Operating Income", "EBIT"), "net_income": ("Net Income", "Net Income Common Stockholders"),
        "pretax_income": ("Pretax Income", "Income Before Tax"), "tax_expense": ("Tax Provision", "Income Tax Expense"),
        "eps": ("Diluted EPS", "DilutedEPS"), "ebitda": ("EBITDA",),
    },
    "balance_sheet": {
        "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"),
        "inventory": ("Inventory",), "current_assets": ("Current Assets", "Total Current Assets"),
        "current_liabilities": ("Current Liabilities", "Total Current Liabilities"), "total_assets": ("Total Assets",),
        "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liabilities"), "total_debt": ("Total Debt",),
        "long_term_debt": ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
        "shareholders_equity": ("Stockholders Equity", "Common Stock Equity"), "retained_earnings": ("Retained Earnings",),
        "shares_issued": ("Ordinary Shares Number", "Share Issued"),
    },
    "cash_flow": {
        "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
        "capital_expenditure": ("Capital Expenditure", "Capital Expenditures"),
        "free_cash_flow": ("Free Cash Flow",), "financing_cash_flow": ("Financing Cash Flow", "Cash Flow From Continuing Financing Activities"),
        "investing_cash_flow": ("Investing Cash Flow", "Cash Flow From Continuing Investing Activities"),
        "depreciation": ("Depreciation", "Depreciation And Amortization"),
        "amortization": ("Amortization", "Amortization Of Intangibles"),
    },
}


def _yf_val(df, key, col):
    if df is None or df.empty or key not in df.index or col not in df.columns:
        return None
    value = df.loc[key, col]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # 过滤 NaN


def _statement_value(df: Any, aliases: tuple[str, ...], column: Any) -> float | None:
    if df is None or df.empty or column not in df.columns:
        return None
    rows = {"".join(char.lower() for char in str(row) if char.isalnum()): row for row in df.index}
    for alias in aliases:
        row = rows.get("".join(char.lower() for char in alias if char.isalnum()))
        if row is not None:
            return _yf_val(df, row, column)
    return None


def _period_label(period_end: str, frequency: str) -> tuple[int, str]:
    point = datetime.fromisoformat(period_end).date()
    return point.year, ("FY" if frequency == "annual" else f"Q{(point.month - 1) // 3 + 1}")


def fetch_yf_financial_statements(ticker: str, frequency: str) -> list[dict]:
    """读取 Yahoo 三表并标准化核心展示行；缺失字段显式保留为 None。

    Yahoo 的资本开支通常为负数，展示时保持原值；缺少 FCF 时按 OCF - CapEx（负数 CapEx 等价于相加）补算。
    """
    stock = yf.Ticker(ticker)
    if frequency == "annual":
        income, balance, cashflow = stock.income_stmt, stock.balance_sheet, stock.cash_flow
    elif frequency == "quarterly":
        income, balance, cashflow = stock.quarterly_income_stmt, stock.quarterly_balance_sheet, stock.quarterly_cash_flow
    else:
        raise ValueError("frequency must be annual or quarterly")
    columns: dict[str, Any] = {}
    for statement in (income, balance, cashflow):
        if statement is not None and not statement.empty:
            for column in statement.columns:
                columns[str(column)[:10]] = column
    rows: list[dict] = []
    for period_end, column in sorted(columns.items(), reverse=True):
        statements = {}
        for name, fields in _STATEMENT_FIELDS.items():
            dataframe = {"income_statement": income, "balance_sheet": balance, "cash_flow": cashflow}[name]
            statements[name] = {field: _statement_value(dataframe, aliases, column) for field, aliases in fields.items()}
        cash = statements["cash_flow"]
        income_values = statements["income_statement"]
        if income_values["ebitda"] is None and income_values["operating_income"] is not None:
            depreciation, amortization = cash["depreciation"], cash["amortization"]
            if depreciation is not None or amortization is not None:
                income_values["ebitda"] = income_values["operating_income"] + (depreciation or 0) + (amortization or 0)
        if cash["free_cash_flow"] is None and cash["operating_cash_flow"] is not None and cash["capital_expenditure"] is not None:
            capex = cash["capital_expenditure"]
            cash["free_cash_flow"] = cash["operating_cash_flow"] + capex if capex < 0 else cash["operating_cash_flow"] - capex
        if not any(value is not None for group in statements.values() for value in group.values()):
            continue
        fiscal_year, fiscal_period = _period_label(period_end, frequency)
        rows.append({"period_end": date.fromisoformat(period_end), "fiscal_year": fiscal_year, "fiscal_period": fiscal_period, "currency": None, **statements})
    return rows


def fetch_yf_info_metrics(ticker: str) -> dict:
    """Return the Yahoo fields used by the fundamentals screen.

    Keep Yahoo's native units here.  The API layer normalizes ratios to percent
    and market cap to millions so it can safely merge optional Finnhub values.
    """
    try:
        info = yf.Ticker(ticker).get_info() or {}
    except Exception:
        return {}
    keys = (
        "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
        "grossMargins", "profitMargins", "operatingMargins", "returnOnEquity",
        "returnOnAssets", "revenueGrowth", "earningsGrowth", "marketCap", "beta",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currency", "regularMarketPrice",
    )
    return {key: info.get(key) for key in keys}


def fetch_yf_recommendations(ticker: str) -> list[dict]:
    """Return Yahoo's current analyst recommendation summary when available."""
    try:
        rows = yf.Ticker(ticker).recommendations_summary
    except Exception:
        return []
    if rows is None or rows.empty:
        return []
    expected = ("period", "strongBuy", "buy", "hold", "sell", "strongSell")
    return [{key: row.get(key) for key in expected} for row in rows.to_dict("records")]


def fetch_stock_profile(ticker: str) -> dict:
    """验证代码并读取基础资料；报价或名称均不存在时视为无效代码。"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.get_info() or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            price = stock.fast_info.last_price
    except Exception:
        return {}
    if not (info.get("symbol") or info.get("shortName") or info.get("longName") or price is not None):
        return {}
    return info


def fetch_yf_quarterly(ticker: str) -> list[dict]:
    """yfinance 季度财报：单季值（无需去累计），合并利润表+现金流，按季度末倒序。"""
    stock = yf.Ticker(ticker)
    income = stock.quarterly_income_stmt
    cashflow = stock.quarterly_cashflow
    cols = set()
    for df in (income, cashflow):
        if df is not None and not df.empty:
            cols.update(str(c)[:10] for c in df.columns)
    rows: list[dict] = []
    for col_str in sorted(cols, reverse=True):
        import pandas as pd

        col = pd.Timestamp(col_str)
        row = {"period_end": col_str}
        for field_name, yf_key in _YF_INCOME.items():
            row[field_name] = _yf_val(income, yf_key, col)
        for field_name, yf_key in _YF_CASHFLOW.items():
            row[field_name] = _yf_val(cashflow, yf_key, col)
        if row.get("revenue") is None and row.get("net_income") is None:
            continue
        rows.append(row)
    return rows


_MARKET_INDICES = [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道琼斯")]


def fetch_index_quotes() -> list[dict]:
    """三大指数实时点位与涨跌（yfinance 免费源）。单个失败标 None，绝不编造。"""
    out: list[dict] = []
    for symbol, name in _MARKET_INDICES:
        price = previous = None
        try:
            info = yf.Ticker(symbol).fast_info
            last, prev = info.last_price, info.previous_close
            price = float(last) if last else None
            previous = float(prev) if prev else None
        except Exception:
            pass
        change_points = (price - previous) if (price is not None and previous) else None
        change_percent = (change_points / previous * 100) if (change_points is not None and previous) else None
        out.append({
            "symbol": symbol,
            "name": name,
            "price": price,
            "previous_close": previous,
            "change_points": change_points,
            "change_percent": change_percent,
        })
    return out


def fetch_quotes(tickers: list[str]) -> list[Quote]:
    quotes: list[Quote] = []
    for ticker in tickers:
        info = yf.Ticker(ticker).fast_info
        price = info.last_price
        if price is None:
            continue
        previous_close = info.previous_close
        volume = info.last_volume
        quotes.append(
            Quote(
                ticker=ticker,
                quote_time=datetime.now(UTC),
                price=float(price),
                previous_close=float(previous_close) if previous_close else None,
                volume=int(volume) if volume else None,
            )
        )
    return quotes


# 技术分析的日线 EOD 历史来源（yfinance 免费源）。校验规则与 fmp_market.parse_history 对齐：
# 只保留正价、high>=low、OHLC 自洽的交易日，绝不编造缺失字段。
_HISTORY_MAX_DAYS = 5 * 366 + 10


def _hist_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def fetch_daily_history(
    ticker: str, *, today: date | None = None, period: str = "5y"
) -> list[dict]:
    """拉取约 5 年日线 EOD，返回按日期升序、字段与 HistoricalPrice 对齐的候选行（source=yahoo）。

    Yahoo 不提供 vwap，vwap 留空由周聚合按 (H+L+C)/3 兜底；change/change_percent 由收盘价日环比推导。
    """
    symbol = ticker.upper()
    frame = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
    if frame is None or frame.empty:
        return []
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=_HISTORY_MAX_DAYS)
    unique: dict[date, dict] = {}
    prev_close: Decimal | None = None
    for index, raw in frame.iterrows():
        try:
            day = index.date()
        except AttributeError:
            continue
        if not isinstance(day, date) or day < cutoff:
            continue
        o, h, low, close = (
            _hist_decimal(raw.get(key)) for key in ("Open", "High", "Low", "Close")
        )
        volume = _hist_decimal(raw.get("Volume"))
        if None in (o, h, low, close) or min(o, h, low, close) <= 0 or h < low:
            prev_close = None
            continue
        if o > h or o < low or close > h or close < low or (volume is not None and volume < 0):
            prev_close = None
            continue
        # 量化到列精度 Numeric(_, 6)，避免 upsert 因浮点/精度差异误判"已变化"。
        _q = Decimal("0.000001")
        change = (close - prev_close).quantize(_q) if prev_close and prev_close > 0 else None
        change_percent = (
            (close - prev_close) / prev_close * 100
        ).quantize(_q) if prev_close and prev_close > 0 else None
        unique[day] = {
            "symbol": symbol,
            "date": day,
            "open": o,
            "high": h,
            "low": low,
            "close": close,
            "volume": int(volume) if volume is not None else None,
            "vwap": None,
            "change": change,
            "change_percent": change_percent,
            "source": "yahoo",
        }
        prev_close = close
    return [unique[key] for key in sorted(unique)]
