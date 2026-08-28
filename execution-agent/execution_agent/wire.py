from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .constants import ENVIRONMENT, VENUE, WIRE_VERSION
from .errors import LeaseError, WireProtocolError


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise WireProtocolError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise WireProtocolError(f"{name} must be finite")
    return result


def parse_time(value: object, name: str = "time") -> datetime:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=UTC)
    if not isinstance(value, str) or not value.strip():
        raise WireProtocolError(f"{name} is required")
    text = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WireProtocolError(f"{name} has invalid timestamp") from exc
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskPolicy:
    version: str
    hash: str
    capital_allocation_usdt: Decimal | None
    allowed_symbols: frozenset[str]
    allowed_deployment_ids: frozenset[int]
    allowed_instrument_ids: frozenset[int]
    max_order_notional_usdt: Decimal | None
    max_gross_notional_usdt: Decimal | None
    max_net_notional_usdt: Decimal | None
    max_leverage: Decimal | None
    max_daily_loss_usdt: Decimal | None
    max_drawdown_usdt: Decimal | None
    max_open_orders: int | None
    cooldown_seconds: int | None
    stale_signal_seconds: int | None
    stale_account_seconds: int | None
    max_funding_rate_abs: Decimal | None = None
    max_volatility: Decimal | None = None
    allow_reduce_only_when_stale: bool = False
    raw: Mapping[str, object] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "RiskPolicy":
        limits = payload.get("limits")
        source: Mapping[str, object] = limits if isinstance(limits, Mapping) else payload
        symbols = source.get("allowed_symbols", payload.get("allowed_symbols", []))
        if isinstance(symbols, str):
            symbols = [item.strip() for item in symbols.split(",") if item.strip()]
        if not isinstance(symbols, (list, tuple, set, frozenset)):
            symbols = []

        def integer_set(key: str) -> frozenset[int]:
            values = source.get(key, [])
            if not isinstance(values, (list, tuple, set, frozenset)):
                return frozenset()
            try:
                return frozenset(int(item) for item in values if int(item) > 0)
            except (TypeError, ValueError):
                return frozenset()

        def optional_decimal(key: str) -> Decimal | None:
            value = source.get(key, payload.get(key))
            return None if value is None or value == "" else _decimal(value, key)

        def optional_int(key: str) -> int | None:
            value = source.get(key, payload.get(key))
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise WireProtocolError(f"{key} must be an integer") from exc

        hash_value = str(
            payload.get("policy_hash", payload.get("hash", source.get("policy_hash", source.get("hash", "")))) or ""
        )
        # The backend hashes only the canonical limits object, never the
        # surrounding policy envelope/version/hash fields.
        body = dict(source)
        body.pop("policy_hash", None)
        body.pop("hash", None)
        if source is payload:
            for key in ("version", "policy_version", "environment", "account_id", "venue"):
                body.pop(key, None)
        computed = payload_hash(body)
        return cls(
            version=str(payload.get("version", "") or ""),
            hash=hash_value,
            capital_allocation_usdt=optional_decimal("capital_allocation_usdt"),
            allowed_symbols=frozenset(str(item).upper() for item in symbols),
            allowed_deployment_ids=integer_set("allowed_deployment_ids"),
            allowed_instrument_ids=integer_set("allowed_instrument_ids"),
            max_order_notional_usdt=optional_decimal("max_order_notional_usdt"),
            max_gross_notional_usdt=optional_decimal("max_gross_notional_usdt"),
            max_net_notional_usdt=optional_decimal("max_net_notional_usdt"),
            max_leverage=optional_decimal("max_leverage"),
            max_daily_loss_usdt=optional_decimal("max_daily_loss_usdt"),
            max_drawdown_usdt=optional_decimal("max_drawdown_usdt"),
            max_open_orders=optional_int("max_open_orders"),
            cooldown_seconds=optional_int("cooldown_seconds"),
            stale_signal_seconds=optional_int("stale_signal_seconds"),
            stale_account_seconds=optional_int("stale_account_seconds"),
            max_funding_rate_abs=optional_decimal("max_funding_rate_abs"),
            max_volatility=optional_decimal("max_volatility"),
            allow_reduce_only_when_stale=bool(source.get("allow_reduce_only_when_stale", False)),
            raw=payload,
        )

    @property
    def computed_hash(self) -> str:
        limits = self.raw.get("limits") if isinstance(self.raw, Mapping) else None
        body = dict(limits) if isinstance(limits, Mapping) else dict(self.raw)
        body.pop("policy_hash", None)
        body.pop("hash", None)
        if not isinstance(limits, Mapping):
            for key in ("version", "policy_version", "environment", "account_id", "venue"):
                body.pop(key, None)
        return payload_hash(body)


@dataclass(frozen=True)
class Lease:
    lease_id: str
    signal_id: str
    account_id: str
    symbol: str
    target_exposure: Decimal
    expires_at: datetime
    issued_at: datetime
    policy: RiskPolicy
    policy_hash: str
    wire_version: str = WIRE_VERSION
    environment: str = ENVIRONMENT
    venue: str = VENUE
    instrument_id: int | None = None
    deployment_id: int | None = None
    signal_time: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "Lease":
        raw_policy = payload.get("policy")
        if not isinstance(raw_policy, Mapping):
            raise LeaseError("lease policy is missing")
        policy = RiskPolicy.from_payload(raw_policy)
        lease_id = str(payload.get("lease_id", "") or "")
        signal_id = str(payload.get("signal_id", "") or "")
        account_id = str(payload.get("account_id", "") or "")
        symbol = str(payload.get("symbol", payload.get("instrument_symbol", "")) or "").upper()
        if not lease_id or not signal_id or not account_id or not symbol:
            raise LeaseError("lease identity is incomplete")
        policy_hash = str(payload.get("policy_hash", policy.hash) or "")
        issued_raw = payload.get("issued_at", payload.get("created_at", payload.get("signal_time")))
        signal_raw = payload.get("signal_time", payload.get("decision_time", issued_raw))
        return cls(
            lease_id=lease_id,
            signal_id=signal_id,
            account_id=account_id,
            symbol=symbol,
            target_exposure=_decimal(payload.get("target_exposure"), "target_exposure"),
            expires_at=parse_time(payload.get("expires_at"), "expires_at"),
            issued_at=parse_time(issued_raw, "issued_at"),
            policy=policy,
            policy_hash=policy_hash,
            wire_version=str(payload.get("wire_version", WIRE_VERSION) or ""),
            environment=str(payload.get("environment", "") or ""),
            venue=str(payload.get("venue", "") or ""),
            instrument_id=int(payload["instrument_id"]) if payload.get("instrument_id") is not None else None,
            deployment_id=int(payload["deployment_id"]) if payload.get("deployment_id") is not None else None,
            signal_time=parse_time(signal_raw, "signal_time") if signal_raw is not None else None,
            metadata=dict(payload),
        )

    def validate(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if self.wire_version != WIRE_VERSION:
            raise LeaseError("unsupported lease wire version")
        if self.environment != ENVIRONMENT:
            raise LeaseError("lease environment is not TEST")
        if self.venue != VENUE:
            raise LeaseError("lease venue is not Binance USD-M")
        if self.expires_at <= current:
            raise LeaseError("lease has expired")
        if self.target_exposure < Decimal("-1") or self.target_exposure > Decimal("1"):
            raise LeaseError("target exposure is outside bounds")
        if self.policy.version == "" or self.policy_hash == "":
            raise LeaseError("policy version/hash is required")
        if self.policy.hash and self.policy_hash != self.policy.hash:
            raise LeaseError("policy hash mismatch")
        if self.policy.computed_hash != self.policy_hash:
            raise LeaseError("policy hash mismatch")
        if self.policy.allowed_symbols and self.symbol not in self.policy.allowed_symbols:
            raise LeaseError("instrument is outside policy allowlist")
        if self.instrument_id is None or self.instrument_id not in self.policy.allowed_instrument_ids:
            raise LeaseError("instrument ID is outside policy allowlist")
        if self.deployment_id is None or self.deployment_id not in self.policy.allowed_deployment_ids:
            raise LeaseError("deployment is outside policy allowlist")

    def client_order_id(self, agent_id: str) -> str:
        return deterministic_client_order_id(agent_id, self.lease_id)

    def as_dict(self) -> dict[str, object]:
        return {
            "wire_version": self.wire_version,
            "lease_id": self.lease_id,
            "signal_id": self.signal_id,
            "account_id": self.account_id,
            "environment": self.environment,
            "venue": self.venue,
            "symbol": self.symbol,
            "instrument_id": self.instrument_id,
            "deployment_id": self.deployment_id,
            "target_exposure": str(self.target_exposure),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "policy_hash": self.policy_hash,
            "policy_version": self.policy.version,
        }


def deterministic_client_order_id(agent_id: str, lease_id: str) -> str:
    digest = hashlib.sha256(f"{agent_id}:{lease_id}".encode("utf-8")).hexdigest()
    return "EA" + digest[:34]


@dataclass(frozen=True)
class AgentEvent:
    lease_id: str
    event_type: str
    payload: Mapping[str, object]
    event_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def stable_id(self) -> str:
        if self.event_id:
            return self.event_id
        body = {"lease_id": self.lease_id, "event_type": self.event_type, "payload": self.payload}
        return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "wire_version": WIRE_VERSION,
            "event_id": self.stable_id(),
            "lease_id": self.lease_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "payload": _json_value(self.payload),
        }
