from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CryptoAsset, CryptoInstrument, MarketCandle, User
from app.services.quant.backtest.service import _funding_at_boundary, create_run, execute_run, owned_run, rerun
from app.services.quant.features import materialize_features
from app.tasks.celery_app import celery_app


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session):
    user = User(username="quant", password_hash="x", role="admin", status="active")
    other = User(username="other", password_hash="x", role="user", status="active")
    quote = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether", asset_kind="token", status="active")
    db.add_all([user, other, quote]); db.flush()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    instruments = []
    for offset, (slug, symbol) in enumerate((("bitcoin", "BTC"), ("ethereum", "ETH"), ("cardano", "ADA"))):
        asset = CryptoAsset(slug=slug, symbol=symbol, display_name=symbol, asset_kind="coin", status="active")
        db.add(asset); db.flush()
        instrument = CryptoInstrument(
            venue="binance", market="usdm_futures", provider_symbol=f"{symbol}USDT", kind="perpetual",
            base_asset_id=asset.id, quote_asset_id=quote.id, settlement_asset_id=quote.id,
            tick_size=Decimal("0.01"), step_size=Decimal("0.001"), min_notional=Decimal("5"),
            status="trading", calendar="utc",
        )
        db.add(instrument); db.flush(); instruments.append(instrument)
        for index in range(65):
            open_ms = int((start + timedelta(hours=index)).timestamp() * 1000)
            price = Decimal(100 + offset * 10 + index)
            db.add(MarketCandle(
                instrument_id=instrument.id, interval="1h", open_time_ms=open_ms,
                close_time_ms=open_ms + 3_599_999, price_type="trade", provider="binance_usdm", feed="rest",
                open=price, high=price + 2, low=price - 1, close=price + 1,
                base_volume=100 + index, quote_volume=10_000, taker_buy_base_volume=60, trades=10,
                source_hash=f"{offset:02d}{index:062d}"[-64:], final=True, fetched_at=start + timedelta(days=10),
            ))
    db.commit()
    materialize_features(db, instruments, ["1h"]); db.commit()
    return user, other, instruments, start


def _create(db, user, instruments, start):
    return create_run(
        db, user_id=user.id, strategy_key="dual-ma-trend-v1",
        instrument_ids=[row.id for row in instruments], interval="1h",
        start_at=start, end_at=start + timedelta(hours=65), target_exposure=1,
        initial_capital=Decimal("100000"), leverage=Decimal("1"),
        taker_fee_bps=Decimal("5"), spread_bps=Decimal("2"), slippage_bps=Decimal("2"), split_mode="full",
    )


def test_three_instrument_run_is_owned_replayable_and_deterministic(db):
    user, other, instruments, start = _seed(db)
    run = _create(db, user, instruments, start)
    assert owned_run(db, other.id, run.id) is None
    execute_run(db, run.id); db.refresh(run)
    assert run.status == "completed" and run.result_hash
    replay = rerun(db, run)
    execute_run(db, replay.id); db.refresh(replay)
    assert replay.result_hash == run.result_hash
    assert replay.manifest_hash == run.manifest_hash


def test_quant_tasks_are_isolated_on_single_queue():
    expected = {
        "app.tasks.celery_app.ensure_crypto_quant_features_fresh",
        "app.tasks.celery_app.run_crypto_backtest",
    }
    assert {celery_app.tasks[name].queue for name in expected} == {"quant"}
    assert celery_app.conf.beat_schedule["materialize-crypto-quant-features"]["task"] in expected


def test_realized_funding_is_applied_once_at_its_exact_boundary():
    boundary = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [
        type("Feature", (), {"payload": {"funding": {"funding_time": boundary.isoformat(), "funding_rate": "0.001"}}})(),
        type("Feature", (), {"payload": {"funding": {"funding_time": boundary.isoformat(), "funding_rate": "0.001"}}})(),
    ]
    assert _funding_at_boundary(rows, 1, boundary) == "0.001"
    assert _funding_at_boundary(rows, 1, boundary + timedelta(hours=1)) == "0"
