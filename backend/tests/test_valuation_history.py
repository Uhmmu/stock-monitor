"""Historical P/E 引擎测试：TTM、point-in-time、拆股一致性、统计与区间。"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import HistoricalPrice, SecEpsFact, StockSplit
from app.services.valuation_history import (
    _apply_split_adjustment,
    _percentile,
    _parse_eps_facts,
    fetch_eps_facts,
    pe_history_payload,
    upsert_eps_facts,
)

TABLES = [SecEpsFact.__table__, StockSplit.__table__, HistoricalPrice.__table__]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def _quarter(ticker, period_end, filed, eps, *, period_start=None):
    start = period_start or period_end - timedelta(days=91)
    return SecEpsFact(
        ticker=ticker, cik="0000000000", period_start=start, period_end=period_end,
        duration_days=(period_end - start).days, form="10-Q", first_filed=filed, eps=eps,
    )


def _price(ticker, day, close, source="fmp"):
    return HistoricalPrice(symbol=ticker, date=day, open=close, high=close, low=close,
                           close=close, volume=1000, source=source)


# ---------------------------------------------------------------- point-in-time TTM

def test_ttm_only_uses_quarters_already_filed(db):
    """核心防 look-ahead：财报发布日之前的交易日不得使用该季 EPS。"""
    rows = [
        _quarter("T", date(2025, 3, 31), date(2025, 4, 25), 1.0),
        _quarter("T", date(2025, 6, 30), date(2025, 7, 25), 1.1),
        _quarter("T", date(2025, 9, 30), date(2025, 10, 25), 1.2),
        _quarter("T", date(2025, 12, 31), date(2026, 1, 25), 1.3),
        _quarter("T", date(2026, 3, 31), date(2026, 4, 25), 1.4),
        # 财季 2026-06-30 已结束，但 2026-08-20 才发布
        _quarter("T", date(2026, 6, 30), date(2026, 8, 20), 1.5),
    ]
    db.add_all(rows + [
        _price("T", date(2026, 6, 30), 50.0),
        _price("T", date(2026, 8, 21), 54.0),
    ])
    db.commit()

    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    by_date = {row["date"]: row for row in payload["series"]}
    # 2026-06-30：市场只知道前四季（含 2026-03-31 季），TTM=5.0，绝不能提前用 1.5
    assert by_date["2026-06-30"]["eps_ttm"] == pytest.approx(1.1 + 1.2 + 1.3 + 1.4)
    # 2026-08-21（发布之后）：TTM 滚动到含 1.5
    assert by_date["2026-08-21"]["eps_ttm"] == pytest.approx(1.2 + 1.3 + 1.4 + 1.5)
    assert by_date["2026-08-21"]["pe"] == pytest.approx(54.0 / 5.4)


def test_missing_quarter_breaks_ttm(db):
    """财季缺口：跨缺口的窗口不得产出假 TTM；连续四季恢复后 TTM 才恢复。"""
    rows = [
        _quarter("T", date(2025, 3, 31), date(2025, 4, 25), 1.0),
        _quarter("T", date(2025, 6, 30), date(2025, 7, 25), 1.1),
        # 缺 2025-09-30 季
        _quarter("T", date(2025, 12, 31), date(2026, 1, 25), 1.3),
        _quarter("T", date(2026, 3, 31), date(2026, 4, 25), 1.4),
        _quarter("T", date(2026, 6, 30), date(2026, 7, 25), 1.5),
        _quarter("T", date(2026, 9, 30), date(2026, 10, 25), 1.6),
        _quarter("T", date(2026, 12, 31), date(2027, 1, 25), 1.7),
    ]
    db.add_all(rows + [
        _price("T", date(2025, 8, 1), 50.0),   # 缺口期：无 TTM
        _price("T", date(2026, 2, 2), 50.0),   # 仍只有跨缺口窗口
        _price("T", date(2027, 2, 1), 60.0),   # 连续四季（2026 内）成立后恢复
    ])
    db.commit()
    payload = pe_history_payload(db, "T", "max", today=date(2027, 8, 31))
    by_date = {row["date"]: row for row in payload["series"]}
    # 首个有效 TTM 生效日之前的交易日不进入序列（图表与统计都不需要空转点）
    assert "2025-08-01" not in by_date
    assert "2026-02-02" not in by_date
    # 唯一成立的窗口：2026-03-31..2026-12-31 四季
    assert by_date["2027-02-01"]["eps_ttm"] == pytest.approx(1.4 + 1.5 + 1.6 + 1.7)


# ---------------------------------------------------------------- EPS facts 解析

def _raw_fact(start, end, val, filed, form="10-Q", accn="0000000000-00-000000"):
    return {"start": start.isoformat(), "end": end.isoformat(), "val": val,
            "accn": accn, "fy": end.year, "fp": "Q3", "form": form, "filed": filed.isoformat()}


def test_parse_eps_facts_dedup_and_q4_derivation():
    payload = {"units": {"USD/shares": [
        _raw_fact(date(2025, 1, 1), date(2025, 3, 31), 0.9, date(2025, 4, 25)),
        _raw_fact(date(2025, 4, 1), date(2025, 6, 30), 1.0, date(2025, 7, 25)),
        # 同期在次年 10-Q 里被重述为 1.05（比较期），首次公开值 1.0 必须胜出
        _raw_fact(date(2025, 4, 1), date(2025, 6, 30), 1.05, date(2026, 7, 25)),
        _raw_fact(date(2025, 7, 1), date(2025, 9, 30), 1.1, date(2025, 10, 28)),
        _raw_fact(date(2025, 1, 1), date(2025, 9, 30), 3.0, date(2025, 10, 28)),  # 9M YTD
        _raw_fact(date(2025, 1, 1), date(2025, 12, 31), 4.0, date(2026, 2, 10), form="10-K"),  # FY
    ]}}
    periods = _parse_eps_facts(payload)
    quarters = [p for p in periods if 80 <= p["duration_days"] <= 105]
    by_end = {p["period_end"]: p for p in quarters}
    assert by_end[date(2025, 6, 30)]["eps"] == 1.0
    assert by_end[date(2025, 6, 30)]["first_filed"] == date(2025, 7, 25)
    # Q4 = FY − 9M，生效于两者都公开之后（10-K 披露日）
    q4 = by_end[date(2025, 12, 31)]
    assert q4["eps"] == pytest.approx(1.0)
    assert q4["first_filed"] == date(2026, 2, 10)
    # YTD / FY 中间事实不进入季度集合
    assert len(quarters) == 4


def test_upsert_eps_facts_stores_quarters_only(db):
    periods = _parse_eps_facts({"units": {"USD/shares": [
        _raw_fact(date(2025, 1, 1), date(2025, 3, 31), 0.9, date(2025, 4, 25)),
        _raw_fact(date(2025, 4, 1), date(2025, 6, 30), 1.0, date(2025, 7, 25)),
        _raw_fact(date(2025, 1, 1), date(2025, 9, 30), 3.0, date(2025, 10, 28)),
        _raw_fact(date(2025, 1, 1), date(2025, 12, 31), 4.0, date(2026, 2, 10), form="10-K"),
    ]}})
    count = upsert_eps_facts(db, "T", "0000000000", periods)
    assert count == 3  # Q1, Q2, 派生 Q4（FY/9M 中间事实不落库）
    # 幂等：重放同样数据不翻倍
    assert upsert_eps_facts(db, "T", "0000000000", periods) == 3
    assert db.query(SecEpsFact).count() == 3


# ---------------------------------------------------------------- 负 TTM / N/M

def test_negative_ttm_yields_null_pe_and_excluded_from_stats(db):
    rows = [
        _quarter("T", date(2025, 3, 31), date(2025, 4, 25), -0.2),
        _quarter("T", date(2025, 6, 30), date(2025, 7, 25), -0.2),
        _quarter("T", date(2025, 9, 30), date(2025, 10, 25), -0.2),
        _quarter("T", date(2025, 12, 31), date(2026, 1, 25), -0.2),
    ]
    db.add_all(rows + [_price("T", date(2026, 2, 2), 50.0)])
    db.commit()
    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    row = payload["series"][0]
    assert row["pe"] is None and row["eps_ttm"] == pytest.approx(-0.8)
    assert payload["statistics"] is None
    assert payload["current"]["pe"] is None
    assert payload["current"]["pe_status"] == "negative_ttm"


# ---------------------------------------------------------------- 拆股一致性

def test_eps_split_adjusted_to_current_share_basis(db):
    """披露日之后发生 10:1 拆股：旧 EPS 必须除以 10 才能匹配复权价格。"""
    rows = [
        _quarter("T", date(2024, 1, 31), date(2024, 2, 22), 0.56),   # 已是拆股后披露
        _quarter("T", date(2024, 4, 30), date(2024, 5, 22), 5.98),   # 拆股前披露，需 /10
        _quarter("T", date(2024, 7, 31), date(2024, 8, 28), 0.67),
        _quarter("T", date(2024, 10, 31), date(2024, 11, 20), 0.69),
        _quarter("T", date(2025, 1, 31), date(2025, 2, 26), 0.77),
    ]
    db.add_all(rows)
    db.add(StockSplit(symbol="T", ex_date=date(2024, 6, 10), ratio=10.0))
    db.add(_price("T", date(2025, 3, 3), 110.0))  # FMP 复权价（拆股前后连续）
    db.commit()
    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    row = payload["series"][0]
    # 2025-03-03 时点最新已公开窗口：2024-04-30..2025-01-31（0.598 已折算 + 三个拆股后季度）
    assert row["eps_ttm"] == pytest.approx(0.598 + 0.67 + 0.69 + 0.77)
    assert row["pe"] == pytest.approx(110.0 / row["eps_ttm"])


def test_price_split_adjustment_applies_to_unadjusted_series():
    prices = [
        (date(2024, 6, 3), 1200.0), (date(2024, 6, 7), 1208.0),
        (date(2024, 6, 10), 121.8), (date(2024, 6, 11), 120.9),
    ]
    adjusted = _apply_split_adjustment(prices, [(date(2024, 6, 10), 10.0)])
    assert [round(c, 2) for _, c in adjusted] == [120.0, 120.8, 121.8, 120.9]
    # 已复权序列（拆股日前后连续）必须原样保留
    continuous = [(date(2024, 6, 7), 120.8), (date(2024, 6, 10), 121.8)]
    assert _apply_split_adjustment(continuous, [(date(2024, 6, 10), 10.0)]) == continuous


def test_no_pe_jump_across_split(db):
    """拆股前后 P/E 不应出现 10x / 0.1x 断层（整链路一致性）。"""
    rows = [
        _quarter("T", date(2024, 1, 31), date(2024, 2, 22), 0.56),
        _quarter("T", date(2024, 4, 30), date(2024, 5, 22), 5.98),
        _quarter("T", date(2024, 7, 31), date(2024, 8, 28), 0.67),
        _quarter("T", date(2024, 10, 31), date(2024, 11, 20), 0.69),
        _quarter("T", date(2025, 1, 31), date(2025, 2, 26), 0.77),
    ]
    db.add_all(rows)
    db.add(StockSplit(symbol="T", ex_date=date(2024, 6, 10), ratio=10.0))
    db.add_all([
        _price("T", date(2025, 2, 27), 110.0),   # 全部四季已知的最早 TTM 生效日
        _price("T", date(2025, 8, 25), 130.0),
        _quarter("T", date(2025, 4, 30), date(2025, 5, 22), 0.81),
        _quarter("T", date(2025, 7, 31), date(2025, 8, 20), 0.82),
    ])
    db.commit()
    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    pe_first = payload["series"][0]["pe"]
    pe_last = payload["series"][-1]["pe"]
    assert pe_first == pytest.approx(110.0 / (0.598 + 0.67 + 0.69 + 0.77), rel=0.01)
    assert pe_last == pytest.approx(130.0 / (0.69 + 0.77 + 0.81 + 0.82), rel=0.01)
    # 两个时点盈利结构相近，P/E 不应出现数量级断层
    assert 0.4 < pe_first / pe_last < 2.5


# ---------------------------------------------------------------- 统计与区间

def _seed_two_regimes(db):
    """早年 P/E≈10（TTM 1.0 × 价格 10），近年 P/E≈20（价格 20）。"""
    quarters = [
        (date(2020, 3, 31), date(2020, 4, 25)), (date(2020, 6, 30), date(2020, 7, 25)),
        (date(2020, 9, 30), date(2020, 10, 25)), (date(2020, 12, 31), date(2021, 1, 25)),
        (date(2021, 3, 31), date(2021, 4, 25)), (date(2021, 6, 30), date(2021, 7, 25)),
        (date(2021, 9, 30), date(2021, 10, 25)), (date(2021, 12, 31), date(2022, 1, 25)),
        (date(2022, 3, 31), date(2022, 4, 25)), (date(2022, 6, 30), date(2022, 7, 25)),
        (date(2022, 9, 30), date(2022, 10, 25)), (date(2022, 12, 31), date(2023, 1, 25)),
        (date(2023, 3, 31), date(2023, 4, 25)), (date(2023, 6, 30), date(2023, 7, 25)),
        (date(2023, 9, 30), date(2023, 10, 25)), (date(2023, 12, 31), date(2024, 1, 25)),
        (date(2024, 3, 31), date(2024, 4, 25)), (date(2024, 6, 30), date(2024, 7, 25)),
        (date(2024, 9, 30), date(2024, 10, 25)), (date(2024, 12, 31), date(2025, 1, 25)),
    ]
    db.add_all([_quarter("T", end, filed, 0.25) for end, filed in quarters])
    prices = []
    for day in (date(2021, 6, 1), date(2022, 6, 1)):       # 早年：TTM=1.0，价 10 → P/E 10
        prices.append(_price("T", day, 10.0))
    for day in (date(2025, 6, 2), date(2026, 6, 1)):       # 近年：价 20 → P/E 20
        prices.append(_price("T", day, 20.0))
    db.add_all(prices)
    db.commit()


def test_statistics_and_range_recomputation(db):
    _seed_two_regimes(db)
    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    assert payload["status"] == "ok"
    stats = payload["statistics"]
    assert stats["valid_points"] == 4
    assert stats["median"] == pytest.approx(15.0)   # {10,10,20,20} → 15
    assert stats["mean"] == pytest.approx(15.0)
    # 线性插值分位（numpy 语义）：p25/p75 落在重复值区间内
    assert stats["p25"] == pytest.approx(10.0)
    assert stats["p75"] == pytest.approx(20.0)
    current = payload["current"]
    assert current["pe"] == pytest.approx(20.0)
    assert stats["percentile"] == pytest.approx(100.0)  # 4/4 ≤ 20.0（含等于）
    assert stats["vs_median_pct"] == pytest.approx((20 / 15 - 1) * 100)

    # 3y 区间只含近年 P/E≈20 → 统计必须整体重算，而非只裁剪曲线
    recent = pe_history_payload(db, "T", "3y", today=date(2026, 8, 31))
    assert recent["statistics"]["valid_points"] == 2
    assert recent["statistics"]["median"] == pytest.approx(20.0)
    assert recent["statistics"]["percentile"] == pytest.approx(100.0)
    assert recent["history"]["first_date"] == "2025-06-02"


def test_insufficient_and_missing_states(db):
    # 无任何 facts
    assert pe_history_payload(db, "T", "5y", today=date(2026, 8, 31))["status"] == "no_eps_data"
    # facts 不足四季
    db.add_all([
        _quarter("IPO", date(2026, 3, 31), date(2026, 4, 25), 1.0),
        _quarter("IPO", date(2026, 6, 30), date(2026, 7, 25), 1.1),
        _price("IPO", date(2026, 8, 3), 30.0),
    ])
    db.commit()
    payload = pe_history_payload(db, "IPO", "5y", today=date(2026, 8, 31))
    assert payload["status"] == "insufficient_history"
    assert payload["series"] == []


def test_percentile_helper():
    values = [10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 25) == pytest.approx(17.5)
    assert _percentile(values, 50) == pytest.approx(25.0)
    assert _percentile(values, 75) == pytest.approx(32.5)
    assert _percentile([], 50) is None


def test_companyconcept_url_zero_pads_cik(monkeypatch):
    """SEC 要求 CIK 填充到 10 位；不填充会得到 404。"""
    seen = {}

    def fake_get_json(url):
        seen["url"] = url
        return {"units": {"USD/shares": []}}

    monkeypatch.setattr("app.services.valuation_history._get_json", fake_get_json)
    fetch_eps_facts("MSFT", "0000789019")
    assert seen["url"] == "https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/EarningsPerShareDiluted.json"


def test_full_precision_not_rounded(db):
    db.add_all([
        _quarter("T", date(2025, 3, 31), date(2025, 4, 25), 1.0),
        _quarter("T", date(2025, 6, 30), date(2025, 7, 25), 1.0),
        _quarter("T", date(2025, 9, 30), date(2025, 10, 25), 1.0),
        _quarter("T", date(2025, 12, 31), date(2026, 1, 25), 1.0),
        _price("T", date(2026, 2, 2), 100.0 / 3.0),
    ])
    db.commit()
    payload = pe_history_payload(db, "T", "max", today=date(2026, 8, 31))
    # 引擎不做中途取整；差异只来自价格列本身的 Numeric(20,6) 存储精度
    assert payload["series"][0]["pe"] == pytest.approx(100.0 / 12.0, rel=1e-6)
