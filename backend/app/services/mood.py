"""Deterministic AI Mood engine.

The engine is deliberately a database read model.  It never calls a market,
news, options, or language-model provider.  Every source is filtered to the
requested trading date before it is adapted into a bounded signal, and missing
data remains missing instead of becoming a neutral score.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    HistoricalPrice,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseSnapshot,
    MoodSnapshot,
    NewsItem,
    OptionsSnapshot,
    Security,
    StockProfile,
    TechnicalAnalysis,
    WatchlistItem,
)
from app.services.industry_pulse.calculation import calculate_etf_metrics


CALCULATION_VERSION = "mood_v1"
MOOD_CALCULATION_VERSION = CALCULATION_VERSION

MOOD_STATES = (
    "DORMANT",
    "EARLY_IMPROVEMENT",
    "ACCUMULATION",
    "EXPANSION",
    "LEADERSHIP",
    "CROWDED",
    "DISTRIBUTION",
    "DETERIORATION",
    "BREAKDOWN",
    "INSUFFICIENT_DATA",
)
STATES = MOOD_STATES
SCOPE_TYPES = ("market", "sector", "ai_chain", "watchlist")
DIVERGENCE_TYPES = (
    "PRICE_BREADTH",
    "PRICE_RS",
    "PRICE_OPTIONS",
    "PRICE_NEWS",
    "NEWS_OPTIONS",
    "TECHNICAL_BREADTH",
)

_BASE_WEIGHTS = {
    "price": 0.22,
    "technical": 0.15,
    "breadth": 0.20,
    "relative_strength": 0.13,
    "options": 0.12,
    "news": 0.12,
    "volume": 0.06,
    "composite": 0.08,
}
_EVENT_HALF_LIFE = {
    "earnings": 14.0,
    "guidance": 14.0,
    "fda": 14.0,
    "regulatory": 21.0,
    "regulation": 21.0,
    "merger": 21.0,
    "acquisition": 21.0,
    "bankruptcy": 30.0,
    "lawsuit": 21.0,
    "dividend": 10.0,
    "macro": 7.0,
}


class MoodSignal(BaseModel):
    """Stable signal DTO used in snapshots and report payloads."""

    model_config = ConfigDict(extra="allow")

    signal_id: str
    source: str
    scope_type: str
    scope_key: str
    category: str
    metric: str
    as_of: date | datetime | str
    source_as_of: date | datetime | str | None = None
    direction: str = "unknown"
    normalized_score: float | None = None
    status: str = "UNAVAILABLE"
    trend: str | None = None
    percentile: float | None = None
    zscore: float | None = None
    anomaly: str | None = None
    freshness: float | str | None = None
    quality: float | None = None
    confidence: float | str | None = None
    coverage: float | None = None
    missing_reason: str | None = None
    evidence_refs: list[str] = []
    evidence: dict[str, Any] = {}
    raw_evidence: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        return _safe(self.model_dump(mode="json"))


# A short alias is useful to callers that want the contract without knowing
# the implementation name; it is the same Pydantic model, not a hierarchy.
Signal = MoodSignal


def _safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _safe(value.model_dump(mode="json"))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _safe(value.item())
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float | None:
    number = _num(value)
    return max(low, min(high, number)) if number is not None else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _hash(value: Any) -> str:
    encoded = json.dumps(_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _direction(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 55:
        return "bullish"
    if score <= 45:
        return "bearish"
    return "neutral"


def _return_score(value: Any) -> float | None:
    number = _num(value)
    return 50.0 + max(-20.0, min(20.0, number)) / 20.0 * 50.0 if number is not None else None


def _as_score(value: Any) -> float | None:
    number = _num(value)
    return max(0.0, min(100.0, number)) if number is not None else None


def _quality(value: Any, default: float = 0.0) -> float:
    number = _num(value)
    if number is not None:
        return max(0.0, min(1.0, number))
    text = str(value or "").upper()
    return {"HIGH": .9, "MEDIUM": .65, "LOW": .35, "READY": .8, "PARTIAL": .5, "DEGRADED": .5}.get(text, default)


def _freshness(as_of: date, observed: Any) -> tuple[float, str]:
    observed_day = _date(observed)
    if observed_day is None:
        return 0.0, "UNAVAILABLE"
    age = max(0, (as_of - observed_day).days)
    if age <= 1:
        return 1.0, "FRESH"
    if age <= 3:
        return .5, "STALE"
    return 0.0, "EXPIRED"


def _signal(
    *,
    signal_id: str,
    source: str,
    scope_type: str,
    scope_key: str,
    category: str,
    metric: str,
    as_of: date,
    score: float | None = None,
    status: str = "READY",
    observed: Any = None,
    trend: str | None = None,
    percentile: Any = None,
    zscore: Any = None,
    anomaly: str | None = None,
    quality: Any = None,
    confidence: Any = None,
    coverage: Any = None,
    missing_reason: str | None = None,
    evidence_refs: Iterable[str] = (),
    evidence: Mapping[str, Any] | None = None,
    raw_evidence: Any = None,
) -> MoodSignal:
    freshness, freshness_status = _freshness(as_of, observed)
    status = str(status or "UNAVAILABLE").upper()
    if status == "READY" and freshness_status in {"EXPIRED", "UNAVAILABLE"}:
        status = "STALE" if freshness_status == "EXPIRED" else "UNAVAILABLE"
    if status == "PARTIAL" and freshness_status == "UNAVAILABLE":
        status = "PARTIAL"
    quality_value = _quality(quality, .0)
    coverage_value = _clamp(coverage, 0.0, 1.0)
    confidence_value = _num(confidence)
    if confidence_value is None:
        confidence_value = min(quality_value, coverage_value if coverage_value is not None else quality_value)
    return MoodSignal(
        signal_id=signal_id,
        source=source,
        scope_type=scope_type,
        scope_key=scope_key,
        category=category,
        metric=metric,
        as_of=as_of,
        source_as_of=_safe(observed),
        direction=_direction(score),
        normalized_score=_as_score(score),
        status=status,
        trend=trend,
        percentile=_num(percentile),
        zscore=_num(zscore),
        anomaly=anomaly,
        freshness=freshness,
        quality=quality_value,
        confidence=_clamp(confidence_value, 0.0, 1.0),
        coverage=coverage_value,
        missing_reason=missing_reason,
        evidence_refs=list(evidence_refs),
        evidence={"freshness_status": freshness_status, **dict(evidence or {})},
        raw_evidence=_safe(raw_evidence),
    )


def _history_rows(db: Session, symbol: str, as_of: date) -> list[HistoricalPrice]:
    try:
        return list(db.scalars(
            select(HistoricalPrice)
            .where(HistoricalPrice.symbol == symbol.upper(), HistoricalPrice.date <= as_of)
            .order_by(HistoricalPrice.date.asc())
        ).all())
    except Exception:
        return []


def _metrics(db: Session, symbol: str, as_of: date) -> dict[str, Any]:
    rows = _history_rows(db, symbol, as_of)
    if not rows:
        return {"status": "unavailable", "data_quality": 0.0, "coverage": 0.0, "as_of": None, "symbol": symbol.upper()}
    benchmark = rows if symbol.upper() == "SPY" else _history_rows(db, "SPY", as_of)
    metrics = calculate_etf_metrics(rows, benchmark_rows=benchmark, benchmark_name="SPY", as_of=as_of)
    metrics["symbol"] = symbol.upper()
    return metrics


def _history_signals(db: Session, scope_type: str, scope_key: str, symbol: str, as_of: date) -> list[MoodSignal]:
    metric = _metrics(db, symbol, as_of)
    observed = metric.get("as_of")
    quality = metric.get("data_quality", 0.0)
    coverage = metric.get("coverage", 0.0)
    if metric.get("status") == "unavailable" or observed is None:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:price_return_20d",
            source="historical_price", scope_type=scope_type, scope_key=scope_key,
            category="price", metric="return_20d", as_of=as_of, status="UNAVAILABLE",
            quality=0, coverage=coverage, observed=None, missing_reason=f"historical_price_missing:{symbol}",
            evidence={"symbol": symbol},
        )]
    outputs: list[MoodSignal] = []
    outputs.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:price_return_20d", source="historical_price",
        scope_type=scope_type, scope_key=scope_key, category="price", metric="return_20d",
        as_of=as_of, score=_return_score(metric.get("return_20d")), status="READY" if metric.get("return_20d") is not None else "PARTIAL",
        observed=observed, trend="up" if (metric.get("return_20d") or 0) > 0 else "down" if (metric.get("return_20d") or 0) < 0 else "flat",
        quality=quality, confidence=quality, coverage=coverage,
        missing_reason=None if metric.get("return_20d") is not None else "return_20d_missing",
        evidence_refs=[f"historical_price:{symbol}"], evidence={"symbol": symbol, "return_20d": metric.get("return_20d"), "bars": metric.get("bars")},
        raw_evidence={"return_5d": metric.get("return_5d"), "return_20d": metric.get("return_20d"), "return_60d": metric.get("return_60d"), "as_of": observed},
    ))
    rs_score = _return_score(metric.get("rs_20d"))
    outputs.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:relative_strength", source="historical_price",
        scope_type=scope_type, scope_key=scope_key, category="relative_strength", metric="rs_20d",
        as_of=as_of, score=rs_score, status="READY" if rs_score is not None else "PARTIAL", observed=observed,
        trend="improving" if (metric.get("rs_ratio_slope") or 0) > 0 else "weakening" if (metric.get("rs_ratio_slope") or 0) < 0 else "flat",
        quality=quality, confidence=quality, coverage=coverage,
        missing_reason=None if rs_score is not None else "benchmark_or_rs_missing",
        evidence_refs=[f"historical_price:{symbol}", "historical_price:SPY"],
        evidence={"benchmark": metric.get("relative_strength_benchmark"), "rs_20d": metric.get("rs_20d"), "rs_ratio_slope": metric.get("rs_ratio_slope")},
        raw_evidence={"rs_20d": metric.get("rs_20d"), "rs_breakout": metric.get("rs_breakout")},
    ))
    trend_score = (metric.get("scores") or {}).get("trend")
    outputs.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:trend", source="historical_price",
        scope_type=scope_type, scope_key=scope_key, category="technical", metric="trend_score",
        as_of=as_of, score=trend_score, status="READY" if trend_score is not None else "PARTIAL", observed=observed,
        trend=metric.get("volatility_state"), quality=quality, confidence=quality, coverage=coverage,
        missing_reason=None if trend_score is not None else "trend_score_missing",
        evidence_refs=[f"historical_price:{symbol}"], evidence={"trend_score": trend_score, "ma": metric.get("ma")},
        raw_evidence={"return_60d": metric.get("return_60d"), "ma20_slope": metric.get("ma20_slope"), "volatility_state": metric.get("volatility_state")},
    ))
    volume_score = (metric.get("scores") or {}).get("volume")
    if volume_score is not None:
        outputs.append(_signal(
            signal_id=f"{scope_type}:{scope_key}:volume", source="historical_price",
            scope_type=scope_type, scope_key=scope_key, category="volume", metric="volume_score",
            as_of=as_of, score=volume_score, status="READY", observed=observed, percentile=metric.get("volume_percentile"),
            zscore=metric.get("volume_z"), quality=quality, confidence=quality, coverage=coverage,
            evidence_refs=[f"historical_price:{symbol}"], evidence={"relative_volume": metric.get("relative_volume")},
        ))
    return outputs


def _node_snapshot(db: Session, node_id: int, as_of: date) -> IndustryPulseSnapshot | None:
    try:
        return db.scalar(
            select(IndustryPulseSnapshot)
            .where(IndustryPulseSnapshot.node_id == node_id, IndustryPulseSnapshot.trading_date <= as_of)
            .order_by(IndustryPulseSnapshot.trading_date.desc())
            .limit(1)
        )
    except Exception:
        return None


def _node_signals(db: Session, scope_type: str, scope_key: str, node_id: int, as_of: date) -> list[MoodSignal]:
    row = _node_snapshot(db, node_id, as_of)
    if row is None:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:industry_pulse", source="industry_pulse",
            scope_type=scope_type, scope_key=scope_key, category="breadth", metric="pulse", as_of=as_of,
            status="UNAVAILABLE", missing_reason="industry_pulse_snapshot_missing", quality=0, coverage=0,
        )]
    metrics = row.metrics_json or {}
    basket = metrics.get("basket") or {}
    quality = _quality(row.data_quality, 0.0)
    coverage = _clamp(row.coverage_quality, 0.0, 1.0) or 0.0
    confidence = _clamp(row.confidence, 0.0, 1.0) or 0.0
    common = {
        "source": "industry_pulse", "scope_type": scope_type, "scope_key": scope_key,
        "as_of": as_of, "observed": row.trading_date, "quality": quality,
        "confidence": confidence, "coverage": coverage,
        "evidence_refs": [f"industry_pulse:{row.node_id}:{row.trading_date}"],
    }
    signals: list[MoodSignal] = []
    for category, metric, value in (
        ("composite", "pulse", row.pulse),
        ("breadth", "breadth_score", row.breadth_score if row.breadth_score is not None else basket.get("breadth_score")),
        ("relative_strength", "relative_strength_score", row.relative_strength_score),
        ("technical", "trend_score", row.trend_score),
        ("volume", "volume_score", row.volume_score),
        ("technical", "momentum_score", row.momentum_score),
    ):
        status = "READY" if _num(value) is not None else "PARTIAL"
        signals.append(_signal(
            signal_id=f"{scope_type}:{scope_key}:{metric}", metric=metric, category=category,
            score=value, status=status, missing_reason=None if _num(value) is not None else f"{metric}_missing",
            raw_evidence={"node_id": row.node_id, "trading_date": row.trading_date, "mood": row.mood, "regime": row.regime},
            evidence={"proxy_mode": metrics.get("proxy_mode"), "data_quality": row.data_quality, "coverage_quality": row.coverage_quality},
            **common,
        ))
    return signals


def _technical_signals(db: Session, scope_type: str, scope_key: str, symbol: str, as_of: date) -> list[MoodSignal]:
    try:
        row = db.get(TechnicalAnalysis, symbol.upper())
    except Exception:
        row = None
    data_through = _date(row.data_through) if row else None
    if row is None or row.status != "ready" or not row.analysis or data_through is None or data_through > as_of:
        reason = "technical_analysis_missing" if row is None else "technical_analysis_after_as_of" if data_through and data_through > as_of else "technical_analysis_not_ready"
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:technical_analysis", source="technical_analysis",
            scope_type=scope_type, scope_key=scope_key, category="technical", metric="weekly_trend", as_of=as_of,
            status="UNAVAILABLE", observed=data_through, quality=0, coverage=0, missing_reason=reason,
            evidence={"symbol": symbol},
        )]
    analysis = row.analysis or {}
    indicators = analysis.get("indicators") or {}
    weekly = str(analysis.get("weeklyTrend") or analysis.get("weekly_trend") or "").lower()
    trend_score = {"bullish": 78.0, "uptrend": 78.0, "bearish": 22.0, "downtrend": 22.0, "neutral": 50.0, "range": 50.0}.get(weekly, None)
    quality = 1.0 if row.status == "ready" else .0
    freshness, _status = _freshness(as_of, data_through)
    return [
        _signal(
            signal_id=f"{scope_type}:{scope_key}:technical_analysis", source="technical_analysis",
            scope_type=scope_type, scope_key=scope_key, category="technical", metric="weekly_trend", as_of=as_of,
            score=trend_score, status="READY" if trend_score is not None else "PARTIAL", observed=data_through,
            trend=weekly or None, quality=quality, confidence=min(quality, freshness), coverage=1.0,
            missing_reason=None if trend_score is not None else "weekly_trend_missing",
            evidence_refs=[f"technical_analysis:{symbol}"], evidence={"symbol": symbol, "data_through": data_through, "analysis_version": row.analysis_version},
            raw_evidence={"weeklyTrend": weekly, "latestClose": analysis.get("latestClose")},
        ),
        _signal(
            signal_id=f"{scope_type}:{scope_key}:technical_rsi", source="technical_analysis",
            scope_type=scope_type, scope_key=scope_key, category="technical", metric="rsi14", as_of=as_of,
            score=indicators.get("rsi14"), status="READY" if indicators.get("rsi14") is not None else "PARTIAL", observed=data_through,
            quality=quality, confidence=min(quality, freshness), coverage=1.0,
            missing_reason=None if indicators.get("rsi14") is not None else "rsi14_missing",
            evidence_refs=[f"technical_analysis:{symbol}"], raw_evidence={"rsi14": indicators.get("rsi14"), "atr14": indicators.get("atr14")},
        ),
    ]


def _option_rows(db: Session, symbols: Iterable[str], as_of: date) -> list[OptionsSnapshot]:
    values = sorted({str(item).upper() for item in symbols if item})
    if not values:
        return []
    try:
        rows = db.scalars(
            select(OptionsSnapshot)
            .where(OptionsSnapshot.symbol.in_(values), OptionsSnapshot.trading_date <= as_of)
            .order_by(OptionsSnapshot.symbol, OptionsSnapshot.trading_date.desc())
        ).all()
    except Exception:
        return []
    selected: dict[str, OptionsSnapshot] = {}
    for row in rows:
        selected.setdefault(row.symbol, row)
    return list(selected.values())


def _options_signals(db: Session, scope_type: str, scope_key: str, symbols: Iterable[str], as_of: date) -> list[MoodSignal]:
    rows = _option_rows(db, symbols, as_of)
    if not rows:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:options", source="options_snapshot",
            scope_type=scope_type, scope_key=scope_key, category="options", metric="options_state", as_of=as_of,
            status="UNAVAILABLE", quality=0, coverage=0, missing_reason="options_snapshot_missing",
        )]
    evidence: list[dict[str, Any]] = []
    quality_values: list[float] = []
    coverage_values: list[float] = []
    observed: list[date] = []
    for row in rows:
        metrics = row.metrics_json or {}
        state = metrics.get("options_state") if isinstance(metrics.get("options_state"), dict) else {}
        bias = str((state.get("bias") or {}).get("status") or metrics.get("options_bias") or "INSUFFICIENT_DATA").upper()
        risk = str((state.get("risk_pricing") or {}).get("status") or metrics.get("term_structure_status") or "INSUFFICIENT_DATA").upper()
        positioning = str((state.get("positioning") or {}).get("status") or "INSUFFICIENT_DATA").upper()
        positioning_raw = (state.get("positioning") or {}).get("raw_metrics") or {}
        activity = (state.get("activity") or {}).get("raw_metrics") or {}
        activity_value = _num(activity.get("percentile"))
        if activity_value is None:
            activity_value = _num(metrics.get("activity_percentile"))
        historical = str((state.get("historical_regime") or {}).get("status") or metrics.get("activity_anomaly") or "").upper()
        quality = _quality(row.quality_score, 0.0)
        coverage = _clamp(row.coverage, 0.0, 1.0) or 0.0
        quality_values.append(quality); coverage_values.append(coverage)
        observed.append(row.trading_date)
        evidence.append({
            "symbol": row.symbol, "trading_date": row.trading_date, "status": row.status,
            "bias": bias, "risk": risk, "positioning": positioning, "positioning_raw": positioning_raw,
            "activity_percentile": activity_value, "historical": historical,
            "quality": quality, "coverage": coverage, "warnings": row.warnings or [],
        })
    if not evidence:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:options", source="options_snapshot",
            scope_type=scope_type, scope_key=scope_key, category="options", metric="options_state", as_of=as_of,
            status="PARTIAL", quality=0, coverage=0, missing_reason="options_state_insufficient",
            evidence={"symbols": list(symbols)},
        )]
    latest = max(observed)
    freshness, freshness_status = _freshness(as_of, latest)
    quality = sum(quality_values) / len(quality_values)
    coverage = sum(coverage_values) / len(coverage_values)
    refs = [f"options_snapshot:{item['symbol']}:{item['trading_date']}" for item in evidence]
    status = "READY" if freshness > 0 else "STALE"
    common = {
        "source": "options_snapshot", "scope_type": scope_type, "scope_key": scope_key, "as_of": as_of,
        "observed": latest, "quality": quality, "confidence": min(quality, freshness), "coverage": coverage,
        "evidence_refs": refs, "evidence": {"freshness_status": freshness_status, "symbols": [item["symbol"] for item in evidence]},
        "raw_evidence": evidence,
    }
    output: list[MoodSignal] = []
    # Bias and activity are descriptive.  They deliberately carry no bullish
    # score: call-heavy does not mean the underlying will rise.
    bias_ready = [item["bias"] for item in evidence if item["bias"] not in {"INSUFFICIENT_DATA", "MIXED"}]
    output.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:options_bias", category="options", metric="bias", score=None,
        status=status if bias_ready else "PARTIAL", missing_reason=None if bias_ready else "options_bias_insufficient", **common,
    ))
    activity_ready = [item["activity_percentile"] for item in evidence if item["activity_percentile"] is not None]
    output.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:options_activity", category="options", metric="activity_percentile", score=None,
        percentile=(sum(activity_ready) / len(activity_ready)) if activity_ready else None,
        status=status if activity_ready else "PARTIAL", missing_reason=None if activity_ready else "options_activity_insufficient_history", **common,
    ))
    positioning_ready = [item for item in evidence if item["positioning"] != "INSUFFICIENT_DATA"]
    output.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:options_positioning", category="options", metric="positioning", score=None,
        status=status if positioning_ready else "PARTIAL",
        missing_reason=None if positioning_ready else "options_positioning_insufficient", **common,
    ))
    risk_ready = [item["risk"] for item in evidence if item["risk"] in {"IV_HIGH", "IV_LOW", "IV_NORMAL"}]
    risk_values = [{"IV_HIGH": 35.0, "IV_LOW": 65.0, "IV_NORMAL": 50.0}[item] for item in risk_ready]
    output.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:options_risk_pricing", category="options", metric="risk_pricing", score=(sum(risk_values) / len(risk_values)) if risk_values else None,
        status=status if risk_values else "PARTIAL", trend="risk_high" if risk_values and sum(risk_values) / len(risk_values) < 45 else "risk_low" if risk_values and sum(risk_values) / len(risk_values) > 55 else "normal",
        missing_reason=None if risk_values else "options_risk_pricing_insufficient", **common,
    ))
    anomaly_ready = [str((item.get("historical") or "")).upper() for item in evidence if item.get("historical")]
    anomaly_values = [35.0 if item in {"HIGH", "EXTREME"} else 50.0 for item in anomaly_ready]
    output.append(_signal(
        signal_id=f"{scope_type}:{scope_key}:options_historical_regime", category="options", metric="historical_regime", score=(sum(anomaly_values) / len(anomaly_values)) if anomaly_values else None,
        anomaly=anomaly_ready[0] if anomaly_ready else None, status=status if anomaly_values else "PARTIAL",
        missing_reason=None if anomaly_values else "options_history_insufficient", **common,
    ))
    return output


def dedupe_news_rows(rows: Iterable[NewsItem]) -> list[NewsItem]:
    """Dedupe by canonical story, then cluster, then provider fingerprint."""

    selected: dict[str, NewsItem] = {}
    for row in rows:
        key = row.canonical_story_id or row.cluster_key or row.fingerprint or f"row:{row.id}"
        current = selected.get(key)
        if current is None:
            selected[key] = row
            continue
        rank = (
            _num(row.quality_score) or 0,
            _num(row.importance_score) or 0,
            _dt(row.published_at or row.found_at) or datetime.min.replace(tzinfo=UTC),
        )
        old_rank = (
            _num(current.quality_score) or 0,
            _num(current.importance_score) or 0,
            _dt(current.published_at or current.found_at) or datetime.min.replace(tzinfo=UTC),
        )
        if rank > old_rank:
            selected[key] = row
    return sorted(selected.values(), key=lambda row: _dt(row.published_at or row.found_at) or datetime.min.replace(tzinfo=UTC), reverse=True)


def _news_values(row: NewsItem) -> tuple[float | None, float | None, str]:
    sentiment = _num(row.sentiment_score)
    if sentiment is None:
        label = str(row.ai_sentiment or "").lower()
        sentiment = {"positive": 1.0, "bullish": 1.0, "negative": -1.0, "bearish": -1.0, "neutral": 0.0}.get(label)
    impact = _num(row.importance_score)
    if impact is None and row.ai_importance is not None:
        impact = max(0.0, min(1.0, float(row.ai_importance) / 100.0))
    if impact is None:
        impact = _num(row.relevance_score)
    event = str(row.ai_event_type or row.news_type or "article").lower()
    return sentiment, max(0.0, min(1.0, impact)) if impact is not None else None, event


def _news_signal(db: Session, scope_type: str, scope_key: str, tickers: Iterable[str], as_of: date) -> list[MoodSignal]:
    ticker_values = {str(item).upper() for item in tickers if item}
    try:
        rows = list(db.scalars(select(NewsItem).order_by(NewsItem.published_at.desc().nullslast(), NewsItem.found_at.desc())).all())
    except Exception:
        rows = []
    filtered: list[NewsItem] = []
    for row in rows:
        timestamp = _dt(row.published_at or row.found_at)
        if timestamp is None or timestamp.date() > as_of:
            continue
        if scope_type == "market":
            if str(row.scope or "").lower() != "market" and str(row.ticker or "").upper() != "__MARKET__":
                continue
        elif str(row.ticker or "").upper() not in ticker_values and not (set(str(item).upper() for item in (row.symbols or [])) & ticker_values):
            continue
        filtered.append(row)
    rows = dedupe_news_rows(filtered)
    if not rows:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:news", source="news_item", scope_type=scope_type, scope_key=scope_key,
            category="news", metric="sentiment_impact", as_of=as_of, status="UNAVAILABLE", quality=0, coverage=0,
            missing_reason="news_snapshot_missing", evidence={"tickers": sorted(ticker_values)},
        )]
    sentiment_total = impact_total = weight_total = 0.0
    sentiment_count = 0
    evidence: list[dict[str, Any]] = []
    latest: datetime | None = None
    current_attention = [row for row in rows if _dt(row.published_at or row.found_at) and (as_of - (_dt(row.published_at or row.found_at) or datetime.now(UTC)).date()).days <= 7]
    prior_attention = [row for row in rows if _dt(row.published_at or row.found_at) and 7 < (as_of - (_dt(row.published_at or row.found_at) or datetime.now(UTC)).date()).days <= 14]
    current_sources = {str(row.source or row.provider or "unknown").lower() for row in current_attention}
    prior_sources = {str(row.source or row.provider or "unknown").lower() for row in prior_attention}
    current_high_impact = sum(1 for row in current_attention if (_news_values(row)[1] or 0) >= .6)
    prior_high_impact = sum(1 for row in prior_attention if (_news_values(row)[1] or 0) >= .6)
    current_attention_value = len(current_attention) + len(current_sources) * .5 + current_high_impact
    prior_attention_value = len(prior_attention) + len(prior_sources) * .5 + prior_high_impact
    for row in rows:
        timestamp = _dt(row.published_at or row.found_at)
        if timestamp is None:
            continue
        latest = max(latest, timestamp) if latest else timestamp
        sentiment, impact, event = _news_values(row)
        age = max(0.0, (as_of - timestamp.date()).days)
        half_life = next((value for key, value in _EVENT_HALF_LIFE.items() if key in event), 3.0)
        decay = 0.5 ** (age / half_life)
        quality = _quality(row.quality_score, .5)
        weight = decay * max(.1, quality)
        if sentiment is not None:
            sentiment_total += sentiment * weight
            sentiment_count += 1
        if impact is not None:
            impact_total += impact * weight
        weight_total += weight
        evidence.append({
            "id": row.id, "story_key": row.canonical_story_id or row.cluster_key or row.fingerprint,
            "ticker": row.ticker, "published_at": timestamp, "event": event,
            "sentiment": sentiment, "impact": impact, "decay": decay,
        })
    if weight_total <= 0 or sentiment_count == 0:
        return [_signal(
            signal_id=f"{scope_type}:{scope_key}:news", source="news_item", scope_type=scope_type, scope_key=scope_key,
            category="news", metric="sentiment_impact", as_of=as_of, status="PARTIAL", observed=latest,
            quality=.35, confidence=.2, coverage=min(1.0, len(rows) / 5), missing_reason="news_sentiment_missing",
            evidence={"deduplicated_count": len(rows)}, raw_evidence=evidence,
        )]
    sentiment = sentiment_total / weight_total
    impact = impact_total / weight_total
    freshness, _freshness_status = _freshness(as_of, latest)
    quality = min(1.0, .45 + min(1.0, len(rows) / 10) * .45)
    coverage = min(1.0, len(rows) / 10)
    attention_status = "READY" if prior_attention_value > 0 and len(prior_attention) >= 3 else "INSUFFICIENT_HISTORY"
    attention_score = None
    attention_trend = None
    if attention_status == "READY":
        ratio = current_attention_value / prior_attention_value if prior_attention_value else 1.0
        attention_score = max(0.0, min(100.0, 50.0 + (ratio - 1.0) * 50.0))
        attention_trend = "rising" if ratio > 1.1 else "falling" if ratio < .9 else "stable"
    attention_signal = _signal(
        signal_id=f"{scope_type}:{scope_key}:news_attention", source="news_item", scope_type=scope_type, scope_key=scope_key,
        category="news", metric="attention", as_of=as_of, score=attention_score, status=attention_status,
        observed=latest, trend=attention_trend, quality=quality, confidence=min(quality, freshness) if attention_score is not None else .2,
        coverage=coverage, missing_reason=None if attention_score is not None else "news_attention_insufficient_history",
        evidence_refs=[f"news_item:{row.id}" for row in rows],
        evidence={"current_unique_events": len(current_attention), "prior_unique_events": len(prior_attention), "current_sources": len(current_sources), "prior_sources": len(prior_sources), "current_high_impact": current_high_impact, "prior_high_impact": prior_high_impact},
        raw_evidence={"current": current_attention_value, "prior": prior_attention_value},
    )
    return [
        _signal(
            signal_id=f"{scope_type}:{scope_key}:news_sentiment", source="news_item", scope_type=scope_type, scope_key=scope_key,
            category="news", metric="sentiment", as_of=as_of, score=50 + sentiment * 50, status="READY" if freshness > 0 else "STALE",
            observed=latest, trend="positive" if sentiment > .1 else "negative" if sentiment < -.1 else "neutral",
            quality=quality, confidence=min(quality, freshness), coverage=coverage,
            missing_reason=None if freshness > 0 else "news_stale", evidence_refs=[f"news_item:{row.id}" for row in rows],
            evidence={"deduplicated_count": len(rows), "sentiment": sentiment, "impact": impact}, raw_evidence=evidence,
        ), attention_signal,
        _signal(
            signal_id=f"{scope_type}:{scope_key}:news_impact", source="news_item", scope_type=scope_type, scope_key=scope_key,
            category="news", metric="impact", as_of=as_of, score=50 + sentiment * 50 * impact, status="READY" if freshness > 0 else "STALE",
            observed=latest, quality=quality, confidence=min(quality, freshness), coverage=coverage,
            evidence_refs=[f"news_item:{row.id}" for row in rows], evidence={"deduplicated_count": len(rows), "sentiment": sentiment, "impact": impact}, raw_evidence={"impact": impact},
        ),
    ]


def _descendant_ids(db: Session, node_id: int) -> set[int]:
    try:
        nodes = list(db.scalars(select(IndustryPulseNode)).all())
    except Exception:
        return {node_id}
    children: dict[int, list[int]] = defaultdict(list)
    for node in nodes:
        if node.parent_id is not None:
            children[node.parent_id].append(node.id)
    result = {node_id}; pending = [node_id]
    while pending:
        current = pending.pop()
        for child in children.get(current, []):
            if child not in result:
                result.add(child); pending.append(child)
    return result


def _node_symbols(db: Session, node_id: int, *, as_of: date | None = None, etf_only: bool = False, exclude_etf: bool = False) -> list[str]:
    node_ids = _descendant_ids(db, node_id)
    try:
        rows = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id.in_(node_ids), IndustryPulseInstrument.enabled.is_(True))).all()
    except Exception:
        return []
    values = []
    cutoff = as_of or date.today()
    for row in rows:
        if row.valid_from and row.valid_from > cutoff:
            continue
        if row.valid_to and row.valid_to < cutoff:
            continue
        if etf_only and row.mapping_type != "etf_proxy":
            continue
        if exclude_etf and row.mapping_type == "etf_proxy":
            continue
        if row.ticker:
            values.append(row.ticker.upper())
    return list(dict.fromkeys(values))


def _scope_specs(db: Session, scopes: set[str] | None) -> list[tuple[str, str, int | None]]:
    requested = {str(item).strip() for item in scopes or [] if str(item).strip()}
    include_all = not requested
    specs: list[tuple[str, str, int | None]] = [("market", "US", None)] if include_all or "market" in requested or "US" in requested else []
    try:
        nodes = list(db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.enabled.is_(True))).all())
    except Exception:
        nodes = []
    for node in nodes:
        scope_type = "sector" if node.taxonomy == "base" and node.level in {"sector", "group", "leaf"} else "ai_chain" if node.taxonomy == "ai" and node.level in {"sector", "group", "leaf"} else None
        if scope_type is None:
            continue
        exact = f"{scope_type}:{node.node_key}"
        if include_all or scope_type in requested or node.node_key in requested or exact in requested:
            specs.append((scope_type, node.node_key, node.id))
    if include_all or "watchlist" in requested:
        try:
            watched = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True)).order_by(WatchlistItem.ticker)).all()
        except Exception:
            watched = []
        specs.extend(("watchlist", row.ticker.upper(), None) for row in watched if row.ticker)
    else:
        for item in requested:
            if item.startswith("watchlist:"):
                specs.append(("watchlist", item.split(":", 1)[1].upper(), None))
    return list(dict.fromkeys(specs))


def _sector_participation_signals(db: Session, as_of: date) -> list[MoodSignal]:
    try:
        nodes = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector", IndustryPulseNode.enabled.is_(True))).all()
    except Exception:
        nodes = []
    rows = [_node_snapshot(db, node.id, as_of) for node in nodes]
    rows = [row for row in rows if row is not None and row.pulse is not None]
    if not rows:
        return [_signal(
            signal_id="market:US:sector_participation", source="industry_pulse", scope_type="market", scope_key="US",
            category="breadth", metric="sector_participation", as_of=as_of, status="UNAVAILABLE", quality=0, coverage=0,
            missing_reason="whole_market_breadth_unavailable:sector_participation_missing",
        )]
    strong = sum(float(row.pulse) >= 60 for row in rows) / len(rows) * 100
    quality = sum(_quality(row.data_quality, 0) for row in rows) / len(rows)
    coverage = sum(_clamp(row.coverage_quality, 0, 1) or 0 for row in rows) / len(rows)
    latest = max(row.trading_date for row in rows)
    return [_signal(
        signal_id="market:US:sector_participation", source="industry_pulse", scope_type="market", scope_key="US",
        category="breadth", metric="sector_participation", as_of=as_of, score=strong, status="PARTIAL", observed=latest,
        quality=quality, confidence=min(.6, quality), coverage=coverage,
        missing_reason="whole_market_breadth_unavailable:sector_participation_only",
        evidence_refs=[f"industry_pulse:{row.node_id}:{row.trading_date}" for row in rows],
        evidence={"strong_sectors": sum(float(row.pulse) >= 60 for row in rows), "eligible_sectors": len(rows), "scope": "sector_participation"},
    )]


def _category_scores(signals: Iterable[MoodSignal]) -> dict[str, float]:
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for signal in signals:
        score = _num(signal.normalized_score)
        if score is None or signal.status not in {"READY", "PARTIAL", "STALE"}:
            continue
        quality = _quality(signal.quality, 0)
        confidence = _quality(signal.confidence, 0)
        coverage = _clamp(signal.coverage, 0, 1) or 0
        freshness = _num(signal.freshness)
        if freshness is None:
            freshness = 0 if str(signal.freshness).upper() in {"EXPIRED", "UNAVAILABLE"} else 1
        weight = _BASE_WEIGHTS.get(signal.category, .08) * quality * confidence * coverage * max(0, min(1, freshness))
        if weight > 0:
            buckets[signal.category].append((score, weight))
    return {category: sum(value * weight for value, weight in values) / sum(weight for _, weight in values) for category, values in buckets.items() if values and sum(weight for _, weight in values) > 0}


def aggregate_signals(signals: Iterable[MoodSignal]) -> dict[str, Any]:
    """Combine signals using quality/confidence/coverage/freshness weights."""

    values = list(signals)
    valid = []
    missing_sources: list[str] = []
    stale_sources: list[str] = []
    supporting: list[dict[str, Any]] = []
    contradicting: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    def evidence_item(signal: MoodSignal, stance: str, weight: float | None = None) -> dict[str, Any]:
        return {
            "stance": stance, "category": signal.category, "message": f"{signal.metric}: {signal.normalized_score}",
            "value": signal.normalized_score, "weight": round(weight, 6) if weight is not None else None,
            "source": signal.source, "signal_id": signal.signal_id,
        }
    for signal in values:
        if signal.status not in {"READY", "PARTIAL", "STALE"} or signal.normalized_score is None:
            missing_sources.append(signal.missing_reason or signal.source)
            continue
        if signal.status in {"STALE", "PARTIAL"} or _num(signal.freshness) in {0.0, .5}:
            stale_sources.append(signal.source)
        quality = _quality(signal.quality, 0)
        confidence = _quality(signal.confidence, 0)
        coverage = _clamp(signal.coverage, 0, 1) or 0
        freshness = _num(signal.freshness)
        if freshness is None:
            freshness = 0 if str(signal.freshness).upper() in {"EXPIRED", "UNAVAILABLE"} else 1
        weight = _BASE_WEIGHTS.get(signal.category, .08) * quality * confidence * coverage * max(0, min(1, freshness))
        if weight <= 0:
            warnings.append(signal.signal_id)
            continue
        valid.append((signal, weight))
        if signal.normalized_score >= 55:
            supporting.append(evidence_item(signal, "supporting", weight))
        elif signal.normalized_score <= 45:
            contradicting.append(evidence_item(signal, "contradicting", weight))
        else:
            warnings.append(evidence_item(signal, "warning", weight))
    if not valid:
        return {
            "mood_score": None, "agreement_score": None, "agreement_level": "UNAVAILABLE", "confidence": 0.0,
            "quality": 0.0, "coverage": 0.0, "freshness_status": "UNAVAILABLE", "category_scores": {},
            "missing_sources": list(dict.fromkeys(missing_sources)), "stale_sources": list(dict.fromkeys(stale_sources)),
            "evidence": {"supporting": supporting, "contradicting": contradicting, "warnings": warnings},
        }
    total = sum(weight for _, weight in valid)
    score = sum(float(signal.normalized_score) * weight for signal, weight in valid) / total
    category_scores = _category_scores(signal for signal, _ in valid)
    bull = sum(weight for signal, weight in valid if signal.normalized_score >= 55)
    bear = sum(weight for signal, weight in valid if signal.normalized_score <= 45)
    neutral = max(0.0, total - bull - bear)
    agreement = max(bull, bear, neutral) / total if total else 0.0
    agreement_level = "HIGH" if agreement >= .75 else "MEDIUM" if agreement >= .55 else "LOW"
    quality = sum(_quality(signal.quality, 0) * weight for signal, weight in valid) / total
    coverage = sum((_clamp(signal.coverage, 0, 1) or 0) * weight for signal, weight in valid) / total
    confidence = sum((_quality(signal.confidence, 0)) * weight for signal, weight in valid) / total
    if len(stale_sources) >= len(valid):
        freshness_status = "STALE"
    elif stale_sources:
        freshness_status = "MIXED"
    else:
        freshness_status = "FRESH"
    return {
        "mood_score": round(score, 4), "agreement_score": round(agreement, 4), "agreement_level": agreement_level,
        "confidence": round(confidence * agreement, 4), "quality": round(quality, 4), "coverage": round(coverage, 4),
        "freshness_status": freshness_status, "category_scores": category_scores,
        "missing_sources": list(dict.fromkeys(missing_sources)), "stale_sources": list(dict.fromkeys(stale_sources)),
        "evidence": {"supporting": supporting, "contradicting": contradicting, "warnings": warnings},
    }


def classify_mood_state(summary: Mapping[str, Any], previous_state: str | None = None) -> str:
    """Classify a candidate state; transitions are applied separately."""

    score = _num(summary.get("mood_score"))
    if score is None or _num(summary.get("coverage")) is not None and float(summary.get("coverage") or 0) < .12:
        return "INSUFFICIENT_DATA"
    categories = summary.get("category_scores") or {}
    price = _num(categories.get("price")); breadth = _num(categories.get("breadth")); rs = _num(categories.get("relative_strength")); options = _num(categories.get("options")); news = _num(categories.get("news")); technical = _num(categories.get("technical"))
    if score <= 25 and (price is None or price <= 40) and (breadth is None or breadth <= 45):
        return "BREAKDOWN"
    if score >= 78 and (options is not None and options <= 45 or (breadth is not None and breadth < 48)):
        return "CROWDED"
    if score >= 66 and (price is None or price >= 60) and (rs is None or rs >= 60) and (breadth is None or breadth >= 55) and (technical is None or technical >= 55):
        return "LEADERSHIP" if breadth is not None and breadth < 70 else "EXPANSION"
    if score >= 64 and (breadth is None or breadth >= 55):
        return "EXPANSION"
    if score >= 68 and breadth is not None and breadth < 55 and (price is None or price >= 60) and (rs is None or rs >= 60):
        return "LEADERSHIP"
    if 54 <= score < 66 and (price is None or price >= 52) and (breadth is None or breadth >= 48):
        return "ACCUMULATION"
    if 50 <= score < 58 and any(value is not None and value >= 52 for value in (price, rs, technical)):
        return "EARLY_IMPROVEMENT"
    if 42 <= score < 58 and price is not None and price >= 55 and (breadth is not None and breadth < 45 or options is not None and options < 45 or news is not None and news < 45):
        return "DISTRIBUTION"
    if score < 42 and (price is None or price < 48) and (breadth is None or breadth < 48):
        return "DETERIORATION"
    return "DORMANT"


def classify_state(summary: Mapping[str, Any], previous_state: str | None = None) -> str:
    return classify_mood_state(summary, previous_state)


WATCHLIST_STATES = ("TRENDING_UP", "IMPROVING", "NEUTRAL", "WEAKENING", "TRENDING_DOWN", "STRETCHED", "INSUFFICIENT_DATA")


def classify_watchlist_state(summary: Mapping[str, Any]) -> str:
    """Use a light stock state vocabulary; holdings do not enter sector lifecycle states."""

    score = _num(summary.get("mood_score"))
    if score is None or (_num(summary.get("coverage")) or 0) < .12:
        return "INSUFFICIENT_DATA"
    categories = summary.get("category_scores") or {}
    price = _num(categories.get("price")); technical = _num(categories.get("technical")); options = _num(categories.get("options")); rs = _num(categories.get("relative_strength"))
    if score >= 70 and (technical is None or technical >= 65) and (options is None or options < 65):
        return "STRETCHED"
    if score >= 65 and (price is None or price >= 60) and (rs is None or rs >= 55):
        return "TRENDING_UP"
    if score >= 55:
        return "IMPROVING"
    if score <= 35 and (price is None or price <= 40):
        return "TRENDING_DOWN"
    if score < 48:
        return "WEAKENING"
    return "NEUTRAL"


def _divergence_active(name: str, scores: Mapping[str, float]) -> tuple[bool, dict[str, Any]]:
    def mismatch(left: str, right: str) -> bool:
        a, b = _num(scores.get(left)), _num(scores.get(right))
        return a is not None and b is not None and ((a >= 58 and b <= 42) or (a <= 42 and b >= 58))
    pairs = {
        "PRICE_BREADTH": ("price", "breadth"), "PRICE_RS": ("price", "relative_strength"),
        "PRICE_OPTIONS": ("price", "options"), "PRICE_NEWS": ("price", "news"),
        "NEWS_OPTIONS": ("news", "options"), "TECHNICAL_BREADTH": ("technical", "breadth"),
    }
    left, right = pairs[name]
    active = mismatch(left, right)
    # For price/options the meaningful contradiction is price rising while
    # downside protection/IV risk rises, not call-vs-put direction.
    if name == "PRICE_OPTIONS":
        price, option_risk = _num(scores.get("price")), _num(scores.get("options"))
        active = price is not None and option_risk is not None and ((price >= 58 and option_risk <= 42) or (price <= 42 and option_risk >= 58))
    evidence = {"left": scores.get(left), "right": scores.get(right), "metrics": [left, right]}
    left_value, right_value = _num(scores.get(left)), _num(scores.get(right))
    severity = abs(left_value - right_value) / 100 if left_value is not None and right_value is not None else 0.0
    evidence["severity_score"] = severity
    return active, evidence


def calculate_divergences(signals: Iterable[MoodSignal], previous: Iterable[Mapping[str, Any]] | None = None, as_of: date | None = None) -> list[dict[str, Any]]:
    """Return all six divergence records, including inactive/resolved ones."""

    values = list(signals)
    summary = aggregate_signals(values)
    scores = summary.get("category_scores") or {}
    previous_by_type = {str(item.get("type")): item for item in previous or []}
    day = as_of or max((_date(item.as_of) for item in values if _date(item.as_of)), default=date.today())
    result = []
    for name in DIVERGENCE_TYPES:
        active, evidence = _divergence_active(name, scores)
        old = previous_by_type.get(name) or {}
        old_active = bool(old.get("active")) and not bool(old.get("resolved"))
        if active:
            first = _date(old.get("first_seen")) if old_active else day
            persistence = int(old.get("persistence_sessions") or 0) + 1 if old_active else 1
            severity_score = (_num(evidence.get("severity_score")) or 0) * min(1.0, persistence / 3.0)
            severity = "HIGH" if severity_score >= .3 else "MEDIUM" if severity_score >= .16 else "LOW"
            result.append({
                "type": name, "active": True, "onset": not old_active, "persistence_sessions": persistence,
                "duration_sessions": persistence, "severity": severity, "severity_score": round(severity_score, 4), "confidence": round(min(1.0, .45 + severity_score), 4),
                "first_seen": first, "last_seen": day, "evidence": evidence, "resolved": False,
            })
        elif old_active:
            result.append({
                "type": name, "active": False, "onset": False, "persistence_sessions": int(old.get("persistence_sessions") or 1),
                "duration_sessions": int(old.get("duration_sessions") or old.get("persistence_sessions") or 1), "severity": "NONE", "confidence": _num(old.get("confidence")) or 0.0,
                "first_seen": _date(old.get("first_seen")), "last_seen": _date(old.get("last_seen")) or day,
                "evidence": {"resolved_on": day, "prior": old.get("evidence") or {}}, "resolved": True,
            })
        else:
            result.append({
                "type": name, "active": False, "onset": False, "persistence_sessions": 0,
                "duration_sessions": 0, "severity": "NONE", "confidence": 0.0, "first_seen": None, "last_seen": None,
                "evidence": evidence, "resolved": False,
            })
    return _safe(result)


def _business_sessions(start: date | None, end: date) -> int:
    if start is None or start > end:
        return 1
    days = (end - start).days + 1
    return max(1, sum((start + timedelta(days=index)).weekday() < 5 for index in range(days)))


def _transition(candidate: str, summary: Mapping[str, Any], previous: MoodSnapshot | None) -> tuple[str, dict[str, Any], date | None, int]:
    score = _num(summary.get("mood_score"))
    if previous is None:
        state = candidate
        changed = True
        confirmed = True
        fast_path = False
    elif candidate == "INSUFFICIENT_DATA":
        state, changed, confirmed, fast_path = candidate, previous.state != candidate, True, False
    elif previous.state == candidate:
        state, changed, confirmed, fast_path = candidate, False, True, False
    elif candidate == "BREAKDOWN" and score is not None and score <= 25:
        state, changed, confirmed, fast_path = candidate, True, True, True
    elif previous.candidate_state == candidate:
        state, changed, confirmed, fast_path = candidate, True, True, False
    else:
        state, changed, confirmed, fast_path = previous.state, False, False, False
    start = _date(summary.get("as_of")) if changed else (_date(previous.state_started_on) if previous else None)
    duration = _business_sessions(start, _date(summary.get("as_of")) or date.today()) if start else 1
    return state, {
        "changed": changed, "from": previous.state if previous else None, "to": state,
        "candidate": candidate, "confirmed": confirmed, "fast_path": fast_path,
        "confirmation_required": candidate not in {"INSUFFICIENT_DATA", "BREAKDOWN"},
        "reason": "initial" if previous is None else "severe_breakdown" if fast_path else "candidate_confirmed" if changed else "awaiting_confirmation",
    }, start, duration


def _latest_prior(
    db: Session,
    scope_type: str,
    scope_key: str,
    as_of: date,
    version: str,
    snapshot_type: str = "INTRADAY",
) -> tuple[MoodSnapshot | None, list[MoodSnapshot]]:
    try:
        rows = list(db.scalars(
            select(MoodSnapshot)
            .where(
                MoodSnapshot.scope_type == scope_type,
                MoodSnapshot.scope_key == scope_key,
                MoodSnapshot.calculation_version == version,
                MoodSnapshot.snapshot_type == snapshot_type,
                MoodSnapshot.trading_date < as_of,
            )
            .order_by(MoodSnapshot.trading_date.desc())
            .limit(128)
        ).all())
    except Exception:
        rows = []
    return (rows[0] if rows else None, list(reversed(rows)))


def _scope_payload(db: Session, scope_type: str, scope_key: str, node_id: int | None, as_of: date, version: str, previous: MoodSnapshot | None) -> dict[str, Any]:
    symbols: list[str] = []
    proxy_symbols: list[str] = []
    constituent_symbols: list[str] = []
    signals: list[MoodSignal] = []
    if scope_type == "watchlist":
        symbols = [scope_key.upper()]
    elif node_id is not None:
        proxy_symbols = _node_symbols(db, node_id, as_of=as_of, etf_only=True)
        constituent_symbols = _node_symbols(db, node_id, as_of=as_of, exclude_etf=True)
        symbols = proxy_symbols or constituent_symbols
        signals.extend(_node_signals(db, scope_type, scope_key, node_id, as_of))
    elif scope_type == "market":
        symbols = ["SPY"]
        signals.extend(_sector_participation_signals(db, as_of))
    if symbols:
        # Keep the adapter bounded while retaining a deterministic aggregate.
        for symbol in symbols[:32]:
            signals.extend(_history_signals(db, scope_type, scope_key, symbol, as_of))
            if scope_type == "watchlist":
                signals.extend(_technical_signals(db, scope_type, scope_key, symbol, as_of))
        signals.extend(_options_signals(db, scope_type, scope_key, symbols[:32] if scope_type != "market" else ["SPY", "QQQ", "IWM"], as_of))
        signals.extend(_news_signal(db, scope_type, scope_key, constituent_symbols or symbols, as_of))
    elif scope_type == "market":
        signals.extend(_history_signals(db, scope_type, scope_key, "SPY", as_of))
        signals.extend(_options_signals(db, scope_type, scope_key, ["SPY", "QQQ", "IWM"], as_of))
        signals.extend(_news_signal(db, scope_type, scope_key, [], as_of))
    summary = aggregate_signals(signals)
    prior_divergences = previous.divergences if previous and isinstance(previous.divergences, list) else []
    divergences = calculate_divergences(signals, prior_divergences, as_of)
    candidate = classify_watchlist_state(summary) if scope_type == "watchlist" else classify_mood_state(summary, previous.state if previous else None)
    state, transition, state_started, duration = _transition(candidate, {**summary, "as_of": as_of}, previous)
    previous_score = _num(previous.mood_score) if previous else None
    score = _num(summary.get("mood_score"))
    direction = "up" if score is not None and previous_score is not None and score > previous_score + 2 else "down" if score is not None and previous_score is not None and score < previous_score - 2 else "flat" if score is not None and previous_score is not None else _direction(score)
    phase = "improving" if state in {"EARLY_IMPROVEMENT", "ACCUMULATION", "EXPANSION", "LEADERSHIP", "TRENDING_UP", "IMPROVING"} else "deteriorating" if state in {"DISTRIBUTION", "DETERIORATION", "BREAKDOWN", "TRENDING_DOWN", "WEAKENING"} else "neutral"
    regime = "risk_on" if state in {"EXPANSION", "LEADERSHIP", "ACCUMULATION", "TRENDING_UP"} else "risk_off" if state in {"DISTRIBUTION", "DETERIORATION", "BREAKDOWN", "TRENDING_DOWN"} else "transition" if state in {"EARLY_IMPROVEMENT", "IMPROVING"} else "neutral"
    signal_payload = [item.as_dict() for item in signals]
    evidence = {
        **summary.get("evidence", {}),
        "category_scores": summary.get("category_scores", {}),
        "scope": {"scope_type": scope_type, "scope_key": scope_key, "symbols": symbols},
    }
    transition["reason_detail"] = {
        "category_scores": summary.get("category_scores", {}),
        "top_changed_evidence": (summary.get("evidence", {}).get("supporting", [])[:2] + summary.get("evidence", {}).get("contradicting", [])[:2]),
    }
    source_dates = [_date(item.source_as_of) for item in signals if _date(item.source_as_of)]
    source_timestamp = datetime.combine(max(source_dates), datetime.min.time(), tzinfo=UTC) if source_dates else None
    material = {
        "scope_type": scope_type, "scope_key": scope_key, "trading_date": as_of,
        "signals": signal_payload, "evidence": evidence, "divergences": divergences,
        "candidate_state": candidate, "previous_state": previous.state if previous else None,
    }
    node_level = None
    if node_id is not None:
        try:
            node_level = db.get(IndustryPulseNode, node_id).level if db.get(IndustryPulseNode, node_id) else None
        except Exception:
            node_level = None
    return {
        "scope_type": scope_type, "scope_key": scope_key, "trading_date": as_of, "state": state,
        "candidate_state": candidate, "previous_state": previous.state if previous else None,
        "direction": direction, "phase": phase, "regime": regime, "mood_score": score,
        "agreement_score": summary.get("agreement_score"), "agreement_level": summary.get("agreement_level"),
        "confidence": summary.get("confidence"), "quality": summary.get("quality"), "coverage": summary.get("coverage"),
        "freshness_status": summary.get("freshness_status"), "state_started_on": state_started,
        "duration_sessions": duration, "calculation_version": version, "input_hash": _hash(material),
        "source_timestamp": source_timestamp, "calculated_at": datetime.now(UTC), "signals": signal_payload,
        "evidence": evidence, "divergences": divergences, "transition": transition,
        "missing_sources": summary.get("missing_sources", []), "stale_sources": summary.get("stale_sources", []),
        "input_manifest": {
            "version": version, "as_of": as_of.isoformat(), "symbols": symbols, "source_types": sorted({item.source for item in signals}),
            "node_level": node_level, "evidence_type": "DIRECT" if scope_type == "market" else "PROXY" if proxy_symbols else "CONSTITUENT",
            "proxy_symbols": proxy_symbols, "constituent_symbols": constituent_symbols,
        },
    }


def _persist(
    db: Session,
    values: Mapping[str, Any],
    *,
    force: bool = False,
    immutable: bool = False,
) -> tuple[MoodSnapshot, str]:
    values = dict(values)
    values.setdefault("snapshot_type", "INTRADAY")
    for key in ("signals", "evidence", "divergences", "transition", "missing_sources", "stale_sources", "input_manifest"):
        values[key] = _safe(values.get(key))
    row = db.scalar(select(MoodSnapshot).where(
        MoodSnapshot.scope_type == values["scope_type"], MoodSnapshot.scope_key == values["scope_key"],
        MoodSnapshot.trading_date == values["trading_date"], MoodSnapshot.calculation_version == values["calculation_version"],
        MoodSnapshot.snapshot_type == values["snapshot_type"],
    ).limit(1))
    if row is None:
        row = MoodSnapshot(**dict(values)); db.add(row); db.flush(); return row, "created"
    if immutable or not force and row.input_hash == values["input_hash"]:
        return row, "skipped"
    for key, value in values.items():
        if key != "id":
            setattr(row, key, value)
    db.flush()
    return row, "updated"


def _default_as_of(db: Session) -> date:
    candidates: list[date] = []
    for model, column in ((HistoricalPrice, HistoricalPrice.date), (IndustryPulseSnapshot, IndustryPulseSnapshot.trading_date), (OptionsSnapshot, OptionsSnapshot.trading_date)):
        try:
            value = db.scalar(select(func.max(column)))
            parsed = _date(value)
            if parsed:
                candidates.append(parsed)
        except Exception:
            continue
    return max(candidates) if candidates else date.today()


def sync_mood(
    db: Session,
    as_of: date | None = None,
    scopes: set[str] | None = None,
    force: bool = False,
    snapshot_type: str = "INTRADAY",
) -> dict[str, Any]:
    """Calculate and upsert current snapshots without committing the session."""

    day = _date(as_of) or _default_as_of(db)
    specs = _scope_specs(db, scopes)
    counts = defaultdict(int)
    for scope_type, scope_key, node_id in specs:
        previous, _history = _latest_prior(db, scope_type, scope_key, day, CALCULATION_VERSION, snapshot_type)
        values = _scope_payload(db, scope_type, scope_key, node_id, day, CALCULATION_VERSION, previous)
        values["snapshot_type"] = snapshot_type
        _row, action = _persist(db, values, force=force, immutable=snapshot_type == "EOD")
        counts[action] += 1
        counts["insufficient"] += int(values["state"] == "INSUFFICIENT_DATA")
    return {
        "status": "completed" if specs else "insufficient_data", "as_of": day.isoformat(), "calculation_version": CALCULATION_VERSION,
        "scope_count": len(specs), "created": counts["created"], "updated": counts["updated"], "skipped": counts["skipped"], "insufficient": counts["insufficient"],
    }


def rebuild_mood_history(db: Session, start: date, end: date, calculation_version: str = CALCULATION_VERSION) -> dict[str, Any]:
    """Recompute each date in order; all source queries remain <= that date."""

    first, last = _date(start), _date(end)
    if first is None or last is None or first > last:
        return {"status": "invalid_range", "dates": 0, "calculation_version": calculation_version}
    dates: set[date] = set()
    for model, column in ((HistoricalPrice, HistoricalPrice.date), (IndustryPulseSnapshot, IndustryPulseSnapshot.trading_date), (OptionsSnapshot, OptionsSnapshot.trading_date)):
        try:
            dates.update(value for value in (_date(item) for item in db.scalars(select(column).where(column >= first, column <= last)).all()) if value is not None)
        except Exception:
            continue
    try:
        news_dates = db.execute(select(NewsItem.published_at, NewsItem.found_at)).all()
        dates.update(timestamp.date() for published, found in news_dates if (timestamp := _dt(published or found)) and first <= timestamp.date() <= last)
    except Exception:
        pass
    if not dates:
        dates = {first}
    total = 0; created = updated = skipped = 0
    for day in sorted(dates):
        for scope_type, scope_key, node_id in _scope_specs(db, None):
            previous, _history = _latest_prior(db, scope_type, scope_key, day, calculation_version, "INTRADAY")
            values = _scope_payload(db, scope_type, scope_key, node_id, day, calculation_version, previous)
            values["snapshot_type"] = "INTRADAY"
            _row, action = _persist(db, values, force=True)
            total += 1; created += int(action == "created"); updated += int(action == "updated"); skipped += int(action == "skipped")
    return {"status": "completed", "start": first.isoformat(), "end": last.isoformat(), "dates": len(dates), "snapshots": total, "created": created, "updated": updated, "skipped": skipped, "calculation_version": calculation_version}


def _snapshot_out(row: MoodSnapshot, db: Session | None = None) -> dict[str, Any]:
    node_level = (row.input_manifest or {}).get("node_level") if isinstance(row.input_manifest, dict) else None
    name = row.scope_key
    name_zh = None
    if row.scope_type == "market":
        name, name_zh = "US Market", "美国市场"
    elif db is not None and row.scope_type in {"sector", "ai_chain"}:
        try:
            node = db.scalar(select(IndustryPulseNode).where(
                IndustryPulseNode.taxonomy == ("base" if row.scope_type == "sector" else "ai"),
                IndustryPulseNode.node_key == row.scope_key,
            ).limit(1))
        except Exception:
            node = None
        if node is not None:
            name, name_zh, node_level = node.name, node.name_zh, node.level
    elif db is not None and row.scope_type == "watchlist":
        try:
            security = db.scalar(select(Security).where(Security.display_symbol == row.scope_key).limit(1))
            profile = db.get(StockProfile, row.scope_key)
        except Exception:
            security = profile = None
        name = (security.display_name if security else None) or (profile.company_name if profile else None) or row.scope_key
    return _safe({
        "id": row.id, "scope_type": row.scope_type, "scope_key": row.scope_key, "trading_date": row.trading_date,
        "name": name, "name_zh": name_zh, "level": node_level,
        "state": row.state, "candidate_state": row.candidate_state, "previous_state": row.previous_state,
        "direction": row.direction, "phase": row.phase, "regime": row.regime, "mood_score": row.mood_score,
        "agreement_score": row.agreement_score, "agreement_level": row.agreement_level, "confidence": row.confidence,
        "quality": row.quality, "coverage": row.coverage, "freshness_status": row.freshness_status,
        "state_started_on": row.state_started_on, "duration_sessions": row.duration_sessions,
        "calculation_version": row.calculation_version, "input_hash": row.input_hash, "source_timestamp": row.source_timestamp,
        "calculated_at": row.calculated_at, "snapshot_type": row.snapshot_type, "input_cutoff": row.input_cutoff,
        "warnings": row.warnings or [], "signals": row.signals or [], "evidence": row.evidence or {},
        "divergences": row.divergences or [], "transition": row.transition or {}, "missing_sources": row.missing_sources or [],
        "stale_sources": row.stale_sources or [], "input_manifest": row.input_manifest or {},
    })


def _latest_rows(db: Session, *, scope_type: str | None = None, scope_key: str | None = None) -> list[MoodSnapshot]:
    try:
        query = select(MoodSnapshot).where(MoodSnapshot.calculation_version == CALCULATION_VERSION)
        query = query.where(MoodSnapshot.snapshot_type == "INTRADAY")
        if scope_type:
            query = query.where(MoodSnapshot.scope_type == scope_type)
        if scope_key:
            query = query.where(MoodSnapshot.scope_key == scope_key)
        rows = list(db.scalars(query.order_by(MoodSnapshot.trading_date.desc(), MoodSnapshot.calculated_at.desc())).all())
    except Exception:
        return []
    selected: dict[tuple[str, str], MoodSnapshot] = {}
    for row in rows:
        selected.setdefault((row.scope_type, row.scope_key), row)
    return list(selected.values())


def _history_points(db: Session, row: MoodSnapshot, limit: int = 180) -> list[dict[str, Any]]:
    try:
        rows = list(db.scalars(select(MoodSnapshot).where(
            MoodSnapshot.scope_type == row.scope_type, MoodSnapshot.scope_key == row.scope_key,
            MoodSnapshot.calculation_version == row.calculation_version,
            MoodSnapshot.snapshot_type == "INTRADAY",
        ).order_by(MoodSnapshot.trading_date.desc()).limit(max(1, min(limit, 3650)))).all())
    except Exception:
        rows = []
    return [_safe({
        "date": item.trading_date, "as_of": item.trading_date, "mood_score": item.mood_score,
        "state": item.state, "direction": item.direction, "phase": item.phase, "transition": item.transition or {},
    }) for item in reversed(rows)]


def latest_mood_payload(db: Session, scope_type: str | None = None, scope_key: str | None = None, range_days: int = 20) -> dict[str, Any]:
    rows = _latest_rows(db, scope_type=scope_type, scope_key=scope_key)
    if scope_type and scope_key:
        return _snapshot_out(rows[0], db) if rows else {"scope_type": scope_type, "scope_key": scope_key, "status": "unavailable", "state": "INSUFFICIENT_DATA"}
    if scope_type:
        days = max((_date(row.trading_date) for row in rows), default=None)
        return {"scope_type": scope_type, "as_of": days, "status": "ready" if rows else "unavailable", "snapshots": [_snapshot_out(row, db) for row in rows]}
    payload = mood_report_payload(db)
    payload["range_days"] = max(1, min(int(range_days), 3650))
    return payload


def mood_history_payload(db: Session, scope_type: str, scope_key: str, days: int = 30) -> dict[str, Any]:
    try:
        rows = list(db.scalars(
            select(MoodSnapshot).where(
                MoodSnapshot.scope_type == scope_type, MoodSnapshot.scope_key == scope_key,
                MoodSnapshot.calculation_version == CALCULATION_VERSION,
                MoodSnapshot.snapshot_type == "INTRADAY",
            ).order_by(MoodSnapshot.trading_date.desc()).limit(max(1, min(int(days), 3650)))
        ).all())
    except Exception:
        rows = []
    rows.reverse()
    latest = _snapshot_out(rows[-1], db) if rows else None
    return {"scope_type": scope_type, "scope_key": scope_key, "as_of": rows[-1].trading_date if rows else None, "status": "ready" if rows else "unavailable", "calculation_version": CALCULATION_VERSION, "item": latest, "history": [_snapshot_out(row, db) for row in rows]}


def _vix_payload(db: Session, as_of: date | None) -> dict[str, Any]:
    query = select(HistoricalPrice).where(HistoricalPrice.symbol == "^VIX")
    if as_of:
        query = query.where(HistoricalPrice.date <= as_of)
    rows = list(db.scalars(query.order_by(HistoricalPrice.date.desc()).limit(2)).all())
    if not rows:
        return {"value": None, "change_percent": None, "as_of": None, "status": "UNAVAILABLE", "regime": None}
    value = _num(rows[0].adjusted_close if rows[0].adjusted_close is not None else rows[0].close)
    previous = _num(rows[1].adjusted_close if len(rows) > 1 and rows[1].adjusted_close is not None else rows[1].close) if len(rows) > 1 else None
    change_percent = (value / previous - 1) * 100 if value is not None and previous and previous > 0 else None
    status = _freshness(as_of or rows[0].date, rows[0].date)[1]
    regime = "LOW" if value is not None and value < 15 else "NORMAL" if value is not None and value < 20 else "ELEVATED" if value is not None and value < 30 else "HIGH" if value is not None else None
    return _safe({
        "value": round(value, 2) if value is not None else None,
        "change_percent": round(change_percent, 2) if change_percent is not None else None,
        "previous_close": previous,
        "as_of": rows[0].date,
        "status": status,
        "regime": regime,
    })


PRICE_HISTORY_SOURCES = ("fmp", "yahoo")


def price_history_payload(db: Session, symbol: str, days: int = 180) -> dict[str, Any]:
    """Database-only daily OHLC read model for mood-console charts (VIX and related symbols).

    Preferred source (FMP) wins per date; the fallback source only fills missing dates,
    so partial coverage on either side never drops days.
    """
    value = symbol.strip().upper()
    if not value or len(value) > 32:
        return {"symbol": value or symbol, "status": "invalid_symbol", "source": None, "candles": [], "as_of": None}
    limit = max(30, min(int(days), 365))
    by_date: dict[date, HistoricalPrice] = {}
    source_used: str | None = None
    for source in PRICE_HISTORY_SOURCES:
        try:
            rows = list(db.scalars(
                select(HistoricalPrice)
                .where(HistoricalPrice.symbol == value, HistoricalPrice.source == source)
                .order_by(HistoricalPrice.date.desc())
                .limit(limit)
            ).all())
        except Exception:
            rows = []
        for row in rows:
            day = _date(row.date)
            if day is not None and day not in by_date:
                by_date[day] = row
                source_used = source_used or source
    candles = []
    for day in sorted(by_date):
        row = by_date[day]
        open_, high, low = _num(row.open), _num(row.high), _num(row.low)
        close = _num(row.close if row.close is not None else row.adjusted_close)
        if None in (open_, high, low, close):
            continue
        candles.append({
            "time": day.isoformat(), "open": open_, "high": high, "low": low,
            "close": close, "volume": _num(row.volume),
        })
    return _safe({
        "symbol": value, "status": "ready" if candles else "unavailable",
        "source": source_used, "as_of": candles[-1]["time"] if candles else None,
        "candles": candles,
    })


def mood_report_payload(db: Session) -> dict[str, Any]:
    rows = _latest_rows(db)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        payload = _snapshot_out(row, db)
        payload["history"] = _history_points(db, row)
        grouped[row.scope_type].append(payload)
    market = next(iter(grouped.get("market", [])), None)
    sectors = [item for item in grouped.get("sector", []) if item.get("level") == "sector" or item.get("level") is None]
    industries = [item for item in grouped.get("sector", []) if item.get("level") in {"group", "leaf"}]
    ai_chain = grouped.get("ai_chain", [])
    watchlist = grouped.get("watchlist", [])
    all_rows = [item for values in grouped.values() for item in values]
    ordered = sorted((item for item in all_rows if item.get("mood_score") is not None), key=lambda item: item["mood_score"], reverse=True)
    movers = {
        "improving": [item for item in all_rows if item.get("direction") == "up"][:10],
        "deteriorating": [item for item in all_rows if item.get("direction") == "down"][:10],
        "new_leadership": [item for item in ordered if item.get("state") in {"LEADERSHIP", "TRENDING_UP"}][:10],
        "new_crowded": [item for item in ordered if item.get("state") in {"CROWDED", "STRETCHED"}][:10],
        "strongest": ordered[:10],
    }
    divergences = [{"scope_type": item["scope_type"], "scope_key": item["scope_key"], **divergence} for item in all_rows for divergence in item.get("divergences", []) if divergence.get("active") or divergence.get("resolved")]
    transitions = [{"scope_type": item["scope_type"], "scope_key": item["scope_key"], **(item.get("transition") or {})} for item in all_rows if (item.get("transition") or {}).get("changed")]
    as_of = max((_date(item.get("trading_date")) for item in all_rows if _date(item.get("trading_date"))), default=None)
    status = "ready" if market and market.get("state") != "INSUFFICIENT_DATA" else "insufficient_data" if all_rows else "unavailable"
    limitations = ["Whole-market breadth is unavailable; market breadth uses sector participation only."]
    report_sections = [
        {"id": "state", "title": "Mood state", "state": market.get("state") if market else "INSUFFICIENT_DATA", "score": market.get("mood_score") if market else None},
        {"id": "breadth", "title": "Breadth and participation", "evidence": market.get("evidence", {}).get("category_scores", {}).get("breadth") if market else None, "missing": market.get("missing_sources", []) if market else ["market_snapshot_missing"]},
        {"id": "divergence", "title": "Divergences", "count": len([item for item in divergences if item.get("active")])},
        {"id": "transitions", "title": "Transitions", "count": len(transitions)},
    ]
    report = {
        "market_mood": market.get("state") if market else None,
        "sector_regime": sectors[0].get("state") if sectors else None,
        "regime_changes": transitions,
        "ai_chain_mood": ai_chain[0].get("state") if ai_chain else None,
        "key_divergences": divergences,
        "crowding_signals": movers["new_crowded"],
        "improving_sectors": [item for item in sectors if item.get("direction") == "up"],
        "deteriorating_sectors": [item for item in sectors if item.get("direction") == "down"],
        "limitations": limitations,
        "sections": report_sections,
    }
    category_scores = market.get("evidence", {}).get("category_scores", {}) if market else {}
    market_window = {
        "state": market.get("state") if market else None,
        "score": market.get("mood_score") if market else None,
        "confidence": market.get("confidence") if market else None,
        "coverage": market.get("coverage") if market else None,
        "category_scores": category_scores,
        "vix": _vix_payload(db, as_of),
        "participation": {
            "improving": sum(item.get("direction") == "up" for item in sectors),
            "deteriorating": sum(item.get("direction") == "down" for item in sectors),
            "tracked": len(sectors),
        },
        "active_divergences": sum(bool(item.get("active")) for item in divergences),
    }
    return {
        "as_of": as_of, "status": status, "calculation_version": CALCULATION_VERSION,
        "market": market, "sectors": sectors, "industries": industries, "ai_chain": ai_chain, "watchlist": watchlist,
        "movers": movers, "divergences": divergences, "transitions": transitions, "limitations": limitations,
        "report": report,
        "report_sections": report_sections,
        "market_window": market_window,
    }


__all__ = [
    "CALCULATION_VERSION", "MOOD_CALCULATION_VERSION", "MOOD_STATES", "STATES", "SCOPE_TYPES", "DIVERGENCE_TYPES",
    "MoodSignal", "Signal", "aggregate_signals", "classify_mood_state", "classify_state", "calculate_divergences",
    "dedupe_news_rows", "sync_mood", "rebuild_mood_history", "latest_mood_payload", "mood_history_payload", "mood_report_payload",
    "price_history_payload",
]
