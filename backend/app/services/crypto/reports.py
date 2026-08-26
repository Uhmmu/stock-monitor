"""Assemble persisted crypto research evidence into an idempotent report."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CryptoResearchReport
from app.services.llm import generate_analysis


REPORT_TYPE = "crypto_research"
EVIDENCE_VERSION = "crypto-research-evidence-v1"
SECTIONS = ("market", "technical", "derivatives", "fundamentals", "news", "regime")
LABELS = {name: name.title() for name in SECTIONS}
META = {
    "as_of", "available", "coverage", "fetched_at", "freshness", "freshness_status",
    "generated_at", "last_updated", "provider", "provider_timestamp", "reason", "source",
    "sources", "status", "timestamp", "timestamps", "warnings",
}


def _safe(value: Any, depth: int = 0) -> Any:
    """Keep evidence JSON-safe and bounded before it reaches prompts/JSON columns."""

    if depth > 8:
        return "[truncated]"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.replace(tzinfo=UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        result = {str(key): _safe(item, depth + 1) for key, item in items[:48]}
        if len(items) > 48:
            result["_truncated"] = f"{len(items) - 48} keys omitted"
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [_safe(item, depth + 1) for item in items[:24]]
        if len(items) > 24:
            result.append(f"[truncated: {len(items) - 24} items omitted]")
        return result
    if isinstance(value, str):
        return value[:2_000]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:2_000]


def _hash(value: Any) -> str:
    payload = json.dumps(_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _warnings(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return list(dict.fromkeys(str(item).strip()[:500] for item in values if item not in (None, "")))[:32]


def _source_rows(name: str, raw: Mapping[str, Any], timestamp: Any, freshness: Any) -> list[dict[str, Any]]:
    values = raw.get("sources", raw.get("source", raw.get("provider")))
    values = values if isinstance(values, (list, tuple, set)) else [values] if values is not None else []
    rows = []
    for value in list(values)[:24]:
        if isinstance(value, Mapping):
            row = dict(_safe(value))
            row.setdefault("section", name)
        else:
            row = {"section": name, "source": str(value)[:2_000]}
        if timestamp is not None:
            row.setdefault("timestamp", _safe(timestamp))
        if freshness is not None:
            row.setdefault("freshness", _safe(freshness))
        if row not in rows:
            rows.append(row)
    return rows


def _section(name: str, raw: Any, fallback_coverage: Any = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if raw is None:
        return {
            "status": "missing", "available": False, "data": None, "source": None,
            "timestamp": None, "freshness": "unavailable", "coverage": fallback_coverage or 0,
            "sources": [], "warnings": [f"数据不足：未提供已持久化的 {LABELS[name]} evidence"],
        }, []
    mapping = raw if isinstance(raw, Mapping) else None
    status = str(mapping.get("status", "available")).casefold() if mapping else "available"
    timestamp = next((mapping.get(key) for key in ("timestamp", "as_of", "observed_at", "fetched_at", "provider_timestamp", "generated_at", "last_updated") if mapping.get(key) is not None), None) if mapping else None
    freshness = mapping.get("freshness", mapping.get("freshness_status")) if mapping else None
    source = mapping.get("source", mapping.get("provider")) if mapping else None
    coverage = mapping.get("coverage", fallback_coverage) if mapping else fallback_coverage
    warnings = _warnings(mapping.get("warnings") if mapping else None)
    if status in {"missing", "unavailable", "error"}:
        warnings = _warnings([*warnings, mapping.get("reason") if mapping else None])
        payload = None
    elif mapping and "data" in mapping:
        payload = mapping["data"]
    elif mapping:
        payload = {key: value for key, value in mapping.items() if key not in META}
    else:
        payload = raw
    available = payload not in (None, {}, []) and status not in {"missing", "unavailable", "error"}
    if not available:
        warnings = warnings or [f"数据不足：{LABELS[name]} persisted evidence is unavailable"]
        status = status if status != "available" else "missing"
        payload = None
    sources = _source_rows(name, mapping or {}, timestamp, freshness)
    return {
        "status": status, "available": available, "data": _safe(payload) if available else None,
        "source": _safe(source), "timestamp": _safe(timestamp),
        "freshness": _safe(freshness) if freshness is not None else ("unknown" if available else "unavailable"),
        "coverage": _safe(coverage), "sources": _safe(sources), "warnings": warnings,
    }, sources


def build_crypto_evidence(context: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
    """Return bounded sections, flattened sources, coverage and warnings."""

    if not isinstance(context, Mapping):
        raise TypeError("crypto research context must be a mapping")
    nested = context.get("sections")
    top_coverage = context.get("coverage")
    sections, sources, missing = {}, [], []
    for name in SECTIONS:
        raw = context.get(name)
        if raw is None and isinstance(nested, Mapping):
            raw = nested.get(name)
        fallback = top_coverage.get(name) if isinstance(top_coverage, Mapping) else None
        section, section_sources = _section(name, raw, fallback)
        sections[name] = section
        sources.extend(item for item in section_sources if item not in sources)
        if not section["available"]:
            missing.append(name)
    warnings = _warnings(context.get("warnings"))
    for item in context.get("sources", []) if isinstance(context.get("sources"), list) else []:
        if isinstance(item, Mapping):
            safe_item = dict(_safe(item))
            if safe_item not in sources:
                sources.append(safe_item)
    for section in sections.values():
        warnings.extend(item for item in section["warnings"] if item not in warnings)
    available = [name for name in SECTIONS if sections[name]["available"]]
    coverage = {
        **{name: sections[name]["coverage"] for name in SECTIONS},
        "status": "complete" if not missing else "partial" if available else "unavailable",
        "available_sections": available, "missing_sections": missing, "required_sections": list(SECTIONS),
    }
    return {"version": EVIDENCE_VERSION, "sections": sections, "missing_sections": missing}, sources, coverage, warnings[:64]


def persist_crypto_research_report(
    db: Session,
    *,
    context: Mapping[str, Any],
    asset_id: int,
    title: str,
    instrument_id: int | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    idempotency_key: str | None = None,
    generator: Callable[..., tuple[str, str]] | None = None,
    tier: str = "medium",
) -> CryptoResearchReport:
    """Generate once from persisted context and return the idempotent row."""

    if not isinstance(asset_id, int) or isinstance(asset_id, bool) or asset_id <= 0:
        raise ValueError("asset_id must be a positive integer")
    if instrument_id is not None and (not isinstance(instrument_id, int) or isinstance(instrument_id, bool) or instrument_id <= 0):
        raise ValueError("instrument_id must be a positive integer")
    title = str(title).strip()
    if not title or len(title) > 256:
        raise ValueError("title must be 1-256 characters")
    if period_start and period_end and period_start > period_end:
        raise ValueError("period_start must not be after period_end")
    manifest, sources, coverage, warnings = build_crypto_evidence(context)
    key = idempotency_key or "crypto-research:" + _hash({
        "asset_id": asset_id, "instrument_id": instrument_id, "title": title,
        "period_start": period_start, "period_end": period_end, "evidence": manifest,
    })
    if len(key) > 128:
        raise ValueError("idempotency_key must be 1-128 characters")
    existing = db.scalar(select(CryptoResearchReport).where(CryptoResearchReport.idempotency_key == key))
    if existing is not None:
        return existing
    envelope = {"report_type": REPORT_TYPE, "title": title, "period": {"start": _safe(period_start), "end": _safe(period_end)}, "evidence": manifest, "coverage": coverage, "warnings": warnings}
    generated = (generator or generate_analysis)(
        title, json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2), tier=tier, report_type=REPORT_TYPE
    )
    if not isinstance(generated, tuple) or len(generated) != 2:
        raise TypeError("crypto report generator must return (content, model)")
    content, model = str(generated[0]).strip(), generated[1]
    if not content:
        raise ValueError("crypto report generator returned empty content")
    row = CryptoResearchReport(
        idempotency_key=key, asset_id=asset_id, instrument_id=instrument_id, title=title,
        content=content, model=str(model)[:128] if model is not None else None,
        sources=_safe(sources), evidence_manifest=_safe(manifest), coverage=_safe(coverage),
        warnings=_safe(warnings), period_start=period_start, period_end=period_end,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        duplicate = db.scalar(select(CryptoResearchReport).where(CryptoResearchReport.idempotency_key == key))
        if duplicate is not None:
            return duplicate
        raise
    return row
