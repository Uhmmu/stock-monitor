"""Durable, expiring quant signals and their scheduled generation.

A signal is a desired position (normalized exposure in [-1, 1]) produced by a
released strategy at a closed UTC boundary.  It is not an order: there is no
side/type field, no broker linkage and no Binance import anywhere in this
module.  Signals expire non-extendably; anything not consumed before
``expires_at`` is unleaseable forever, even if the worker was offline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CryptoInstrument,
    QuantFeatureSet,
    QuantFeatureValue,
    QuantSignal,
    QuantSignalRun,
    QuantStrategyDeployment,
    User,
)
from app.services.quant.backtest.contracts import BarEvent
from app.services.quant.backtest.service import ALLOWED_SYMBOLS, INTERVALS
from app.services.quant.backtest.strategies import get_strategy
from app.services.quant.features import FEATURE_SET_KEY
from app.services.quant.registry import (
    STRATEGY_REGISTRY,
    canonical_hash,
    feature_set_definition,
    strategy_config_hash,
    validate_parameters,
)

SIGNAL_STATUSES = ("generated", "superseded", "expired", "rejected", "consumed")
RUN_STATUSES = (
    "signal_created", "no_signal", "duplicate", "stale_data",
    "missing_data", "failed", "skipped_paused", "skipped_expired_boundary",
)
RETRYABLE_RUN_STATUSES = ("missing_data", "stale_data", "failed")

INTERVAL_DELTAS: dict[str, timedelta] = {
    "1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def boundary_lag() -> timedelta:
    return timedelta(minutes=max(1, int(get_settings().quant_signal_boundary_lag_minutes)))


def boundary_for(interval: str, now: datetime) -> datetime:
    """Return the close instant of the newest boundary closed before ``now - lag``."""

    delta = INTERVAL_DELTAS[interval]
    reference = _utc(now) - boundary_lag()
    epoch = int(reference.timestamp())
    step = int(delta.total_seconds())
    return datetime.fromtimestamp((epoch // step) * step, UTC)


def signal_expiry(boundary: datetime, interval: str) -> datetime:
    """Expiry never outlives the next decision point minus the safety lag."""

    cap = timedelta(minutes=max(15, int(get_settings().quant_signal_max_validity_minutes)))
    return boundary + min(INTERVAL_DELTAS[interval] - boundary_lag(), cap)


def allowed_instrument(db: Session, instrument_id: int) -> CryptoInstrument | None:
    return db.scalar(select(CryptoInstrument).where(
        CryptoInstrument.id == instrument_id,
        CryptoInstrument.market == "usdm_futures",
        CryptoInstrument.kind == "perpetual",
        CryptoInstrument.status == "trading",
        CryptoInstrument.provider_symbol.in_(ALLOWED_SYMBOLS),
    ))


# --- deployments -----------------------------------------------------------


def create_deployment(
    db: Session, *, user_id: int, strategy_key: str, instrument_id: int,
    interval: str, target_exposure: float = 1.0,
) -> QuantStrategyDeployment:
    if strategy_key not in STRATEGY_REGISTRY:
        raise ValueError("unknown strategy")
    if interval not in INTERVALS:
        raise ValueError("unsupported interval")
    parameters = validate_parameters(strategy_key, {"target_exposure": target_exposure})
    instrument = allowed_instrument(db, instrument_id)
    if instrument is None:
        raise ValueError("标的必须是 BTC/ETH/ADA 的 active Binance USD-M perpetual")
    if db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise ValueError("unknown user")
    existing = db.scalar(select(QuantStrategyDeployment).where(
        QuantStrategyDeployment.user_id == user_id,
        QuantStrategyDeployment.environment == "paper",
        QuantStrategyDeployment.strategy_key == strategy_key,
        QuantStrategyDeployment.instrument_id == instrument_id,
        QuantStrategyDeployment.interval == interval,
    ))
    if existing is not None:
        raise RuntimeError("该策略部署已存在，可暂停或恢复，不需要重复创建")
    definition = STRATEGY_REGISTRY[strategy_key]
    row = QuantStrategyDeployment(
        user_id=user_id, environment="paper", strategy_key=strategy_key,
        strategy_version=definition.version, instrument_id=instrument_id,
        interval=interval, target_exposure=Decimal(str(parameters["target_exposure"])),
        status="paused",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_deployment_status(
    db: Session, deployment: QuantStrategyDeployment, *, status: str, reason: str | None = None,
) -> QuantStrategyDeployment:
    if status not in ("active", "paused"):
        raise ValueError("unsupported status")
    deployment.status = status
    if status == "paused":
        deployment.paused_at = _now()
        deployment.pause_reason = reason or "user pause"
        # Pausing also retires the deployment's live target so no stale signal
        # remains leasable while the strategy is switched off.
        db.execute(
            update(QuantSignal)
            .where(
                QuantSignal.deployment_id == deployment.id,
                QuantSignal.status == "generated",
            )
            .values(status="superseded", superseded_by_id=None)
            .execution_options(synchronize_session=False)
        )
    else:
        deployment.pause_reason = None
    db.commit()
    db.refresh(deployment)
    return deployment


def list_deployments(db: Session, user_id: int) -> list[QuantStrategyDeployment]:
    return list(db.scalars(
        select(QuantStrategyDeployment)
        .where(QuantStrategyDeployment.user_id == user_id)
        .order_by(QuantStrategyDeployment.created_at.desc())
    ))


def owned_deployment(db: Session, user_id: int, deployment_id: int) -> QuantStrategyDeployment | None:
    return db.scalar(select(QuantStrategyDeployment).where(
        QuantStrategyDeployment.id == deployment_id,
        QuantStrategyDeployment.user_id == user_id,
    ))


# --- signal lifecycle ------------------------------------------------------


def expire_due_signals(db: Session, *, now: datetime | None = None) -> int:
    """Transition leasable signals whose expiry passed; idempotent."""

    moment = _utc(now or _now())
    expired = db.execute(
        update(QuantSignal)
        .where(QuantSignal.status == "generated", QuantSignal.expires_at <= moment)
        .values(status="expired")
        .execution_options(synchronize_session=False)
    ).rowcount
    if expired:
        db.commit()
    return int(expired)


def consume_signal(
    db: Session, signal_id: int, *, now: datetime | None = None, reason: str | None = None,
) -> QuantSignal | None:
    """Atomically lease one signal; expired or already-consumed rows return None."""

    moment = _utc(now or _now())
    claimed = db.execute(
        update(QuantSignal)
        .where(
            QuantSignal.id == signal_id,
            QuantSignal.status == "generated",
            QuantSignal.expires_at > moment,
        )
        .values(status="consumed", consumed_at=moment, consumed_reason=reason)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if not claimed:
        return None
    return db.get(QuantSignal, signal_id)


def reject_signal(db: Session, signal: QuantSignal, reason: str) -> QuantSignal:
    row = db.execute(
        update(QuantSignal)
        .where(QuantSignal.id == signal.id, QuantSignal.status == "generated")
        .values(status="rejected", rejected_reason=reason[:2000])
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    db.refresh(signal)
    if not row:
        raise RuntimeError(f"signal {signal.id} could not be rejected from status {signal.status}")
    return signal


def signal_idempotency_key(deployment: QuantStrategyDeployment, boundary: datetime) -> str:
    return (
        f"sig-{deployment.id}-{deployment.instrument_id}-{deployment.interval}-"
        f"{int(_utc(boundary).timestamp() * 1000)}"
    )


def _feature_set_id(db: Session) -> int | None:
    definition = feature_set_definition()
    return db.scalar(select(QuantFeatureSet.id).where(
        QuantFeatureSet.feature_set_key == definition.key,
        QuantFeatureSet.version == definition.version,
    ))


def latest_final_feature(
    db: Session, *, instrument_id: int, interval: str, boundary: datetime,
) -> QuantFeatureValue | None:
    """The causal feature vintage for one closed boundary, or None.

    Uses the same strict availability filter as backtest replay
    (``available_at <= as_of``), so signals only see inputs a backtest
    could have seen at that instant.
    """

    feature_set_id = _feature_set_id(db)
    if feature_set_id is None:
        return None
    moment = _utc(boundary)
    return db.scalar(
        select(QuantFeatureValue)
        .where(
            QuantFeatureValue.feature_set_id == feature_set_id,
            QuantFeatureValue.instrument_id == instrument_id,
            QuantFeatureValue.interval == interval,
            QuantFeatureValue.as_of == moment,
            QuantFeatureValue.available_at <= QuantFeatureValue.as_of,
        )
        .order_by(QuantFeatureValue.id.desc())
        .limit(1)
    )


def build_decision_bar(feature: QuantFeatureValue) -> BarEvent:
    bar = feature.payload.get("bar") or {}
    if not bar.get("close"):
        raise ValueError("feature payload is missing the decision bar")
    return BarEvent(
        instrument_id=feature.instrument_id,
        timestamp=_utc(feature.as_of),
        open=bar.get("open"), high=bar.get("high"), low=bar.get("low"),
        close=bar.get("close"),
        volume=bar.get("base_volume") or "0",
        funding_rate=str((feature.payload.get("funding") or {}).get("funding_rate") or "0"),
        features={
            key: value for key, value in feature.payload.items()
            if isinstance(value, (int, float, str)) and value is not None
        },
    )


def _claim_run(
    db: Session, deployment: QuantStrategyDeployment, boundary: datetime,
) -> tuple[QuantSignalRun, bool]:
    """Claim the single run row per (deployment, boundary).

    Returns ``(run, claimable)``; a final run (signal created or a terminal
    no-signal/duplicate state) is returned unmodified and not re-processed, so
    duplicate Beat dispatches for one boundary stay idempotent.
    """

    existing = db.scalar(select(QuantSignalRun).where(
        QuantSignalRun.deployment_id == deployment.id,
        QuantSignalRun.boundary == _utc(boundary),
    ))
    if existing is None:
        existing = QuantSignalRun(
            user_id=deployment.user_id, deployment_id=deployment.id,
            instrument_id=deployment.instrument_id, interval=deployment.interval,
            boundary=_utc(boundary), status="failed", reason="initialized",
        )
        db.add(existing)
        db.flush()
        return existing, True
    if existing.signal_id is not None or existing.status not in RETRYABLE_RUN_STATUSES:
        return existing, False
    existing.retries = (existing.retries or 0) + 1
    return existing, True


def _finalize_run(
    run: QuantSignalRun, *, status: str, reason: str | None = None,
    feature: QuantFeatureValue | None = None, now: datetime | None = None,
    signal: QuantSignal | None = None,
) -> None:
    run.status = status
    run.reason = reason
    if feature is not None:
        run.feature_as_of = feature.as_of
        run.feature_available_at = feature.available_at
        run.lag_seconds = int((_utc(now or _now()) - _utc(feature.available_at)).total_seconds())
    if signal is not None:
        run.signal_id = signal.id


def generate_for_deployment(
    db: Session, deployment: QuantStrategyDeployment, *, now: datetime | None = None,
) -> QuantSignalRun | None:
    """One deterministic generation attempt for the deployment's newest boundary."""

    moment = _utc(now or _now())
    if deployment.status != "active":
        return None
    boundary = boundary_for(deployment.interval, moment)
    expiry = signal_expiry(boundary, deployment.interval)
    run, claimable = _claim_run(db, deployment, boundary)
    if not claimable:
        return run
    if moment >= expiry:
        _finalize_run(run, status="skipped_expired_boundary", reason="boundary already past decision window", now=moment)
        db.commit()
        return run
    feature = latest_final_feature(
        db, instrument_id=deployment.instrument_id, interval=deployment.interval, boundary=boundary,
    )
    if feature is None:
        _finalize_run(run, status="missing_data", reason="no finalized causal feature at boundary", now=moment)
        db.commit()
        return run
    key = signal_idempotency_key(deployment, boundary)
    existing_signal = db.scalar(select(QuantSignal).where(QuantSignal.idempotency_key == key))
    if existing_signal is not None:
        _finalize_run(run, status="duplicate", reason="signal already exists for this decision point", feature=feature, now=moment, signal=existing_signal)
        db.commit()
        return run
    try:
        bar = build_decision_bar(feature)
        raw_target = get_strategy(deployment.strategy_key)(bar)
        if not isinstance(raw_target, Decimal):
            raw_target = Decimal(str(raw_target))
        target = raw_target * Decimal(str(deployment.target_exposure))
        target = max(Decimal("-1"), min(Decimal("1"), target))
    except Exception as exc:  # strategy isolation: one bad deployment never fails the batch
        _finalize_run(run, status="failed", reason=f"{type(exc).__name__}: {str(exc)[:400]}", feature=feature, now=moment)
        db.commit()
        return run

    latest = db.scalar(
        select(QuantSignal)
        .where(QuantSignal.deployment_id == deployment.id)
        .order_by(QuantSignal.decision_time.desc(), QuantSignal.id.desc())
        .limit(1),
    )
    if latest is not None and Decimal(str(latest.target_exposure)) == target:
        _finalize_run(run, status="no_signal", reason="target unchanged", feature=feature, now=moment)
        db.commit()
        return run
    if latest is None and target == Decimal("0"):
        _finalize_run(run, status="no_signal", reason="flat target with no prior exposure", feature=feature, now=moment)
        db.commit()
        return run

    bar_payload = feature.payload.get("bar") or {}
    evidence = {
        "bar": {name: _json(bar_payload.get(name)) for name in ("open", "high", "low", "close", "base_volume")},
        "features": _json({
            key: value for key, value in feature.payload.items()
            if key in ("rsi14", "sma20", "sma50", "macd_histogram") and value is not None
        }),
        "raw_target": str(raw_target),
        "target_exposure_setting": str(deployment.target_exposure),
        "feature_input_hash": feature.input_hash,
        "funding_rate": str((feature.payload.get("funding") or {}).get("funding_rate") or "0"),
        "fill_policy_note": "signal is a desired position; execution belongs to the paper layer",
    }
    signal = QuantSignal(
        user_id=deployment.user_id, deployment_id=deployment.id, environment="paper",
        status="generated", strategy_key=deployment.strategy_key,
        strategy_version=deployment.strategy_version, instrument_id=deployment.instrument_id,
        interval=deployment.interval, decision_time=_utc(boundary), target_exposure=target,
        reason=(
            f"{deployment.strategy_key} raw target {raw_target} at closed {deployment.interval} "
            f"boundary {boundary.isoformat()}"
        ),
        evidence=evidence, feature_value_id=feature.id, input_hash=feature.input_hash,
        data_hash=canonical_hash(evidence["bar"]),
        feature_hash=canonical_hash({"feature_value_id": feature.id, "input_hash": feature.input_hash}),
        code_hash=strategy_config_hash(deployment.strategy_key, {"target_exposure": float(deployment.target_exposure)}),
        idempotency_key=key, valid_from=moment, expires_at=expiry,
    )
    db.add(signal)
    db.flush()
    if latest is not None and latest.status == "generated":
        latest.status = "superseded"
        latest.superseded_by_id = signal.id
    _finalize_run(run, status="signal_created", feature=feature, now=moment, signal=signal)
    db.commit()
    return run


def generate_due_signals(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    expire_due_signals(db, now=now)
    moment = _utc(now or _now())
    deployments = list(db.scalars(
        select(QuantStrategyDeployment).where(QuantStrategyDeployment.status == "active")
    ))
    counters: dict[str, int] = {}
    for deployment in deployments:
        run = generate_for_deployment(db, deployment, now=moment)
        status = run.status if run is not None else "skipped_paused"
        counters[status] = counters.get(status, 0) + 1
    return {"deployments": len(deployments), "runs": counters}


# --- read helpers ----------------------------------------------------------


def signal_payload(db: Session, signal: QuantSignal, *, now: datetime | None = None) -> dict[str, Any]:
    moment = _utc(now or _now())
    effective_status = (
        "expired" if signal.status == "generated" and _utc(signal.expires_at) <= moment else signal.status
    )
    instrument = db.get(CryptoInstrument, signal.instrument_id)
    deployment = db.get(QuantStrategyDeployment, signal.deployment_id)
    return {
        "id": signal.id, "environment": signal.environment, "status": effective_status,
        "strategy_key": signal.strategy_key, "strategy_version": signal.strategy_version,
        "instrument_id": signal.instrument_id,
        "instrument_symbol": instrument.provider_symbol if instrument else None,
        "deployment_id": signal.deployment_id,
        "deployment_status": deployment.status if deployment else None,
        "interval": signal.interval, "decision_time": signal.decision_time,
        "target_exposure": str(signal.target_exposure), "reason": signal.reason,
        "evidence": signal.evidence, "feature_value_id": signal.feature_value_id,
        "input_hash": signal.input_hash, "data_hash": signal.data_hash,
        "feature_hash": signal.feature_hash, "code_hash": signal.code_hash,
        "idempotency_key": signal.idempotency_key,
        "generated_at": signal.generated_at, "valid_from": signal.valid_from,
        "expires_at": signal.expires_at,
        "expires_in_seconds": max(0, int((_utc(signal.expires_at) - moment).total_seconds())),
        "server_time": moment.isoformat(),
        "consumed_at": signal.consumed_at, "consumed_reason": signal.consumed_reason,
        "rejected_reason": signal.rejected_reason, "superseded_by_id": signal.superseded_by_id,
    }


def list_signals(
    db: Session, user_id: int, *, status: str | None = None, limit: int = 30, offset: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    query = select(QuantSignal).where(QuantSignal.user_id == user_id)
    if status:
        if status not in SIGNAL_STATUSES:
            raise ValueError("unsupported signal status filter")
        query = query.where(QuantSignal.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(QuantSignal.generated_at.desc(), QuantSignal.id.desc()).limit(limit).offset(offset)
    )
    moment = _utc(now or _now())
    return {
        "items": [signal_payload(db, row, now=moment) for row in rows],
        "total": total, "limit": limit, "offset": offset, "server_time": moment.isoformat(),
    }


def get_signal(db: Session, user_id: int, signal_id: int) -> QuantSignal | None:
    return db.scalar(select(QuantSignal).where(
        QuantSignal.id == signal_id, QuantSignal.user_id == user_id,
    ))


def list_signal_runs(db: Session, user_id: int, *, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    query = select(QuantSignalRun).where(QuantSignalRun.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(QuantSignalRun.created_at.desc(), QuantSignalRun.id.desc()).limit(limit).offset(offset)
    )
    return {
        "items": [
            {
                "id": row.id, "deployment_id": row.deployment_id, "instrument_id": row.instrument_id,
                "interval": row.interval, "boundary": row.boundary, "status": row.status,
                "reason": row.reason, "feature_as_of": row.feature_as_of,
                "feature_available_at": row.feature_available_at, "lag_seconds": row.lag_seconds,
                "retries": row.retries, "signal_id": row.signal_id, "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total, "limit": limit, "offset": offset,
    }


def deployment_payload(db: Session, deployment: QuantStrategyDeployment) -> dict[str, Any]:
    instrument = db.get(CryptoInstrument, deployment.instrument_id)
    active_signal = db.scalar(
        select(QuantSignal).where(
            QuantSignal.deployment_id == deployment.id, QuantSignal.status == "generated",
        ).order_by(QuantSignal.id.desc()).limit(1)
    )
    last_signal = db.scalar(
        select(QuantSignal).where(QuantSignal.deployment_id == deployment.id)
        .order_by(QuantSignal.decision_time.desc(), QuantSignal.id.desc()).limit(1)
    )
    last_run = db.scalar(
        select(QuantSignalRun).where(QuantSignalRun.deployment_id == deployment.id)
        .order_by(QuantSignalRun.created_at.desc(), QuantSignalRun.id.desc()).limit(1)
    )
    return {
        "id": deployment.id, "environment": deployment.environment, "status": deployment.status,
        "strategy_key": deployment.strategy_key, "strategy_version": deployment.strategy_version,
        "instrument_id": deployment.instrument_id,
        "instrument_symbol": instrument.provider_symbol if instrument else None,
        "interval": deployment.interval, "target_exposure": str(deployment.target_exposure),
        "paused_at": deployment.paused_at, "pause_reason": deployment.pause_reason,
        "created_at": deployment.created_at, "updated_at": deployment.updated_at,
        "active_signal_id": active_signal.id if active_signal else None,
        "last_signal": (
            {"id": last_signal.id, "target_exposure": str(last_signal.target_exposure),
             "status": last_signal.status, "decision_time": last_signal.decision_time}
            if last_signal else None
        ),
        "last_run": (
            {"id": last_run.id, "status": last_run.status, "reason": last_run.reason,
             "boundary": last_run.boundary, "created_at": last_run.created_at}
            if last_run else None
        ),
    }


def manual_generation_cooldown(db: Session, *, seconds: int = 60) -> QuantSignalRun | None:
    """Most recent run inside the cooldown window, if any."""

    cutoff = _now() - timedelta(seconds=seconds)
    return db.scalar(
        select(QuantSignalRun).where(QuantSignalRun.created_at > cutoff)
        .order_by(QuantSignalRun.created_at.desc()).limit(1)
    )
