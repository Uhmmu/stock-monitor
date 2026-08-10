from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CompanyProfile, FinancialStatementSnapshot, HistoricalPrice, PriceSnapshot, Security, StockProfile, ValuationSnapshot
from app.services.stock_compare import (
    METRIC_REGISTRY,
    _percentile,
    _rank,
    _relative,
    _trend,
    compare_history,
    compare_symbols,
    normalize_symbols,
)

TABLES = [Security.__table__, StockProfile.__table__, CompanyProfile.__table__, PriceSnapshot.__table__, HistoricalPrice.__table__, FinancialStatementSnapshot.__table__, ValuationSnapshot.__table__]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def _valuation(symbol: str, pe: float, peg: float | None, day: date):
    return ValuationSnapshot(
        ticker=symbol,
        snapshot_date=day,
        payload={
            "valuation": [
                {"key": "forward_pe", "value": pe, "status": "available"},
                {"key": "peg", "value": peg, "status": "available" if peg is not None else "insufficient"},
                {"key": "fcf_yield", "value": 4 if symbol == "AAA" else 2, "status": "available"},
            ],
            "health": [{"key": "altman_z", "value": 3.2}, {"key": "piotroski", "value": 7}],
            "consensus": {"current": 100, "value": 120 if symbol == "AAA" else 90},
            "dcf_scenarios": {"current": 100, "base": 115 if symbol == "AAA" else 95},
            "model_signals": ([{"verdict": "低估", "stars": 4}, {"verdict": "低估", "stars": 5}, {"verdict": "合理", "stars": 3}] if symbol == "AAA" else [{"verdict": "偏贵", "stars": 2}, {"verdict": "偏贵", "stars": 1}]),
            "peers": {"official_symbols": ["CCC"]},
        },
        source_version="test",
    )


def _statement(symbol: str, year: int, revenue: float, *, margin: float, period_end: date):
    return FinancialStatementSnapshot(
        ticker=symbol,
        frequency="annual",
        fiscal_year=year,
        fiscal_period="FY",
        period_end=period_end,
        currency="USD",
        income_statement={
            "revenue": revenue,
            "gross_profit": revenue * margin,
            "operating_income": revenue * (margin - .15),
            "net_income": revenue * (margin - .22),
            "eps": revenue / 100,
            "pretax_income": revenue * (margin - .2),
            "tax_expense": revenue * .04,
            "ebitda": revenue * (margin - .1),
        },
        balance_sheet={
            "cash": 100,
            "total_debt": 200,
            "current_assets": 400,
            "current_liabilities": 200,
            "total_assets": 1000,
            "shareholders_equity": 500,
        },
        cash_flow={"operating_cash_flow": revenue * .2, "capital_expenditure": -revenue * .05},
        source="yfinance",
        synced_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _seed(db: Session):
    db.add_all([
        Security(display_symbol="AAA", display_name="Alpha", yahoo_symbol="AAA", currency="USD", instrument_type="EQUITY"),
        Security(display_symbol="BBB", display_name="Beta", yahoo_symbol="BBB", currency="USD", instrument_type="EQUITY"),
        StockProfile(ticker="AAA", company_name="Alpha", official_sector="Technology", official_industry="Software"),
        StockProfile(ticker="BBB", company_name="Beta", official_sector="Financial Services", official_industry="Banks - Regional"),
        PriceSnapshot(symbol="AAA", last_price=110, previous_close=100, provider="test", market_timestamp=datetime(2026, 8, 8, tzinfo=UTC)),
        PriceSnapshot(symbol="BBB", last_price=90, previous_close=100, provider="test", market_timestamp=datetime(2026, 8, 8, tzinfo=UTC)),
        _valuation("AAA", 20, 1.2, date(2026, 8, 1)),
        _valuation("BBB", 30, None, date(2026, 8, 1)),
        _statement("AAA", 2025, 1200, margin=.55, period_end=date(2025, 12, 31)),
        _statement("AAA", 2024, 1000, margin=.50, period_end=date(2024, 12, 31)),
        _statement("BBB", 2025, 900, margin=.45, period_end=date(2025, 9, 30)),
        _statement("BBB", 2024, 850, margin=.44, period_end=date(2024, 9, 30)),
    ])
    start = date(2025, 1, 1)
    for index in range(14):
        day = start + timedelta(days=index * 30)
        db.add(HistoricalPrice(symbol="AAA", date=day, open=100 + index, high=102 + index, low=99 + index, close=100 + index, source="fmp"))
        if index:
            db.add(HistoricalPrice(symbol="BBB", date=day, open=80 + index, high=82 + index, low=79 + index, close=80 + index, source="fmp"))
    db.commit()


def test_registry_is_unique_and_input_is_bounded():
    keys = [item.key for item in METRIC_REGISTRY]
    assert len(keys) == len(set(keys))
    assert normalize_symbols([" aaa ", "BBB", "AAA"]) == ["AAA", "BBB"]
    with pytest.raises(ValueError):
        normalize_symbols(["AAA"])
    with pytest.raises(ValueError):
        normalize_symbols(["A;DROP", "BBB"])


def test_direction_ties_percentiles_and_difference_math():
    values = [("A", 10.0), ("B", 20.0), ("C", 20.0)]
    assert _rank(values, 20, "higher_better") == 1
    assert _rank(values, 10, "lower_better") == 1
    assert _percentile([10, 20, 20], 20, "higher_better") == 75
    assert _percentile([10, 20, 20], 10, "lower_better") == 100
    assert _relative(52, 16, "percentage_points") == 36
    assert _relative(120, 100, "percent") == 20


def test_trend_semantics_are_directional_and_neutral():
    points = [{"value": 10}, {"value": 15}]
    assert _trend(points, "higher_better") == "improving"
    assert _trend(points, "lower_better") == "deteriorating"
    assert _trend(points, "neutral") == "rising"
    assert _trend([{"value": 10}, {"value": 10.1}], "higher_better") == "stable"


def test_compare_preserves_missing_mixed_periods_and_cross_industry_caution(db):
    _seed(db)
    result = compare_symbols(db, ["AAA", "BBB"])
    metrics = {item["definition"]["key"]: item for item in result["metrics"]}

    pe = metrics["forward_pe"]
    assert pe["cells"]["AAA"]["rank"] == 1
    assert pe["cells"]["AAA"]["percentile"] == 100
    assert pe["cells"]["AAA"]["is_best"] is True
    assert pe["cells"]["BBB"]["is_worst"] is True
    assert pe["cells"]["AAA"]["relative"]["kind"] == "percent"

    assert metrics["peg"]["cells"]["BBB"]["status"] == "missing"
    assert metrics["peg"]["available_count"] == 1
    assert metrics["price"]["available_count"] == 2
    assert metrics["price"]["cells"]["AAA"]["rank"] is None
    assert metrics["valuation_model_agreement_pct"]["cells"]["AAA"]["value"] == pytest.approx(66.666667)
    assert metrics["valuation_model_agreement_pct"]["cells"]["AAA"]["rank"] is None
    assert metrics["gross_margin_pct"]["period_mismatch"] is True
    assert metrics["gross_margin_pct"]["cells"]["AAA"]["is_best"] is False
    assert metrics["gross_margin_pct"]["comparison_warning"]
    assert result["suggested_peers"] == ["CCC"]
    assert result["categories"] == list(dict.fromkeys(item["definition"]["category"] for item in result["metrics"]))


def test_history_is_chronological_and_price_uses_common_index_base(db):
    _seed(db)
    financial = compare_history(db, ["AAA", "BBB"], "gross_margin_pct")
    aaa = financial["series"][0]["points"]
    assert financial["mode"] == "raw"
    assert [point["date"] for point in aaa] == sorted(point["date"] for point in aaa)
    assert aaa[-1]["value"] == pytest.approx(55)

    price = compare_history(db, ["AAA", "BBB"], "price")
    assert price["mode"] == "indexed"
    assert price["series"][0]["points"][0]["date"] == price["series"][1]["points"][0]["date"]
    assert price["series"][0]["points"][0]["indexed"] == 100
    assert price["series"][1]["points"][0]["indexed"] == 100


def test_equal_values_are_tied_without_fake_best_or_worst(db):
    _seed(db)
    row = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == "BBB"))
    payload = dict(row.payload)
    payload["valuation"] = [{**item, "value": 20} if item["key"] == "forward_pe" else item for item in payload["valuation"]]
    row.payload = payload
    db.commit()

    metric = next(item for item in compare_symbols(db, ["AAA", "BBB"])["metrics"] if item["definition"]["key"] == "forward_pe")
    assert metric["cells"]["AAA"]["rank"] == metric["cells"]["BBB"]["rank"] == 1
    assert metric["cells"]["AAA"]["is_best"] is False
    assert metric["cells"]["BBB"]["is_worst"] is False
