from dataclasses import dataclass
from datetime import UTC, datetime

import yfinance as yf


@dataclass(frozen=True)
class Quote:
    ticker: str
    quote_time: datetime
    price: float
    previous_close: float | None
    volume: int | None


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


def _yf_val(df, key, col):
    if df is None or df.empty or key not in df.index or col not in df.columns:
        return None
    value = df.loc[key, col]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # 过滤 NaN


def fetch_yf_info_metrics(ticker: str) -> dict:
    """yfinance info 里的 Beta / 52周高低（Finnhub 常缺）。注意字段大小写。"""
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return {}
    return {
        "beta": info.get("beta"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
    }


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
