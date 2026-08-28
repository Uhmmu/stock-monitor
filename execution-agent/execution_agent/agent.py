from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping

from .binance import BinanceAccount, BinanceClient, ExchangeFilter
from .config import AgentConfig
from .control import ControlPlaneClient
from .errors import (
    AmbiguousOrderError,
    BinanceError,
    ControlPlaneError,
    ExecutionBlocked,
    LeaseError,
    UnresolvedOrderError,
)
from .journal import Journal, JournalOrder
from .risk import AccountSnapshot, MarketSnapshot, SymbolFilters, evaluate_order
from .security import InstanceLock, KillSwitch, redact
from .wire import AgentEvent, Lease


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


def _order_trades(items: list[Mapping[str, object]], client_order_id: str, exchange_order_id: object) -> list[dict[str, object]]:
    """Attach the client ID that Binance userTrades omits."""

    return [
        {**dict(item), "clientOrderId": client_order_id}
        for item in items
        if str(item.get("clientOrderId", "")) == client_order_id
        or (exchange_order_id is not None and str(item.get("order", item.get("orderId", ""))) == str(exchange_order_id))
    ]


class ExecutionAgent:
    """One-process TEST executor. The local journal is the crash boundary."""

    def __init__(
        self,
        config: AgentConfig,
        control: ControlPlaneClient,
        exchange: BinanceClient,
        journal: Journal,
        *,
        kill_switch: KillSwitch | None = None,
        clock=time.time,
    ):
        self.config = config
        self.control = control
        self.exchange = exchange
        self.journal = journal
        self.kill_switch = kill_switch or KillSwitch(config.kill_switch_path)
        self.clock = clock
        self._started = False

    @property
    def blocked(self) -> bool:
        return self.kill_switch.is_active() or self.journal.mismatch_blocked()

    def _ensure_unblocked(self) -> None:
        if self.kill_switch.is_active():
            raise ExecutionBlocked(f"local kill switch active: {self.kill_switch.reason() or 'operator or safety trip'}")
        if self.journal.mismatch_blocked():
            raise ExecutionBlocked("local reconciliation mismatch blocks execution")

    def startup(self) -> None:
        if self._started:
            return
        # Every incomplete order is queried before a new lease is considered.
        # A PREPARED row is deliberately conservative: after a crash we cannot
        # prove whether the HTTP request left the process.
        for order in self.journal.incomplete_orders():
            found = self.exchange.query_order(symbol=order.symbol, client_order_id=order.client_order_id)
            if found is None:
                self.journal.mark_status(order.client_order_id, "UNKNOWN")
                self.journal.record_reconciliation("unknown", {"client_order_id": order.client_order_id})
                self.kill_switch.trip("unresolved local order after restart")
                raise ExecutionBlocked("incomplete order could not be reconciled")
            self.journal.record_exchange_order(found)
            trades = self.exchange.user_trades(symbol=order.symbol)
            self.journal.record_fills(_order_trades(trades, order.client_order_id, found.get("orderId")))
            status = str(found.get("status", "")).upper()
            if status in {"NEW", "PARTIALLY_FILLED"} and hasattr(self.exchange, "cancel_order"):
                # Recovery is allowed to query/cancel even while the local
                # kill switch is active; only new lease execution is blocked.
                try:
                    cancelled = self.exchange.cancel_order(symbol=order.symbol, client_order_id=order.client_order_id)
                    self.journal.record_exchange_order(cancelled)
                except BinanceError:
                    self.journal.record_reconciliation("unknown", {"client_order_id": order.client_order_id, "reason": "cancel_failed"})
        if self.journal.incomplete_orders():
            self.kill_switch.trip("incomplete order remains after restart reconciliation")
            raise ExecutionBlocked("incomplete order remains after restart reconciliation")
        self._flush_pending_events()
        self._ensure_unblocked()
        self._started = True

    def _flush_pending_events(self) -> None:
        for payload in self.journal.pending_events():
            event_id = str(payload.get("event_id", ""))
            try:
                self.control.post_event_payload(payload, idempotency_key=event_id)
            except ControlPlaneError:
                # Keep it durable for the next run; no order is attempted while
                # the remote audit channel is unavailable.
                self.kill_switch.trip("control event delivery unavailable")
                raise ExecutionBlocked("control event delivery unavailable")
            self.journal.mark_event_sent(event_id)

    def _publish(self, lease_id: str, event_type: str, payload: Mapping[str, object]) -> bool:
        event = AgentEvent(lease_id=lease_id, event_type=event_type, payload=dict(redact(dict(payload))))
        inserted = self.journal.record_event(event)
        if not inserted:
            return True
        try:
            self.control.post_event(event)
        except ControlPlaneError:
            self.kill_switch.trip("control event delivery unavailable")
            return False
        self.journal.mark_event_sent(event.stable_id())
        return True

    def _account_snapshot(self, value: BinanceAccount | AccountSnapshot) -> AccountSnapshot:
        if isinstance(value, AccountSnapshot):
            account = value
        else:
            account = AccountSnapshot(
                available_balance_usdt=value.available_balance_usdt,
                equity_usdt=value.equity_usdt,
                gross_notional_usdt=value.gross_notional_usdt,
                net_notional_usdt=value.net_notional_usdt,
                positions=value.positions,
                open_orders=value.open_orders,
                as_of=_as_datetime(value.as_of),
                daily_loss_usdt=value.daily_loss_usdt,
                drawdown_usdt=value.drawdown_usdt,
                last_order_at=_as_datetime(value.last_order_at) if value.last_order_at is not None else None,
            )
        if account.equity_usdt is not None and (account.daily_loss_usdt is None or account.drawdown_usdt is None):
            daily_loss, drawdown = self.journal.account_risk_metrics(account.equity_usdt, observed_at=account.as_of.timestamp())
            account = replace(
                account,
                daily_loss_usdt=account.daily_loss_usdt if account.daily_loss_usdt is not None else daily_loss,
                drawdown_usdt=account.drawdown_usdt if account.drawdown_usdt is not None else drawdown,
            )
        return account

    def _exchange_filter(self, value: ExchangeFilter | SymbolFilters) -> SymbolFilters:
        if isinstance(value, SymbolFilters):
            return value
        return SymbolFilters(
            step_size=value.step_size,
            min_quantity=value.min_quantity,
            max_quantity=value.max_quantity,
            min_notional=value.min_notional,
        )

    def _market_snapshot(self, lease: Lease, value: object) -> MarketSnapshot:
        if isinstance(value, MarketSnapshot):
            return value
        price, as_of = value  # adapter returns (Decimal, epoch seconds)
        evidence = lease.metadata.get("risk_evidence") if isinstance(lease.metadata, Mapping) else None
        if not isinstance(evidence, Mapping):
            evidence = {}
        evidence_time = evidence.get("as_of")
        try:
            evidence_as_of = _as_datetime(evidence_time) if evidence_time is not None else None
        except (TypeError, ValueError, OverflowError):
            evidence_as_of = None
        from .wire import parse_time

        if evidence_as_of is None and evidence_time is not None:
            try:
                evidence_as_of = parse_time(evidence_time, "risk_evidence.as_of")
            except Exception:
                evidence_as_of = None
        def evidence_decimal(*keys: str) -> Decimal | None:
            for key in keys:
                if evidence.get(key) is not None:
                    try:
                        result = Decimal(str(evidence[key]))
                        if result.is_finite():
                            return result
                    except Exception:
                        return None
            return None
        return MarketSnapshot(
            lease.symbol,
            price,
            _as_datetime(as_of),
            funding_rate=evidence_decimal("funding_rate"),
            volatility=evidence_decimal("realized_volatility_24", "volatility"),
            evidence_as_of=evidence_as_of,
        )

    def _reconcile_symbol(self, symbol: str, *, account: AccountSnapshot | None = None) -> bool:
        account = account or self._account_snapshot(self.exchange.account_snapshot())
        local = self.journal.rebuild_positions()
        remote = {key.upper(): Decimal(str(value)) for key, value in account.positions.items()}
        symbols = set(local) | set(remote)
        mismatch = {
            key: {"local": str(local.get(key, Decimal("0"))), "remote": str(remote.get(key, Decimal("0")))}
            for key in symbols
            if abs(local.get(key, Decimal("0")) - remote.get(key, Decimal("0"))) > Decimal("0.00000001")
        }
        self.journal.record_reconciliation("mismatch" if mismatch else "ok", mismatch)
        if mismatch:
            self.kill_switch.trip("local and exchange positions differ")
            return False
        return True

    def process_lease(self, lease: Lease) -> dict[str, object]:
        self._ensure_unblocked()
        try:
            lease.validate(now=_as_datetime(self.clock()))
        except LeaseError as exc:
            self._publish(lease.lease_id, "risk_reject", {"reason": str(exc)})
            self._publish(lease.lease_id, "lease_reject", {"status": "rejected", "reason": str(exc)})
            return {"status": "rejected", "reason": str(exc)}

        client_order_id = lease.client_order_id(self.config.agent_id)
        try:
            if hasattr(self.exchange, "server_time"):
                self.exchange.server_time()
            exchange_filter = self._exchange_filter(self.exchange.exchange_filters(lease.symbol))
            account = self._account_snapshot(self.exchange.account_snapshot())
            market = self._market_snapshot(lease, self.exchange.mark_price(lease.symbol))
        except BinanceError as exc:
            reason = str(exc)
            self._publish(lease.lease_id, "risk_reject", {"reason": reason})
            self._publish(lease.lease_id, "lease_reject", {"status": "rejected", "reason": reason})
            return {"status": "rejected", "reason": reason}

        if not self._reconcile_symbol(lease.symbol, account=account):
            self._publish(lease.lease_id, "risk_reject", {"reason": "local_reconciliation_mismatch"})
            self._publish(lease.lease_id, "lease_reject", {"status": "risk_rejected", "reason": "local_reconciliation_mismatch"})
            return {"status": "risk_rejected", "reason": "local_reconciliation_mismatch"}

        decision = evaluate_order(
            lease,
            account=account,
            market=market,
            filters=exchange_filter,
            now=_as_datetime(self.clock()),
        )
        if not decision.approved:
            self._publish(lease.lease_id, "risk_reject", {"reason": decision.reason, **dict(decision.details)})
            self._publish(lease.lease_id, "lease_reject", {"status": "risk_rejected", "reason": decision.reason})
            return {"status": "risk_rejected", "reason": decision.reason}
        if decision.plan is None:
            self._publish(lease.lease_id, "lease_ack", {"status": "no_order_needed"})
            return {"status": "no_order_needed"}

        plan = decision.plan
        self.journal.prepare_order(
            lease_id=lease.lease_id,
            client_order_id=client_order_id,
            symbol=plan.symbol,
            side=plan.side,
            quantity=plan.quantity,
            target_exposure=lease.target_exposure,
            payload={"wire_version": lease.wire_version, "policy_hash": lease.policy_hash},
        )
        order_payload = {
            "client_order_id": client_order_id,
            "instrument_id": lease.instrument_id,
            "symbol": plan.symbol,
            "side": plan.side.lower(),
            "quantity": str(plan.quantity),
            "price": str(market.price),
            "order_type": "market",
        }
        if not self._publish(lease.lease_id, "order_submitted", order_payload):
            return {"status": "blocked", "client_order_id": client_order_id}
        try:
            response = self.exchange.place_with_recovery(
                symbol=plan.symbol,
                side=plan.side,
                quantity=plan.quantity,
                client_order_id=client_order_id,
            )
        except UnresolvedOrderError as exc:
            self.journal.mark_status(client_order_id, "UNKNOWN")
            self.kill_switch.trip("ambiguous Binance order remains unresolved")
            self._publish(lease.lease_id, "order_update", {"client_order_id": client_order_id, "status": "unknown", "reason": str(exc)})
            self._publish(lease.lease_id, "lease_ack", {"status": "unknown", "client_order_id": client_order_id})
            return {"status": "unknown", "client_order_id": client_order_id}
        except AmbiguousOrderError as exc:
            self.journal.mark_status(client_order_id, "UNKNOWN")
            self.kill_switch.trip("ambiguous Binance order requires recovery")
            self._publish(lease.lease_id, "order_update", {"client_order_id": client_order_id, "status": "unknown", "reason": str(exc)})
            return {"status": "unknown", "client_order_id": client_order_id}
        except BinanceError as exc:
            self.journal.mark_status(client_order_id, "REJECTED", payload={"reason": str(exc)})
            self._publish(lease.lease_id, "order_update", {"client_order_id": client_order_id, "status": "rejected", "reason": str(exc)})
            self._publish(lease.lease_id, "lease_reject", {"status": "rejected", "client_order_id": client_order_id})
            return {"status": "rejected", "client_order_id": client_order_id}

        self.journal.record_exchange_order(response)
        trades = self.exchange.user_trades(symbol=plan.symbol)
        related = _order_trades(trades, client_order_id, response.get("orderId"))
        self.journal.record_fills(related)
        exchange_status = str(response.get("status", "")).upper()
        if exchange_status in {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED"}:
            status_value = "cancelled" if exchange_status in {"CANCELED", "CANCELLED", "EXPIRED"} else "rejected"
            self._publish(lease.lease_id, "order_update", {"client_order_id": client_order_id, "status": status_value})
            self._publish(lease.lease_id, "lease_reject", {"status": status_value, "client_order_id": client_order_id})
            return {"status": exchange_status.lower(), "client_order_id": client_order_id}
        self._publish(lease.lease_id, "order_update", {
            "client_order_id": client_order_id,
            "provider_order_id": response.get("orderId"),
            "status": "partially_filled" if exchange_status == "PARTIALLY_FILLED" else "submitted",
        })
        for item in related:
            self._publish(lease.lease_id, "fill", {
                "client_order_id": client_order_id,
                "provider_trade_id": item.get("id", item.get("tradeId")),
                "side": str(item.get("side", plan.side)).lower(),
                "quantity": item.get("qty", item.get("quantity")),
                "price": item.get("price"),
                "fee": item.get("commission", "0"),
                "fee_asset": item.get("commissionAsset"),
                "fill_time": datetime.fromtimestamp(float(item.get("time", self.clock() * 1000)) / 1000, tz=UTC).isoformat(),
            })
        reconciled = self._reconcile_symbol(plan.symbol)
        self._publish(lease.lease_id, "reconciliation", {"client_order_id": client_order_id, "status": "ok" if reconciled else "mismatch"})
        self._publish(lease.lease_id, "lease_ack", {"status": "filled" if related else "submitted", "client_order_id": client_order_id})
        return {"status": "filled" if related else "submitted", "client_order_id": client_order_id, "reconciled": reconciled}

    def run_once(self) -> dict[str, object]:
        self.startup()
        self._ensure_unblocked()
        lease = self.control.get_lease()
        if lease is None:
            return {"status": "idle"}
        return self.process_lease(lease)

    def run_loop(self) -> None:
        self.startup()
        while True:
            try:
                self.run_once()
            except ExecutionBlocked:
                raise
            except (ControlPlaneError, BinanceError):
                # Keep the process alive for transient read-only polling errors;
                # an order ambiguity/mismatch trips the persistent kill switch.
                pass
            time.sleep(self.config.poll_interval_seconds)

    def instance_lock(self) -> InstanceLock:
        return InstanceLock(self.config.lock_path)
