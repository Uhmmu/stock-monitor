from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Portfolio,
    PortfolioPosition,
    Security,
    StockDiscoveryCandidate,
    StockDiscoveryCandidateGroup,
    StockDiscoveryCandidateGroupMembership,
    StockDiscoveryCandidateMetric,
    StockDiscoveryExposure,
    StockDiscoveryFilterResult,
    StockDiscoveryFlowDirection,
    StockDiscoveryMarketContext,
    StockDiscoveryPortfolioSnapshot,
    StockDiscoveryRawPayload,
    StockDiscoveryRun,
    StockDiscoverySettings,
    StockDiscoverySource,
    StockDiscoveryUsage,
    WatchlistItem,
)

from .context import build_portfolio_context
from .normalization import apply_filters, enrich_candidate, resolve_local_symbol
from .perplexity import AgentResult, PerplexityError, _message_text, _tool_outputs, build_request, run_agent
from .schemas import DiscoveryResult, DiscoverySettingsUpdate, FILTER_VERSION, PROMPT_VERSION, SCHEMA_VERSION


TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "blocked_by_budget"}
SUCCESS_STATUSES = {"completed", "completed_with_warnings"}
ACTIVE_STATUSES = {"pending", "running"}

GROUP_LABELS = {
    "strong_flow": "资金加速", "quality_core": "优质核心资产",
    "portfolio_complement": "组合补缺", "contrarian": "逆向关注",
    "early_theme": "早期方向", "defensive": "防御补充", "watch_only": "仅观察",
}

MODEL_PRICING_PER_MILLION = {
    "perplexity/sonar": (.25, 2.5),
    "openai/gpt-5-mini": (.25, 2.0),
    "openai/gpt-5.4-mini": (.75, 4.5),
    "openai/gpt-5.4": (2.5, 15.0),
    "anthropic/claude-sonnet-4-6": (3.0, 15.0),
}


class DiscoveryCooldownError(RuntimeError):
    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"请等待 {seconds} 秒后再重新运行")


def _now() -> datetime:
    return datetime.now(UTC)


def _settings_defaults() -> dict:
    env = get_settings()
    return {
        "model": env.perplexity_agent_model,
        "enable_web_search": env.perplexity_enable_web_search,
        "max_steps": env.perplexity_max_steps,
        "max_output_tokens": env.perplexity_max_output_tokens,
        "monthly_budget_usd": env.perplexity_max_monthly_budget_usd,
        "max_run_cost_usd": env.perplexity_max_run_cost_usd,
        "min_market_cap": 2_000_000_000.0,
        "exclude_current_holdings": True,
        "exclude_watchlist": False,
        "require_positive_fcf": True,
        "max_trailing_pe": 80.0,
        "max_forward_pe": 60.0,
        "max_price_to_sales": 25.0,
        "filter_extreme_momentum": True,
        "missing_data_policy": "warn",
    }


def discovery_settings(db: Session, user_id: int) -> StockDiscoverySettings:
    row = db.scalar(select(StockDiscoverySettings).where(StockDiscoverySettings.user_id == user_id))
    if row is None:
        row = StockDiscoverySettings(user_id=user_id, **_settings_defaults())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_discovery_settings(db: Session, user_id: int, payload: DiscoverySettingsUpdate) -> StockDiscoverySettings:
    row = discovery_settings(db, user_id)
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(row, field, value)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def settings_payload(db: Session, user_id: int) -> dict:
    row = discovery_settings(db, user_id)
    values = {key: getattr(row, key) for key in _settings_defaults()}
    values.update({
        "api_key_configured": bool(get_settings().perplexity_api_key.strip()),
        "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
        "filter_version": FILTER_VERSION,
    })
    return values


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_spend(db: Session, user_id: int, now: datetime | None = None) -> float:
    now = now or _now()
    value = db.scalar(select(func.coalesce(func.sum(StockDiscoveryUsage.total_cost_usd), 0.0))
        .join(StockDiscoveryRun, StockDiscoveryRun.id == StockDiscoveryUsage.run_id)
        .where(StockDiscoveryRun.user_id == user_id, StockDiscoveryRun.requested_at >= _month_start(now)))
    return float(value or 0)


def estimate_max_cost(context: dict, settings: StockDiscoverySettings) -> float:
    input_rate, output_rate = MODEL_PRICING_PER_MILLION.get(settings.model, (5.0, 30.0))
    input_tokens = max(1000, len(json.dumps(context, ensure_ascii=False, default=str)) // 3)
    model = input_tokens / 1_000_000 * input_rate + settings.max_output_tokens / 1_000_000 * output_rate
    enabled_tools = 1 + int(settings.enable_web_search)
    tools = settings.max_steps * enabled_tools * .005
    return round(model + tools, 6)


def _latest_success(db: Session, user_id: int) -> StockDiscoveryRun | None:
    return db.scalar(select(StockDiscoveryRun).where(
        StockDiscoveryRun.user_id == user_id, StockDiscoveryRun.status.in_(SUCCESS_STATUSES),
    ).order_by(StockDiscoveryRun.completed_at.desc()).limit(1))


def _latest_run(db: Session, user_id: int) -> StockDiscoveryRun | None:
    return db.scalar(select(StockDiscoveryRun).where(StockDiscoveryRun.user_id == user_id)
                     .order_by(StockDiscoveryRun.requested_at.desc(), StockDiscoveryRun.id.desc()).limit(1))


def create_discovery_run(db: Session, portfolio: Portfolio, user_id: int) -> tuple[StockDiscoveryRun, bool]:
    now = _now()
    config = discovery_settings(db, user_id)
    active = db.scalar(select(StockDiscoveryRun).where(
        StockDiscoveryRun.user_id == user_id, StockDiscoveryRun.status.in_(ACTIVE_STATUSES),
    ).order_by(StockDiscoveryRun.requested_at.desc()).limit(1))
    if active:
        return active, False
    last = _latest_run(db, user_id)
    cooldown = get_settings().perplexity_manual_refresh_cooldown_seconds
    if last and last.requested_at:
        requested = last.requested_at if last.requested_at.tzinfo else last.requested_at.replace(tzinfo=UTC)
        remaining = cooldown - int((now - requested).total_seconds())
        if remaining > 0:
            raise DiscoveryCooldownError(remaining)

    context, context_hash = build_portfolio_context(db, portfolio, user_id)
    latest_success = _latest_success(db, user_id)
    bucket = now.strftime("%Y%m%d%H%M")
    idempotency_key = hashlib.sha256(f"{user_id}:manual:{bucket}:{context_hash}".encode()).hexdigest()
    existing = db.scalar(select(StockDiscoveryRun).where(StockDiscoveryRun.idempotency_key == idempotency_key))
    if existing:
        return existing, False
    estimated = estimate_max_cost(context, config)
    spent = monthly_spend(db, user_id, now)
    budget_reason = None
    if estimated > config.max_run_cost_usd:
        budget_reason = f"保守预估单次成本 ${estimated:.4f} 超过单次上限 ${config.max_run_cost_usd:.4f}"
    elif spent + estimated > config.monthly_budget_usd:
        budget_reason = f"本月已用 ${spent:.4f}，保守预估本次 ${estimated:.4f}，超过月度上限 ${config.monthly_budget_usd:.4f}"
    status = "blocked_by_budget" if budget_reason else "pending"
    run = StockDiscoveryRun(
        user_id=user_id, portfolio_id=portfolio.id,
        previous_successful_run_id=latest_success.id if latest_success else None,
        idempotency_key=idempotency_key, trigger="manual", status=status,
        stage="budget_check" if budget_reason else "preparing_portfolio",
        requested_at=now, completed_at=now if budget_reason else None,
        model_requested=config.model, portfolio_snapshot_hash=context_hash,
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, filter_version=FILTER_VERSION,
        failure_code="budget_exceeded" if budget_reason else None,
        failure_reason=budget_reason,
        next_scheduled_at=None,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(StockDiscoveryRun).where(StockDiscoveryRun.idempotency_key == idempotency_key)), False
    db.add(StockDiscoveryPortfolioSnapshot(run_id=run.id, context_hash=context_hash, payload=context))
    db.commit()
    db.refresh(run)
    return run, not bool(budget_reason)


def _persist_usage(db: Session, run_id: int, result: AgentResult) -> None:
    db.add(StockDiscoveryUsage(
        run_id=run_id, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        total_tokens=result.total_tokens, finance_search_calls=result.finance_search_calls,
        web_search_calls=result.web_search_calls, tool_cost_usd=result.tool_cost_usd,
        model_cost_usd=result.model_cost_usd, total_cost_usd=result.total_cost_usd,
        raw_usage=result.usage,
    ))


def _persist_failed_agent_payload(db: Session, run_id: int, payload: dict) -> None:
    """Preserve billable malformed/partial responses for audit and budgeting."""
    tools, finance_calls, web_calls = _tool_outputs(payload)
    usage = payload.get("usage") or {}
    costs = usage.get("cost") or {}
    total_cost = float(costs.get("total_cost") or 0)
    tool_cost = float(costs.get("tool_calls_cost") or 0)
    model_cost = float(costs.get("input_cost") or 0) + float(costs.get("output_cost") or 0)
    if model_cost == 0 and total_cost:
        model_cost = max(0.0, total_cost - tool_cost)
    db.add(StockDiscoveryRawPayload(run_id=run_id, response_json=payload,
        output_text=_message_text(payload), parsed_json={}, tool_results=tools))
    db.add(StockDiscoveryUsage(run_id=run_id, input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0), total_tokens=int(usage.get("total_tokens") or 0),
        finance_search_calls=finance_calls, web_search_calls=web_calls, tool_cost_usd=tool_cost,
        model_cost_usd=model_cost, total_cost_usd=total_cost, raw_usage=usage))
    _persist_tool_sources(db, run_id, tools)
    _persist_annotations(db, run_id, payload)


def _persist_tool_sources(db: Session, run_id: int, tool_results: list[dict]) -> None:
    seen: set[str] = set()
    for output in tool_results:
        origin = "perplexity_finance" if output.get("type") == "finance_results" else "perplexity_web"
        for result in output.get("results") or []:
            sources = result.get("sources") or []
            if isinstance(sources, list):
                for item in sources:
                    url = item if isinstance(item, str) else item.get("url")
                    title = "Perplexity Finance" if isinstance(item, str) else item.get("title") or ""
                    if url and url not in seen:
                        seen.add(url)
                        db.add(StockDiscoverySource(run_id=run_id, title=title, url=url, source_type="finance" if origin.endswith("finance") else "other", source_origin=origin))
            url = result.get("url")
            if url and url not in seen:
                seen.add(url)
                db.add(StockDiscoverySource(run_id=run_id, title=result.get("title") or "", url=url, source_type="other", source_origin=origin))


def _persist_annotations(db: Session, run_id: int, payload: dict) -> None:
    existing = set(db.scalars(select(StockDiscoverySource.url).where(StockDiscoverySource.run_id == run_id)).all())
    for output in payload.get("output") or []:
        for block in output.get("content") or []:
            for annotation in block.get("annotations") or []:
                url = annotation.get("url")
                if url and url not in existing:
                    existing.add(url)
                    db.add(StockDiscoverySource(run_id=run_id, title=annotation.get("title") or "",
                        url=url, source_type="other", source_origin="perplexity_web"))


def _persist_diagnosis(db: Session, run_id: int, result: DiscoveryResult) -> None:
    diagnosis = result.portfolio_diagnosis
    for order, item in enumerate(diagnosis.overweight_exposures):
        db.add(StockDiscoveryExposure(run_id=run_id, diagnosis_kind="overweight", exposure_type=item.exposure_type,
            name=item.name, level=item.severity, reasoning=item.evidence, suggested_action=item.suggested_action, display_order=order))
    for order, item in enumerate(diagnosis.underweight_or_missing_exposures):
        db.add(StockDiscoveryExposure(run_id=run_id, diagnosis_kind="missing", exposure_type=item.exposure_type,
            name=item.name, level=item.importance, reasoning=item.reason, suggested_action=item.suggested_action, display_order=order))
    for kind, values in (("strength", diagnosis.portfolio_strengths), ("vulnerability", diagnosis.portfolio_vulnerabilities)):
        for order, text in enumerate(values):
            db.add(StockDiscoveryExposure(run_id=run_id, diagnosis_kind=kind, name=text, level="medium", reasoning=text, display_order=order))
    flows = result.capital_flow_directions
    for order, item in enumerate(flows.strong_current_flows):
        db.add(StockDiscoveryFlowDirection(run_id=run_id, flow_type="strong", direction=item.direction,
            strength=item.strength, payload=item.model_dump(mode="json"), display_order=order))
    for order, item in enumerate(flows.weak_or_early_flows):
        db.add(StockDiscoveryFlowDirection(run_id=run_id, flow_type="early", direction=item.direction,
            strength=item.current_attention, payload=item.model_dump(mode="json"), display_order=order))


def _metric_discrepancy(raw_value: Any, local_value: Any) -> bool:
    try:
        raw_number, local_number = float(raw_value), float(local_value)
    except (TypeError, ValueError):
        return False
    denominator = max(abs(raw_number), abs(local_number), 1e-9)
    return abs(raw_number - local_number) / denominator >= .10


def _persist_metrics(
    db: Session,
    candidate: StockDiscoveryCandidate,
    raw: dict,
    local: dict,
    *,
    include_raw: bool = True,
) -> None:
    financial = raw.get("financial_snapshot") or {}
    if include_raw:
        for key, value in financial.items():
            if key in ("data_periods",) or value is None:
                continue
            db.add(StockDiscoveryCandidateMetric(candidate_id=candidate.id, metric_key=key,
                value=float(value) if isinstance(value, (int, float)) else None,
                text_value=value if isinstance(value, str) else None, source="perplexity_finance",
                data_period=", ".join(financial.get("data_periods") or []) or None,
                is_preferred=local.get(key) is None, has_discrepancy=_metric_discrepancy(value, local.get(key))))
    for key in ("price", "market_cap", "average_volume", "pe_trailing", "pe_forward", "price_to_sales",
                "revenue_growth", "earnings_growth", "gross_margin", "operating_margin", "free_cash_flow"):
        value = local.get(key)
        if value is None:
            continue
        discrepancy = _metric_discrepancy(financial.get(key), value)
        raw_metric = db.scalar(select(StockDiscoveryCandidateMetric).where(
            StockDiscoveryCandidateMetric.candidate_id == candidate.id,
            StockDiscoveryCandidateMetric.metric_key == key,
            StockDiscoveryCandidateMetric.source == "perplexity_finance",
        ))
        if raw_metric:
            raw_metric.is_preferred = False
            raw_metric.has_discrepancy = discrepancy
        db.add(StockDiscoveryCandidateMetric(candidate_id=candidate.id, metric_key=key, value=float(value),
            source="yfinance", data_period=local.get("free_cash_flow_period") if key == "free_cash_flow" else local.get("as_of"),
            is_preferred=True, has_discrepancy=discrepancy))


def _persist_candidates(db: Session, run: StockDiscoveryRun, parsed: DiscoveryResult, config: StockDiscoverySettings) -> list[str]:
    held = set(db.scalars(select(PortfolioPosition.symbol).where(
        PortfolioPosition.portfolio_id == run.portfolio_id, PortfolioPosition.total_quantity > 0)).all())
    watched = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
    groups: dict[str, StockDiscoveryCandidateGroup] = {}
    for order, group in enumerate(parsed.candidate_groups):
        if group.group_id in groups:
            continue
        row = StockDiscoveryCandidateGroup(run_id=run.id, group_id=group.group_id,
            group_name=GROUP_LABELS.get(group.group_type, group.group_name), group_type=group.group_type,
            summary=group.group_summary, display_order=order)
        db.add(row); db.flush(); groups[group.group_id] = row
    avoid_group = StockDiscoveryCandidateGroup(run_id=run.id, group_id="avoid_or_overheated",
        group_name="已过滤与过热候选", group_type="watch_only", summary="Perplexity 原始规避或过热清单", display_order=len(groups))
    db.add(avoid_group); db.flush(); groups[avoid_group.group_id] = avoid_group
    # Expose the Agent-produced grouping before potentially slow local/Yahoo
    # verification. A previous successful result still remains the primary
    # display while a replacement run is active.
    db.commit()

    canonical: dict[str, StockDiscoveryCandidate] = {}
    warnings: list[str] = []
    seen_memberships: set[tuple[int, int]] = set()
    raw_rank = 0
    for group in parsed.candidate_groups:
        for position, item_model in enumerate(group.candidates):
            raw_rank += 1
            raw = item_model.model_dump(mode="json")
            ticker, match_reason, security = resolve_local_symbol(db, raw["ticker"], raw.get("exchange"))
            key = ticker or f"raw:{raw['ticker'].upper()}:{raw.get('company_name', '').casefold()}"
            candidate = canonical.get(key)
            new_candidate = candidate is None
            if candidate is None:
                decision = apply_filters(raw=raw, local={}, ticker=ticker, settings=config,
                    held_symbols=held, watched_symbols=watched, symbol_valid=ticker is not None)
                candidate = StockDiscoveryCandidate(run_id=run.id, raw_ticker=raw["ticker"], normalized_ticker=ticker,
                    canonical_key=key, company_name=raw.get("company_name") or raw["ticker"],
                    exchange=raw.get("exchange"), country=raw.get("country"), raw_rank=raw_rank,
                    candidate_priority=raw.get("candidate_priority", "medium"),
                    symbol_match_status="matched_local" if security else ("normalized" if ticker else "unsupported"),
                    symbol_match_reason=match_reason, filter_status=decision.status, display_status=decision.status,
                    verification_status="pending" if ticker else "failed", raw_data={**raw, "appearances": []},
                    normalized_data={"ticker": ticker, "security_id": security.id if security else None}, local_data={})
                db.add(candidate); db.flush(); canonical[key] = candidate
                db.add(StockDiscoveryFilterResult(candidate_id=candidate.id, status=decision.status,
                    reasons=decision.reasons, details=decision.details, filter_version=FILTER_VERSION))
                _persist_metrics(db, candidate, raw, {})
                for source in raw.get("sources") or []:
                    url = source.get("url")
                    if url:
                        db.add(StockDiscoverySource(run_id=run.id, candidate_id=candidate.id,
                            title=source.get("title") or "", url=url, source_type=source.get("source_type") or "other",
                            source_origin="perplexity_finance" if source.get("source_type") == "finance" else "perplexity_web"))
            appearances = list(candidate.raw_data.get("appearances") or [])
            appearances.append({"group_id": group.group_id, "group_type": group.group_type,
                                "reason": raw.get("discovery_reason"), "raw_order": position})
            candidate.raw_data = {**candidate.raw_data, "appearances": appearances}
            membership_key = (candidate.id, groups[group.group_id].id)
            if membership_key not in seen_memberships:
                seen_memberships.add(membership_key)
                db.add(StockDiscoveryCandidateGroupMembership(candidate_id=candidate.id, group_id=groups[group.group_id].id,
                    original_reason=raw.get("discovery_reason") or "", raw_order=position))
            # Candidate and membership are now queryable by the polling UI.
            db.commit()

            if new_candidate and ticker:
                local, verification = enrich_candidate(db, ticker, raw)
                decision = apply_filters(raw=raw, local=local, ticker=ticker, settings=config,
                    held_symbols=held, watched_symbols=watched, symbol_valid=True)
                candidate.company_name = local.get("company_name") or candidate.company_name
                candidate.filter_status = decision.status
                candidate.display_status = decision.status
                candidate.verification_status = verification
                candidate.local_data = local
                candidate.verified_at = _now() if verification in ("verified", "partial") else None
                filter_row = db.scalar(select(StockDiscoveryFilterResult).where(
                    StockDiscoveryFilterResult.candidate_id == candidate.id))
                filter_row.status = decision.status
                filter_row.reasons = decision.reasons
                filter_row.details = decision.details
                # The Perplexity metrics were committed above. Persist only the
                # preferred local facts here so the source uniqueness constraint
                # remains an audit aid rather than a retry hazard.
                _persist_metrics(db, candidate, raw, local, include_raw=False)
                db.commit()
                if verification != "verified":
                    warnings.append(f"{ticker} 本地数据仅部分验证")
            elif new_candidate:
                warnings.append(f"{raw['ticker']} 股票代码无法在本地验证")

    for position, avoid in enumerate(parsed.avoid_or_overheated):
        raw = avoid.model_dump(mode="json")
        ticker, match_reason, security = resolve_local_symbol(db, raw["ticker"], None)
        key = ticker or f"raw:{raw['ticker'].upper()}:{raw.get('company_name', '').casefold()}"
        candidate = canonical.get(key)
        if candidate is None:
            candidate = StockDiscoveryCandidate(run_id=run.id, raw_ticker=raw["ticker"], normalized_ticker=ticker,
                canonical_key=key, company_name=raw.get("company_name") or raw["ticker"], raw_rank=raw_rank + position + 1,
                candidate_priority="low", symbol_match_status="matched_local" if security else ("normalized" if ticker else "unsupported"),
                symbol_match_reason=match_reason, filter_status="watch_only", display_status="watch_only",
                verification_status="pending", raw_data={**raw, "is_avoid": True, "appearances": []}, normalized_data={"ticker": ticker}, local_data={})
            db.add(candidate); db.flush(); canonical[key] = candidate
            db.add(StockDiscoveryFilterResult(candidate_id=candidate.id, status="watch_only",
                reasons=[raw.get("reason") or "Perplexity 标记为规避或过热"], details={"reconsideration_condition": raw.get("reconsideration_condition")}, filter_version=FILTER_VERSION))
        db.add(StockDiscoveryCandidateGroupMembership(candidate_id=candidate.id, group_id=avoid_group.id,
            original_reason=raw.get("reason") or "", raw_order=position))
        db.commit()
    final = [row for row in canonical.values() if row.display_status in ("accepted", "accepted_with_warning")]
    final.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row.candidate_priority, 3), row.raw_rank or 999))
    for rank, row in enumerate(final, 1): row.final_rank = rank
    return list(dict.fromkeys(warnings))


def execute_discovery_run(db: Session, run_id: int) -> StockDiscoveryRun:
    # The Redis lock is the cross-worker fast path; this row lock is the durable
    # fallback and makes a duplicate delivery harmless.
    run = db.scalar(select(StockDiscoveryRun).where(StockDiscoveryRun.id == run_id).with_for_update())
    if not run or run.status != "pending":
        return run
    config = discovery_settings(db, run.user_id)
    snapshot = db.scalar(select(StockDiscoveryPortfolioSnapshot).where(StockDiscoveryPortfolioSnapshot.run_id == run.id))
    run.status = "running"; run.stage = "analyzing_portfolio"; run.started_at = run.started_at or _now(); db.commit()
    try:
        request = build_request(context=snapshot.payload, model=config.model, max_steps=config.max_steps,
            max_output_tokens=config.max_output_tokens, enable_web_search=config.enable_web_search)
        run.stage = "searching_finance"; db.commit()
        result = run_agent(request)
        run.stage = "normalizing_candidates"; run.model_used = result.model; run.analysis_date = result.parsed.analysis_date
        db.add(StockDiscoveryRawPayload(run_id=run.id, response_json=result.raw_response,
            output_text=result.output_text, parsed_json=result.parsed.model_dump(mode="json"), tool_results=result.tool_results))
        _persist_usage(db, run.id, result); _persist_tool_sources(db, run.id, result.tool_results)
        _persist_annotations(db, run.id, result.raw_response)
        db.add(StockDiscoveryMarketContext(run_id=run.id, summary=result.parsed.market_context.summary,
            risk_regime=result.parsed.market_context.risk_regime, payload=result.parsed.market_context.model_dump(mode="json")))
        _persist_diagnosis(db, run.id, result.parsed)
        db.commit()
        run.stage = "local_verification"; db.commit()
        warnings = _persist_candidates(db, run, result.parsed, config)
        if result.total_cost_usd > config.max_run_cost_usd:
            warnings.append(f"实际成本 ${result.total_cost_usd:.4f} 超过配置的单次预警线 ${config.max_run_cost_usd:.4f}；后续运行仍受预算保护。")
        run.warnings = warnings
        run.status = "completed_with_warnings" if warnings else "completed"
        run.stage = "completed"; run.completed_at = _now(); run.next_scheduled_at = None
        db.commit(); db.refresh(run); return run
    except PerplexityError as exc:
        db.rollback(); run = db.get(StockDiscoveryRun, run_id)
        if exc.raw_response and not db.scalar(select(StockDiscoveryRawPayload.id).where(StockDiscoveryRawPayload.run_id == run_id)):
            _persist_failed_agent_payload(db, run_id, exc.raw_response)
        if exc.retryable:
            run.status = "pending"; run.stage = "retrying"; run.failure_code = exc.code
            run.failure_reason = str(exc)[:1000]; db.commit()
            raise
        run.status = "failed"; run.stage = "failed"; run.completed_at = _now(); run.failure_code = exc.code
        run.failure_reason = str(exc)[:1000]; db.commit()
        return run
    except Exception as exc:
        db.rollback(); run = db.get(StockDiscoveryRun, run_id)
        run.status = "failed"; run.stage = "failed"; run.completed_at = _now(); run.failure_code = "local_processing_failed"
        run.failure_reason = "本地验证或持久化失败"; db.commit()
        raise


def _run_payload(run: StockDiscoveryRun | None) -> dict | None:
    if not run: return None
    return {key: getattr(run, key) for key in (
        "id", "status", "stage", "trigger", "requested_at", "started_at", "completed_at", "analysis_date",
        "next_scheduled_at", "model_requested", "model_used", "prompt_version", "schema_version", "filter_version",
        "warnings", "failure_code", "failure_reason", "previous_successful_run_id",
    )}


def _candidate_payload(db: Session, row: StockDiscoveryCandidate, memberships: list[dict], *, detail: bool = False) -> dict:
    filter_row = db.scalar(select(StockDiscoveryFilterResult).where(StockDiscoveryFilterResult.candidate_id == row.id))
    metrics = list(db.scalars(select(StockDiscoveryCandidateMetric).where(StockDiscoveryCandidateMetric.candidate_id == row.id)).all())
    preferred: dict[str, Any] = {}
    discrepancies: list[dict] = []
    grouped: dict[str, list[StockDiscoveryCandidateMetric]] = defaultdict(list)
    for metric in metrics: grouped[metric.metric_key].append(metric)
    for key, values in grouped.items():
        chosen = next((item for item in values if item.is_preferred), values[0])
        preferred[key] = chosen.value if chosen.value is not None else chosen.text_value
        if any(item.has_discrepancy for item in values) and len(values) > 1:
            discrepancies.append({"metric": key, "values": [{"source": item.source, "value": item.value if item.value is not None else item.text_value, "period": item.data_period} for item in values]})
    raw = row.raw_data or {}
    financial = {**(raw.get("financial_snapshot") or {}), **preferred}
    sources = list(db.scalars(select(StockDiscoverySource).where(StockDiscoverySource.candidate_id == row.id)).all())
    payload = {
        "id": row.id, "raw_ticker": row.raw_ticker, "normalized_ticker": row.normalized_ticker,
        "company_name": row.company_name, "exchange": row.exchange, "country": row.country,
        "raw_rank": row.raw_rank, "final_rank": row.final_rank, "priority": row.candidate_priority,
        "symbol_match_status": row.symbol_match_status, "symbol_match_reason": row.symbol_match_reason,
        "filter_status": row.filter_status, "display_status": row.display_status,
        "filter_reasons": filter_row.reasons if filter_row else [], "filter_details": filter_row.details if filter_row else {},
        "verification_status": row.verification_status, "dismissed": row.dismissed, "researched": row.researched,
        "groups": memberships, "discovery_reason": raw.get("discovery_reason") or raw.get("reason"),
        "portfolio_fit": raw.get("portfolio_fit"), "diversification_effect": raw.get("diversification_effect"),
        "overlap_with_existing_holdings": raw.get("overlap_with_existing_holdings") or [],
        "business_quality_summary": raw.get("business_quality_summary"), "investment_thesis": raw.get("investment_thesis") or [],
        "capital_flow_context": raw.get("capital_flow_context"), "valuation_context": raw.get("valuation_context"), "why_now": raw.get("why_now"),
        "quality_level": raw.get("quality_level", "uncertain"), "valuation_level": raw.get("valuation_level", "uncertain"),
        "momentum_state": raw.get("momentum_state", "uncertain"), "confidence": raw.get("confidence"),
        "financial_snapshot": {key: value for key, value in financial.items() if value is not None and key != "data_periods"},
        "source_badges": sorted(set(item.source for item in metrics) | set(item.source_origin for item in sources)
            | set((row.local_data or {}).get("sources") or [])),
        "source_count": len(sources), "data_discrepancies": discrepancies,
        "major_risks": raw.get("major_risks") or [], "thesis_breakers": raw.get("thesis_breakers") or [],
        "reconsideration_condition": raw.get("reconsideration_condition"),
    }
    if detail:
        payload.update({"raw_analysis": raw, "local_verification": row.local_data,
            "sources": [{"title": item.title, "url": item.url, "source_type": item.source_type, "origin": item.source_origin} for item in sources],
            "facts_to_verify_locally": raw.get("facts_to_verify_locally") or [], "verified_at": row.verified_at})
    return payload


def discovery_run_payload(db: Session, run: StockDiscoveryRun, *, include_candidates: bool = True) -> dict:
    base = _run_payload(run) or {}
    usage = db.scalar(select(StockDiscoveryUsage).where(StockDiscoveryUsage.run_id == run.id))
    base["usage"] = ({key: getattr(usage, key) for key in (
        "input_tokens", "output_tokens", "total_tokens", "finance_search_calls", "web_search_calls",
        "tool_cost_usd", "model_cost_usd", "total_cost_usd") } if usage else None)
    if not include_candidates:
        return base
    groups = list(db.scalars(select(StockDiscoveryCandidateGroup).where(StockDiscoveryCandidateGroup.run_id == run.id)
                             .order_by(StockDiscoveryCandidateGroup.display_order)).all())
    memberships = list(db.execute(select(StockDiscoveryCandidateGroupMembership, StockDiscoveryCandidateGroup)
        .join(StockDiscoveryCandidateGroup, StockDiscoveryCandidateGroup.id == StockDiscoveryCandidateGroupMembership.group_id)
        .where(StockDiscoveryCandidateGroup.run_id == run.id).order_by(StockDiscoveryCandidateGroupMembership.raw_order)).all())
    membership_map: dict[int, list[dict]] = defaultdict(list)
    candidate_ids_by_group: dict[int, list[int]] = defaultdict(list)
    for membership, group in memberships:
        membership_map[membership.candidate_id].append({"id": group.group_id, "name": group.group_name, "type": group.group_type, "reason": membership.original_reason})
        candidate_ids_by_group[group.id].append(membership.candidate_id)
    candidates = list(db.scalars(select(StockDiscoveryCandidate).where(StockDiscoveryCandidate.run_id == run.id)
        .order_by(StockDiscoveryCandidate.final_rank.asc().nullslast(), StockDiscoveryCandidate.raw_rank)).all())
    candidate_map = {row.id: _candidate_payload(db, row, membership_map[row.id]) for row in candidates}
    exposures = list(db.scalars(select(StockDiscoveryExposure).where(StockDiscoveryExposure.run_id == run.id)
        .order_by(StockDiscoveryExposure.diagnosis_kind, StockDiscoveryExposure.display_order)).all())
    flows = list(db.scalars(select(StockDiscoveryFlowDirection).where(StockDiscoveryFlowDirection.run_id == run.id)
        .order_by(StockDiscoveryFlowDirection.flow_type, StockDiscoveryFlowDirection.display_order)).all())
    market = db.scalar(select(StockDiscoveryMarketContext).where(StockDiscoveryMarketContext.run_id == run.id))
    raw_payload = db.scalar(select(StockDiscoveryRawPayload).where(StockDiscoveryRawPayload.run_id == run.id))
    accepted_status = {"accepted", "accepted_with_warning"}
    base.update({
        "market_context": market.payload if market else {},
        "portfolio_diagnosis": {kind: [{"name": row.name, "exposure_type": row.exposure_type, "level": row.level,
            "reasoning": row.reasoning, "suggested_action": row.suggested_action} for row in exposures if row.diagnosis_kind == kind]
            for kind in ("overweight", "missing", "strength", "vulnerability")},
        "capital_flows": {kind: [row.payload for row in flows if row.flow_type == kind] for kind in ("strong", "early")},
        "groups": [{"id": group.group_id, "name": group.group_name, "type": group.group_type, "summary": group.summary,
            "candidates": [candidate_map[cid] for cid in candidate_ids_by_group[group.id] if candidate_map[cid]["display_status"] in accepted_status and not candidate_map[cid]["dismissed"]]}
            for group in groups if group.group_id != "avoid_or_overheated"],
        "raw_candidates": [candidate_map[row.id] for row in sorted(candidates, key=lambda item: item.raw_rank or 999)],
        "filtered_candidates": [candidate_map[row.id] for row in candidates if row.display_status not in accepted_status or row.dismissed],
        "counts": {"raw": len(candidates), "accepted": sum(row.display_status in accepted_status and not row.dismissed for row in candidates),
            "watch_only": sum(row.display_status == "watch_only" for row in candidates),
            "rejected": sum(row.display_status in ("rejected", "unsupported_symbol") for row in candidates)},
        "portfolio_actions": (raw_payload.parsed_json or {}).get("portfolio_actions_for_research", []) if raw_payload else [],
        "limitations": (raw_payload.parsed_json or {}).get("limitations", []) if raw_payload else [],
    })
    return base


def latest_discovery_payload(db: Session, user_id: int) -> dict:
    current = _latest_run(db, user_id)
    success = _latest_success(db, user_id)
    config = discovery_settings(db, user_id)
    partial_count = 0
    if not success and current and current.status in ACTIVE_STATUSES:
        partial_count = int(db.scalar(select(func.count(StockDiscoveryCandidate.id)).where(
            StockDiscoveryCandidate.run_id == current.id)) or 0)
    display_run = success or (current if partial_count else None)
    display = discovery_run_payload(db, display_run) if display_run else None
    return {
        "current_run": _run_payload(current), "result": display,
        "using_previous_result": bool(success and current and success.id != current.id and current.status in ACTIVE_STATUSES | {"failed", "blocked_by_budget"}),
        "api_key_configured": bool(get_settings().perplexity_api_key.strip()),
        "monthly_spend_usd": monthly_spend(db, user_id), "monthly_budget_usd": config.monthly_budget_usd,
    }


def candidate_detail_payload(db: Session, user_id: int, candidate_id: int) -> dict | None:
    row = db.scalar(select(StockDiscoveryCandidate).join(StockDiscoveryRun)
        .where(StockDiscoveryCandidate.id == candidate_id, StockDiscoveryRun.user_id == user_id))
    if not row: return None
    memberships = list(db.execute(select(StockDiscoveryCandidateGroupMembership, StockDiscoveryCandidateGroup)
        .join(StockDiscoveryCandidateGroup, StockDiscoveryCandidateGroup.id == StockDiscoveryCandidateGroupMembership.group_id)
        .where(StockDiscoveryCandidateGroupMembership.candidate_id == row.id)).all())
    groups = [{"id": group.group_id, "name": group.group_name, "type": group.group_type, "reason": membership.original_reason}
              for membership, group in memberships]
    return _candidate_payload(db, row, groups, detail=True)
