"""Paper account state machine: signal → risk → virtual order → fill → ledger.

The fill plus funding ledger is the authority; positions and cash are derived
caches that reconciliation rebuilds exactly.  Cost math mirrors the shared
backtest models (spread half + slippage adverse fill, taker fee on notional,
engine funding sign convention) so paper realism does not diverge from
backtests. Nothing here touches PortfolioPosition, TradeTransaction or IBKR.
The only provider access is credential-free public Binance market data; this
module has no authenticated exchange client and can never submit an order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CryptoAsset,
    CryptoFundingRate,
    CryptoInstrument,
    PaperAccount,
    PaperBalance,
    PaperFill,
    PaperFundingEntry,
    PaperLedgerEvent,
    PaperOrder,
    PaperPosition,
    PaperReconciliation,
    PaperRun,
    QuantFeatureValue,
    QuantSignal,
    QuantStrategyDeployment,
    User,
)
from app.services.quant.paper_fill import PaperFillSimulator, PaperQuote
from app.services.quant.signals import _feature_set_id, _now, _utc

BPS = Decimal("10_000")
FUNDING_INTERVAL = timedelta(hours=8)
FILL_POLICY = "paper-fill-v1"


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def simulate_fill_price(
    raw_price: Decimal, *, tick_size: Decimal, spread_bps: Decimal, slippage_bps: Decimal, buy: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    """Mirror of the backtest engine's taker fill model (parity-tested)."""

    spread = spread_bps / BPS / Decimal("2")
    slip = slippage_bps / BPS
    adverse = spread + slip
    adjusted = raw_price * (Decimal("1") + adverse if buy else Decimal("1") - adverse)
    units = (adjusted / tick_size).to_integral_value(rounding=ROUND_UP if buy else ROUND_DOWN)
    price = units * tick_size
    return price, abs(raw_price * spread), abs(raw_price * slip)


def _quantize_quantity(quantity: Decimal, step_size: Decimal) -> Decimal:
    if step_size <= 0:
        return quantity
    units = (abs(quantity) / step_size).to_integral_value(rounding=ROUND_DOWN)
    return units * step_size


def _active_run(db: Session, account: PaperAccount) -> PaperRun:
    run = db.get(PaperRun, account.current_run_id) if account.current_run_id else None
    if run is None or run.account_id != account.id or run.status != "active":
        raise ValueError("paper account has no active run")
    return run


def _record_event(
    db: Session, account: PaperAccount, *, event_key: str, event_type: str,
    cash_delta: Decimal = Decimal("0"), quantity_delta: Decimal = Decimal("0"),
    amount: Decimal = Decimal("0"), instrument_id: int | None = None,
    order_id: int | None = None, fill_id: int | None = None,
    asset: str = "USDT", event_time: datetime | None = None, metadata: dict | None = None,
) -> PaperLedgerEvent:
    existing = db.scalar(select(PaperLedgerEvent).where(PaperLedgerEvent.event_key == event_key))
    if existing is not None:
        return existing
    event = PaperLedgerEvent(
        account_id=account.id, run_id=_active_run(db, account).id,
        event_key=event_key, event_type=event_type, instrument_id=instrument_id,
        order_id=order_id, fill_id=fill_id, asset=asset,
        cash_delta=cash_delta, quantity_delta=quantity_delta, amount=amount,
        metadata_json=metadata or {}, event_time=_utc(event_time or _now()),
    )
    db.add(event)
    db.flush()
    return event


def _balance(db: Session, account: PaperAccount, asset: str) -> PaperBalance:
    run = _active_run(db, account)
    symbol = asset.upper()
    row = db.scalar(select(PaperBalance).where(PaperBalance.run_id == run.id, PaperBalance.asset == symbol))
    if row is None:
        row = PaperBalance(account_id=account.id, run_id=run.id, asset=symbol)
        db.add(row)
        db.flush()
    return row


def _new_run(
    db: Session, account: PaperAccount, *, initial_equity: Decimal,
    strategy_metadata: dict | None = None,
) -> PaperRun:
    configuration = {
        "maker_fee_bps": str(account.maker_fee_bps), "taker_fee_bps": str(account.taker_fee_bps),
        "slippage_bps": str(account.slippage_bps), "leverage_cap": str(account.leverage_cap),
        "maintenance_margin_ratio": str(account.maintenance_margin_ratio),
        "liquidation_fee_bps": str(account.liquidation_fee_bps),
        "fill_policy": account.fill_policy,
    }
    run = PaperRun(
        account_id=account.id, user_id=account.user_id, initial_equity=initial_equity,
        peak_equity=initial_equity, configuration=configuration,
        strategy_metadata=strategy_metadata or {}, status="active",
    )
    db.add(run)
    db.flush()
    account.current_run_id = run.id
    account.initial_cash = initial_equity
    account.cash = initial_equity
    account.locked_cash = Decimal("0")
    db.add(PaperBalance(
        account_id=account.id, run_id=run.id, asset=account.base_currency,
        available=initial_equity, locked=Decimal("0"),
    ))
    _record_event(
        db, account, event_key=f"run-{run.id}-initial", event_type="INITIAL_DEPOSIT",
        cash_delta=initial_equity, amount=initial_equity, asset=account.base_currency,
    )
    return run


class _PositionState:
    """Pure position math shared by live fills and ledger rebuilds."""

    def __init__(self, quantity: Decimal = Decimal("0"), entry: Decimal = Decimal("0")) -> None:
        self.quantity = quantity
        self.entry = entry
        self.realized = Decimal("0")

    def apply(self, delta: Decimal, price: Decimal) -> Decimal:
        if delta == 0:
            return Decimal("0")
        old_qty = self.quantity
        realized = Decimal("0")
        if old_qty != 0 and old_qty * delta < 0:
            close_qty = min(abs(old_qty), abs(delta))
            realized = (price - self.entry) * close_qty if old_qty > 0 else (self.entry - price) * close_qty
        new_qty = old_qty + delta
        if old_qty == 0:
            self.entry = price
        elif old_qty * delta > 0:
            self.entry = (abs(old_qty) * self.entry + abs(delta) * price) / (abs(old_qty) + abs(delta))
        elif new_qty == 0:
            self.entry = Decimal("0")
        elif old_qty * new_qty < 0:
            self.entry = price
        self.quantity = new_qty
        self.realized += realized
        return realized


# --- account ---------------------------------------------------------------


def ensure_account(
    db: Session, *, user_id: int, initial_cash: Decimal | None = None,
    leverage_cap: Decimal | None = None, taker_fee_bps: Decimal | None = None,
    spread_bps: Decimal | None = None, slippage_bps: Decimal | None = None,
    maker_fee_bps: Decimal | None = None, maintenance_margin_ratio: Decimal | None = None,
    liquidation_fee_bps: Decimal | None = None,
) -> tuple[PaperAccount, str]:
    existing = db.scalar(select(PaperAccount).where(
        PaperAccount.user_id == user_id, PaperAccount.environment == "paper",
    ))
    if existing is not None:
        return existing, "existing"
    if db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise ValueError("unknown user")
    settings = get_settings()
    cash = _d(initial_cash if initial_cash is not None else settings.quant_paper_initial_cash)
    if not Decimal("100") <= cash <= Decimal("10_000_000"):
        raise ValueError("初始资金必须在 100 至 10,000,000 之间")
    fee = _d(taker_fee_bps if taker_fee_bps is not None else settings.quant_paper_taker_fee_bps)
    maker_fee = _d(maker_fee_bps if maker_fee_bps is not None else settings.quant_paper_maker_fee_bps)
    spread = _d(spread_bps if spread_bps is not None else "2")
    slip = _d(slippage_bps if slippage_bps is not None else settings.quant_paper_slippage_bps)
    leverage = _d(leverage_cap if leverage_cap is not None else settings.quant_paper_leverage_cap)
    maintenance = _d(maintenance_margin_ratio if maintenance_margin_ratio is not None else settings.quant_paper_maintenance_margin_ratio)
    liquidation_fee = _d(liquidation_fee_bps if liquidation_fee_bps is not None else settings.quant_paper_liquidation_fee_bps)
    if not Decimal("0") <= maker_fee <= Decimal("100") or not Decimal("0") <= fee <= Decimal("100") or not Decimal("0") <= spread <= Decimal("100") or not Decimal("0") <= slip <= Decimal("200"):
        raise ValueError("成本假设超出支持范围")
    if not Decimal("1") <= leverage <= Decimal("3"):
        raise ValueError("杠杆上限必须在 1 至 3 之间")
    if not Decimal("0") < maintenance <= Decimal("0.1") or not Decimal("0") <= liquidation_fee <= Decimal("500"):
        raise ValueError("保证金参数超出支持范围")
    account = PaperAccount(
        user_id=user_id, account_key="default", name="Paper Account",
        environment="paper", base_currency="USDT",
        initial_cash=cash, cash=cash, status="active",
        taker_fee_bps=fee, maker_fee_bps=maker_fee, spread_bps=spread, slippage_bps=slip,
        leverage_cap=leverage, maintenance_margin_ratio=maintenance,
        liquidation_fee_bps=liquidation_fee, fill_policy=FILL_POLICY,
    )
    db.add(account)
    db.flush()
    _new_run(db, account, initial_equity=cash)
    db.commit()
    db.refresh(account)
    return account, "created"


def owned_account(db: Session, user_id: int) -> PaperAccount | None:
    return db.scalar(select(PaperAccount).where(
        PaperAccount.user_id == user_id, PaperAccount.environment == "paper",
    ))


def set_account_status(db: Session, account: PaperAccount, *, status: str, reason: str | None = None) -> PaperAccount:
    if status not in ("active", "paused"):
        raise ValueError("unsupported status")
    account.status = status
    if status == "paused":
        account.paused_at = _now()
        account.pause_reason = reason or "user pause"
    else:
        account.pause_reason = None
    db.commit()
    db.refresh(account)
    return account


# --- prices ----------------------------------------------------------------


def latest_close(db: Session, instrument_id: int, *, interval: str = "1h") -> Decimal | None:
    feature_set_id = _feature_set_id(db)
    if feature_set_id is None:
        return None
    row = db.scalar(
        select(QuantFeatureValue)
        .where(
            QuantFeatureValue.feature_set_id == feature_set_id,
            QuantFeatureValue.instrument_id == instrument_id,
            QuantFeatureValue.interval == interval,
            QuantFeatureValue.available_at <= QuantFeatureValue.as_of,
        )
        .order_by(QuantFeatureValue.as_of.desc(), QuantFeatureValue.id.desc())
        .limit(1),
    )
    if row is None:
        return None
    close = (row.payload.get("bar") or {}).get("close")
    return _d(close) if close not in (None, "") else None


def mark_prices(db: Session, account: PaperAccount) -> dict[int, Decimal | None]:
    run_id = _active_run(db, account).id
    rows = db.scalars(select(PaperPosition).where(
        PaperPosition.account_id == account.id, PaperPosition.run_id == run_id,
    ))
    marks: dict[int, Decimal | None] = {}
    for row in rows:
        mark = _d(row.mark_price) if row.mark_price is not None else latest_close(db, row.instrument_id)
        if mark is None:
            last_fill = db.scalar(
                select(PaperFill)
                .where(PaperFill.run_id == run_id, PaperFill.instrument_id == row.instrument_id)
                .order_by(PaperFill.fill_time.desc(), PaperFill.id.desc())
                .limit(1),
            )
            mark = _d(last_fill.price) if last_fill is not None else None
        marks[row.instrument_id] = mark
    return marks


def account_nav(db: Session, account: PaperAccount) -> tuple[Decimal, list[str]]:
    """Perpetual-margin NAV, mirroring the engine: cash plus unrealized PnL.

    Opening a position does not spend cash (only fees reduce it), so marking
    must be entry-relative: ``(mark - avg_entry) * quantity``.  Marking with
    ``quantity * mark`` would double-count notional the account never paid and
    inflate every exposure-sized target after the first fill.
    """

    warnings: list[str] = []
    nav = _d(account.cash) + _d(account.locked_cash)
    run_id = _active_run(db, account).id
    for instrument_id, mark in mark_prices(db, account).items():
        position = db.scalar(select(PaperPosition).where(
            PaperPosition.run_id == run_id, PaperPosition.instrument_id == instrument_id,
        ))
        if position is None:
            continue
        quantity = _d(position.quantity)
        if quantity == 0:
            continue
        if mark is None:
            # No mark available: unrealized PnL is unknown, contribute zero
            # (equivalent to marking at entry) and surface the gap explicitly.
            warnings.append(f"instrument {instrument_id}: mark price unavailable; NAV marks unrealized PnL as zero")
        else:
            instrument = db.get(CryptoInstrument, instrument_id)
            if instrument is not None and instrument.market == "spot":
                nav += mark * quantity
                continue
            nav += (mark - _d(position.avg_entry_price)) * quantity
    return nav, warnings


def _update_run_metrics(db: Session, account: PaperAccount) -> None:
    run = _active_run(db, account)
    equity, _ = account_nav(db, account)
    peak = max(_d(run.peak_equity), equity)
    drawdown = (peak - equity) / peak if peak > 0 else Decimal("0")
    run.peak_equity = peak
    run.max_drawdown = max(_d(run.max_drawdown), drawdown)


# --- order / fill state machine --------------------------------------------


def process_pending_signals(
    db: Session, account: PaperAccount, *, now: datetime | None = None,
    quotes: dict[int, PaperQuote] | None = None,
) -> dict[str, Any]:
    moment = _utc(now or _now())
    summary: dict[str, int] = {}
    if account.status != "active":
        return {"account": "paused", "outcomes": summary}
    open_orders = process_open_orders(db, account, quotes=quotes)
    funding = apply_due_funding(db, account, now=moment)
    try:
        liquidation = check_liquidation(db, account, quotes=quotes, now=moment)
    except Exception as exc:
        db.rollback()
        liquidation = {
            "liquidated": 0,
            "assessment": "market_data_unavailable",
            "warnings": [str(exc)[:200]],
        }
    market_data_warnings: list[str] = []
    signals = list(db.scalars(
        select(QuantSignal)
        .join(QuantStrategyDeployment, QuantStrategyDeployment.id == QuantSignal.deployment_id)
        .where(
            QuantSignal.user_id == account.user_id,
            QuantSignal.environment == "paper",
            QuantSignal.status == "generated",
            QuantStrategyDeployment.status == "active",
        )
        .order_by(QuantSignal.decision_time, QuantSignal.id)
    ))
    for signal in signals:
        instrument = db.get(CryptoInstrument, signal.instrument_id)
        try:
            quote = (
                (quotes or {}).get(signal.instrument_id)
                or (public_quote(instrument) if instrument is not None else None)
            )
            if quote is None:
                raise ValueError("paper market quote unavailable")
            quote.validate(now=moment, max_age=timedelta(seconds=30))
        except Exception as exc:
            outcome = "market_data_unavailable"
            summary[outcome] = summary.get(outcome, 0) + 1
            market_data_warnings.append(f"signal {signal.id}: {str(exc)[:200]}")
            continue
        outcome = process_signal(db, account, signal, now=moment, quote=quote)
        summary[outcome] = summary.get(outcome, 0) + 1
    return {"account": "processed", "signals": len(signals), "outcomes": summary,
            "open_orders": open_orders, "liquidation": liquidation,
            "funding_applied": funding["applied"], "funding_warnings": funding["warnings"],
            "market_data_warnings": market_data_warnings}


def process_signal(
    db: Session, account: PaperAccount, signal: QuantSignal, *, now: datetime | None = None,
    quote: PaperQuote | None = None,
) -> str:
    moment = _utc(now or _now())
    client_order_id = f"paper-{account.id}-{signal.id}"
    existing_order = db.scalar(select(PaperOrder).where(PaperOrder.client_order_id == client_order_id))
    if existing_order is not None:
        return "duplicate_order"
    if signal.status != "generated":
        return f"signal_{signal.status}"
    if _utc(signal.expires_at) <= moment:
        db.execute(
            update(QuantSignal)
            .where(QuantSignal.id == signal.id, QuantSignal.status == "generated")
            .values(status="expired")
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return "signal_expired"

    instrument = db.get(CryptoInstrument, signal.instrument_id)
    if instrument is None:
        _reject(db, signal, "instrument missing")
        return "rejected"
    evidence_price = _d((signal.evidence or {}).get("bar", {}).get("close"))
    price = (quote.mark or (quote.bid + quote.ask) / Decimal("2")) if quote is not None else evidence_price
    if price <= 0:
        _reject(db, signal, "decision bar close unavailable")
        return "rejected"

    nav, _warnings = account_nav(db, account)
    target_qty = _quantize_quantity(
        _d(signal.target_exposure) * nav / price, _d(instrument.step_size or "0.001"),
    )
    position = db.scalar(select(PaperPosition).where(
        PaperPosition.run_id == _active_run(db, account).id, PaperPosition.instrument_id == instrument.id,
    ))
    current_qty = _d(position.quantity) if position is not None else Decimal("0")
    delta = target_qty - current_qty
    min_notional = _d(instrument.min_notional or "0")
    step = _d(instrument.step_size or "0.001")
    if abs(delta) < step or abs(delta) * price < min_notional:
        _consume(db, signal, moment, reason="no material delta from current paper position")
        return "no_delta"

    # Independent risk precheck: aggregate gross exposure stays under the cap.
    gross = abs(target_qty) * price
    for other_id, mark in mark_prices(db, account).items():
        if other_id == instrument.id or mark is None:
            continue
        other = db.scalar(select(PaperPosition).where(
            PaperPosition.run_id == _active_run(db, account).id, PaperPosition.instrument_id == other_id,
        ))
        if other is not None:
            gross += abs(_d(other.quantity)) * mark
    if gross > _d(account.leverage_cap) * nav:
        _reject(db, signal, f"leverage cap exceeded: gross {gross} > {account.leverage_cap} x NAV {nav}")
        return "rejected"

    order = PaperOrder(
        user_id=account.user_id, account_id=account.id, run_id=_active_run(db, account).id, signal_id=signal.id,
        client_order_id=client_order_id, instrument_id=instrument.id,
        side="buy" if delta > 0 else "sell", market_type="futures", order_type="market",
        intended_quantity=abs(delta), reference_price=price, status="pending",
        reason=signal.reason,
    )
    db.add(order)
    db.flush()
    if quote is not None:
        decision = PaperFillSimulator(slippage_bps=_d(account.slippage_bps)).decide(
            quote, side=order.side, order_type="market",
            tick_size=_d(instrument.tick_size or "0.0001"), now=moment,
        )
        order.reference_price = decision.reference_price
        apply_fill(
            db, account, order, abs(delta), fill_time=moment, price=decision.price,
            liquidity=decision.liquidity, event_key=f"{client_order_id}-1",
        )
    else:
        apply_fill(db, account, order, abs(delta), fill_time=moment, event_key=f"{client_order_id}-1")
    _consume(db, signal, moment, reason=f"filled paper order {order.client_order_id}")
    db.commit()
    return "filled"


def apply_fill(
    db: Session, account: PaperAccount, order: PaperOrder, quantity: Decimal, *,
    fill_time: datetime | None = None, price: Decimal | None = None,
    liquidity: str = "taker", reason: str | None = None, event_key: str | None = None,
) -> PaperFill:
    """Apply one (possibly partial) fill and update the derived caches."""

    if event_key:
        existing = db.scalar(select(PaperFill).where(PaperFill.event_key == event_key))
        if existing is not None:
            return existing
    if quantity <= 0 or quantity > _d(order.intended_quantity) - _d(order.filled_quantity):
        raise ValueError("fill quantity must be positive and within the remaining order quantity")
    moment = _utc(fill_time or _now())
    instrument = db.get(CryptoInstrument, order.instrument_id)
    buy = order.side == "buy"
    raw_price = _d(order.reference_price)
    if price is None:
        price, spread_unit, slip_unit = simulate_fill_price(
            raw_price, tick_size=_d(instrument.tick_size or "0.0001"),
            spread_bps=_d(account.spread_bps), slippage_bps=_d(account.slippage_bps), buy=buy,
        )
    else:
        price, spread_unit, slip_unit = _d(price), Decimal("0"), abs(_d(price) - raw_price)
    notional = quantity * price
    fee_bps = _d(account.maker_fee_bps) if liquidity == "maker" else _d(account.taker_fee_bps)
    fee = notional * fee_bps / BPS
    spread_cost = quantity * spread_unit
    slippage_cost = quantity * slip_unit
    signed = quantity if buy else -quantity
    fill_key = event_key or f"paper-fill-{order.id}-{_d(order.filled_quantity) + quantity}"
    existing = db.scalar(select(PaperFill).where(PaperFill.event_key == fill_key))
    if existing is not None:
        return existing

    position = db.scalar(select(PaperPosition).where(
        PaperPosition.run_id == order.run_id, PaperPosition.instrument_id == order.instrument_id,
    ))
    if position is None:
        position = PaperPosition(
            account_id=account.id, run_id=order.run_id, instrument_id=order.instrument_id,
            leverage=order.leverage,
        )
        db.add(position)
        db.flush()
    state = _PositionState(_d(position.quantity), _d(position.avg_entry_price))
    realized = state.apply(signed, price)
    position.quantity = state.quantity
    position.avg_entry_price = state.entry
    position.realized_pnl = _d(position.realized_pnl) + realized
    position.total_fees = _d(position.total_fees) + fee

    fill = PaperFill(
        order_id=order.id, account_id=account.id, run_id=order.run_id, user_id=account.user_id,
        instrument_id=order.instrument_id, side=order.side, quantity=quantity,
        event_key=fill_key, liquidity=liquidity,
        price=price, fee=fee, spread_cost=spread_cost, slippage_cost=slippage_cost,
        realized_pnl=realized, mark_price=price, reason=reason, fill_time=moment,
    )
    db.add(fill)
    db.flush()
    position.last_fill_id = fill.id
    if order.market_type == "spot":
        base = db.get(CryptoAsset, instrument.base_asset_id)
        quote = db.get(CryptoAsset, instrument.quote_asset_id)
        if base is None or quote is None or quote.symbol.upper() != account.base_currency:
            raise ValueError("paper Spot currently supports account base-currency quote pairs only")
        base_balance = _balance(db, account, base.symbol)
        if buy:
            account.cash = _d(account.cash) - notional - fee
            base_balance.available = _d(base_balance.available) + quantity
            principal_cash_delta = -notional
        else:
            account.cash = _d(account.cash) + notional - fee
            base_balance.available = _d(base_balance.available) - quantity
            principal_cash_delta = notional
        quote_balance = _balance(db, account, account.base_currency)
        quote_balance.available = account.cash
        position.mark_price = price
    else:
        account.cash = _d(account.cash) + realized - fee
        principal_cash_delta = Decimal("0")
        position.leverage = order.leverage
        position.margin_used = abs(state.quantity) * price / _d(order.leverage)
        position.mark_price = price
        position.unrealized_pnl = Decimal("0")
    previous_filled = _d(order.filled_quantity)
    previous_avg = _d(order.avg_fill_price) if order.avg_fill_price is not None else Decimal("0")
    order.filled_quantity = previous_filled + quantity
    order.avg_fill_price = (
        (previous_filled * previous_avg + quantity * price) / order.filled_quantity
        if order.filled_quantity > 0 else price
    )
    order.fee = _d(order.fee) + fee
    order.spread_cost = _d(order.spread_cost) + spread_cost
    order.slippage_cost = _d(order.slippage_cost) + slippage_cost
    order.status = "filled" if order.filled_quantity >= _d(order.intended_quantity) else "partially_filled"
    _record_event(
        db, account, event_key=f"{fill_key}-fill", event_type="ORDER_FILL",
        instrument_id=order.instrument_id, order_id=order.id, fill_id=fill.id,
        cash_delta=principal_cash_delta, quantity_delta=signed, amount=notional,
        event_time=moment, metadata={"market_type": order.market_type, "liquidity": liquidity},
    )
    if fee:
        _record_event(
            db, account, event_key=f"{fill_key}-fee", event_type="TRADING_FEE",
            instrument_id=order.instrument_id, order_id=order.id, fill_id=fill.id,
            cash_delta=-fee, amount=fee, event_time=moment,
        )
    if realized:
        _record_event(
            db, account, event_key=f"{fill_key}-pnl", event_type="REALIZED_PNL",
            instrument_id=order.instrument_id, order_id=order.id, fill_id=fill.id,
            cash_delta=realized if order.market_type == "futures" else Decimal("0"),
            amount=abs(realized), event_time=moment,
        )
    _update_run_metrics(db, account)
    return fill


def _consume(db: Session, signal: QuantSignal, moment: datetime, *, reason: str) -> None:
    db.execute(
        update(QuantSignal)
        .where(QuantSignal.id == signal.id, QuantSignal.status == "generated",
               QuantSignal.expires_at > moment)
        .values(status="consumed", consumed_at=moment, consumed_reason=reason)
        .execution_options(synchronize_session=False)
    )


def _reject(db: Session, signal: QuantSignal, reason: str) -> None:
    db.execute(
        update(QuantSignal)
        .where(QuantSignal.id == signal.id, QuantSignal.status == "generated")
        .values(status="rejected", rejected_reason=reason[:2000])
        .execution_options(synchronize_session=False)
    )
    db.commit()


# --- funding ---------------------------------------------------------------


def apply_due_funding(db: Session, account: PaperAccount, *, now: datetime | None = None) -> dict[str, Any]:
    """Apply persisted 8h funding events; gaps stay explicit warnings."""

    moment = _utc(now or _now())
    warnings: list[str] = []
    applied = 0
    started = _utc(account.last_funding_boundary or _active_run(db, account).started_at)
    interval_seconds = int(FUNDING_INTERVAL.total_seconds())
    start = datetime.fromtimestamp((int(started.timestamp()) // interval_seconds) * interval_seconds, UTC)
    end = datetime.fromtimestamp(
        (int(moment.timestamp()) // interval_seconds) * interval_seconds,
        UTC,
    )
    if end <= start:
        return {"applied": applied, "warnings": warnings}
    feature_set_id = _feature_set_id(db)
    run = _active_run(db, account)
    positions = {
        row.instrument_id: row for row in db.scalars(
            select(PaperPosition).where(PaperPosition.run_id == run.id)
        )
    }
    boundary = start + FUNDING_INTERVAL
    while boundary <= end:
        boundary_complete = True
        for instrument_id, position in positions.items():
            state = _PositionState()
            for fill in db.scalars(
                select(PaperFill).where(
                    PaperFill.run_id == run.id, PaperFill.instrument_id == instrument_id,
                    PaperFill.fill_time <= boundary,
                ).order_by(PaperFill.fill_time, PaperFill.id)
            ):
                state.apply(_d(fill.quantity) if fill.side == "buy" else -_d(fill.quantity), _d(fill.price))
            if state.quantity == 0:
                continue
            existing = db.scalar(select(PaperFundingEntry).where(
                PaperFundingEntry.run_id == run.id,
                PaperFundingEntry.instrument_id == instrument_id,
                PaperFundingEntry.boundary == boundary,
            ))
            if existing is not None:
                continue
            rate = Decimal("0")
            rate_found = False
            price: Decimal | None = None
            public_funding = db.scalar(
                select(CryptoFundingRate).where(
                    CryptoFundingRate.instrument_id == instrument_id,
                    CryptoFundingRate.funding_time == boundary,
                ).order_by(CryptoFundingRate.revision.desc(), CryptoFundingRate.id.desc()).limit(1)
            )
            if public_funding is not None:
                rate = _d(public_funding.funding_rate)
                rate_found = True
                price = _d(public_funding.mark_price) if public_funding.mark_price is not None else None
            if feature_set_id is not None:
                row = db.scalar(
                    select(QuantFeatureValue)
                    .where(
                        QuantFeatureValue.feature_set_id == feature_set_id,
                        QuantFeatureValue.instrument_id == instrument_id,
                        QuantFeatureValue.interval == "1h",
                        QuantFeatureValue.as_of == boundary,
                    )
                    .order_by(QuantFeatureValue.id.desc())
                    .limit(1),
                )
                if row is not None:
                    funding = row.payload.get("funding") or {}
                    funding_time = funding.get("funding_time")
                    observed = (
                        funding_time if isinstance(funding_time, datetime)
                        else datetime.fromisoformat(str(funding_time).replace("Z", "+00:00")) if funding_time else None
                    )
                    if public_funding is None and observed is not None and _utc(observed) == boundary:
                        rate = _d(funding.get("funding_rate") or "0")
                        rate_found = True
                    bar_open = (row.payload.get("bar") or {}).get("open")
                    if price is None:
                        price = _d(bar_open) if bar_open not in (None, "") else None
            if price is None or not rate_found:
                missing = "rate" if not rate_found else "price"
                warnings.append(f"funding {missing} gap at {boundary.isoformat()} for instrument {instrument_id}")
                boundary_complete = False
                continue
            cost = abs(state.quantity) * price * rate
            if state.quantity < 0:
                cost = -cost
            entry = PaperFundingEntry(
                account_id=account.id, run_id=run.id, user_id=account.user_id, instrument_id=instrument_id,
                boundary=boundary, rate=rate, quantity=state.quantity, price=price,
                cash_delta=-cost,
            )
            db.add(entry)
            db.flush()
            account.cash = _d(account.cash) - cost
            _balance(db, account, account.base_currency).available = max(Decimal("0"), _d(account.cash))
            _record_event(
                db, account, event_key=f"funding-{run.id}-{instrument_id}-{int(boundary.timestamp())}",
                event_type="FUNDING", instrument_id=instrument_id, cash_delta=-cost,
                amount=abs(cost), event_time=boundary,
                metadata={"rate": str(rate), "quantity": str(state.quantity), "price": str(price)},
            )
            applied += 1
        if not boundary_complete:
            break
        account.last_funding_boundary = boundary
        boundary += FUNDING_INTERVAL
    _update_run_metrics(db, account)
    db.commit()
    return {"applied": applied, "warnings": warnings}


# --- reconciliation --------------------------------------------------------


def rebuild_from_ledger(db: Session, account: PaperAccount) -> dict[str, Any]:
    """Derive positions and cash from the append-only ledger only."""

    run = _active_run(db, account)
    fills = list(db.scalars(
        select(PaperFill).where(PaperFill.run_id == run.id)
        .order_by(PaperFill.fill_time, PaperFill.id)
    ))
    funding = list(db.scalars(
        select(PaperFundingEntry).where(PaperFundingEntry.run_id == run.id)
        .order_by(PaperFundingEntry.boundary, PaperFundingEntry.id)
    ))
    states: dict[int, _PositionState] = {}
    fees_by_instrument: dict[int, Decimal] = {}
    cash = _d(run.initial_equity)
    balances: dict[str, Decimal] = {account.base_currency: cash}
    for fill in fills:
        state = states.setdefault(fill.instrument_id, _PositionState())
        realized = state.apply(_d(fill.quantity) if fill.side == "buy" else -_d(fill.quantity), _d(fill.price))
        order = db.get(PaperOrder, fill.order_id)
        instrument = db.get(CryptoInstrument, fill.instrument_id)
        if order is not None and order.market_type == "spot" and instrument is not None:
            base = db.get(CryptoAsset, instrument.base_asset_id)
            if base is None:
                raise ValueError("paper Spot fill has no base asset")
            notional = _d(fill.quantity) * _d(fill.price)
            if fill.side == "buy":
                cash -= notional + _d(fill.fee)
                balances[base.symbol] = balances.get(base.symbol, Decimal("0")) + _d(fill.quantity)
            else:
                cash += notional - _d(fill.fee)
                balances[base.symbol] = balances.get(base.symbol, Decimal("0")) - _d(fill.quantity)
        else:
            cash += realized - _d(fill.fee)
        fees_by_instrument[fill.instrument_id] = fees_by_instrument.get(fill.instrument_id, Decimal("0")) + _d(fill.fee)
    for entry in funding:
        cash += _d(entry.cash_delta)
    balances[account.base_currency] = cash
    return {
        "cash": cash,
        "balances": balances,
        "positions": {
            instrument_id: {"quantity": state.quantity, "avg_entry_price": state.entry,
                            "realized_pnl": state.realized, "total_fees": fees_by_instrument.get(instrument_id, Decimal("0"))}
            for instrument_id, state in states.items()
        },
        "fill_count": len(fills),
        "funding_count": len(funding),
    }


def reconcile_account(db: Session, account: PaperAccount, *, repair: bool = False) -> PaperReconciliation:
    """Compare cache with the ledger; repair only after an explicit request."""

    derived = rebuild_from_ledger(db, account)
    mismatches: list[dict[str, Any]] = []
    cached_rows = {
        row.instrument_id: row for row in db.scalars(
            select(PaperPosition).where(PaperPosition.run_id == _active_run(db, account).id)
        )
    }
    ledger_instruments = set(derived["positions"])
    for instrument_id in ledger_instruments | set(cached_rows):
        ledger = derived["positions"].get(instrument_id)
        cached = cached_rows.get(instrument_id)
        cached_values = None if cached is None else {
            "quantity": _d(cached.quantity), "avg_entry_price": _d(cached.avg_entry_price),
            "realized_pnl": _d(cached.realized_pnl), "total_fees": _d(cached.total_fees),
        }
        ledger_values = None if ledger is None else {
            "quantity": ledger["quantity"], "avg_entry_price": ledger["avg_entry_price"],
            "realized_pnl": ledger["realized_pnl"], "total_fees": ledger["total_fees"],
        }
        if ledger_values != cached_values:
            mismatches.append({
                "instrument_id": instrument_id,
                "cache": {key: str(value) for key, value in (cached_values or {}).items()},
                "ledger": {key: str(value) for key, value in (ledger_values or {}).items()},
            })
    cached_cash_total = _d(account.cash) + _d(account.locked_cash)
    if cached_cash_total != derived["cash"]:
        mismatches.append({
            "instrument_id": None,
            "cache": {"cash": str(account.cash), "locked_cash": str(account.locked_cash)},
            "ledger": {"cash": str(derived["cash"])},
        })
    ledger_cash = db.scalar(
        select(func.coalesce(func.sum(PaperLedgerEvent.cash_delta), 0)).where(
            PaperLedgerEvent.run_id == _active_run(db, account).id
        )
    ) or Decimal("0")
    if abs(_d(ledger_cash) - derived["cash"]) > Decimal("0.000000001"):
        mismatches.append({
            "instrument_id": None,
            "cache": {"event_ledger_cash": str(ledger_cash)},
            "ledger": {"fill_funding_cash": str(derived["cash"])},
        })

    status = "ok"
    if mismatches:
        status = "repaired" if repair else "mismatch"
        if repair:
            for cached in cached_rows.values():
                db.delete(cached)
            db.flush()
            run_id = _active_run(db, account).id
            for instrument_id, ledger in derived["positions"].items():
                db.add(PaperPosition(
                    account_id=account.id, run_id=run_id, instrument_id=instrument_id,
                    quantity=ledger["quantity"], avg_entry_price=ledger["avg_entry_price"],
                    realized_pnl=ledger["realized_pnl"], total_fees=ledger["total_fees"],
                ))
            account.cash = derived["cash"] - _d(account.locked_cash)
            for asset, available in derived["balances"].items():
                balance = _balance(db, account, asset)
                if asset == account.base_currency:
                    balance.available, balance.locked = account.cash, account.locked_cash
                else:
                    balance.available, balance.locked = available, Decimal("0")
    record = PaperReconciliation(
        account_id=account.id, run_id=_active_run(db, account).id,
        status=status, fill_count=derived["fill_count"],
        funding_count=derived["funding_count"], cash_from_ledger=derived["cash"],
        cash_cached=_d(account.cash) + _d(account.locked_cash), mismatches=mismatches, warnings=[],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def reconciliation_payload(row: PaperReconciliation) -> dict[str, Any]:
    return {
        "id": row.id, "account_id": row.account_id, "status": row.status,
        "fill_count": row.fill_count, "funding_count": row.funding_count,
        "cash_from_ledger": str(row.cash_from_ledger), "cash_cached": str(row.cash_cached),
        "mismatches": row.mismatches, "warnings": row.warnings, "created_at": row.created_at,
    }


def list_reconciliations(db: Session, account_id: int, *, limit: int = 20) -> dict[str, Any]:
    query = select(PaperReconciliation).where(PaperReconciliation.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(PaperReconciliation.created_at.desc()).limit(limit))
    return {"items": [reconciliation_payload(row) for row in rows], "total": total, "limit": limit}


# --- read payloads ---------------------------------------------------------


def account_payload(db: Session, account: PaperAccount) -> dict[str, Any]:
    nav, warnings = account_nav(db, account)
    run = _active_run(db, account)
    marks = mark_prices(db, account)
    rows = db.scalars(
        select(PaperPosition).where(PaperPosition.run_id == run.id)
        .order_by(PaperPosition.instrument_id)
    )
    positions = []
    gross = Decimal("0")
    used_margin = Decimal("0")
    unrealized_total = Decimal("0")
    realized_total = Decimal("0")
    fees_total = Decimal("0")
    for row in rows:
        instrument = db.get(CryptoInstrument, row.instrument_id)
        mark = marks.get(row.instrument_id)
        quantity = _d(row.quantity)
        exposure = quantity * mark if mark is not None else None
        if exposure is not None:
            gross += abs(exposure)
        unrealized = (
            (mark - _d(row.avg_entry_price)) * quantity
            if mark is not None and instrument is not None and instrument.market != "spot" else Decimal("0")
        )
        margin = abs(exposure) / _d(row.leverage) if exposure is not None and instrument is not None and instrument.market != "spot" else Decimal("0")
        used_margin += margin
        unrealized_total += unrealized
        realized_total += _d(row.realized_pnl)
        fees_total += _d(row.total_fees)
        liquidation_price = None
        if quantity and instrument is not None and instrument.market != "spot":
            leverage = _d(row.leverage)
            mmr = _d(account.maintenance_margin_ratio)
            liquidation_price = _d(row.avg_entry_price) * (
                Decimal("1") - Decimal("1") / leverage + mmr
                if quantity > 0 else Decimal("1") + Decimal("1") / leverage - mmr
            )
        positions.append({
            "instrument_id": row.instrument_id,
            "instrument_symbol": instrument.provider_symbol if instrument else None,
            "market_type": "spot" if instrument and instrument.market == "spot" else "futures",
            "quantity": str(quantity), "avg_entry_price": str(_d(row.avg_entry_price)),
            "mark_price": str(mark) if mark is not None else None,
            "exposure": str(exposure) if exposure is not None else None,
            "unrealized_pnl": str(unrealized) if mark is not None else None,
            "realized_pnl": str(_d(row.realized_pnl)), "total_fees": str(_d(row.total_fees)),
            "leverage": str(_d(row.leverage)), "margin_used": str(margin),
            "liquidation_price": str(liquidation_price) if liquidation_price is not None else None,
            "locked_quantity": str(_d(row.locked_quantity)),
            "updated_at": row.updated_at,
        })
    last_reconciliation = db.scalar(
        select(PaperReconciliation).where(PaperReconciliation.run_id == run.id)
        .order_by(PaperReconciliation.created_at.desc()).limit(1)
    )
    balances = list(db.scalars(select(PaperBalance).where(PaperBalance.run_id == run.id).order_by(PaperBalance.asset)))
    fills = list(db.scalars(select(PaperFill).where(PaperFill.run_id == run.id)))
    funding_pnl = db.scalar(
        select(func.coalesce(func.sum(PaperFundingEntry.cash_delta), 0)).where(PaperFundingEntry.run_id == run.id)
    ) or Decimal("0")
    wins = sum(1 for fill in fills if _d(fill.realized_pnl) > 0)
    losses = sum(1 for fill in fills if _d(fill.realized_pnl) < 0)
    closed = wins + losses
    performance = {
        "initial_equity": str(_d(run.initial_equity)), "current_equity": str(nav),
        "total_return": str((nav / _d(run.initial_equity) - 1) if _d(run.initial_equity) else Decimal("0")),
        "realized_pnl": str(realized_total), "unrealized_pnl": str(unrealized_total),
        "fees_paid": str(fees_total), "funding_pnl": str(_d(funding_pnl)),
        "trade_count": len(fills), "winning_trades": wins, "losing_trades": losses,
        "win_rate": str(Decimal(wins) / Decimal(closed)) if closed else None,
        "max_drawdown": str(_d(run.max_drawdown)),
    }
    return {
        "id": account.id, "environment": account.environment, "base_currency": account.base_currency,
        "execution_mode": "paper", "available_execution_modes": ["paper"],
        "status": account.status, "paused_at": account.paused_at, "pause_reason": account.pause_reason,
        "initial_cash": str(_d(account.initial_cash)), "cash": str(_d(account.cash)),
        "locked_cash": str(_d(account.locked_cash)), "available_balance": str(_d(account.cash)),
        "wallet_balance": str(_d(account.cash) + _d(account.locked_cash)),
        "equity": str(nav), "nav": str(nav), "gross_exposure": str(gross),
        "used_margin": str(used_margin), "available_margin": str(max(Decimal("0"), nav - used_margin)),
        "exposure_ratio": str(gross / nav) if nav > 0 else None,
        "leverage_cap": str(_d(account.leverage_cap)), "fill_policy": account.fill_policy,
        "costs": {
            "taker_fee_bps": str(_d(account.taker_fee_bps)),
            "maker_fee_bps": str(_d(account.maker_fee_bps)),
            "spread_bps": str(_d(account.spread_bps)),
            "slippage_bps": str(_d(account.slippage_bps)),
            "maintenance_margin_ratio": str(_d(account.maintenance_margin_ratio)),
            "liquidation_fee_bps": str(_d(account.liquidation_fee_bps)),
        },
        "balances": [{"asset": row.asset, "available": str(_d(row.available)), "locked": str(_d(row.locked))} for row in balances],
        "positions": positions, "warnings": warnings, "performance": performance,
        "current_run": run_payload(db, run),
        "last_funding_boundary": account.last_funding_boundary,
        "last_reconciliation": reconciliation_payload(last_reconciliation) if last_reconciliation else None,
        "server_time": _now().isoformat(),
    }


def order_payload(db: Session, order: PaperOrder) -> dict[str, Any]:
    instrument = db.get(CryptoInstrument, order.instrument_id)
    fills = list(db.scalars(
        select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_time, PaperFill.id)
    ))
    return {
        "id": order.id, "account_id": order.account_id, "signal_id": order.signal_id,
        "client_order_id": order.client_order_id,
        "instrument_id": order.instrument_id,
        "instrument_symbol": instrument.provider_symbol if instrument else None,
        "run_id": order.run_id, "side": order.side, "order_type": order.order_type,
        "market_type": order.market_type, "position_side": order.position_side,
        "limit_price": str(_d(order.limit_price)) if order.limit_price is not None else None,
        "leverage": str(_d(order.leverage)),
        "intended_quantity": str(_d(order.intended_quantity)),
        "filled_quantity": str(_d(order.filled_quantity)),
        "reference_price": str(_d(order.reference_price)),
        "avg_fill_price": str(_d(order.avg_fill_price)) if order.avg_fill_price is not None else None,
        "fee": str(_d(order.fee)), "spread_cost": str(_d(order.spread_cost)),
        "slippage_cost": str(_d(order.slippage_cost)), "status": order.status,
        "reason": order.reason, "reject_reason": order.reject_reason,
        "created_at": order.created_at,
        "fills": [
            {
                "id": fill.id, "side": fill.side, "quantity": str(_d(fill.quantity)),
                "price": str(_d(fill.price)), "fee": str(_d(fill.fee)),
                "liquidity": fill.liquidity, "reason": fill.reason,
                "spread_cost": str(_d(fill.spread_cost)), "slippage_cost": str(_d(fill.slippage_cost)),
                "realized_pnl": str(_d(fill.realized_pnl)), "fill_time": fill.fill_time,
            }
            for fill in fills
        ],
    }


def list_orders(db: Session, account_id: int, *, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    account = db.get(PaperAccount, account_id)
    query = select(PaperOrder).where(
        PaperOrder.account_id == account_id, PaperOrder.run_id == _active_run(db, account).id,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(PaperOrder.created_at.desc(), PaperOrder.id.desc()).limit(limit).offset(offset)
    )
    return {"items": [order_payload(db, row) for row in rows], "total": total, "limit": limit, "offset": offset}


# --- manual broker / market cycle -----------------------------------------


def public_quote(instrument: CryptoInstrument) -> PaperQuote:
    """Read production PUBLIC Binance market data through the existing client."""

    from app.services.crypto.providers.binance import BinancePublicClient

    settings = get_settings()
    client = BinancePublicClient(
        spot_base_url=settings.crypto_binance_spot_base_url,
        usdm_base_url=settings.crypto_binance_usdm_base_url,
        timeout_seconds=settings.crypto_binance_timeout_seconds,
        max_retries=settings.crypto_binance_max_retries,
    )
    market = "spot" if instrument.market == "spot" else "usdm"
    ticker = client.book_ticker(market, instrument.provider_symbol)
    observed = datetime.fromisoformat(ticker.received_at.replace("Z", "+00:00"))
    mark = None
    if market == "usdm":
        mark = client.premium_index(instrument.provider_symbol).mark_price
    return PaperQuote(ticker.bid_price, ticker.ask_price, observed, mark)


def _release_lock(db: Session, account: PaperAccount, order: PaperOrder) -> None:
    if order.order_type != "limit" or order.status not in {"pending", "partially_filled"}:
        return
    instrument = db.get(CryptoInstrument, order.instrument_id)
    remaining = _d(order.intended_quantity) - _d(order.filled_quantity)
    if remaining <= 0 or instrument is None:
        return
    if order.market_type == "spot" and order.side == "sell":
        base = db.get(CryptoAsset, instrument.base_asset_id)
        if base is not None:
            balance = _balance(db, account, base.symbol)
            released = min(_d(balance.locked), remaining)
            balance.locked = _d(balance.locked) - released
            balance.available = _d(balance.available) + released
        return
    reserved = remaining * _d(order.limit_price) * (
        Decimal("1") + _d(account.maker_fee_bps) / BPS
    )
    if order.market_type == "futures":
        reserved = remaining * _d(order.limit_price) / _d(order.leverage)
    released = min(_d(account.locked_cash), reserved)
    account.locked_cash = _d(account.locked_cash) - released
    account.cash = _d(account.cash) + released
    quote = _balance(db, account, account.base_currency)
    quote.available, quote.locked = account.cash, account.locked_cash


def _reserve_limit(db: Session, account: PaperAccount, order: PaperOrder) -> None:
    instrument = db.get(CryptoInstrument, order.instrument_id)
    if instrument is None or order.limit_price is None:
        raise ValueError("limit order is incomplete")
    if order.market_type == "spot" and order.side == "sell":
        base = db.get(CryptoAsset, instrument.base_asset_id)
        if base is None:
            raise ValueError("Spot base asset unavailable")
        balance = _balance(db, account, base.symbol)
        if _d(balance.available) < _d(order.intended_quantity):
            raise ValueError("insufficient Spot base balance")
        balance.available = _d(balance.available) - _d(order.intended_quantity)
        balance.locked = _d(balance.locked) + _d(order.intended_quantity)
        return
    reserved = _d(order.intended_quantity) * _d(order.limit_price) * (
        Decimal("1") + _d(account.maker_fee_bps) / BPS
    )
    if order.market_type == "futures":
        reserved = _d(order.intended_quantity) * _d(order.limit_price) / _d(order.leverage)
    if _d(account.cash) < reserved:
        raise ValueError("insufficient paper available balance")
    account.cash = _d(account.cash) - reserved
    account.locked_cash = _d(account.locked_cash) + reserved
    quote = _balance(db, account, account.base_currency)
    quote.available, quote.locked = account.cash, account.locked_cash


def _validate_order_funds(
    db: Session, account: PaperAccount, instrument: CryptoInstrument, *,
    market_type: str, side: str, quantity: Decimal, price: Decimal, leverage: Decimal,
) -> None:
    notional = quantity * price
    if market_type == "spot":
        base = db.get(CryptoAsset, instrument.base_asset_id)
        quote = db.get(CryptoAsset, instrument.quote_asset_id)
        if base is None or quote is None or quote.symbol.upper() != account.base_currency:
            raise ValueError("paper Spot currently supports USDT-quoted instruments only")
        if side == "buy" and _d(account.cash) < notional * (Decimal("1") + _d(account.taker_fee_bps) / BPS):
            raise ValueError("insufficient Spot quote balance")
        if side == "sell" and _d(_balance(db, account, base.symbol).available) < quantity:
            raise ValueError("insufficient Spot base balance")
        return
    nav, _ = account_nav(db, account)
    positions = list(db.scalars(
        select(PaperPosition).where(PaperPosition.run_id == _active_run(db, account).id)
    ))
    used = sum((_d(row.margin_used) for row in positions), Decimal("0"))
    current = next((row for row in positions if row.instrument_id == instrument.id), None)
    current_qty = _d(current.quantity) if current is not None else Decimal("0")
    signed = quantity if side == "buy" else -quantity
    current_margin = abs(current_qty * price) / leverage
    next_margin = abs((current_qty + signed) * price) / leverage
    extra_margin = max(Decimal("0"), next_margin - current_margin)
    if extra_margin > max(Decimal("0"), nav - used):
        raise ValueError("insufficient Futures available margin")


def submit_manual_order(
    db: Session, account: PaperAccount, *, instrument_id: int, side: str,
    order_type: str, quantity: Decimal | str, limit_price: Decimal | str | None = None,
    leverage: Decimal | str = Decimal("1"), position_side: str = "BOTH",
    client_order_id: str | None = None, quote: PaperQuote | None = None,
) -> PaperOrder:
    if account.status != "active":
        raise ValueError("paper account is paused")
    instrument = db.get(CryptoInstrument, instrument_id)
    if instrument is None or instrument.venue != "binance" or instrument.status != "trading":
        raise ValueError("unsupported paper instrument")
    market_type = "spot" if instrument.market == "spot" else "futures" if instrument.market == "usdm_futures" else ""
    if not market_type:
        raise ValueError("paper supports Binance Spot and USD-M Futures only")
    side, order_type, position_side = side.lower(), order_type.lower(), position_side.upper()
    if side not in {"buy", "sell"} or order_type not in {"market", "limit"}:
        raise ValueError("unsupported paper order")
    if position_side not in {"BOTH", "LONG", "SHORT"}:
        raise ValueError("unsupported Futures position side")
    if market_type == "spot" and position_side != "BOTH":
        raise ValueError("Spot orders do not have LONG/SHORT position sides")
    qty = _quantize_quantity(_d(quantity), _d(instrument.step_size or "0.00000001"))
    lev = _d(leverage)
    if qty <= 0 or lev < 1 or lev > _d(account.leverage_cap):
        raise ValueError("invalid paper quantity or leverage")
    limit = _d(limit_price) if limit_price is not None else None
    if order_type == "limit" and (limit is None or limit <= 0):
        raise ValueError("positive limit price is required")
    stable_id = client_order_id or f"paper-manual-{account.id}-{uuid.uuid4().hex[:20]}"
    existing = db.scalar(select(PaperOrder).where(PaperOrder.client_order_id == stable_id))
    if existing is not None:
        return existing
    market_quote = quote or public_quote(instrument)
    simulator = PaperFillSimulator(slippage_bps=_d(account.slippage_bps))
    decision = simulator.decide(
        market_quote, side=side, order_type=order_type,
        limit_price=limit, tick_size=_d(instrument.tick_size or "0.00000001"),
    )
    reference = market_quote.ask if side == "buy" else market_quote.bid
    check_price = decision.price if decision is not None else _d(limit)
    if qty * check_price < _d(instrument.min_notional or "0"):
        raise ValueError("paper order is below minimum notional")
    _validate_order_funds(
        db, account, instrument, market_type=market_type, side=side,
        quantity=qty, price=check_price, leverage=lev,
    )
    order = PaperOrder(
        user_id=account.user_id, account_id=account.id, run_id=_active_run(db, account).id,
        signal_id=None, client_order_id=stable_id, instrument_id=instrument.id,
        side=side, market_type=market_type, position_side=position_side,
        order_type=order_type, limit_price=limit, leverage=lev,
        intended_quantity=qty, reference_price=reference, status="pending", reason="manual paper order",
    )
    db.add(order)
    db.flush()
    if decision is None:
        _reserve_limit(db, account, order)
    else:
        apply_fill(
            db, account, order, qty, price=decision.price, liquidity=decision.liquidity,
            event_key=f"{stable_id}-1",
        )
    db.commit()
    db.refresh(order)
    return order


def process_open_orders(
    db: Session, account: PaperAccount, *, quotes: dict[int, PaperQuote] | None = None,
) -> dict[str, Any]:
    rows = list(db.scalars(select(PaperOrder).where(
        PaperOrder.run_id == _active_run(db, account).id,
        PaperOrder.status.in_(["pending", "partially_filled"]),
        PaperOrder.order_type == "limit",
    ).order_by(PaperOrder.created_at, PaperOrder.id)))
    filled = 0
    warnings: list[str] = []
    for order in rows:
        instrument = db.get(CryptoInstrument, order.instrument_id)
        try:
            quote = (quotes or {}).get(order.instrument_id) or public_quote(instrument)
            decision = PaperFillSimulator(slippage_bps=_d(account.slippage_bps)).decide(
                quote, side=order.side, order_type="limit", limit_price=_d(order.limit_price),
                tick_size=_d(instrument.tick_size or "0.00000001"),
            )
            if decision is None:
                continue
            remaining = _d(order.intended_quantity) - _d(order.filled_quantity)
            _release_lock(db, account, order)
            apply_fill(
                db, account, order, remaining, price=decision.price, liquidity="maker",
                event_key=f"{order.client_order_id}-{_d(order.filled_quantity) + remaining}",
            )
            filled += 1
        except Exception as exc:
            warnings.append(f"order {order.id}: {str(exc)[:200]}")
    db.commit()
    return {"checked": len(rows), "filled": filled, "warnings": warnings}


def cancel_order(db: Session, account: PaperAccount, order_id: int) -> PaperOrder:
    order = db.scalar(select(PaperOrder).where(
        PaperOrder.id == order_id, PaperOrder.account_id == account.id,
        PaperOrder.run_id == _active_run(db, account).id,
    ))
    if order is None:
        raise ValueError("paper order not found")
    if order.status not in {"pending", "partially_filled"}:
        raise ValueError("paper order is not cancellable")
    _release_lock(db, account, order)
    order.status = "cancelled"
    order.cancelled_at = _now()
    db.commit()
    db.refresh(order)
    return order


def check_liquidation(
    db: Session, account: PaperAccount, *, quotes: dict[int, PaperQuote] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = _utc(now or _now())
    run = _active_run(db, account)
    positions = list(db.scalars(select(PaperPosition).where(PaperPosition.run_id == run.id)))
    futures = []
    maintenance = Decimal("0")
    unrealized = Decimal("0")
    for position in positions:
        instrument = db.get(CryptoInstrument, position.instrument_id)
        if instrument is None or instrument.market == "spot" or _d(position.quantity) == 0:
            continue
        quote = (quotes or {}).get(position.instrument_id) or public_quote(instrument)
        quote.validate(now=moment, max_age=timedelta(seconds=30))
        mark = quote.mark or (quote.bid + quote.ask) / Decimal("2")
        position.mark_price = mark
        position.unrealized_pnl = (mark - _d(position.avg_entry_price)) * _d(position.quantity)
        position.margin_used = abs(_d(position.quantity) * mark) / _d(position.leverage)
        maintenance += abs(_d(position.quantity) * mark) * _d(account.maintenance_margin_ratio)
        unrealized += _d(position.unrealized_pnl)
        futures.append((position, instrument, mark))
    equity = _d(account.cash) + _d(account.locked_cash) + unrealized
    if not futures or equity > maintenance:
        db.commit()
        return {"liquidated": 0, "equity": str(equity), "maintenance_margin": str(maintenance)}
    count = 0
    for position, instrument, mark in futures:
        side = "sell" if _d(position.quantity) > 0 else "buy"
        qty = abs(_d(position.quantity))
        order = PaperOrder(
            user_id=account.user_id, account_id=account.id, run_id=run.id,
            client_order_id=f"liquidation-{run.id}-{instrument.id}-{uuid.uuid4().hex[:12]}",
            instrument_id=instrument.id, side=side, market_type="futures", position_side="BOTH",
            order_type="market", leverage=position.leverage, intended_quantity=qty,
            reference_price=mark, status="pending", reason="simulated liquidation",
        )
        db.add(order)
        db.flush()
        fill = apply_fill(
            db, account, order, qty, price=mark, liquidity="taker", reason="liquidation",
            event_key=f"{order.client_order_id}-1",
        )
        liquidation_fee = qty * mark * _d(account.liquidation_fee_bps) / BPS
        account.cash = _d(account.cash) - liquidation_fee
        fill.fee = _d(fill.fee) + liquidation_fee
        order.fee = _d(order.fee) + liquidation_fee
        closed_position = db.scalar(select(PaperPosition).where(
            PaperPosition.run_id == run.id, PaperPosition.instrument_id == instrument.id,
        ))
        if closed_position is not None:
            closed_position.total_fees = _d(closed_position.total_fees) + liquidation_fee
        _record_event(
            db, account, event_key=f"{order.client_order_id}-liquidation", event_type="LIQUIDATION",
            instrument_id=instrument.id, order_id=order.id, fill_id=fill.id,
            cash_delta=-liquidation_fee, amount=liquidation_fee,
            metadata={"maintenance_margin_ratio": str(account.maintenance_margin_ratio)},
        )
        count += 1
    _balance(db, account, account.base_currency).available = max(Decimal("0"), _d(account.cash))
    _update_run_metrics(db, account)
    db.commit()
    return {"liquidated": count, "equity": str(equity), "maintenance_margin": str(maintenance)}


def reset_account(
    db: Session, account: PaperAccount, *, initial_cash: Decimal | str | None = None,
    strategy_metadata: dict | None = None,
) -> PaperRun:
    old = _active_run(db, account)
    for order in db.scalars(select(PaperOrder).where(
        PaperOrder.run_id == old.id, PaperOrder.status.in_(["pending", "partially_filled"]),
    )):
        _release_lock(db, account, order)
        order.status, order.cancelled_at = "cancelled", _now()
    ending, _ = account_nav(db, account)
    old.status, old.ending_equity, old.ended_at = "completed", ending, _now()
    capital = _d(initial_cash if initial_cash is not None else account.initial_cash)
    if not Decimal("100") <= capital <= Decimal("10_000_000"):
        raise ValueError("初始资金必须在 100 至 10,000,000 之间")
    run = _new_run(db, account, initial_equity=capital, strategy_metadata=strategy_metadata)
    _record_event(
        db, account, event_key=f"run-{run.id}-reset", event_type="MANUAL_RESET",
        amount=capital, metadata={"previous_run_id": old.id},
    )
    account.last_funding_boundary = None
    db.commit()
    db.refresh(run)
    return run


def run_payload(db: Session, run: PaperRun) -> dict[str, Any]:
    fill_count = db.scalar(select(func.count(PaperFill.id)).where(PaperFill.run_id == run.id)) or 0
    return {
        "id": run.id, "status": run.status, "initial_equity": str(_d(run.initial_equity)),
        "ending_equity": str(_d(run.ending_equity)) if run.ending_equity is not None else None,
        "peak_equity": str(_d(run.peak_equity)), "max_drawdown": str(_d(run.max_drawdown)),
        "configuration": run.configuration, "strategy_metadata": run.strategy_metadata,
        "started_at": run.started_at, "ended_at": run.ended_at, "trade_count": fill_count,
    }


def list_runs(db: Session, account: PaperAccount, *, limit: int = 50) -> dict[str, Any]:
    rows = list(db.scalars(select(PaperRun).where(PaperRun.account_id == account.id).order_by(PaperRun.id.desc()).limit(limit)))
    return {"items": [run_payload(db, row) for row in rows], "total": len(rows)}


def list_fills(db: Session, account: PaperAccount, *, limit: int = 100) -> dict[str, Any]:
    rows = list(db.scalars(select(PaperFill).where(
        PaperFill.run_id == _active_run(db, account).id,
    ).order_by(PaperFill.fill_time.desc(), PaperFill.id.desc()).limit(limit)))
    return {"items": [
        {"id": row.id, "order_id": row.order_id, "instrument_id": row.instrument_id,
         "side": row.side, "quantity": str(_d(row.quantity)), "price": str(_d(row.price)),
         "fee": str(_d(row.fee)), "liquidity": row.liquidity,
         "realized_pnl": str(_d(row.realized_pnl)), "reason": row.reason, "fill_time": row.fill_time}
        for row in rows
    ], "total": len(rows)}


def list_ledger(db: Session, account: PaperAccount, *, limit: int = 100) -> dict[str, Any]:
    rows = list(db.scalars(select(PaperLedgerEvent).where(
        PaperLedgerEvent.run_id == _active_run(db, account).id,
    ).order_by(PaperLedgerEvent.event_time.desc(), PaperLedgerEvent.id.desc()).limit(limit)))
    return {"items": [
        {"id": row.id, "event_key": row.event_key, "event_type": row.event_type,
         "instrument_id": row.instrument_id, "order_id": row.order_id, "fill_id": row.fill_id,
         "asset": row.asset, "cash_delta": str(_d(row.cash_delta)),
         "quantity_delta": str(_d(row.quantity_delta)), "amount": str(_d(row.amount)),
         "metadata": row.metadata_json, "event_time": row.event_time}
        for row in rows
    ], "total": len(rows)}
