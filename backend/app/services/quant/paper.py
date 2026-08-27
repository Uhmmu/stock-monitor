"""Paper account state machine: signal → risk → virtual order → fill → ledger.

The fill plus funding ledger is the authority; positions and cash are derived
caches that reconciliation rebuilds exactly.  Cost math mirrors the shared
backtest models (spread half + slippage adverse fill, taker fee on notional,
engine funding sign convention) so paper realism does not diverge from
backtests.  Nothing here touches PortfolioPosition, TradeTransaction or IBKR,
and no provider or exchange client is imported.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CryptoInstrument,
    PaperAccount,
    PaperFill,
    PaperFundingEntry,
    PaperOrder,
    PaperPosition,
    PaperReconciliation,
    QuantFeatureValue,
    QuantSignal,
    QuantStrategyDeployment,
    User,
)
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
    fee = _d(taker_fee_bps if taker_fee_bps is not None else "5")
    spread = _d(spread_bps if spread_bps is not None else "2")
    slip = _d(slippage_bps if slippage_bps is not None else "2")
    leverage = _d(leverage_cap if leverage_cap is not None else settings.quant_paper_leverage_cap)
    if not Decimal("0") <= fee <= Decimal("100") or not Decimal("0") <= spread <= Decimal("100") or not Decimal("0") <= slip <= Decimal("200"):
        raise ValueError("成本假设超出支持范围")
    if not Decimal("1") <= leverage <= Decimal("3"):
        raise ValueError("杠杆上限必须在 1 至 3 之间")
    account = PaperAccount(
        user_id=user_id, environment="paper", base_currency="USDT",
        initial_cash=cash, cash=cash, status="active",
        taker_fee_bps=fee, spread_bps=spread, slippage_bps=slip,
        leverage_cap=leverage, fill_policy=FILL_POLICY,
    )
    db.add(account)
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
    rows = db.scalars(select(PaperPosition).where(PaperPosition.account_id == account.id))
    marks: dict[int, Decimal | None] = {}
    for row in rows:
        mark = latest_close(db, row.instrument_id)
        if mark is None:
            last_fill = db.scalar(
                select(PaperFill)
                .where(PaperFill.account_id == account.id, PaperFill.instrument_id == row.instrument_id)
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
    nav = _d(account.cash)
    for instrument_id, mark in mark_prices(db, account).items():
        position = db.scalar(select(PaperPosition).where(
            PaperPosition.account_id == account.id, PaperPosition.instrument_id == instrument_id,
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
            nav += (mark - _d(position.avg_entry_price)) * quantity
    return nav, warnings


# --- order / fill state machine --------------------------------------------


def process_pending_signals(db: Session, account: PaperAccount, *, now: datetime | None = None) -> dict[str, Any]:
    moment = _utc(now or _now())
    summary: dict[str, int] = {}
    if account.status != "active":
        return {"account": "paused", "outcomes": summary}
    funding = apply_due_funding(db, account, now=moment)
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
        outcome = process_signal(db, account, signal, now=moment)
        summary[outcome] = summary.get(outcome, 0) + 1
    return {"account": "processed", "signals": len(signals), "outcomes": summary,
            "funding_applied": funding["applied"], "funding_warnings": funding["warnings"]}


def process_signal(
    db: Session, account: PaperAccount, signal: QuantSignal, *, now: datetime | None = None,
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
    price = _d((signal.evidence or {}).get("bar", {}).get("close"))
    if price <= 0:
        _reject(db, signal, "decision bar close unavailable")
        return "rejected"

    nav, _warnings = account_nav(db, account)
    target_qty = _quantize_quantity(
        _d(signal.target_exposure) * nav / price, _d(instrument.step_size or "0.001"),
    )
    position = db.scalar(select(PaperPosition).where(
        PaperPosition.account_id == account.id, PaperPosition.instrument_id == instrument.id,
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
            PaperPosition.account_id == account.id, PaperPosition.instrument_id == other_id,
        ))
        if other is not None:
            gross += abs(_d(other.quantity)) * mark
    if gross > _d(account.leverage_cap) * nav:
        _reject(db, signal, f"leverage cap exceeded: gross {gross} > {account.leverage_cap} x NAV {nav}")
        return "rejected"

    order = PaperOrder(
        user_id=account.user_id, account_id=account.id, signal_id=signal.id,
        client_order_id=client_order_id, instrument_id=instrument.id,
        side="buy" if delta > 0 else "sell", order_type="market",
        intended_quantity=abs(delta), reference_price=price, status="pending",
        reason=signal.reason,
    )
    db.add(order)
    db.flush()
    apply_fill(db, account, order, abs(delta), fill_time=moment)
    _consume(db, signal, moment, reason=f"filled paper order {order.client_order_id}")
    db.commit()
    return "filled"


def apply_fill(
    db: Session, account: PaperAccount, order: PaperOrder, quantity: Decimal, *,
    fill_time: datetime | None = None,
) -> PaperFill:
    """Apply one (possibly partial) fill and update the derived caches."""

    if quantity <= 0 or quantity > _d(order.intended_quantity) - _d(order.filled_quantity):
        raise ValueError("fill quantity must be positive and within the remaining order quantity")
    moment = _utc(fill_time or _now())
    instrument = db.get(CryptoInstrument, order.instrument_id)
    buy = order.side == "buy"
    raw_price = _d(order.reference_price)
    price, spread_unit, slip_unit = simulate_fill_price(
        raw_price, tick_size=_d(instrument.tick_size or "0.0001"),
        spread_bps=_d(account.spread_bps), slippage_bps=_d(account.slippage_bps), buy=buy,
    )
    notional = quantity * price
    fee = notional * _d(account.taker_fee_bps) / BPS
    spread_cost = quantity * spread_unit
    slippage_cost = quantity * slip_unit
    signed = quantity if buy else -quantity

    position = db.scalar(select(PaperPosition).where(
        PaperPosition.account_id == account.id, PaperPosition.instrument_id == order.instrument_id,
    ))
    if position is None:
        position = PaperPosition(account_id=account.id, instrument_id=order.instrument_id)
        db.add(position)
        db.flush()
    state = _PositionState(_d(position.quantity), _d(position.avg_entry_price))
    realized = state.apply(signed, price)
    position.quantity = state.quantity
    position.avg_entry_price = state.entry
    position.realized_pnl = _d(position.realized_pnl) + realized
    position.total_fees = _d(position.total_fees) + fee

    fill = PaperFill(
        order_id=order.id, account_id=account.id, user_id=account.user_id,
        instrument_id=order.instrument_id, side=order.side, quantity=quantity,
        price=price, fee=fee, spread_cost=spread_cost, slippage_cost=slippage_cost,
        realized_pnl=realized, fill_time=moment,
    )
    db.add(fill)
    db.flush()
    position.last_fill_id = fill.id
    account.cash = _d(account.cash) + realized - fee
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
    start = _utc(account.last_funding_boundary or account.created_at)
    end = datetime.fromtimestamp(
        (int(moment.timestamp()) // int(FUNDING_INTERVAL.total_seconds())) * int(FUNDING_INTERVAL.total_seconds()),
        UTC,
    )
    if end <= start:
        return {"applied": applied, "warnings": warnings}
    feature_set_id = _feature_set_id(db)
    positions = {
        row.instrument_id: row for row in db.scalars(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
    }
    boundary = start + FUNDING_INTERVAL
    while boundary <= end:
        for instrument_id, position in positions.items():
            if _d(position.quantity) == 0:
                continue
            existing = db.scalar(select(PaperFundingEntry).where(
                PaperFundingEntry.account_id == account.id,
                PaperFundingEntry.instrument_id == instrument_id,
                PaperFundingEntry.boundary == boundary,
            ))
            if existing is not None:
                continue
            rate = Decimal("0")
            price: Decimal | None = None
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
                    if observed is not None and _utc(observed) == boundary:
                        rate = _d(funding.get("funding_rate") or "0")
                    bar_open = (row.payload.get("bar") or {}).get("open")
                    price = _d(bar_open) if bar_open not in (None, "") else None
            if price is None:
                warnings.append(f"funding price gap at {boundary.isoformat()} for instrument {instrument_id}")
                continue
            cost = abs(_d(position.quantity)) * price * rate
            if _d(position.quantity) < 0:
                cost = -cost
            db.add(PaperFundingEntry(
                account_id=account.id, user_id=account.user_id, instrument_id=instrument_id,
                boundary=boundary, rate=rate, quantity=_d(position.quantity), price=price,
                cash_delta=-cost,
            ))
            account.cash = _d(account.cash) - cost
            applied += 1
        account.last_funding_boundary = boundary
        boundary += FUNDING_INTERVAL
    db.commit()
    return {"applied": applied, "warnings": warnings}


# --- reconciliation --------------------------------------------------------


def rebuild_from_ledger(db: Session, account: PaperAccount) -> dict[str, Any]:
    """Derive positions and cash from the append-only ledger only."""

    fills = list(db.scalars(
        select(PaperFill).where(PaperFill.account_id == account.id)
        .order_by(PaperFill.fill_time, PaperFill.id)
    ))
    funding = list(db.scalars(
        select(PaperFundingEntry).where(PaperFundingEntry.account_id == account.id)
        .order_by(PaperFundingEntry.boundary, PaperFundingEntry.id)
    ))
    states: dict[int, _PositionState] = {}
    fees_by_instrument: dict[int, Decimal] = {}
    cash = _d(account.initial_cash)
    for fill in fills:
        state = states.setdefault(fill.instrument_id, _PositionState())
        realized = state.apply(_d(fill.quantity) if fill.side == "buy" else -_d(fill.quantity), _d(fill.price))
        cash += realized - _d(fill.fee)
        fees_by_instrument[fill.instrument_id] = fees_by_instrument.get(fill.instrument_id, Decimal("0")) + _d(fill.fee)
    for entry in funding:
        cash += _d(entry.cash_delta)
    return {
        "cash": cash,
        "positions": {
            instrument_id: {"quantity": state.quantity, "avg_entry_price": state.entry,
                            "realized_pnl": state.realized, "total_fees": fees_by_instrument.get(instrument_id, Decimal("0"))}
            for instrument_id, state in states.items()
        },
        "fill_count": len(fills),
        "funding_count": len(funding),
    }


def reconcile_account(db: Session, account: PaperAccount) -> PaperReconciliation:
    """Compare cache with the ledger, repair the cache, and record evidence."""

    derived = rebuild_from_ledger(db, account)
    mismatches: list[dict[str, Any]] = []
    cached_rows = {
        row.instrument_id: row for row in db.scalars(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
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
    if _d(account.cash) != derived["cash"]:
        mismatches.append({
            "instrument_id": None,
            "cache": {"cash": str(account.cash)},
            "ledger": {"cash": str(derived["cash"])},
        })

    status = "ok"
    if mismatches:
        status = "repaired"
        for cached in cached_rows.values():
            db.delete(cached)
        db.flush()
        for instrument_id, ledger in derived["positions"].items():
            db.add(PaperPosition(
                account_id=account.id, instrument_id=instrument_id,
                quantity=ledger["quantity"], avg_entry_price=ledger["avg_entry_price"],
                realized_pnl=ledger["realized_pnl"], total_fees=ledger["total_fees"],
            ))
        account.cash = derived["cash"]
    record = PaperReconciliation(
        account_id=account.id, status=status, fill_count=derived["fill_count"],
        funding_count=derived["funding_count"], cash_from_ledger=derived["cash"],
        cash_cached=_d(account.cash), mismatches=mismatches, warnings=[],
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
    marks = mark_prices(db, account)
    rows = db.scalars(
        select(PaperPosition).where(PaperPosition.account_id == account.id)
        .order_by(PaperPosition.instrument_id)
    )
    positions = []
    gross = Decimal("0")
    for row in rows:
        instrument = db.get(CryptoInstrument, row.instrument_id)
        mark = marks.get(row.instrument_id)
        quantity = _d(row.quantity)
        exposure = quantity * mark if mark is not None else None
        if exposure is not None:
            gross += abs(exposure)
        positions.append({
            "instrument_id": row.instrument_id,
            "instrument_symbol": instrument.provider_symbol if instrument else None,
            "quantity": str(quantity), "avg_entry_price": str(_d(row.avg_entry_price)),
            "mark_price": str(mark) if mark is not None else None,
            "exposure": str(exposure) if exposure is not None else None,
            "unrealized_pnl": (
                str((mark - _d(row.avg_entry_price)) * quantity)
                if mark is not None else None
            ),
            "realized_pnl": str(_d(row.realized_pnl)), "total_fees": str(_d(row.total_fees)),
            "updated_at": row.updated_at,
        })
    last_reconciliation = db.scalar(
        select(PaperReconciliation).where(PaperReconciliation.account_id == account.id)
        .order_by(PaperReconciliation.created_at.desc()).limit(1)
    )
    return {
        "id": account.id, "environment": account.environment, "base_currency": account.base_currency,
        "status": account.status, "paused_at": account.paused_at, "pause_reason": account.pause_reason,
        "initial_cash": str(_d(account.initial_cash)), "cash": str(_d(account.cash)),
        "nav": str(nav), "gross_exposure": str(gross),
        "exposure_ratio": str(gross / nav) if nav > 0 else None,
        "leverage_cap": str(_d(account.leverage_cap)), "fill_policy": account.fill_policy,
        "costs": {
            "taker_fee_bps": str(_d(account.taker_fee_bps)),
            "spread_bps": str(_d(account.spread_bps)),
            "slippage_bps": str(_d(account.slippage_bps)),
        },
        "positions": positions, "warnings": warnings,
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
        "side": order.side, "order_type": order.order_type,
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
                "spread_cost": str(_d(fill.spread_cost)), "slippage_cost": str(_d(fill.slippage_cost)),
                "realized_pnl": str(_d(fill.realized_pnl)), "fill_time": fill.fill_time,
            }
            for fill in fills
        ],
    }


def list_orders(db: Session, account_id: int, *, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    query = select(PaperOrder).where(PaperOrder.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(PaperOrder.created_at.desc(), PaperOrder.id.desc()).limit(limit).offset(offset)
    )
    return {"items": [order_payload(db, row) for row in rows], "total": total, "limit": limit, "offset": offset}
