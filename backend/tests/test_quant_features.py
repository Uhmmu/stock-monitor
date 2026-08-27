from __future__ import annotations

from copy import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    CryptoAsset,
    CryptoInstrument,
    QuantFeatureSet,
    QuantFeatureValue,
    QuantStrategyDefinition,
)
from app.services.quant.features import (
    build_feature_payload,
    candle_available_at,
    ensure_registry,
    funding_available_at,
    metric_available_at,
    persist_feature_value,
)


HOUR_MS = 3_600_000
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def candle(index: int, *, source_hash: str | None = None, final: bool = True):
    opened = Decimal(100 + index)
    return SimpleNamespace(
        instrument_id=1,
        interval="1h",
        open_time_ms=index * HOUR_MS,
        close_time_ms=(index + 1) * HOUR_MS - 1,
        price_type="trade",
        provider="binance_usdm",
        feed="rest",
        open=opened,
        high=opened + 1,
        low=opened - 1,
        close=opened,
        base_volume=Decimal(10 + index),
        quote_volume=Decimal(1000 + index),
        taker_buy_base_volume=Decimal(6 + index / 10),
        taker_buy_quote_volume=Decimal(600),
        trades=10,
        final=final,
        source_hash=source_hash or f"candle-{index}",
        fetched_at=BASE + timedelta(hours=index + 2),
    )


def metric(*, observed_at: datetime, provider_timestamp: datetime | None = None):
    return SimpleNamespace(
        instrument_id=1,
        interval="1h",
        observed_at=observed_at,
        provider="binance_usdm",
        open_interest_base=Decimal("100"),
        open_interest_quote=None,
        open_interest_usd=None,
        basis=None,
        basis_rate=Decimal("0.01"),
        premium=None,
        mark_price=None,
        index_price=None,
        taker_buy_sell_ratio=Decimal("1.2"),
        taker_buy_volume=None,
        taker_sell_volume=None,
        futures_volume_base=None,
        futures_volume_quote=None,
        source_hash="metric-hash",
        revision=0,
        coverage_start=None,
        coverage_end=None,
        provider_timestamp=provider_timestamp,
        fetched_at=BASE + timedelta(days=1),
        quality="ok",
    )


def funding(*, funding_time: datetime, provider_timestamp: datetime | None = None):
    return SimpleNamespace(
        instrument_id=1,
        funding_time=funding_time,
        provider="binance_usdm",
        funding_rate=Decimal("0.001"),
        mark_price=None,
        source_hash="funding-hash",
        revision=0,
        coverage_start=None,
        coverage_end=None,
        provider_timestamp=provider_timestamp,
        fetched_at=BASE + timedelta(days=1),
        quality="ok",
    )


def test_source_causal_boundaries_and_no_predicted_funding():
    row = candle(1)
    assert candle_available_at(row) == datetime.fromtimestamp(2 * 3600, UTC)
    assert candle_available_at(copy(SimpleNamespace(**{**row.__dict__, "final": False}))) is None

    observed = BASE + timedelta(hours=2)
    derivatives = metric(
        observed_at=observed,
        provider_timestamp=observed + timedelta(hours=3),
    )
    derivatives.coverage_end = observed + timedelta(hours=2)
    assert metric_available_at(derivatives) == observed + timedelta(hours=3)

    realized = funding(
        funding_time=observed,
        provider_timestamp=observed + timedelta(hours=2),
    )
    realized.coverage_end = observed + timedelta(hours=4)
    assert funding_available_at(realized) == observed + timedelta(hours=4)


def test_feature_excludes_future_published_sources_and_freezes_bar():
    candles = [candle(index) for index in range(60)]
    current = candles[-1]
    observed = candle_available_at(current) - timedelta(hours=1)
    derivatives = metric(observed_at=observed, provider_timestamp=observed + timedelta(hours=3))
    realized = funding(funding_time=observed, provider_timestamp=observed + timedelta(hours=4))
    built = build_feature_payload(candles, candle=current, metrics=[derivatives], funding=[realized])

    # Event timestamps are not publication timestamps: both rows are still
    # causally unavailable at this decision bar, so the candle boundary wins.
    assert built["available_at"] == candle_available_at(current)
    assert built["payload"]["derivatives"] == {}
    assert built["payload"]["funding"] == {}
    assert "DERIVATIVES_UNAVAILABLE" in built["warnings"]
    assert "FUNDING_UNAVAILABLE" in built["warnings"]
    assert built["payload"]["bar"]["close"] == str(current.close)
    assert "predicted_rate" not in built["payload"]["funding"]
    assert built["payload"]["sma20"] is not None


def test_feature_uses_causally_eligible_metric_and_funding():
    candles = [candle(index) for index in range(60)]
    current = candles[-1]
    as_of = candle_available_at(current)
    assert as_of is not None
    observed = as_of - timedelta(hours=2)
    derivatives = metric(observed_at=observed, provider_timestamp=as_of - timedelta(hours=1))
    realized = funding(funding_time=observed, provider_timestamp=as_of - timedelta(hours=1))
    built = build_feature_payload(candles, candle=current, metrics=[derivatives], funding=[realized])

    assert built["available_at"] == as_of
    assert built["payload"]["derivatives"]["basis_rate"] == "0.01"
    assert built["payload"]["derivatives"]["taker_buy_sell_ratio"] == "1.2"
    assert built["payload"]["funding"]["funding_rate"] == "0.001"
    assert "DERIVATIVES_UNAVAILABLE" not in built["warnings"]
    assert "FUNDING_UNAVAILABLE" not in built["warnings"]


def test_future_rows_do_not_change_past_feature_hash():
    candles = [candle(index) for index in range(60)]
    target = candles[40]
    before = build_feature_payload(candles, candle=target)
    future = candle(61, source_hash="future-revised")
    after = build_feature_payload(candles + [future], candle=target)
    assert before["input_hash"] == after["input_hash"]
    assert before["payload"] == after["payload"]


def test_source_revision_changes_input_hash():
    candles = [candle(index) for index in range(60)]
    first = build_feature_payload(candles)
    revised = [copy(row) for row in candles]
    revised[-1].source_hash = "revised-source"
    second = build_feature_payload(revised)
    assert first["input_hash"] != second["input_hash"]


def test_append_only_feature_persistence_allows_new_vintage():
    engine = create_engine("sqlite:///:memory:")
    for table in (CryptoAsset, CryptoInstrument, QuantStrategyDefinition, QuantFeatureSet, QuantFeatureValue):
        table.__table__.create(engine)
    with Session(engine) as db:
        registry = ensure_registry(db)
        built = build_feature_payload([candle(index) for index in range(60)])
        first, status = persist_feature_value(db, built, feature_set_id=registry["feature_set_id"])
        again, replay_status = persist_feature_value(db, built, feature_set_id=registry["feature_set_id"])
        revised_candles = [candle(index) for index in range(59)] + [candle(59, source_hash="revision")]
        revised, revised_status = persist_feature_value(
            db,
            build_feature_payload(revised_candles),
            feature_set_id=registry["feature_set_id"],
        )
        assert status == "inserted" and replay_status == "unchanged"
        assert revised_status == "inserted"
        assert again.id == first.id and revised.id != first.id
        assert db.query(QuantFeatureValue).count() == 2
