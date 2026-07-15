"""汇总当日行情、市场环境、基本面指标、分析师评级为报告 evidence 文本。
行情/指数走 yfinance（能拿 volume 和指数），基本面/评级走 Finnhub。
每块独立 try/except，单块失败不影响其余；缺数据标注"数据不足"，绝不编造。"""
import yfinance as yf

from app.services.finnhub_mcp import fetch_basic_metrics, fetch_recommendations

_INDICES = [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道琼斯")]


def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "数据不足"
    try:
        return f"{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "数据不足"


def _day_quote(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).fast_info
        last = info.last_price
        prev = info.previous_close
        if last is None:
            return "当日行情：数据不足"
        change = ((last - prev) / prev * 100) if prev else None
        return (
            f"当日行情：现价 {_fmt(last)}，昨收 {_fmt(prev)}，"
            f"涨跌 {_fmt(change, '%')}，开 {_fmt(info.open)}，"
            f"日内高 {_fmt(info.day_high)}，日内低 {_fmt(info.day_low)}，"
            f"成交量 {_fmt(info.last_volume, '', 0)}"
        )
    except Exception:
        return "当日行情：数据不足"


def _market_env() -> str:
    parts = []
    for symbol, name in _INDICES:
        try:
            info = yf.Ticker(symbol).fast_info
            last, prev = info.last_price, info.previous_close
            change = ((last - prev) / prev * 100) if (last and prev) else None
            parts.append(f"{name} {_fmt(last)}（{_fmt(change, '%')}）")
        except Exception:
            parts.append(f"{name} 数据不足")
    return "市场环境：" + "，".join(parts)


_METRIC_LABELS = [
    ("peTTM", "P/E(TTM)", ""), ("pbAnnual", "P/B", ""), ("psTTM", "P/S(TTM)", ""),
    ("grossMarginTTM", "毛利率", "%"), ("netProfitMarginTTM", "净利率", "%"),
    ("operatingMarginTTM", "营业利润率", "%"), ("roeTTM", "ROE", "%"), ("roaTTM", "ROA", "%"),
    ("revenueGrowthTTMYoy", "营收增速(YoY)", "%"), ("epsGrowthTTMYoy", "EPS增速(YoY)", "%"),
    ("beta", "Beta", ""), ("52WeekHigh", "52周高", ""), ("52WeekLow", "52周低", ""),
]


def _fundamentals(ticker: str) -> str:
    try:
        metric = fetch_basic_metrics(ticker)
    except Exception:
        return "基本面指标：数据不足"
    if not metric:
        return "基本面指标：数据不足"
    parts = [f"{label} {_fmt(metric.get(key), suffix)}" for key, label, suffix in _METRIC_LABELS if metric.get(key) is not None]
    return "基本面指标：" + ("，".join(parts) if parts else "数据不足")


def _recommendations(ticker: str) -> str:
    try:
        rows = fetch_recommendations(ticker)
    except Exception:
        return "分析师评级：数据不足"
    if not rows:
        return "分析师评级：数据不足"
    latest = rows[0]
    return (
        f"分析师评级（{latest.get('period', '近期')}）："
        f"强烈买入 {latest.get('strongBuy', 0)}，买入 {latest.get('buy', 0)}，"
        f"持有 {latest.get('hold', 0)}，卖出 {latest.get('sell', 0)}，"
        f"强烈卖出 {latest.get('strongSell', 0)}"
    )


def build_market_context(ticker: str) -> str:
    """返回注入报告 evidence 的市场上下文 markdown 块。"""
    blocks = [_day_quote(ticker), _market_env(), _fundamentals(ticker), _recommendations(ticker)]
    return "\n\n# 市场与基本面数据\n" + "\n".join(f"- {b}" for b in blocks)

