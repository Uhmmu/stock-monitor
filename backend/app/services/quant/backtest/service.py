"""Persisted, user-owned adapter around the pure crypto backtest engine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    BacktestEquityPoint,
    BacktestRun,
    BacktestTrade,
    CryptoInstrument,
    QuantFeatureValue,
    QuantStrategyDefinition,
    User,
)
from app.services.quant.backtest.contracts import BacktestConfig, BarEvent, InstrumentSpec
from app.services.quant.backtest.engine import BacktestCancelled, run_backtest
from app.services.quant.backtest.strategies import get_strategy
from app.services.quant.features import ensure_registry, feature_status
from app.services.quant.registry import STRATEGY_REGISTRY, canonical_hash, feature_set_definition, validate_parameters


ACTIVE_STATUSES = ("pending", "running", "cancel_requested")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
ALLOWED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ADAUSDT")
INTERVALS = ("1h", "4h", "1d")
MAX_DAYS = 365
MAX_EVENTS = 30_000
MIN_BARS = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return value.astimezone(UTC)


def _db_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _funding_at_boundary(values: list[QuantFeatureValue], index: int, boundary: datetime) -> str:
    """Use a realized funding event once, at the boundary when it became known."""
    if index == 0:
        return "0"
    funding = (values[index - 1].payload.get("funding") or {})
    funding_time = funding.get("funding_time")
    if funding_time is None:
        return "0"
    observed = funding_time if isinstance(funding_time, datetime) else datetime.fromisoformat(str(funding_time).replace("Z", "+00:00"))
    return str(funding.get("funding_rate") or "0") if _db_utc(observed) == _db_utc(boundary) else "0"


def _instruments(db: Session, ids: list[int] | None = None) -> list[CryptoInstrument]:
    query = select(CryptoInstrument).where(
        CryptoInstrument.market == "usdm_futures",
        CryptoInstrument.kind == "perpetual",
        CryptoInstrument.status == "trading",
        CryptoInstrument.provider_symbol.in_(ALLOWED_SYMBOLS),
    )
    if ids is not None:
        query = query.where(CryptoInstrument.id.in_(ids))
    return list(db.scalars(query.order_by(CryptoInstrument.provider_symbol)))


def definitions_payload(db: Session) -> dict[str, Any]:
    rows = ensure_registry(db)
    db.commit()
    return {
        "strategies": [
            {
                "key": definition.key,
                "version": definition.version,
                "label": definition.name,
                "description": definition.description,
                "parameters": _json(definition.parameter_schema),
                "config_hash": definition.config_hash,
            }
            for definition in STRATEGY_REGISTRY.values()
        ],
        "feature_set": feature_set_definition().as_dict(),
        "instruments": [
            {
                "id": row.id,
                "provider_symbol": row.provider_symbol,
                "display_label": f"{row.provider_symbol.removesuffix('USDT')}/USDT · Binance · Perpetual",
                "kind": row.kind,
                "venue": row.venue,
            }
            for row in _instruments(db)
        ],
        "intervals": list(INTERVALS),
        "defaults": {
            "target_exposure": 1.0,
            "initial_capital": 100000,
            "leverage": 1,
            "taker_fee_bps": 5,
            "spread_bps": 2,
            "slippage_bps": 2,
            "split_mode": "full",
        },
        "limits": {"max_instruments": 3, "max_days": MAX_DAYS, "max_events": MAX_EVENTS},
    }


def features_payload(db: Session) -> dict[str, Any]:
    return feature_status(db)


def _select_feature_rows(
    db: Session, *, instrument_ids: list[int], interval: str, start_at: datetime, end_at: datetime,
) -> dict[int, list[QuantFeatureValue]]:
    rows = list(db.scalars(
        select(QuantFeatureValue)
        .where(
            QuantFeatureValue.instrument_id.in_(instrument_ids),
            QuantFeatureValue.interval == interval,
            QuantFeatureValue.as_of >= start_at,
            QuantFeatureValue.as_of <= end_at,
            QuantFeatureValue.available_at <= QuantFeatureValue.as_of,
        )
        .order_by(QuantFeatureValue.instrument_id, QuantFeatureValue.as_of, QuantFeatureValue.id)
    ))
    latest: dict[tuple[int, datetime], QuantFeatureValue] = {}
    for row in rows:
        latest[(row.instrument_id, row.as_of)] = row
    grouped = {
        instrument_id: sorted(
            (row for (iid, _), row in latest.items() if iid == instrument_id),
            key=lambda row: row.as_of,
        )
        for instrument_id in instrument_ids
    }
    if any(len(values) < MIN_BARS for values in grouped.values()):
        counts = {str(key): len(value) for key, value in grouped.items()}
        raise ValueError(f"数据不足：每个标的至少需要 {MIN_BARS} 个完整特征点；当前 {counts}")
    timestamps = [[row.as_of for row in grouped[instrument_id]] for instrument_id in instrument_ids]
    if any(values != timestamps[0] for values in timestamps[1:]):
        raise ValueError("所选标的特征时间轴不完整或不一致，请先补齐数据")
    if sum(map(len, grouped.values())) > MAX_EVENTS:
        raise ValueError(f"回测输入超过 {MAX_EVENTS} 个事件点")
    return grouped


def create_run(
    db: Session,
    *,
    user_id: int,
    strategy_key: str,
    instrument_ids: list[int],
    interval: str,
    start_at: datetime,
    end_at: datetime,
    target_exposure: float,
    initial_capital: Decimal,
    leverage: Decimal,
    taker_fee_bps: Decimal,
    spread_bps: Decimal,
    slippage_bps: Decimal,
    split_mode: str,
) -> BacktestRun:
    if strategy_key not in STRATEGY_REGISTRY:
        raise ValueError("unknown strategy")
    parameters = validate_parameters(strategy_key, {"target_exposure": target_exposure})
    if interval not in INTERVALS:
        raise ValueError("unsupported interval")
    start_at, end_at = _aware(start_at, "start_at"), _aware(end_at, "end_at")
    if start_at >= end_at or end_at - start_at > timedelta(days=MAX_DAYS):
        raise ValueError("回测窗口必须为正且不超过 365 天")
    if not 1 <= len(set(instrument_ids)) <= 3:
        raise ValueError("请选择 1–3 个不重复标的")
    if not Decimal("1000") <= initial_capital <= Decimal("1000000"):
        raise ValueError("initial_capital must be between 1000 and 1000000")
    if not Decimal("1") <= leverage <= Decimal("3"):
        raise ValueError("leverage must be between 1 and 3")
    if not (Decimal("0") <= taker_fee_bps <= Decimal("100") and Decimal("0") <= spread_bps <= Decimal("100") and Decimal("0") <= slippage_bps <= Decimal("200")):
        raise ValueError("cost assumptions are outside supported bounds")
    if split_mode not in ("full", "60_20_20"):
        raise ValueError("unsupported split_mode")
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise ValueError("unknown user")
    if db.scalar(select(BacktestRun.id).where(BacktestRun.user_id == user_id, BacktestRun.status.in_(ACTIVE_STATUSES)).limit(1)):
        raise RuntimeError("当前已有运行中的回测")

    registry = ensure_registry(db)
    instruments = _instruments(db, list(set(instrument_ids)))
    if len(instruments) != len(set(instrument_ids)):
        raise ValueError("标的必须是 BTC/ETH/ADA 的 active Binance USD-M perpetual")
    ordered_ids = [row.id for row in instruments]
    grouped = _select_feature_rows(
        db, instrument_ids=ordered_ids, interval=interval, start_at=start_at, end_at=end_at,
    )
    feature_ids = {str(key): [row.id for row in values] for key, values in grouped.items()}
    input_hashes = [row.input_hash for key in ordered_ids for row in grouped[key]]
    backfilled = sum(
        int(row.created_at is not None and _db_utc(row.created_at) > _db_utc(row.available_at))
        for key in ordered_ids for row in grouped[key]
    )
    total = len(input_hashes)
    manifest = {
        "version": "crypto-backtest-manifest-v1",
        "source_causal_version": "source_causal_v1",
        "ingestion_realism": False,
        "backfill_ratio": backfilled / total if total else 0,
        "feature_value_ids": feature_ids,
        "instrument_ids": ordered_ids,
        "symbols": [row.provider_symbol for row in instruments],
        "interval": interval,
        "window_start": start_at.isoformat(),
        "window_end": end_at.isoformat(),
    }
    definition: QuantStrategyDefinition = registry["strategies"][strategy_key]
    data_hash = canonical_hash(input_hashes)
    feature_hash = canonical_hash(feature_ids)
    config = {
        "leverage": str(leverage), "taker_fee_bps": str(taker_fee_bps),
        "spread_bps": str(spread_bps), "slippage_bps": str(slippage_bps),
        "maintenance_margin_ratio": "0.005", "split_mode": split_mode,
    }
    run = BacktestRun(
        user_id=user_id,
        strategy_definition_id=definition.id,
        status="pending",
        interval=interval,
        window_start=start_at,
        window_end=end_at,
        parameters=_json(parameters),
        config=config,
        manifest=manifest,
        manifest_hash=canonical_hash({"manifest": manifest, "parameters": parameters, "config": config}),
        data_hash=data_hash,
        feature_hash=feature_hash,
        code_hash=canonical_hash({"strategy": definition.config_hash, "feature": registry["feature_set"].config_hash}),
        initial_capital=initial_capital,
        seed=0,
        warnings=["BACKFILLED_AFTER_EVENT_TIME", "INGESTION_REALISM_FALSE"] if backfilled else ["INGESTION_REALISM_FALSE"],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_run(db: Session, run_id: int) -> BacktestRun:
    run = db.get(BacktestRun, run_id)
    if run is None or run.status != "pending":
        return run
    now = _now()
    claimed = db.execute(
        update(BacktestRun)
        .where(BacktestRun.id == run_id, BacktestRun.status == "pending")
        .values(status="running", started_at=now, heartbeat_at=now)
    ).rowcount
    db.commit()
    if not claimed:
        db.refresh(run)
        return run
    db.refresh(run)
    try:
        manifest = run.manifest or {}
        feature_ids = [item for values in manifest["feature_value_ids"].values() for item in values]
        rows = list(db.scalars(select(QuantFeatureValue).where(QuantFeatureValue.id.in_(feature_ids))))
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(feature_ids):
            raise ValueError("frozen feature input is missing")
        instruments = list(db.scalars(select(CryptoInstrument).where(CryptoInstrument.id.in_(manifest["instrument_ids"]))))
        instrument_map = {row.id: row for row in instruments}
        specs, bars = [], {}
        for instrument_id in manifest["instrument_ids"]:
            instrument = instrument_map[instrument_id]
            specs.append(InstrumentSpec(
                instrument_id=instrument.id,
                symbol=instrument.provider_symbol,
                tick_size=instrument.tick_size or Decimal("0.0001"),
                step_size=instrument.step_size or Decimal("0.001"),
                min_notional=instrument.min_notional or Decimal("0"),
            ))
            values = [by_id[item] for item in manifest["feature_value_ids"][str(instrument_id)]]
            interval_delta = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}[run.interval]
            bars[instrument_id] = [BarEvent(
                instrument_id=instrument_id,
                timestamp=row.as_of,
                open=row.payload["bar"]["open"], high=row.payload["bar"]["high"],
                low=row.payload["bar"]["low"], close=row.payload["bar"]["close"],
                volume=row.payload["bar"].get("base_volume") or "0",
                funding_rate=_funding_at_boundary(values, index, row.as_of - interval_delta),
                features={key: value for key, value in row.payload.items() if isinstance(value, (int, float, str)) and value is not None},
            ) for index, row in enumerate(values)]
        exposure = Decimal(str(run.parameters["target_exposure"]))
        base_strategy = get_strategy(instrument_map and db.get(QuantStrategyDefinition, run.strategy_definition_id).strategy_key)
        strategy = lambda *args: base_strategy(*args) * exposure
        cfg = BacktestConfig(
            initial_capital=run.initial_capital, interval=run.interval,
            leverage=run.config["leverage"], strategy_name=db.get(QuantStrategyDefinition, run.strategy_definition_id).strategy_key,
            taker_fee_bps=run.config["taker_fee_bps"], full_spread_bps=run.config["spread_bps"],
            slippage_bps=run.config["slippage_bps"], seed=run.seed,
        )
        def progress(index: int, _timestamp: datetime) -> bool:
            if index % 100:
                return True
            db.expire(run)
            db.refresh(run)
            if run.status == "cancel_requested":
                return False
            run.heartbeat_at = _now()
            db.commit()
            return True

        result = run_backtest(specs, bars, cfg, strategy=strategy, progress=progress)
        if run.status == "cancel_requested":
            run.status = "cancelled"
            run.completed_at = _now()
            db.commit()
            return run
        db.execute(delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id))
        db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run.id))
        for point in result.equity:
            db.add(BacktestEquityPoint(
                run_id=run.id, timestamp=point.timestamp, nav=point.nav, cash=point.cash,
                gross_exposure=point.gross_notional, drawdown=point.drawdown,
            ))
        for trade in result.trades:
            fill_time = trade.timestamp - interval_delta
            db.add(BacktestTrade(
                run_id=run.id, instrument_id=int(trade.instrument_id),
                decision_time=fill_time, fill_time=fill_time,
                side=trade.side, quantity=trade.quantity, price=trade.price, fee=trade.fee,
                slippage=trade.slippage_cost, funding=Decimal("0"), realized_pnl=trade.realized_pnl,
                reason=trade.action, status="filled",
            ))
        metrics = _json(dict(result.metrics))
        if run.config.get("split_mode") == "60_20_20":
            metrics["segments"] = _json(dict(result.segments))
        metrics["reject_details"] = _json([row.to_dict() for row in result.rejects])
        metrics["liquidation_details"] = _json([row.to_dict() for row in result.liquidations])
        run.metrics = metrics
        run.result_hash = result.result_hash
        run.status = "completed"
        run.completed_at = _now()
        run.heartbeat_at = _now()
        db.commit()
        db.refresh(run)
        return run
    except BacktestCancelled:
        db.rollback()
        run = db.get(BacktestRun, run_id)
        if run is not None:
            db.execute(delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id))
            db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run.id))
            run.status = "cancelled"
            run.completed_at = _now()
            db.commit()
        return run
    except Exception as exc:
        db.rollback()
        run = db.get(BacktestRun, run_id)
        if run is not None:
            db.execute(delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id))
            db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run.id))
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = _now()
            db.commit()
        raise


def run_payload(db: Session, run: BacktestRun) -> dict[str, Any]:
    strategy = db.get(QuantStrategyDefinition, run.strategy_definition_id)
    return {
        "id": run.id, "status": run.status, "strategy_key": strategy.strategy_key if strategy else None,
        "strategy_version": strategy.version if strategy else None, "instrument_ids": (run.manifest or {}).get("instrument_ids", []),
        "interval": run.interval, "start_at": run.window_start, "end_at": run.window_end,
        "parameters": run.parameters, "config": run.config, "manifest": run.manifest,
        "manifest_hash": run.manifest_hash, "data_hash": run.data_hash, "feature_hash": run.feature_hash,
        "code_hash": run.code_hash, "result_hash": run.result_hash, "seed": run.seed,
        "metrics": run.metrics, "warnings": run.warnings, "error": run.error_message,
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at,
    }


def list_runs(db: Session, user_id: int, limit: int, offset: int) -> dict[str, Any]:
    query = select(BacktestRun).where(BacktestRun.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(BacktestRun.created_at.desc()).limit(limit).offset(offset))
    return {"items": [run_payload(db, row) for row in rows], "total": total, "limit": limit, "offset": offset}


def owned_run(db: Session, user_id: int, run_id: int) -> BacktestRun | None:
    return db.scalar(select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user_id))


def cancel_run(db: Session, run: BacktestRun) -> BacktestRun:
    if run.status == "pending":
        run.status, run.completed_at = "cancelled", _now()
    elif run.status == "running":
        run.status = "cancel_requested"
    db.commit()
    return run


def recover_stale_runs(db: Session, *, older_than: timedelta = timedelta(minutes=10)) -> int:
    cutoff = _now() - older_than
    rows = list(db.scalars(select(BacktestRun).where(or_(
        and_(BacktestRun.status == "pending", BacktestRun.requested_at < cutoff),
        and_(
            BacktestRun.status.in_(("running", "cancel_requested")),
            BacktestRun.heartbeat_at < cutoff,
        ),
    ))))
    for run in rows:
        db.execute(delete(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id))
        db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run.id))
        run.status = "cancelled" if run.status == "cancel_requested" else "failed"
        run.error_message = None if run.status == "cancelled" else "worker heartbeat timed out"
        run.completed_at = _now()
    if rows:
        db.commit()
    return len(rows)


def rerun(db: Session, run: BacktestRun) -> BacktestRun:
    if run.status != "completed":
        raise ValueError("only completed runs can be replayed")
    if db.scalar(select(BacktestRun.id).where(BacktestRun.user_id == run.user_id, BacktestRun.status.in_(ACTIVE_STATUSES)).limit(1)):
        raise RuntimeError("当前已有运行中的回测")
    clone = BacktestRun(
        user_id=run.user_id, strategy_definition_id=run.strategy_definition_id, rerun_of_id=run.id,
        status="pending", interval=run.interval, window_start=run.window_start, window_end=run.window_end,
        parameters=run.parameters, config=run.config, manifest=run.manifest, manifest_hash=run.manifest_hash,
        data_hash=run.data_hash, feature_hash=run.feature_hash, code_hash=run.code_hash,
        initial_capital=run.initial_capital, seed=run.seed, warnings=run.warnings,
    )
    db.add(clone); db.commit(); db.refresh(clone)
    return clone
