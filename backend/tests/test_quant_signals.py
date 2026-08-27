"""Goal 5 WP 11.1/11.2 — signal lifecycle and scheduled generation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.quant_routes import router
from app.auth import create_token
from app.config import get_settings
from app.database import Base, get_db
from app.models import CryptoAsset, CryptoInstrument, MarketCandle, QuantSignal, User
from app.services.quant import signals as signal_service
from app.services.quant.features import materialize_features

TABLES = [
    "users", "crypto_assets", "crypto_instruments", "market_candles",
    "crypto_derivatives_metrics", "crypto_funding_rates",
    "quant_strategy_definitions", "quant_feature_sets", "quant_feature_values",
    "quant_strategy_deployments", "quant_signals", "quant_signal_runs",
]


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("QUANT_SIGNAL_ENABLED", "true")
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in TABLES])
    with Session(engine) as session:
        yield session
    engine.dispose()
    get_settings.cache_clear()


def _seed(db: Session, *, falling_tail: int = 0):
    user = User(username="sig", password_hash="x", role="user", status="active")
    other = User(username="other", password_hash="x", role="user", status="active")
    quote = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether", asset_kind="token", status="active")
    db.add_all([user, other, quote]); db.flush()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    asset = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin", asset_kind="coin", status="active")
    db.add(asset); db.flush()
    instrument = CryptoInstrument(
        venue="binance", market="usdm_futures", provider_symbol="BTCUSDT", kind="perpetual",
        base_asset_id=asset.id, quote_asset_id=quote.id, settlement_asset_id=quote.id,
        tick_size=Decimal("0.01"), step_size=Decimal("0.001"), min_notional=Decimal("5"),
        status="trading", calendar="utc",
    )
    db.add(instrument); db.flush()
    total = 65 + falling_tail
    for index in range(total):
        open_ms = int((start + timedelta(hours=index)).timestamp() * 1000)
        if index < 65:
            price = Decimal(100 + index)
        else:
            price = Decimal(164 - (index - 65) * 2)
        db.add(MarketCandle(
            instrument_id=instrument.id, interval="1h", open_time_ms=open_ms,
            close_time_ms=open_ms + 3_599_999, price_type="trade", provider="binance_usdm", feed="rest",
            open=price, high=price + 2, low=price - 1, close=price + 1,
            base_volume=100 + index, quote_volume=10_000, taker_buy_base_volume=60, trades=10,
            source_hash=f"{index:064d}"[-64:], final=True, fetched_at=start + timedelta(days=10),
        ))
    db.commit()
    materialize_features(db, [instrument], ["1h"]); db.commit()
    return user, other, instrument, start


def _active_deployment(db: Session, user, instrument, *, strategy="dual-ma-trend-v1", interval="1h"):
    deployment = signal_service.create_deployment(
        db, user_id=user.id, strategy_key=strategy, instrument_id=instrument.id,
        interval=interval, target_exposure=1.0,
    )
    signal_service.set_deployment_status(db, deployment, status="active")
    db.refresh(deployment)
    return deployment


def _signal(db: Session, signal_id: int) -> QuantSignal:
    return db.scalar(select(QuantSignal).where(QuantSignal.id == signal_id))


def test_boundary_math_uses_utc_floor_and_lag():
    now = datetime(2026, 3, 1, 14, 7, tzinfo=UTC)
    assert signal_service.boundary_for("1h", now) == datetime(2026, 3, 1, 14, tzinfo=UTC)
    now = datetime(2026, 3, 1, 14, 3, tzinfo=UTC)
    assert signal_service.boundary_for("1h", now) == datetime(2026, 3, 1, 13, tzinfo=UTC)
    now = datetime(2026, 3, 1, 14, 7, tzinfo=UTC)
    assert signal_service.boundary_for("4h", now) == datetime(2026, 3, 1, 12, tzinfo=UTC)
    expiry = signal_service.signal_expiry(datetime(2026, 3, 1, 14, tzinfo=UTC), "1h")
    assert expiry == datetime(2026, 3, 1, 14, 55, tzinfo=UTC)


def test_deployment_starts_paused_and_duplicates_rejected(db):
    user, _other, instrument, _start = _seed(db)
    deployment = signal_service.create_deployment(
        db, user_id=user.id, strategy_key="dual-ma-trend-v1",
        instrument_id=instrument.id, interval="1h", target_exposure=0.5,
    )
    assert deployment.status == "paused" and deployment.environment == "paper"
    assert Decimal(str(deployment.target_exposure)) == Decimal("0.5")
    with pytest.raises(RuntimeError):
        signal_service.create_deployment(
            db, user_id=user.id, strategy_key="dual-ma-trend-v1",
            instrument_id=instrument.id, interval="1h",
        )
    with pytest.raises(ValueError):
        signal_service.create_deployment(
            db, user_id=user.id, strategy_key="not-a-strategy",
            instrument_id=instrument.id, interval="1h",
        )
    with pytest.raises(ValueError):
        signal_service.create_deployment(
            db, user_id=user.id, strategy_key="dual-ma-trend-v1",
            instrument_id=instrument.id, interval="13m",
        )


def test_generation_is_deterministic_deduped_and_bounded(db):
    user, _other, instrument, start = _seed(db, falling_tail=1)
    deployment = _active_deployment(db, user, instrument)
    now = start + timedelta(hours=65, minutes=10)
    run = signal_service.generate_for_deployment(db, deployment, now=now)
    assert run.status == "signal_created"
    signal = _signal(db, run.signal_id)
    assert Decimal(str(signal.target_exposure)) == Decimal("1")  # rising series: SMA20 > SMA50
    assert signal.environment == "paper"
    assert signal.idempotency_key == signal_service.signal_idempotency_key(deployment, run.boundary)
    # No order-shaped fields exist on the signal model.
    for forbidden in ("side", "order_type", "price", "quantity"):
        assert not hasattr(signal, forbidden)
    # Same decision point again → the finalized run returns unchanged; still one logical signal.
    again = signal_service.generate_for_deployment(db, deployment, now=now + timedelta(minutes=5))
    assert again.id == run.id and again.status == "signal_created" and again.signal_id == signal.id
    assert db.scalar(select(func.count()).select_from(QuantSignal)) == 1
    # Unchanged target at the next boundary → no_signal record with reason.
    later = signal_service.generate_for_deployment(db, deployment, now=now + timedelta(hours=1, minutes=10))
    assert later.status == "no_signal" and later.reason == "target unchanged"


def test_new_target_supersedes_prior_active_signal(db):
    user, _other, instrument, start = _seed(db, falling_tail=60)
    deployment = _active_deployment(db, user, instrument)
    first = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=10),
    )
    assert first.status == "signal_created"
    signal_one = _signal(db, first.signal_id)
    second = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=125, minutes=10),
    )
    assert second.status == "signal_created"
    db.refresh(signal_one)
    assert signal_one.status == "superseded" and signal_one.superseded_by_id == second.signal_id
    assert Decimal(str(_signal(db, second.signal_id).target_exposure)) == Decimal("-1")  # falling tail


def test_missing_feature_records_missing_data_and_retries(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument, interval="4h")
    now = start + timedelta(hours=65, minutes=10)
    run = signal_service.generate_for_deployment(db, deployment, now=now)
    assert run.status == "missing_data"
    db.refresh(run)
    assert run.retries == 0  # first attempt creates the run
    retry = signal_service.generate_for_deployment(db, deployment, now=now + timedelta(minutes=5))
    assert retry.id == run.id and retry.retries == 1


def test_stale_boundary_past_decision_window_is_skipped(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    run = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=10),
    )
    assert run.status == "signal_created"
    # Way past the validity window, the (already deduped) boundary cannot mint a new signal.
    late = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=70, minutes=10),
    )
    assert late.boundary != run.boundary  # a newer boundary is selected instead


def test_paused_deployment_generates_nothing_and_retires_active_signal(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    run = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=10),
    )
    signal = _signal(db, run.signal_id)
    signal_service.set_deployment_status(db, deployment, status="paused", reason="user pause")
    db.refresh(signal)
    assert signal.status == "superseded"
    assert signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=20),
    ) is None


def test_expiry_is_terminal_and_unleaseable_forever(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    now = start + timedelta(hours=65, minutes=10)
    run = signal_service.generate_for_deployment(db, deployment, now=now)
    signal = _signal(db, run.signal_id)
    # Leasable before expiry, exactly once.
    assert signal_service.consume_signal(db, signal.id, now=now + timedelta(minutes=30)) is not None
    assert signal_service.consume_signal(db, signal.id, now=now + timedelta(minutes=31)) is None
    # A still-generated signal expires and can never be consumed afterwards.
    deployment2 = signal_service.create_deployment(
        db, user_id=user.id, strategy_key="rsi-mean-reversion-v1",
        instrument_id=instrument.id, interval="1h",
    )
    signal_service.set_deployment_status(db, deployment2, status="active")
    db.refresh(deployment2)
    run2 = signal_service.generate_for_deployment(db, deployment2, now=now)
    signal2 = _signal(db, run2.signal_id)
    expired = signal_service.expire_due_signals(db, now=now + timedelta(hours=2))
    assert expired >= 1
    db.refresh(signal2)
    assert signal2.status == "expired"
    assert signal_service.consume_signal(db, signal2.id, now=now + timedelta(hours=3)) is None


def test_reject_is_only_valid_from_generated(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    run = signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=10),
    )
    signal = _signal(db, run.signal_id)
    signal_service.reject_signal(db, signal, "risk cap")
    db.refresh(signal)
    assert signal.status == "rejected" and signal.rejected_reason == "risk cap"
    with pytest.raises(RuntimeError):
        signal_service.reject_signal(db, signal, "again")


def test_signal_ownership_and_status_filter(db):
    user, other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    signal_service.generate_for_deployment(
        db, deployment, now=start + timedelta(hours=65, minutes=10),
    )
    assert signal_service.get_signal(db, other.id, 1) is None
    listing = signal_service.list_signals(
        db, user.id, status="generated", now=start + timedelta(hours=65, minutes=20),
    )
    assert listing["total"] == 1 and listing["items"][0]["status"] == "generated"
    payload = listing["items"][0]
    assert payload["expires_in_seconds"] > 0 and "server_time" in payload
    with pytest.raises(ValueError):
        signal_service.list_signals(db, user.id, status="not-a-status")


def test_generate_due_signals_counts_and_expires(db):
    user, _other, instrument, start = _seed(db)
    deployment = _active_deployment(db, user, instrument)
    paused = signal_service.create_deployment(
        db, user_id=user.id, strategy_key="rsi-mean-reversion-v1",
        instrument_id=instrument.id, interval="1h",
    )
    result = signal_service.generate_due_signals(db, now=start + timedelta(hours=65, minutes=10))
    assert result["deployments"] == 1  # paused deployments are not selected
    assert result["runs"].get("signal_created") == 1
    assert paused.status == "paused"


@pytest.fixture()
def client(db):
    user, _other, instrument, start = _seed(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {create_token(user.id)}"})
        yield test_client, user, instrument, start
    app.dependency_overrides.pop(get_db, None)


def test_signal_api_requires_enabled_flag(db, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("QUANT_SIGNAL_ENABLED", raising=False)
    user = User(username="flag", password_hash="x", role="user", status="active")
    db.add(user); db.commit(); db.refresh(user)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {create_token(user.id)}"})
        assert test_client.get("/api/crypto/quant/signals").status_code == 503
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def test_signal_read_api_contract(client):
    test_client, user, instrument, _start = client
    response = test_client.post("/api/crypto/quant/deployments", json={
        "strategy_key": "dual-ma-trend-v1", "instrument_id": instrument.id,
        "interval": "1h", "target_exposure": 1.0,
    })
    assert response.status_code == 201
    deployment_id = response.json()["id"]
    assert response.json()["status"] == "paused"
    resume = test_client.post(f"/api/crypto/quant/deployments/{deployment_id}/resume")
    assert resume.status_code == 200 and resume.json()["status"] == "active"
    duplicate = test_client.post("/api/crypto/quant/deployments", json={
        "strategy_key": "dual-ma-trend-v1", "instrument_id": instrument.id,
        "interval": "1h", "target_exposure": 0.5,
    })
    assert duplicate.status_code == 409
    assert test_client.get("/api/crypto/quant/signals").json()["total"] == 0
    assert test_client.get("/api/crypto/quant/signals", params={"status": "bogus"}).status_code == 422
    assert test_client.get("/api/crypto/quant/signals/999").status_code == 404
    assert test_client.get("/api/crypto/quant/signals/runs").json()["total"] == 0
    pause = test_client.post(f"/api/crypto/quant/deployments/{deployment_id}/pause", json={"reason": "hold"})
    assert pause.status_code == 200 and pause.json()["status"] == "paused"
    assert pause.json()["pause_reason"] == "hold"
