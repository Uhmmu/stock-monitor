"""Equal-weight v1 synthetic indexes for canonical base leaves."""

from __future__ import annotations

from datetime import date, timedelta
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IndustryPulseInstrument, IndustryPulseNode, IndustrySyntheticIndex
from app.services.industry_pulse.calculation import calculate_constituent_breadth, calculate_etf_metrics


METHODOLOGY_VERSION = "equal_weight_v1"


def calculate_equal_weight_index(histories: dict[str, list[dict]], *, expected: int = 5) -> list[dict]:
    returns: dict[str, dict[date, float]] = {}
    for symbol, rows in histories.items():
        ordered = sorted(rows, key=lambda row: row["date"])
        returns[symbol] = {
            current["date"]: current.get("adjusted_close") or current["close"]
            for current in ordered
        }
    days = sorted({day for values in returns.values() for day in values})
    previous: dict[str, float] = {}
    index_value = 100.0
    started = False
    output: list[dict] = []
    for day in days:
        daily = []
        for symbol, values in returns.items():
            value = values.get(day)
            if value is None:
                continue
            if symbol in previous and previous[symbol] > 0:
                daily.append(value / previous[symbol] - 1)
            previous[symbol] = value
        if not started and len(previous) >= 4:
            started = True
            output.append({"date": day, "index_value": 100.0, "daily_return": None, "valid_constituents": len(previous), "expected_constituents": expected, "coverage_quality": min(1.0, len(previous) / expected), "calculation_status": "READY" if len(previous) == expected else "DEGRADED"})
            continue
        if not started:
            continue
        valid = len(daily)
        coverage = min(1.0, valid / expected)
        if valid >= 4:
            daily_return = sum(daily) / valid
            index_value *= 1 + daily_return
            status = "READY" if valid == expected else "DEGRADED"
        else:
            daily_return, status = None, "INSUFFICIENT_COVERAGE"
        output.append({"date": day, "index_value": index_value if daily_return is not None else None, "daily_return": daily_return, "valid_constituents": valid, "expected_constituents": expected, "coverage_quality": coverage, "calculation_status": status})
    return output


def persist_leaf_indexes(db: Session, histories: dict[str, list[dict]], *, as_of: date | None = None) -> dict:
    leaves = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "leaf")).all()
    mappings = db.scalars(select(IndustryPulseInstrument).where(
        IndustryPulseInstrument.node_id.in_([leaf.id for leaf in leaves]),
        IndustryPulseInstrument.classification_source == "MANUAL_CURATED_SEED",
        IndustryPulseInstrument.seed_version == 1,
    )).all()
    by_node: dict[int, list[IndustryPulseInstrument]] = {}
    for mapping in mappings:
        by_node.setdefault(mapping.node_id, []).append(mapping)
    latest_by_node = dict(db.execute(select(IndustrySyntheticIndex.node_id, func.max(IndustrySyntheticIndex.trading_date)).where(IndustrySyntheticIndex.node_id.in_([leaf.id for leaf in leaves])).group_by(IndustrySyntheticIndex.node_id)).all())
    cutoff = min(latest_by_node.values()) - timedelta(days=10) if len(latest_by_node) == len(leaves) and latest_by_node else None
    existing_query = select(IndustrySyntheticIndex).where(IndustrySyntheticIndex.node_id.in_([leaf.id for leaf in leaves]))
    if cutoff:
        existing_query = existing_query.where(IndustrySyntheticIndex.trading_date >= cutoff)
    existing = {(row.node_id, row.trading_date): row for row in db.scalars(existing_query).all()}
    ready = degraded = insufficient = written = 0
    for leaf in leaves:
        members = by_node.get(leaf.id, [])
        leaf_histories = {
            mapping.ticker: [row for row in histories.get(mapping.ticker, []) if (mapping.valid_from is None or row["date"] >= mapping.valid_from) and (mapping.valid_to is None or row["date"] <= mapping.valid_to)]
            for mapping in members
        }
        points = calculate_equal_weight_index(leaf_histories)
        synthetic_rows = [{"date": point["date"], "open": point["index_value"], "high": point["index_value"], "low": point["index_value"], "close": point["index_value"], "volume": None} for point in points if point["index_value"] is not None]
        metrics = calculate_etf_metrics(synthetic_rows, as_of=as_of) if synthetic_rows else {}
        breadth = calculate_constituent_breadth(leaf_histories, {symbol: 1 / max(1, len(leaf_histories)) for symbol in leaf_histories}, as_of=as_of)
        latest_existing = latest_by_node.get(leaf.id)
        write_points = [point for point in points if latest_existing is None or point["date"] >= latest_existing - timedelta(days=10)]
        for index, point in enumerate(write_points):
            key = (leaf.id, point["date"])
            row = existing.get(key)
            if row is None:
                row = IndustrySyntheticIndex(node_id=leaf.id, trading_date=point["date"])
                db.add(row)
            row.index_value = point["index_value"]
            row.daily_return = point["daily_return"]
            row.valid_constituents = point["valid_constituents"]
            row.expected_constituents = point["expected_constituents"]
            row.coverage_quality = point["coverage_quality"]
            row.calculation_status = point["calculation_status"]
            row.methodology_version = METHODOLOGY_VERSION
            payload = {"weighting": "equal", "base_index": 100}
            if index == len(write_points) - 1:
                payload.update({"metrics": metrics, "breadth": breadth})
            row.metrics_json = json.loads(json.dumps(payload, default=str))
            written += 1
        status = points[-1]["calculation_status"] if points else "INSUFFICIENT_COVERAGE"
        ready += int(status == "READY")
        degraded += int(status == "DEGRADED")
        insufficient += int(status == "INSUFFICIENT_COVERAGE")
        db.flush()
    return {"leaf_count": len(leaves), "written": written, "ready": ready, "degraded": degraded, "insufficient": insufficient}
