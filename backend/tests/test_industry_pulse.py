from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    HistoricalPrice,
    CompanyProfile,
    IndustryPulseFocusSignal,
    IndustryPulseClassificationCache,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseNarrative,
    IndustryPulseRelation,
    IndustryPulseSnapshot,
    IndustryPulseSyncRun,
    Security,
    StockProfile,
    PeerRelation,
    ValuationSnapshot,
)
from app.services.industry_pulse.calculation import calculate_basket_signal, calculate_basket_weights, calculate_constituent_breadth, calculate_etf_metrics, calculate_focus, calculate_hybrid_composite, classify_mood
from app.services.industry_pulse.classification import classify_security
from app.services.industry_pulse.constituents import ClassificationBatch, MembershipSuggestion, SymbolClassification, _normalize_classification_payload, bootstrap_ai_constituents
from app.services.industry_pulse.provider import DailyBar, ProviderHistory, fetch_histories
from app.services.industry_pulse.service import _constituent_health, _fetch_lookback_days, _history_backfill_complete, _merge_history, _pulse_stock_mappings, _stock_mapping_active, _stored_history_payload, _upsert_history, _upsert_snapshot, ai_chain_payload, ensure_seed_data, focus_payload, overview_payload, sync_security_classifications, taxonomy_payload


TABLES = [
    HistoricalPrice.__table__,
    Security.__table__,
    StockProfile.__table__,
    CompanyProfile.__table__,
    PeerRelation.__table__,
    ValuationSnapshot.__table__,
    IndustryPulseNode.__table__,
    IndustryPulseRelation.__table__,
    IndustryPulseInstrument.__table__,
    IndustryPulseClassificationCache.__table__,
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


def test_incremental_fetch_does_not_redownload_universe_for_few_failures():
    symbols = {f"S{index}" for index in range(100)}
    cached = {symbol: {date(2025, 1, 1) + timedelta(days=day) for day in range(252)} for symbol in list(symbols)[:98]}
    assert _fetch_lookback_days(cached, symbols) == 10
    assert _history_backfill_complete({1, 2}, {1, 2, 3})
    assert not _history_backfill_complete({1, 2}, {1})


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
    accelerator = db.query(IndustryPulseNode).filter_by(node_key="ai.compute.accelerators").one()
    assert {row.ticker for row in db.query(IndustryPulseInstrument).filter_by(node_id=accelerator.id).all()} >= {"SMH", "SOXX"}
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


def test_focus_emits_breadth_narrow_and_internal_confirmation():
    row = {"node_id": 1, "pulse": 70, "change_5d": 5, "relative_strength": 65, "coverage_quality": .8, "confidence": .8, "metrics_json": {"proxy_mode": "HYBRID", "basket": {"narrow_leadership": True, "breadth": {"breadth_score": 70}}, "etf_signal": {"pulse": 70}, "basket_signal": {"pulse": 72}}}
    types = {item["signal_type"] for item in calculate_focus([row])}
    assert {"breadth_expansion", "narrow_leadership", "internal_confirmation"} <= types


def test_stock_membership_eligibility_checks_thresholds_dates_and_enabled(monkeypatch):
    day = date(2026, 8, 10)
    row = IndustryPulseInstrument(node_id=1, ticker="NVDA", instrument_type="stock", mapping_type="theme_exposure", role="reference", exposure=.8, confidence=.8, enabled=True, enabled_for_pulse=True, valid_from=day - timedelta(days=1))
    assert _stock_mapping_active(row, day)
    row.exposure = .2
    assert not _stock_mapping_active(row, day)
    row.exposure, row.confidence = .8, .4
    assert not _stock_mapping_active(row, day)
    row.confidence, row.valid_to = .8, day - timedelta(days=1)
    assert not _stock_mapping_active(row, day)
    row.valid_to, row.enabled_for_pulse = None, False
    assert not _stock_mapping_active(row, day)


def test_basket_weighting_caps_single_stock_and_top_three():
    mappings = [{"ticker": f"S{index}", "exposure": 1 if index == 0 else .3, "confidence": 1, "constituent_role": "CORE"} for index in range(8)]
    result = calculate_basket_weights(mappings)
    assert sum(result["weights"].values()) == pytest.approx(1)
    assert max(result["weights"].values()) <= .18 + 1e-9
    assert result["top_three_weight"] <= .45 + 1e-9
    five = calculate_basket_weights(mappings[:5])
    assert five["single_stock_cap"] == pytest.approx(.20)
    assert not five["top_three_cap_applied"]


def test_role_weights_ignore_continuous_luna_scores():
    rows = [
        {"ticker": "CORE", "exposure": .1, "confidence": .1, "constituent_role": "CORE"},
        {"ticker": "SECONDARY", "exposure": 1, "confidence": 1, "constituent_role": "SECONDARY"},
        {"ticker": "ENABLER", "exposure": 1, "confidence": 1, "constituent_role": "ENABLER"},
    ] + [{"ticker": f"E{index}", "constituent_role": "ENABLER"} for index in range(9)]
    weights = calculate_basket_weights(rows)["weights"]
    assert weights["CORE"] / weights["SECONDARY"] == pytest.approx(1 / .75)
    assert weights["SECONDARY"] / weights["ENABLER"] == pytest.approx(.75 / .5)


def test_constituent_failures_are_temporary_before_stale_or_invalid():
    failed = ProviderHistory("BAD", status="unavailable", error_code="empty_response")
    assert _constituent_health(failed, 1, no_history=True, manual_seed=True) == "TEMPORARY_DATA_FAILURE"
    assert _constituent_health(failed, 3, no_history=False, manual_seed=True) == "STALE"
    assert _constituent_health(failed, 5, no_history=True, manual_seed=True) == "SEED_INVALID"


def test_manual_seed_is_canonical_when_ai_memberships_also_exist():
    day = date(2026, 8, 10)
    def member(ticker, source):
        return IndustryPulseInstrument(node_id=1, ticker=ticker, instrument_type="stock", mapping_type="theme_exposure", role="reference", exposure=1, confidence=1, enabled=True, enabled_for_pulse=True, classification_source=source)
    assert [row.ticker for row in _pulse_stock_mappings([member("SEED", "MANUAL_CURATED_SEED"), member("AI", "AI_CLASSIFIED")], day)] == ["SEED"]


def test_synthetic_basket_and_breadth_are_causal_and_keep_denominators():
    histories = {f"S{index}": _bars(300, slope=1 + index * .1) for index in range(6)}
    mappings = [{"ticker": symbol, "exposure": .9, "confidence": .9, "constituent_role": "CORE"} for symbol in histories]
    result = calculate_basket_signal(histories, mappings, benchmark_rows=histories["S0"], as_of=histories["S0"][-2]["date"])
    assert result["status"] == "ready" and result["pulse"] is not None
    assert result["basket"]["synthetic_index_base"] == 100
    assert result["basket"]["historical_membership_mode"] == "MONTHLY_ROLE_WEIGHT_RECONSTRUCTION"
    assert result["basket"]["rebalance_frequency"] == "MONTHLY"
    assert result["basket"]["coverage_confidence"] == "MEDIUM"
    assert result["basket"]["top_contributors_5d"]
    breadth = result["basket"]["breadth"]
    assert breadth["above_ma20_count"] == 6 and breadth["above_ma20_eligible"] == 6
    assert breadth["positive_20d_count"] == 6 and breadth["positive_20d_eligible"] == 6
    assert all(item["return_20d"] is not None for item in breadth["constituents"])


def test_basket_missing_member_and_minimum_threshold_return_null_not_zero():
    histories = {f"S{index}": _bars(100) for index in range(4)}
    mappings = [{"ticker": symbol, "exposure": .9, "confidence": .9, "constituent_role": "CORE"} for symbol in histories]
    result = calculate_basket_signal(histories, mappings, benchmark_rows=histories["S0"], as_of=histories["S0"][-1]["date"])
    assert result["status"] == "INSUFFICIENT_COVERAGE"
    assert result["pulse"] is None


def test_late_partial_union_day_does_not_hide_latest_complete_basket():
    histories = {f"S{index}": _bars(100) for index in range(5)}
    histories["LATE"] = _bars(101)
    mappings = [{"ticker": symbol, "constituent_role": "CORE"} for symbol in histories]
    result = calculate_basket_signal(histories, mappings, benchmark_rows=histories["S0"])
    assert result["status"] == "ready"
    assert result["basket"]["valid_constituents"] == 6
    assert result["basket"]["as_of"] == histories["S0"][-1]["date"]


def test_hybrid_fallback_and_disagreement_degrade_confidence():
    etf = {"pulse": 80, "confidence": .8, "coverage_quality": .8, "components": {"trend": 80, "breadth": 50}, "heat": 70, "risk": 30, "mood": "strong", "members": ["ETF"]}
    basket = {"pulse": 40, "confidence": .8, "coverage_quality": .8, "components": {"trend": 40, "breadth": 30}, "heat": 40, "risk": 50, "mood": "cooling", "members": ["AAA"], "basket": {}}
    hybrid = calculate_hybrid_composite(etf, basket)
    assert hybrid["proxy_mode"] == "HYBRID"
    assert hybrid["confidence"] < .8 and hybrid["etf_basket_disagreement"] == 40
    assert calculate_hybrid_composite(etf, {"pulse": None})["proxy_mode"] == "DIRECT_ETF"
    assert calculate_hybrid_composite({"pulse": None}, basket)["pulse"] == 40


def test_luna_bootstrap_is_idempotent_and_manual_membership_wins(db):
    ensure_seed_data(db)
    node = db.query(IndustryPulseNode).filter_by(node_key="ai.compute.accelerators").one()
    db.commit()
    def fake(rows):
        return ClassificationBatch(results=[SymbolClassification(symbol=row["symbol"], memberships=[MembershipSuggestion(node=row["candidate_nodes"][0], role="CORE", exposure_weight=.8, confidence=.8, short_reason="fixture evidence")]) for row in rows]), "gpt-5.6-luna"
    first = bootstrap_ai_constituents(db, classifier=fake, hydrate=False)
    second = bootstrap_ai_constituents(db, classifier=fake, hydrate=False)
    assert first["classified"] > 100 and second["due"] == 0
    rows = db.query(IndustryPulseInstrument).filter_by(node_id=node.id, ticker="NVDA").all()
    assert len(rows) == 1 and rows[0].classification_source == "MANUAL_CURATED_SEED"
    amd = db.query(IndustryPulseInstrument).filter_by(node_id=node.id, ticker="AMD").one()
    assert amd.classification_source == "MANUAL_CURATED_SEED"


def test_luna_flat_membership_response_is_normalized():
    payload = {"memberships": [{"company_symbol": "NVDA", "node_id": "ai.compute.accelerators", "exposure": "CORE", "confidence": .95}]}
    result = _normalize_classification_payload(payload)
    assert result.results[0].symbol == "NVDA"
    assert result.results[0].memberships[0].node == "ai.compute.accelerators"
    assert result.results[0].memberships[0].exposure_weight == .9


def test_chain_coverage_and_no_strong_node_semantics(db):
    ensure_seed_data(db)
    group = db.query(IndustryPulseNode).filter_by(taxonomy="ai", level="group").first()
    db.add(IndustryPulseSnapshot(node_id=group.id, trading_date=date(2026, 8, 10), pulse=55, confidence=.8, coverage_quality=.8, metrics_json={"proxy_mode": "EQUITY_BASKET", "basket": {"valid_constituents": 6}}))
    db.commit()
    payload = ai_chain_payload(db)
    assert payload["concentration"]["status"] == "NO_STRONG_NODES"
    assert payload["breadth_summary"]["strong_nodes"] == 0
    assert payload["coverage"]["equity_basket_nodes"] == 1
    assert payload["coverage"]["calculable_nodes"] == 1


def test_chain_concentration_can_move_from_concentrated_to_broad(db):
    ensure_seed_data(db)
    groups = db.query(IndustryPulseNode).filter_by(taxonomy="ai", level="group").all()
    day = date(2026, 8, 10)
    db.add_all([IndustryPulseSnapshot(node_id=node.id, trading_date=day, pulse=70, confidence=.8, coverage_quality=.8) for node in groups[:3]])
    db.commit()
    assert ai_chain_payload(db)["concentration"]["status"] == "CONCENTRATED"
    db.add_all([IndustryPulseSnapshot(node_id=node.id, trading_date=day, pulse=70, confidence=.8, coverage_quality=.8) for node in groups[3:]])
    db.commit()
    assert ai_chain_payload(db)["concentration"]["status"] == "BROAD"


def test_propagation_eligibility_and_deterministic_states(db):
    ensure_seed_data(db)
    edge = db.query(IndustryPulseRelation).filter_by(relation_type="downstream").first()
    day = date(2026, 8, 10)
    for index in range(60):
        current = day - timedelta(days=59 - index)
        db.add(IndustryPulseSnapshot(node_id=edge.source_node_id, trading_date=current, pulse=70, change_5d=2, confidence=.8, coverage_quality=.8))
        db.add(IndustryPulseSnapshot(node_id=edge.target_node_id, trading_date=current, pulse=55, change_5d=2, confidence=.8, coverage_quality=.8))
    db.commit()
    def state():
        return next(row for row in ai_chain_payload(db)["propagation_edges"] if row["source_id"] == edge.source_node_id and row["target_id"] == edge.target_node_id)["status"]
    assert state() == "ACTIVE"
    target = db.query(IndustryPulseSnapshot).filter_by(node_id=edge.target_node_id, trading_date=day).one()
    target.confidence = .4
    db.commit()
    assert state() == "LOW_CONFIDENCE"
    target.confidence, target.coverage_quality = .8, .4
    db.commit()
    assert state() == "INSUFFICIENT_COVERAGE"
    target.coverage_quality, target.pulse, target.change_5d = .8, 45, 0
    db.commit()
    assert state() == "LAGGING"
    source = db.query(IndustryPulseSnapshot).filter_by(node_id=edge.source_node_id, trading_date=day).one()
    source.pulse = 50
    db.commit()
    assert state() == "DORMANT"


def test_propagation_requires_minimum_history(db):
    ensure_seed_data(db)
    edge = db.query(IndustryPulseRelation).filter_by(relation_type="downstream").first()
    day = date(2026, 8, 10)
    db.add_all([IndustryPulseSnapshot(node_id=node_id, trading_date=day, pulse=70, confidence=.8, coverage_quality=.8) for node_id in (edge.source_node_id, edge.target_node_id)])
    db.commit()
    row = next(row for row in ai_chain_payload(db)["propagation_edges"] if row["source_id"] == edge.source_node_id and row["target_id"] == edge.target_node_id)
    assert row["status"] == "INSUFFICIENT_HISTORY"
