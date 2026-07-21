"""汇总当日行情、市场环境、基本面指标、分析师评级为报告 evidence 文本。
行情/指数走 yfinance（能拿 volume 和指数），基本面/评级走 Finnhub。
每块独立 try/except，单块失败不影响其余；缺数据标注"数据不足"，绝不编造。"""
import yfinance as yf

from app.services.finnhub_mcp import fetch_basic_metrics, fetch_recommendations
from app.services.volume_stats import volume_context

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
            f"成交量 {_fmt(info.last_volume, '', 0)}{_volume_context(ticker, info.last_volume)}"
        )
    except Exception:
        return "当日行情：数据不足"


def _volume_context(ticker: str, current_volume) -> str:
    """成交量对比语境：30日均量 + 预估全天量 + 量比 + 放量/缩量。追加在成交量数字之后。"""
    try:
        ctx = volume_context(ticker, float(current_volume) if current_volume else None)
    except Exception:
        return ""
    if ctx["label"] is None:
        return ""
    parts = [f"30日均量 {_fmt(ctx['avg_volume'], '', 0)}"]
    if ctx["estimated_full_day"] is not None:
        parts.append(f"预估全天量 {_fmt(ctx['estimated_full_day'], '', 0)}")
    parts.append(f"量比 {_fmt(ctx['ratio'], '倍')}（{ctx['label']}）")
    return "，" + "，".join(parts)


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


def _fundamentals(ticker: str | None) -> str:
    if not ticker:
        return "基本面指标：该数据源暂不支持"
    try:
        metric = fetch_basic_metrics(ticker)
    except Exception:
        return "基本面指标：数据不足"
    if not metric:
        return "基本面指标：数据不足"
    parts = [f"{label} {_fmt(metric.get(key), suffix)}" for key, label, suffix in _METRIC_LABELS if metric.get(key) is not None]
    return "基本面指标：" + ("，".join(parts) if parts else "数据不足")


def _recommendations(ticker: str | None) -> str:
    if not ticker:
        return "分析师评级：该数据源暂不支持"
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


def _insider_trades(ticker: str) -> str:
    """近 90 天 Form 4 内部人大单（高管/5%以上股东两日内申报的巨额交易），带日期。"""
    from datetime import date, timedelta

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import SecInsiderTrade

    code_names = {"P": "买入", "S": "卖出", "M": "期权行权", "A": "授予", "G": "赠予", "D": "处置", "F": "税务代扣"}
    since = date.today() - timedelta(days=90)
    try:
        with SessionLocal() as db:
            rows = db.scalars(
                select(SecInsiderTrade)
                .where(SecInsiderTrade.ticker == ticker.upper(), SecInsiderTrade.transaction_date >= since)
                .order_by(SecInsiderTrade.value.desc().nullslast(), SecInsiderTrade.transaction_date.desc())
                .limit(8)
            ).all()
    except Exception:
        return "内部人交易（近90天）：数据不足"
    if not rows:
        return "内部人交易（近90天）：无"
    parts = []
    for r in rows:
        code = code_names.get(r.transaction_code or "", r.transaction_code or "交易")
        seg = f"{r.transaction_date or '日期不详'} {r.insider_name}"
        if r.insider_title:
            seg += f"（{r.insider_title}）"
        seg += f" {code}"
        if r.shares:
            seg += f" {_fmt(r.shares, '股', 0)}"
        if r.value:
            seg += f"（{_fmt(r.value, '美元', 0)}）"
        if r.flag == "ceo_buy":
            seg += "【CEO买入信号】"
        elif r.flag == "heavy_sell":
            seg += "【大额抛售】"
        parts.append(seg)
    return "内部人交易（近90天，Form 4）：" + "；".join(parts)


def _institutional_holdings(ticker: str) -> str:
    """13F 机构持仓：最新季度前几大持有机构 + 相对上一季度的增减，带季度日期。"""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Sec13FHolding

    try:
        with SessionLocal() as db:
            latest_period = db.scalar(
                select(Sec13FHolding.report_period)
                .where(Sec13FHolding.ticker == ticker.upper())
                .order_by(Sec13FHolding.report_period.desc())
                .limit(1)
            )
            if latest_period is None:
                return "机构持仓（13F）：数据不足"
            rows = db.scalars(
                select(Sec13FHolding)
                .where(Sec13FHolding.ticker == ticker.upper(), Sec13FHolding.report_period == latest_period)
                .order_by(Sec13FHolding.value_usd.desc().nullslast())
                .limit(8)
            ).all()
            prev_period = db.scalar(
                select(Sec13FHolding.report_period)
                .where(Sec13FHolding.ticker == ticker.upper(), Sec13FHolding.report_period < latest_period)
                .order_by(Sec13FHolding.report_period.desc())
                .limit(1)
            )
            prev_shares: dict[str, float] = {}
            if prev_period is not None:
                prev_rows = db.scalars(
                    select(Sec13FHolding).where(
                        Sec13FHolding.ticker == ticker.upper(), Sec13FHolding.report_period == prev_period
                    )
                ).all()
                for r in prev_rows:
                    if r.shares is not None:
                        prev_shares[r.manager_name] = prev_shares.get(r.manager_name, 0.0) + r.shares
    except Exception:
        return "机构持仓（13F）：数据不足"
    if not rows:
        return "机构持仓（13F）：数据不足"
    parts = []
    for r in rows:
        seg = r.manager_name
        if r.shares:
            seg += f" 持 {_fmt(r.shares, '股', 0)}"
        if r.value_usd:
            seg += f"（市值 {_fmt(r.value_usd, '美元', 0)}）"
        if r.put_call:
            seg += f"[{r.put_call}]"
        prev = prev_shares.get(r.manager_name)
        if prev is not None and r.shares is not None:
            delta = r.shares - prev
            if abs(delta) > 0:
                seg += f"，环比{'增持' if delta > 0 else '减持'} {_fmt(abs(delta), '股', 0)}"
        elif prev is None and prev_period is not None:
            seg += "，本季新建仓"
        parts.append(seg)
    return f"机构持仓（13F，季度截至 {latest_period}）：" + "；".join(parts)


def build_market_context(ticker: str, finnhub_symbol: str | None = None) -> str:
    """返回注入报告 evidence 的市场上下文 markdown 块。"""
    blocks = [
        _day_quote(ticker),
        _market_env(),
        _fundamentals(finnhub_symbol),
        _recommendations(finnhub_symbol),
        _insider_trades(ticker),
        _institutional_holdings(ticker),
    ]
    return "\n\n# 市场与基本面数据\n" + "\n".join(f"- {b}" for b in blocks)
