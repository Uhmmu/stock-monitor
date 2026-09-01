"""Goal 5 WP 12.1/12.2 — paper account state machine and reconciliation tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.quant_routes import router
from app.auth import create_token
from app.config import get_settings
from app.database import Base, get_db
from app.models import (
    CryptoAsset,
    CryptoInstrument,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    QuantFeatureValue,
    QuantSignal,
    QuantStrategyDeployment,
    User,
)
from app.services.quant import paper as paper_service
from app.services.quant import signals as signal_service
from app.services.quant.backtest.contracts import BacktestConfig, InstrumentSpec
from app.services.quant.backtest.engine import _fill_price
from app.services.quant.features import ensure_registry
from app.services.quant.paper_fill import PaperQuote

TABLES = [
    "users", "crypto_assets", "crypto_instruments", "market_candles",
    "crypto_derivatives_metrics", "crypto_funding_rates",
    "quant_strategy_definitions", "quant_feature_sets", "quant_feature_values",
    "quant_strategy_deployments", "quant_signals", "quant_signal_runs",
    "paper_accounts", "paper_runs", "paper_balances", "paper_orders", "paper_fills", "paper_funding_entries",
    "paper_positions", "paper_reconciliations", "paper_ledger_events",
]


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("QUANT_SIGNAL_ENABLED", "true")
    monkeypatch.setenv("QUANT_PAPER_ENABLED", "true")
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


def _seed(db: Session, *, symbols=("BTCUSDT",)):
    user = User(username="paper", password_hash="x", role="user", status="active")
    other = User(username="other", password_hash="x", role="user", status="active")
    quote = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether", asset_kind="token", status="active")
    db.add_all([user, other, quote]); db.flush()
    instruments = []
    for index, symbol in enumerate(symbols):
        asset = CryptoAsset(
            slug=symbol.lower(), symbol=symbol.removesuffix("USDT"),
            display_name=symbol, asset_kind="coin", status="active",
        )
        db.add(asset); db.flush()
        instrument = CryptoInstrument(
            venue="binance", market="usdm_futures", provider_symbol=symbol, kind="perpetual",
            base_asset_id=asset.id, quote_asset_id=quote.id, settlement_asset_id=quote.id,
            tick_size=Decimal("0.01"), step_size=Decimal("0.001"), min_notional=Decimal("5"),
            status="trading", calendar="utc",
        )
        db.add(instrument); db.flush()
        instruments.append(instrument)
    ensure_registry(db)
    db.commit()
    return user, other, instruments


def _deployment(db: Session, user, instrument, *, strategy="dual-ma-trend-v1"):
    deployment = signal_service.create_deployment(
        db, user_id=user.id, strategy_key=strategy, instrument_id=instrument.id,
        interval="1h", target_exposure=Decimal("1"),
    )
    signal_service.set_deployment_status(db, deployment, status="active")
    db.refresh(deployment)
    return deployment


def _make_signal(
    db: Session, deployment: QuantStrategyDeployment, *, target: str, close: str = "165",
    decision: datetime | None = None, valid_for: timedelta = timedelta(minutes=50),
) -> QuantSignal:
    moment = decision or datetime.now(UTC)
    signal = QuantSignal(
        user_id=deployment.user_id, deployment_id=deployment.id, environment="paper",
        status="generated", strategy_key=deployment.strategy_key,
        strategy_version=deployment.strategy_version, instrument_id=deployment.instrument_id,
        interval=deployment.interval, decision_time=moment,
        target_exposure=Decimal(target), reason="test signal",
        evidence={"bar": {"close": close}},
        data_hash=uuid.uuid4().hex, feature_hash=uuid.uuid4().hex, code_hash=uuid.uuid4().hex,
        idempotency_key=f"sig-{uuid.uuid4().hex}",
        valid_from=moment, expires_at=moment + valid_for,
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def _account(db: Session, user, **kwargs) -> PaperAccount:
    account, _created = paper_service.ensure_account(db, user_id=user.id, **kwargs)
    return account


def _spot_instrument(db: Session, futures: CryptoInstrument) -> CryptoInstrument:
    spot = CryptoInstrument(
        venue="binance", market="spot", provider_symbol=futures.provider_symbol, kind="spot",
        base_asset_id=futures.base_asset_id, quote_asset_id=futures.quote_asset_id,
        tick_size=futures.tick_size, step_size=futures.step_size, min_notional=futures.min_notional,
        status="trading", calendar="utc",
    )
    db.add(spot); db.commit(); db.refresh(spot)
    return spot


def _quote(bid="99", ask="100", mark=None, *, observed_at: datetime | None = None):
    return PaperQuote(
        Decimal(bid), Decimal(ask), observed_at or datetime.now(UTC),
        Decimal(mark) if mark else None,
    )


def test_fill_price_parity_with_backtest_engine():
    config = BacktestConfig(
        initial_capital=Decimal("10000"), interval="1h", leverage=Decimal("1"),
        strategy_name="dual-ma-trend-v1", taker_fee_bps=Decimal("5"),
        full_spread_bps=Decimal("2"), slippage_bps=Decimal("2"), seed=0,
    )
    instrument = InstrumentSpec(
        instrument_id=1, symbol="BTCUSDT", tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"), min_notional=Decimal("5"),
    )
    for raw in (Decimal("165"), Decimal("0.3123"), Decimal("99_999.5")):
        for buy in (True, False):
            engine_price, engine_spread, engine_slip = _fill_price(raw, config, instrument, buy=buy)
            paper_price, paper_spread, paper_slip = paper_service.simulate_fill_price(
                raw, tick_size=instrument.tick_size, spread_bps=Decimal("2"),
                slippage_bps=Decimal("2"), buy=buy,
            )
            assert paper_price == engine_price
            assert paper_spread == engine_spread
            assert paper_slip == engine_slip


def test_open_duplicate_flatten_and_ledger_rebuild(db):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    initial = Decimal("10000")
    now = datetime.now(UTC)

    opened = _make_signal(db, deployment, target="1")
    outcome = paper_service.process_signal(db, account, opened, now=now + timedelta(minutes=10))
    assert outcome == "filled"
    order = db.scalar(select(PaperOrder))
    assert order is not None and order.side == "buy" and order.status == "filled"
    expected_qty = (Decimal("1") * initial / Decimal("165")).quantize(Decimal("0.001"))
    assert Decimal(str(order.intended_quantity)) == expected_qty
    expected_price, _spread, _slip = paper_service.simulate_fill_price(
        Decimal("165"), tick_size=Decimal("0.01"), spread_bps=Decimal("2"),
        slippage_bps=Decimal("2"), buy=True,
    )
    assert Decimal(str(order.avg_fill_price)) == expected_price
    position = db.scalar(select(PaperPosition))
    assert Decimal(str(position.quantity)) == expected_qty
    assert Decimal(str(position.avg_entry_price)) == expected_price
    expected_fee = expected_qty * expected_price * Decimal("5") / Decimal("10_000")
    assert account.cash == initial - expected_fee
    # Perpetual-margin NAV: opening spends no cash, so NAV must equal cash plus
    # entry-relative unrealized PnL (mark = entry right after the fill), never
    # cash plus full notional.
    nav, _warnings = paper_service.account_nav(db, account)
    assert nav == initial - expected_fee
    db.refresh(opened)
    assert opened.status == "consumed" and opened.consumed_reason

    # Re-processing the same signal cannot mint a second logical order/fill.
    again = paper_service.process_signal(db, account, opened, now=now + timedelta(minutes=11))
    assert again == "duplicate_order"
    assert db.scalar(select(PaperOrder.id).where(PaperOrder.id == order.id)) is not None
    assert len(list(db.scalars(select(PaperFill)))) == 1

    # Flatten to zero: realized PnL flows into cash, position resets.
    flattened = _make_signal(db, deployment, target="0")
    outcome = paper_service.process_signal(db, account, flattened, now=now + timedelta(minutes=20))
    assert outcome == "filled"
    db.refresh(position)
    assert Decimal(str(position.quantity)) == 0
    assert Decimal(str(position.avg_entry_price)) == 0
    sell_price, _s, _l = paper_service.simulate_fill_price(
        Decimal("165"), tick_size=Decimal("0.01"), spread_bps=Decimal("2"),
        slippage_bps=Decimal("2"), buy=False,
    )
    expected_realized = (sell_price - expected_price) * expected_qty
    assert Decimal(str(position.realized_pnl)) == expected_realized
    sell_fee = expected_qty * sell_price * Decimal("5") / Decimal("10_000")
    assert account.cash == initial - expected_fee + expected_realized - sell_fee

    # Restart drill: the ledger rebuild must match the derived cache exactly.
    derived = paper_service.rebuild_from_ledger(db, account)
    ledger_position = derived["positions"][instrument.id]
    assert ledger_position["quantity"] == Decimal(str(position.quantity))
    assert ledger_position["avg_entry_price"] == Decimal(str(position.avg_entry_price))
    assert ledger_position["realized_pnl"] == Decimal(str(position.realized_pnl))
    assert derived["cash"] == account.cash


def test_below_min_notional_delta_consumes_without_order(db):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    signal = _make_signal(db, deployment, target="0.00001")
    outcome = paper_service.process_signal(db, account, signal, now=datetime.now(UTC) + timedelta(minutes=5))
    assert outcome == "no_delta"
    db.refresh(signal)
    assert signal.status == "consumed" and "no material delta" in (signal.consumed_reason or "")
    assert db.scalar(select(PaperOrder)) is None


def test_leverage_cap_rejects_second_instrument(db):
    user, _other, (btc, eth) = _seed(db, symbols=("BTCUSDT", "ETHUSDT"))
    btc_deployment = _deployment(db, user, btc)
    eth_deployment = _deployment(db, user, eth, strategy="rsi-mean-reversion-v1")
    account = _account(db, user, initial_cash=Decimal("10000"), leverage_cap=Decimal("1"))
    now = datetime.now(UTC)
    first = _make_signal(db, btc_deployment, target="1")
    assert paper_service.process_signal(db, account, first, now=now) == "filled"
    nav, _warnings = paper_service.account_nav(db, account)
    second = _make_signal(db, eth_deployment, target="1", close="165")
    outcome = paper_service.process_signal(db, account, second, now=now)
    assert outcome == "rejected"
    db.refresh(second)
    assert second.status == "rejected" and "leverage cap" in (second.rejected_reason or "")
    assert db.scalar(select(PaperOrder).where(PaperOrder.signal_id == second.id)) is None
    assert nav > 0


def test_expired_signal_never_leases_and_pauses_block_processing(db):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    now = datetime.now(UTC)
    stale = _make_signal(db, deployment, target="1", valid_for=timedelta(minutes=5))
    outcome = paper_service.process_signal(db, account, stale, now=now + timedelta(minutes=30))
    assert outcome == "signal_expired"
    db.refresh(stale)
    assert stale.status == "expired"
    assert db.scalar(select(PaperOrder)) is None

    # Paused accounts process nothing even with a leasable signal present.
    fresh = _make_signal(db, deployment, target="1")
    paper_service.set_account_status(db, account, status="paused", reason="kill switch")
    summary = paper_service.process_pending_signals(db, account, now=now + timedelta(minutes=31))
    assert summary["account"] == "paused" and not summary.get("outcomes")
    paper_service.set_account_status(db, account, status="active")
    processing_time = now + timedelta(minutes=32)
    summary = paper_service.process_pending_signals(
        db, account, now=processing_time,
        quotes={instrument.id: _quote("164", "165", "164.5", observed_at=processing_time)},
    )
    assert summary["outcomes"].get("filled") == 1
    assert summary["account"] == "processed"
    db.refresh(fresh)
    assert fresh.status == "consumed"


def test_pending_signal_waits_for_fresh_public_quote(db, monkeypatch):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    signal = _make_signal(db, deployment, target="1")
    monkeypatch.setattr(
        paper_service, "public_quote",
        lambda _instrument: (_ for _ in ()).throw(TimeoutError("public quote timeout")),
    )

    summary = paper_service.process_pending_signals(db, account)

    assert summary["outcomes"] == {"market_data_unavailable": 1}
    assert summary["market_data_warnings"] == [f"signal {signal.id}: public quote timeout"]
    db.refresh(signal)
    assert signal.status == "generated"
    assert db.scalar(select(PaperOrder)) is None


def test_partial_fills_advance_the_state_machine(db):
    user, _other, (instrument,) = _seed(db)
    account = _account(db, user)
    order = PaperOrder(
        user_id=user.id, account_id=account.id, run_id=account.current_run_id, signal_id=None,
        client_order_id=f"paper-{account.id}-manual", instrument_id=instrument.id,
        side="buy", intended_quantity=Decimal("10"), reference_price=Decimal("165"),
        status="pending",
    )
    db.add(order); db.commit(); db.refresh(order)
    first = paper_service.apply_fill(db, account, order, Decimal("4"), event_key="partial-fill-1")
    assert order.status == "partially_filled" and Decimal(str(order.filled_quantity)) == 4
    replay = paper_service.apply_fill(db, account, order, Decimal("4"), event_key="partial-fill-1")
    assert replay.id == first.id and Decimal(str(order.filled_quantity)) == 4
    expected_avg_1 = Decimal(str(order.avg_fill_price))
    second = paper_service.apply_fill(db, account, order, Decimal("6"))
    assert order.status == "filled" and Decimal(str(order.filled_quantity)) == 10
    total_fee = Decimal(str(first.fee)) + Decimal(str(second.fee))
    assert Decimal(str(order.fee)) == total_fee
    # Weighted average fill price across both partial fills.
    expected_avg = (4 * Decimal(str(first.price)) + 6 * Decimal(str(second.price))) / 10
    assert Decimal(str(order.avg_fill_price)) == expected_avg
    assert Decimal(str(expected_avg_1)) == Decimal(str(first.price))
    with pytest.raises(ValueError):
        paper_service.apply_fill(db, account, order, Decimal("1"))


def test_funding_accrual_is_persisted_idempotent_and_in_ledger(db):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    raw_now = datetime.now(UTC)
    now = datetime.fromtimestamp((int(raw_now.timestamp()) // (8 * 3600)) * (8 * 3600), UTC)
    boundary = now - timedelta(hours=8)
    opened = _make_signal(db, deployment, target="1", decision=boundary - timedelta(minutes=30))
    paper_service.process_signal(db, account, opened, now=boundary - timedelta(minutes=20))
    position = db.scalar(select(PaperPosition))
    quantity = Decimal(str(position.quantity))
    assert quantity > 0

    feature_set_id = ensure_registry(db)["feature_set_id"]
    db.add(QuantFeatureValue(
        feature_set_id=feature_set_id, instrument_id=instrument.id, interval="1h",
        bar_open_time_ms=int((boundary - timedelta(hours=1)).timestamp() * 1000),
        as_of=boundary, available_at=boundary,
        input_hash=uuid.uuid4().hex, input_snapshot={}, payload={
            "bar": {"open": "160", "close": "160"},
            "funding": {"funding_time": boundary.isoformat(), "funding_rate": "0.0001"},
        },
        coverage=1.0, quality="ok", omissions=[], warnings=[],
    ))
    account.last_funding_boundary = boundary - timedelta(hours=8)
    db.commit()

    result = paper_service.apply_due_funding(db, account, now=now)
    assert result["applied"] == 1
    entry = db.scalar(select(paper_service.PaperFundingEntry))
    expected_delta = -(quantity * Decimal("160") * Decimal("0.0001"))
    assert Decimal(str(entry.cash_delta)) == expected_delta
    db.refresh(account)
    # Idempotent: replaying the same window applies nothing new.
    again = paper_service.apply_due_funding(db, account, now=now)
    assert again["applied"] == 0
    # Funding entries are part of the ledger rebuild.
    derived = paper_service.rebuild_from_ledger(db, account)
    assert derived["funding_count"] == 1
    assert derived["cash"] == account.cash


def test_reconciliation_repairs_tampered_cache(db):
    user, _other, (instrument,) = _seed(db)
    deployment = _deployment(db, user, instrument)
    account = _account(db, user)
    now = datetime.now(UTC)
    opened = _make_signal(db, deployment, target="1")
    paper_service.process_signal(db, account, opened, now=now)
    clean = paper_service.reconcile_account(db, account)
    assert clean.status == "ok" and clean.mismatches == [], clean.mismatches
    position = db.scalar(select(PaperPosition))
    tampered_quantity = Decimal(str(position.quantity)) + Decimal("7")
    position.quantity = tampered_quantity
    account.cash = Decimal(str(account.cash)) + Decimal("100")
    db.commit()
    detected = paper_service.reconcile_account(db, account)
    assert detected.status == "mismatch" and len(detected.mismatches) >= 1
    # Background reconciliation is detect-only; repair requires explicit authority.
    repaired = paper_service.reconcile_account(db, account, repair=True)
    assert repaired.status == "repaired" and len(repaired.mismatches) >= 1
    position = db.scalar(select(PaperPosition).where(PaperPosition.account_id == account.id))
    db.refresh(account)
    derived = paper_service.rebuild_from_ledger(db, account)
    assert Decimal(str(position.quantity)) == derived["positions"][instrument.id]["quantity"]
    assert account.cash == derived["cash"]
    stable = paper_service.reconcile_account(db, account)
    assert stable.status == "ok"


def test_account_isolation_and_validation(db):
    user, other, (instrument,) = _seed(db)
    account = _account(db, user, initial_cash=Decimal("5000"))
    assert paper_service.owned_account(db, other.id) is None
    duplicate, created = paper_service.ensure_account(db, user_id=user.id)
    assert created == "existing" and duplicate.id == account.id
    with pytest.raises(ValueError):
        paper_service.ensure_account(db, user_id=other.id, initial_cash=Decimal("1"))
    with pytest.raises(ValueError):
        paper_service.ensure_account(db, user_id=other.id, leverage_cap=Decimal("10"))


def test_spot_market_buy_sell_balance_fees_and_duplicate_submit(db):
    user, _other, (future,) = _seed(db)
    spot = _spot_instrument(db, future)
    account = _account(db, user, initial_cash=Decimal("1000"))
    bought = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="buy", order_type="market",
        quantity="2", quote=_quote(), client_order_id="paper-spot-buy-0001",
    )
    duplicate = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="buy", order_type="market",
        quantity="2", quote=_quote(), client_order_id="paper-spot-buy-0001",
    )
    assert bought.id == duplicate.id and bought.status == "filled"
    base = paper_service._balance(db, account, "BTC")
    assert base.available == Decimal("2")
    assert account.cash < Decimal("800")
    sold = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="sell", order_type="market",
        quantity="1", quote=_quote(), client_order_id="paper-spot-sell-0001",
    )
    assert sold.status == "filled" and base.available == Decimal("1")
    with pytest.raises(ValueError, match="insufficient Spot base"):
        paper_service.submit_manual_order(
            db, account, instrument_id=spot.id, side="sell", order_type="market",
            quantity="2", quote=_quote(), client_order_id="paper-spot-sell-0002",
        )
    assert len(paper_service.list_ledger(db, account)["items"]) >= 5


def test_limit_cross_cancel_and_restart_recovery(db):
    user, _other, (future,) = _seed(db)
    spot = _spot_instrument(db, future)
    account = _account(db, user, initial_cash=Decimal("1000"))
    pending = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="buy", order_type="limit",
        quantity="1", limit_price="95", quote=_quote(), client_order_id="paper-limit-buy-0001",
    )
    assert pending.status == "pending" and account.locked_cash > 0
    db.expire_all()  # process-style restart: recover the durable open row, not process memory
    account = db.get(PaperAccount, account.id)
    result = paper_service.process_open_orders(db, account, quotes={spot.id: _quote("94", "95")})
    db.refresh(pending)
    assert result["filled"] == 1 and pending.status == "filled" and account.locked_cash == 0

    sell_limit = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="sell", order_type="limit",
        quantity="1", limit_price="105", quote=_quote(), client_order_id="paper-limit-sell-0001",
    )
    assert sell_limit.status == "pending" and paper_service._balance(db, account, "BTC").locked == 1
    sold = paper_service.process_open_orders(db, account, quotes={spot.id: _quote("105", "106")})
    assert sold["filled"] == 1 and sell_limit.status == "filled"

    pending2 = paper_service.submit_manual_order(
        db, account, instrument_id=spot.id, side="buy", order_type="limit",
        quantity="1", limit_price="90", quote=_quote(), client_order_id="paper-limit-buy-0002",
    )
    cancelled = paper_service.cancel_order(db, account, pending2.id)
    assert cancelled.status == "cancelled" and account.locked_cash == 0


def test_futures_long_short_margin_liquidation_and_run_reset(db):
    user, _other, (future,) = _seed(db)
    account = _account(db, user, initial_cash=Decimal("1000"), leverage_cap=Decimal("3"))
    long = paper_service.submit_manual_order(
        db, account, instrument_id=future.id, side="buy", order_type="market",
        quantity="20", leverage="3", position_side="LONG", quote=_quote("99", "100", "100"),
        client_order_id="paper-future-long-0001",
    )
    assert long.status == "filled"
    position = db.scalar(select(PaperPosition).where(PaperPosition.run_id == account.current_run_id))
    assert position.quantity > 0 and position.margin_used > 0
    liquidation = paper_service.check_liquidation(
        db, account, quotes={future.id: _quote("49", "50", "50")},
    )
    db.refresh(position)
    assert liquidation["liquidated"] == 1 and position.quantity == 0
    assert any(item["event_type"] == "LIQUIDATION" for item in paper_service.list_ledger(db, account)["items"])

    old_run = account.current_run_id
    new_run = paper_service.reset_account(db, account, initial_cash="2000", strategy_metadata={"strategy": "v2"})
    assert new_run.id != old_run and account.cash == Decimal("2000")
    runs = paper_service.list_runs(db, account)["items"]
    assert len(runs) == 2 and runs[1]["status"] == "completed"
    short = paper_service.submit_manual_order(
        db, account, instrument_id=future.id, side="sell", order_type="market",
        quantity="1", leverage="2", position_side="SHORT", quote=_quote("99", "100", "100"),
        client_order_id="paper-future-short-0001",
    )
    closed = paper_service.submit_manual_order(
        db, account, instrument_id=future.id, side="buy", order_type="market",
        quantity="1", leverage="2", position_side="SHORT", quote=_quote("89", "90", "90"),
        client_order_id="paper-future-short-close-0001",
    )
    assert short.status == closed.status == "filled"
    short_position = db.scalar(select(PaperPosition).where(PaperPosition.run_id == new_run.id))
    assert short_position.quantity == 0 and short_position.realized_pnl > 0


def test_task_gates_respect_disabled_flags(db, monkeypatch):
    import importlib
    tasks_module = importlib.import_module("app.tasks.celery_app")
    # Worker settings are snapshotted at process start; emulate a worker whose
    # flags are off and confirm the tasks exit before touching the database.
    monkeypatch.setattr(tasks_module.settings, "quant_signal_enabled", False, raising=False)
    monkeypatch.setattr(tasks_module.settings, "quant_paper_enabled", False, raising=False)
    assert tasks_module.run_quant_signal_generation() == {"skipped": "quant_signal_disabled"}
    assert tasks_module.process_paper_signals() == {"account_id": None, "skipped": "quant_paper_disabled"}
    assert tasks_module.reconcile_paper_accounts() == {"skipped": "quant_paper_disabled"}


@pytest.fixture()
def client(db):
    user, _other, (instrument,) = _seed(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {create_token(user.id)}"})
        yield test_client, user, instrument
    app.dependency_overrides.pop(get_db, None)


def test_paper_api_contract(client):
    test_client, user, instrument = client
    assert test_client.get("/api/crypto/quant/paper").json() == {"account": None}
    created = test_client.post("/api/crypto/quant/paper/account", json={"initial_cash": "10000"})
    assert created.status_code == 201
    payload = created.json()["account"]
    assert payload["environment"] == "paper" and payload["base_currency"] == "USDT"
    assert payload["execution_mode"] == "paper" and payload["current_run"]["status"] == "active"
    assert payload["available_execution_modes"] == ["paper"]
    assert payload["positions"] == [] and payload["nav"] == "10000"
    config = test_client.get("/api/crypto/quant/paper/config")
    assert config.status_code == 200
    assert config.json()["credentials_required"] is False
    assert config.json()["authenticated_trading_available"] is False
    assert test_client.get("/api/crypto/quant/paper/runs").json()["total"] == 1
    assert test_client.get("/api/crypto/quant/paper/fills").json()["total"] == 0
    assert test_client.get("/api/crypto/quant/paper/ledger").json()["total"] == 1
    duplicate = test_client.post("/api/crypto/quant/paper/account", json={"initial_cash": "20000"})
    assert duplicate.status_code == 409
    paused = test_client.post("/api/crypto/quant/paper/pause", json={"reason": "hold"})
    assert paused.status_code == 200 and paused.json()["account"]["status"] == "paused"
    resumed = test_client.post("/api/crypto/quant/paper/resume")
    assert resumed.status_code == 200 and resumed.json()["account"]["status"] == "active"
    assert test_client.get("/api/crypto/quant/paper/orders").json()["total"] == 0
    reconciled = test_client.post("/api/crypto/quant/paper/reconcile")
    assert reconciled.status_code == 200
    assert reconciled.json()["reconciliation"]["status"] == "ok"
    assert test_client.get("/api/crypto/quant/paper/reconciliations").json()["total"] == 1
    denied_reset = test_client.post("/api/crypto/quant/paper/reset", json={"confirm": "no"})
    assert denied_reset.status_code == 422
    reset = test_client.post("/api/crypto/quant/paper/reset", json={"confirm": "RESET PAPER"})
    assert reset.status_code == 201 and reset.json()["account"]["current_run"]["id"] != payload["current_run"]["id"]
    bad = test_client.post("/api/crypto/quant/paper/account", json={"initial_cash": "1"})
    assert bad.status_code == 422
