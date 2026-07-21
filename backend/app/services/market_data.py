from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

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
