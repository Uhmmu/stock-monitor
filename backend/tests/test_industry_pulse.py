from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    HistoricalPrice,
    CompanyProfile,
    IndustryPulseFocusSignal,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseNarrative,
    IndustryPulseRelation,
    IndustryPulseSnapshot,
    IndustryPulseSyncRun,
    Security,
    StockProfile,
)
from app.services.industry_pulse.calculation import calculate_etf_metrics, calculate_focus, classify_mood
from app.services.industry_pulse.classification import classify_security
from app.services.industry_pulse.provider import DailyBar, ProviderHistory, fetch_histories
from app.services.industry_pulse.service import _merge_history, _stored_history_payload, _upsert_history, _upsert_snapshot, ai_chain_payload, ensure_seed_data, focus_payload, overview_payload, sync_security_classifications, taxonomy_payload


TABLES = [
    HistoricalPrice.__table__,
    Security.__table__,
    StockProfile.__table__,
    CompanyProfile.__table__,
    IndustryPulseNode.__table__,
    IndustryPulseRelation.__table__,
    IndustryPulseInstrument.__table__,
    IndustryPulseSnapshot.__table__,
    IndustryPulseFocusSignal.__table__,
    IndustryPulseSyncRun.__table__,
    IndustryPulseNarrative.__table__,
]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def _bars(count=300, slope=1.0, start=date(2025, 1, 1)):
    return [{"date": start + timedelta(days=index), "open": 100 + index * slope, "high": 101 + index * slope, "low": 99 + index * slope, "close": 100 + index * slope, "volume": 1000 + index * 10} for index in range(count)]


def test_provider_yfinance_failure_falls_back_then_explicitly_unavailable():
    fallback = ProviderHistory("AAA", bars=[] , provider=None, status="unavailable", error_code="no_key")
    result = fetch_histories(["AAA", "BBB"], days=30, yfinance_fetcher=lambda symbols, days: {"AAA": fallback, "BBB": ProviderHistory("BBB", bars=_bars(40), provider="yfinance", status="success", volume_available=True)}, finnhub_fetcher=lambda ticker, days: ProviderHistory(ticker, bars=_bars(40), provider="finnhub", status="fallback", volume_available=False) if ticker == "AAA" else ProviderHistory(ticker))
    assert result["AAA"].status == "fallback"
    assert result["BBB"].provider == "yfinance"
    degraded = ProviderHistory("SMHX", bars=_bars(40), provider="yfinance", status="degraded", volume_available=True, malformed_rows=10, total_rows=50)
    assert degraded.data_quality < ProviderHistory("OK", bars=_bars(40), provider="yfinance", status="success", volume_available=True, total_rows=40).data_quality


def test_provider_short_or_volume_missing_history_uses_fallback():
    short = ProviderHistory("AAA", bars=_bars(40), provider="yfinance", status="success", volume_available=True)
    no_volume = ProviderHistory("BBB", bars=_bars(300), provider="yfinance", status="success", volume_available=False)
    result = fetch_histories(["AAA", "BBB"], days=300, yfinance_fetcher=lambda symbols, days: {"AAA": short, "BBB": no_volume}, finnhub_fetcher=lambda ticker, days: ProviderHistory(ticker, bars=_bars(300), provider="finnhub", status="fallback", volume_available=True))
    assert result["AAA"].provider == "finnhub"
    assert result["BBB"].provider == "finnhub"


def test_yfinance_incremental_refresh_uses_short_batch_period(monkeypatch):
    from app.services.industry_pulse import provider
    calls = []
    monkeypatch.setattr(provider.yf, "download", lambda **kwargs: calls.append(kwargs) or provider.pd.DataFrame())
    provider.fetch_yfinance_batch(["SPY"], days=45)
    assert calls[0]["period"] == "3mo"


def test_incremental_bars_merge_with_full_persisted_history(db):
    full = ProviderHistory("SPY", bars=[DailyBar(**row) for row in _bars(300)], provider="yfinance", status="success", volume_available=True, total_rows=300)
    cache = {}
    _upsert_history(db, "SPY", full, cache)
    _upsert_history(db, "SPY", ProviderHistory("SPY", bars=full.bars[-45:], provider="yfinance", status="success", volume_available=True, total_rows=45), cache)
    merged = _stored_history_payload(list(cache.values()))
    assert len(merged) == 300
    assert calculate_etf_metrics(merged, benchmark_rows=merged)["return_252d"] is not None


def test_current_fallback_rows_override_stale_cached_provider_on_same_date():
    day = date(2026, 8, 10)
    stored = [{"date": day, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}]
    fresh = [DailyBar(day, 200, 201, 199, 200, 2000)]
    assert _merge_history(stored, fresh)[0]["close"] == 200


def test_metrics_are_causal_and_rs_is_percent_not_100x():
    rows = _bars(300)
    benchmark = _bars(300, slope=.5)
    latest = calculate_etf_metrics(rows, benchmark_rows=benchmark, as_of=rows[-2]["date"])
    assert latest["as_of"] == rows[-2]["date"]
    assert latest["rs_20d"] is not None and abs(latest["rs_20d"]) < 10000
    assert latest["rs_breakout_20d"] is True
    assert latest["volatility_state"] in {"contracting", "normal", "expanding", "extreme", "unknown"}
    assert latest["dollar_volume"] > 0
    assert 0 <= latest["liquidity_quality"] <= 1


def test_metrics_reject_stale_history():
    rows = _bars(260)
    metrics = calculate_etf_metrics(rows, benchmark_rows=rows, as_of=rows[-1]["date"] + timedelta(days=10))
    assert metrics["status"] == "unavailable"
    assert metrics["error_code"] == "stale_history"
    assert metrics["data_quality"] == 0


def test_relative_strength_uses_common_dates():
    rows = _bars(80)
    benchmark = [row for index, row in enumerate(_bars(80, slope=.5)) if index % 2 == 0]
    metrics = calculate_etf_metrics(rows, benchmark_rows=benchmark, as_of=rows[-1]["date"])
    common_last = rows[-2]  # final common date is the last even-indexed row
    benchmark_last = benchmark[-1]
    assert metrics["rs_ratio"] == pytest.approx(common_last["close"] / benchmark_last["close"])


def test_classification_preserves_weak_theme_but_excludes_it_from_pulse():
    row = classify_security("MSFT")
    assert row["primary_industry"].endswith("enterprise_software")
    assert row["theme_exposures"]
    assert all(value >= .3 for value in row["included_theme_exposures"].values())
    assert any(value < .3 for value in row["theme_exposures"].values())


def test_seed_is_idempotent_and_overview_is_base_sectors_only(db):
    first = ensure_seed_data(db)
    db.commit()
    second = ensure_seed_data(db)
    db.commit()
    assert first["nodes"] == second["nodes"]
    assert db.query(IndustryPulseNode).count() >= 400
    sector = db.query(IndustryPulseNode).filter_by(taxonomy="base", level="sector").first()
    db.add(IndustryPulseSnapshot(node_id=sector.id, trading_date=date(2026, 8, 10), pulse=70, mood="strong", heat=60, risk=20, coverage_quality=.9))
    db.commit()
    payload = overview_payload(db)
    assert len(payload["sectors"]) == 1
    assert payload["sectors"][0]["pulse"] == 70
    taxonomy_nodes = taxonomy_payload(db)["nodes"]
    assert all(node["taxonomy"] == "base" for node in taxonomy_nodes)
    assert next(node for node in taxonomy_nodes if node["id"] == sector.id)["pulse"] == 70


def test_security_classification_persists_base_and_separate_theme_mappings(db):
    ensure_seed_data(db)
    db.add(Security(display_symbol="MSFT", yahoo_symbol="MSFT"))
    db.commit()
    result = sync_security_classifications(db)
    db.commit()
    rows = db.query(IndustryPulseInstrument).filter_by(ticker="MSFT", instrument_type="stock").all()
    assert result["classified"] == 1
    assert any(row.mapping_type == "primary_industry" for row in rows)
    assert any(row.mapping_type == "theme_exposure" for row in rows)
    assert all(row.role == "reference" for row in rows)


def test_pulse_deltas_require_exact_prior_trading_points(db):
    node = IndustryPulseNode(taxonomy="base", node_key="test.delta", name="Delta", level="leaf")
    db.add(node)
    db.flush()
    prior = [IndustryPulseSnapshot(node_id=node.id, trading_date=date(2026, 8, 1) + timedelta(days=index), pulse=50 + index) for index in range(5)]
    db.add_all(prior)
    db.flush()
    row = _upsert_snapshot(db, node.id, date(2026, 8, 10), {"pulse": 70, "coverage_quality": .8, "confidence": .7, "components": {}}, metrics={}, benchmark={}, previous=prior[-1], prior_rows=prior)
    assert row.change_5d == 20
    assert row.change_20d is None


def test_focus_and_ai_payloads_flatten_quality_and_change_fields(db):
    ensure_seed_data(db)
    sector = db.query(IndustryPulseNode).filter_by(taxonomy="base", level="sector").first()
    ai_leaf = db.query(IndustryPulseNode).filter_by(taxonomy="ai", level="leaf").first()
    day = date(2026, 8, 10)
    sector_snapshot = IndustryPulseSnapshot(node_id=sector.id, trading_date=day, pulse=70, change_5d=6, breadth_score=65, relative_strength_score=72, coverage_quality=.8, confidence=.7)
    ai_snapshot = IndustryPulseSnapshot(node_id=ai_leaf.id, trading_date=day, pulse=75, change_5d=5, breadth_score=60, relative_strength_score=68, coverage_quality=.75, confidence=.65)
    db.add_all([sector_snapshot, ai_snapshot, IndustryPulseFocusSignal(node_id=sector.id, trading_date=day, signal_type="leaders", rank=1, score=70, payload={})])
    db.commit()
    focus_row = focus_payload(db)["buckets"]["leaders"][0]
    assert focus_row["change_5d"] == 6 and focus_row["relative_strength_score"] == 72 and focus_row["coverage_quality"] == .8
    ai_row = next(row for row in ai_chain_payload(db)["nodes"] if row["id"] == ai_leaf.id)
    assert ai_row["change_5d"] == 5 and ai_row["relative_strength_score"] == 68 and ai_row["confidence"] == .65
    chain = ai_chain_payload(db)
    assert chain["available_groups"] == 1
    derived_group = next(group for category in chain["groups"] for group in category["rows"])
    assert derived_group["pulse"] == 75 and derived_group["derived_from_children"] is True
    assert derived_group["name_zh"]


def test_focus_gates_do_not_emit_unqualified_buckets():
    rows = [{"node_id": 1, "pulse": 80, "change_5d": 2, "relative_strength": 10, "volume_z": 0, "heat": 50, "risk": 20, "direction": "up", "coverage_quality": .8, "confidence": .8, "metrics_json": {"rs_breakout": False}}, {"node_id": 2, "pulse": 30, "change_5d": -5, "relative_strength": -2, "volume_z": 3, "heat": 85, "risk": 80, "direction": "down", "coverage_quality": .8, "confidence": .8, "metrics_json": {"rs_breakout": False}}]
    signals = calculate_focus(rows)
    assert not any(item["signal_type"] == "volume_shock" and item["node_id"] == 1 for item in signals)
    assert any(item["signal_type"] == "risk_off" and item["node_id"] == 2 for item in signals)
    assert classify_mood(80, 90, 80, 70, 80) == "overheated"
