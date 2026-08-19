"""Historical valuation series (P/E) from stored data — no upstream calls at read time.

价格侧：`historical_prices.close`（FMP 主源，已是拆股复权、非股息复权口径）。
EPS 侧：`sec_eps_facts`（SEC XBRL companyconcept 的 diluted EPS 首次披露事实，含 first_filed），
构建 point-in-time TTM：每个交易日使用「当时已公开的最近四个连续财季」的 diluted EPS 之和，
彻底避免 look-ahead bias 与 fiscal-period-end 泄露。

拆股一致性：SEC as-reported EPS 是当时股本口径。拆股发生后，价格历史（FMP）已复权到当前股本，
而旧财报 EPS 没有；因此按 `stock_splits` 把每条 EPS 折算到当前股本（除以披露日之后的累计拆股系数）。
若某次拆股后存量价格序列尚未复权（增量同步只写近 14 天的场景），用拆股日前后中位价格比检测并就地折算。
"""
import logging
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, SecEpsFact, SecFiling, StockSplit
from app.services.sec_edgar import _get_json, _ticker_cik_map

logger = logging.getLogger(__name__)

RANGE_YEARS = {"3y": 3, "5y": 5, "10y": 10, "max": None}
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/EarningsPerShareDiluted.json"
PRICE_SOURCES = ("fmp", "yahoo", "yfinance")

# 期间长度分类（天）：单季 / 9 个月累计 / 全年。52/53 周财年与日历季都落在这些窗口内。
_QUARTER_DAYS = (80, 105)
_NINE_MONTH_DAYS = (240, 300)
_FY_DAYS = (330, 385)


def resolve_cik(db: Session, ticker: str) -> str | None:
    cik = db.scalar(select(SecFiling.cik).where(SecFiling.ticker == ticker).limit(1))
    if cik:
        return cik
    try:
        return _ticker_cik_map().get(ticker)
    except Exception:
        return None


def _parse_eps_facts(payload: dict) -> list[dict]:
    """companyconcept JSON → 去重后的期间事实列表（含派生 Q4）。

    同一期间在多份 filing 重复出现时取 first_filed 最早的一条（首次公开值）。
    """
    units = payload.get("units") or {}
    facts = next(iter(units.values()), [])
    by_period: dict[tuple[str, str], dict] = {}
    for fact in facts:
        try:
            start = date.fromisoformat(str(fact["start"])[:10])
            end = date.fromisoformat(str(fact["end"])[:10])
            filed = date.fromisoformat(str(fact["filed"])[:10])
            value = float(fact["val"])
        except (KeyError, TypeError, ValueError):
            continue
        duration = (end - start).days
        if not (_QUARTER_DAYS[0] <= duration <= _FY_DAYS[1]) or value != value:
            continue
        key = (start.isoformat(), end.isoformat())
        current = by_period.get(key)
        if current is None or filed < current["first_filed"]:
            by_period[key] = {
                "period_start": start, "period_end": end, "duration_days": duration,
                "first_filed": filed, "eps": value,
                "form": str(fact.get("form") or ""),
                "accession_number": str(fact.get("accn") or "") or None,
                "fiscal_year": fact.get("fy"), "fiscal_period": fact.get("fp"),
            }

    periods = list(by_period.values())

    # Q4 通常不单独入账（10-K 报全年，Q4 = FY − 9M YTD）；若 8-K/10-K XBRL 已直接
    # 给出 Q4 单季事实，上面的去重已覆盖，派生只在缺失时补齐。
    quarter_ends = {p["period_end"] for p in periods if _QUARTER_DAYS[0] <= p["duration_days"] <= _QUARTER_DAYS[1]}
    nine_month = [p for p in periods if _NINE_MONTH_DAYS[0] <= p["duration_days"] <= _NINE_MONTH_DAYS[1]]
    for fy in periods:
        if not (_FY_DAYS[0] <= fy["duration_days"] <= _FY_DAYS[1]):
            continue
        if fy["period_end"] in quarter_ends:
            continue
        candidates = [
            nm for nm in nine_month
            if 85 <= (fy["period_end"] - nm["period_end"]).days <= 100
        ]
        if not candidates:
            continue
        nm = max(candidates, key=lambda p: p["period_end"])
        q4 = fy["eps"] - nm["eps"]
        start = nm["period_end"] + timedelta(days=1)
        periods.append({
            "period_start": start, "period_end": fy["period_end"],
            "duration_days": (fy["period_end"] - start).days,
            "first_filed": max(fy["first_filed"], nm["first_filed"]),
            "eps": q4, "form": fy["form"], "accession_number": fy["accession_number"],
            "fiscal_year": fy["fiscal_year"], "fiscal_period": fy["fiscal_period"],
            "derived": True,
        })
    return periods


def fetch_eps_facts(ticker: str, cik: str) -> list[dict]:
    url = _CONCEPT_URL.format(cik=int(cik))  # CIK 必须 0 填充到 10 位，否则 SEC 返回 404
    payload = _get_json(url)
    return _parse_eps_facts(payload)


def upsert_eps_facts(db: Session, ticker: str, cik: str, periods: list[dict]) -> int:
    """只保留季度粒度（含派生 Q4）；YTD/FY 中间事实不落库。"""
    rows = [p for p in periods if _QUARTER_DAYS[0] <= p["duration_days"] <= _QUARTER_DAYS[1]]
    for p in rows:
        row = db.scalar(select(SecEpsFact).where(
            SecEpsFact.ticker == ticker,
            SecEpsFact.period_start == p["period_start"],
            SecEpsFact.period_end == p["period_end"],
        ))
        if not row:
            row = SecEpsFact(ticker=ticker, period_start=p["period_start"], period_end=p["period_end"])
            db.add(row)
        row.cik = cik
        row.duration_days = p["duration_days"]
        row.fiscal_year = p.get("fiscal_year")
        row.fiscal_period = p.get("fiscal_period")
        row.form = p["form"] or "unknown"
        row.accession_number = p.get("accession_number")
        row.first_filed = p["first_filed"]
        row.eps = p["eps"]
    db.commit()
    return len(rows)


def fetch_yahoo_splits(yahoo_symbol: str) -> list[tuple[date, float]]:
    import yfinance as yf

    series = yf.Ticker(yahoo_symbol).splits
    if series is None or getattr(series, "empty", True):
        return []
    out = []
    for ts, ratio in series.items():
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            continue
        if ratio and ratio != 1:
            out.append((getattr(ts, "date", lambda: ts)(), ratio))
    return out


def upsert_splits(db: Session, symbol: str, splits: list[tuple[date, float]]) -> int:
    for ex_date, ratio in splits:
        row = db.scalar(select(StockSplit).where(StockSplit.symbol == symbol, StockSplit.ex_date == ex_date))
        if not row:
            row = StockSplit(symbol=symbol, ex_date=ex_date)
            db.add(row)
        row.ratio = ratio
    db.commit()
    return len(splits)


def _load_splits(db: Session, ticker: str) -> list[tuple[date, float]]:
    rows = db.scalars(
        select(StockSplit).where(StockSplit.symbol == ticker).order_by(StockSplit.ex_date)
    ).all()
    return [(row.ex_date, float(row.ratio or 1.0)) for row in rows]


def _split_factor_after(splits: list[tuple[date, float]], day: date) -> float:
    """day 之后的累计拆股系数：day 时点的旧股值除以它 → 当前股本口径。"""
    factor = 1.0
    for ex_date, ratio in splits:
        if ex_date > day:
            factor *= ratio
    return factor


def _load_daily_closes(db: Session, ticker: str) -> list[tuple[date, float]]:
    """按来源优先级逐日去重的收盘价序列（FMP 优先，仅缺失日期回落 yahoo/yfinance）。"""
    by_date: dict[date, float] = {}
    for source in PRICE_SOURCES:
        rows = db.execute(
            select(HistoricalPrice.date, HistoricalPrice.close)
            .where(HistoricalPrice.symbol == ticker, HistoricalPrice.source == source)
            .order_by(HistoricalPrice.date)
        ).all()
        for day, close in rows:
            if day not in by_date and close is not None:
                by_date[day] = float(close)
    return sorted(by_date.items())


def _apply_split_adjustment(prices: list[tuple[date, float]], splits: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """把未复权的存量价格折算到当前股本；已复权（FMP 默认）则原样保留。

    检测方式：拆股日前 5 个交易日与后 5 个交易日的中位价之比 ≈ 1/ratio 说明未复权；
    ≈ 1 说明已复权。两不沾边（数据稀疏/异常）时不调整，宁可保守也不瞎改。
    """
    result = prices
    for ex_date, ratio in splits:
        before = [c for d, c in result if d < ex_date][-5:]
        after = [c for d, c in result if d >= ex_date][:5]
        if not before or not after:
            continue
        observed = median(after) / median(before)
        if observed <= 0:
            continue
        if abs(observed * ratio - 1) <= 0.2:
            result = [(d, c / ratio if d < ex_date else c) for d, c in result]
        elif abs(observed - 1) <= 0.2:
            continue
        else:
            logger.warning("[valuation-history] split adjustment ambiguous ticker split=%s ratio=%s observed=%.3f",
                           ex_date, ratio, observed)
    return result


def _build_ttm_steps(db: Session, ticker: str, splits: list[tuple[date, float]]) -> list[tuple[date, float, date]]:
    """→ [(effective_date, ttm_eps_current_basis, window_end)]，按 effective_date 升序。

    某交易日可用的 TTM = 当时已公开（first_filed <= 该日）的最近四个连续财季之和；
    生成阶段先按「第 4 财季的 first_filed」生效，读取端再按日 as-of 匹配。
    """
    rows = db.scalars(
        select(SecEpsFact).where(SecEpsFact.ticker == ticker).order_by(SecEpsFact.period_end)
    ).all()
    quarters = sorted(
        (
            (row.period_start, row.period_end, row.first_filed,
             row.eps / _split_factor_after(splits, row.first_filed))
            for row in rows
        ),
        key=lambda q: q[1],
    )
    steps: list[tuple[date, float, date]] = []
    for i in range(3, len(quarters)):
        window = quarters[i - 3: i + 1]
        gaps = [(window[j + 1][1] - window[j][1]).days for j in range(3)]
        span = (window[3][1] - window[0][0]).days  # 首季开始 → 末季结束 ≈ 一个财年
        if not all(80 <= g <= 100 for g in gaps) or not 350 <= span <= 380:
            continue
        steps.append((max(q[2] for q in window), sum(q[3] for q in window), window[3][1]))
    steps.sort(key=lambda s: s[0])
    return steps


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * q / 100
    lower, upper = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] * (upper - k) + sorted_values[upper] * (k - lower)


def pe_history_payload(db: Session, ticker: str, range_key: str, *, today: date | None = None) -> dict:
    """组装 Historical P/E 响应；纯读取，不触发外部请求。"""
    today = today or datetime.now(UTC).date()
    years = RANGE_YEARS.get(range_key)
    if years is None and range_key != "max":
        raise ValueError("range 必须是 3y/5y/10y/max")

    splits = _load_splits(db, ticker)
    prices = _apply_split_adjustment(_load_daily_closes(db, ticker), splits)
    steps = _build_ttm_steps(db, ticker, splits)

    has_eps_facts = bool(steps) or bool(db.scalar(select(SecEpsFact.id).where(SecEpsFact.ticker == ticker).limit(1)))
    if not has_eps_facts:
        return {"ticker": ticker, "metric": "pe", "range": range_key, "status": "no_eps_data"}

    # 逐日 as-of join：交易日使用当时已生效的最新 TTM。
    series: list[dict] = []
    step_index = -1
    for day, close in prices:
        while step_index + 1 < len(steps) and steps[step_index + 1][0] <= day:
            step_index += 1
        if step_index < 0:
            continue
        ttm = steps[step_index][1]
        series.append({
            "date": day.isoformat(), "price": close, "eps_ttm": ttm,
            "pe": (close / ttm) if ttm > 0 else None,
        })

    cutoff = None if years is None else today - timedelta(days=years * 366)
    window = [row for row in series if cutoff is None or date.fromisoformat(row["date"]) >= cutoff]

    valid = sorted(row["pe"] for row in window if row["pe"] is not None)
    latest = series[-1] if series else None
    current_pe = latest["pe"] if latest else None

    statistics = None
    if valid:
        stats_median = _percentile(valid, 50)
        percentile = None
        if current_pe is not None:
            percentile = round(sum(1 for v in valid if v <= current_pe) / len(valid) * 100, 1)
        vs_median = (
            (current_pe / stats_median - 1) * 100
            if current_pe is not None and stats_median
            else None
        )
        statistics = {
            "mean": sum(valid) / len(valid),
            "median": stats_median,
            "p25": _percentile(valid, 25),
            "p75": _percentile(valid, 75),
            "percentile": percentile,
            "vs_median_pct": vs_median,
            "valid_points": len(valid),
        }

    first_date = date.fromisoformat(window[0]["date"]) if window else None
    last_date = date.fromisoformat(window[-1]["date"]) if window else None
    years_available = (
        round((last_date - first_date).days / 365.25, 1)
        if first_date and last_date and last_date > first_date
        else None
    )
    return {
        "ticker": ticker,
        "metric": "pe",
        "range": range_key,
        "status": "ok" if window else "insufficient_history",
        "as_of": datetime.now(UTC),
        "current": {
            "price": latest["price"] if latest else None,
            "eps_ttm": latest["eps_ttm"] if latest else None,
            "pe": current_pe,
            "pe_status": ("ok" if current_pe is not None else "negative_ttm") if latest else "unavailable",
            "as_of_date": latest["date"] if latest else None,
        },
        "statistics": statistics,
        "history": {
            "first_date": first_date.isoformat() if first_date else None,
            "last_date": last_date.isoformat() if last_date else None,
            "years_available": years_available,
        },
        "series": window,
    }


def sync_ticker_valuation_history(db: Session, ticker: str, *, deep_years: int = 10) -> dict:
    """单只股票采集：SEC EPS facts + yfinance 拆股 + （必要时）FMP 价格深回填。"""
    result: dict[str, object] = {"ticker": ticker}
    cik = resolve_cik(db, ticker)
    if cik:
        try:
            result["eps_facts"] = upsert_eps_facts(db, ticker, cik, fetch_eps_facts(ticker, cik))
        except Exception as error:
            logger.warning("[valuation-history] eps facts sync failed ticker=%s error=%s", ticker, error)
            result["eps_facts"] = None

    from app.services.securities import provider_symbol

    yahoo_symbol = provider_symbol(db, ticker, "yahoo") or ticker
    try:
        result["splits"] = upsert_splits(db, ticker, fetch_yahoo_splits(yahoo_symbol))
    except Exception as error:
        logger.warning("[valuation-history] splits sync failed ticker=%s error=%s", ticker, error)
        result["splits"] = None

    try:
        from app.services.fmp_market import sync_history

        earliest = db.scalar(
            select(HistoricalPrice.date)
            .where(HistoricalPrice.symbol == ticker, HistoricalPrice.source == "fmp")
            .order_by(HistoricalPrice.date).limit(1)
        )
        target_from = datetime.now(UTC).date() - timedelta(days=deep_years * 366)
        if earliest is None or earliest > target_from:
            result["price_deep_sync"] = sync_history(db, ticker, min_from=target_from)
    except Exception as error:
        logger.warning("[valuation-history] fmp deep history failed ticker=%s error=%s", ticker, error)
    return result
