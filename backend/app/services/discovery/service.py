from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Portfolio,
    PortfolioPosition,
    OpportunityHistory,
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

from .context import build_local_research_context, build_portfolio_context
from .normalization import apply_filters, enrich_candidate, resolve_local_symbol
from .analysis import AnalysisError, AnalysisResult, analyze_opportunities
from .exa import ExaAgentResult, ExaError, build_request as build_exa_request, run_agent as run_exa_agent
from .perplexity import AgentResult, PerplexityError, build_request, run_agent
from .pi_agent import PiAgentError, PiAgentResult, build_request as build_pi_request, run_agent as run_pi_agent
from .progress import agent_events_payload
from .search import SearchError, SearchResult, build_search_queries, run_search
from .schemas import (
    DiscoveryResult,
    DiscoverySettingsUpdate,
    FILTER_VERSION,
    OpportunityBatch,
    PROMPT_VERSION,
    SCHEMA_VERSION,
)


TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "blocked_by_budget"}
SUCCESS_STATUSES = {"completed", "completed_with_warnings"}
ACTIVE_STATUSES = {"pending", "running"}

GROUP_LABELS = {
    "strong_flow": "资金加速", "quality_core": "优质核心资产",
    "portfolio_complement": "组合补缺", "contrarian": "逆向关注",
    "early_theme": "早期方向", "defensive": "防御补充", "watch_only": "仅观察",
}

MODEL_PRICING_PER_MILLION = {
    "openai/gpt-5.4": (2.5, 15.0),
    "openai/gpt-5.4-mini": (.75, 4.5),
}

EXA_FIXED_EFFORT_COST = {
    "minimal": .012,
    "low": .025,
    "medium": .10,
    "high": .50,
    "xhigh": 1.0,
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
        "discovery_mode": "search_local",
        "model": env.perplexity_agent_model,
        "enable_web_search": env.perplexity_enable_web_search,
        "max_steps": env.perplexity_max_steps,
        "max_output_tokens": env.perplexity_max_output_tokens,
        "monthly_budget_usd": env.perplexity_max_monthly_budget_usd,
        "max_run_cost_usd": env.perplexity_max_run_cost_usd,
        "min_market_cap": 2_000_000_000.0,
        "exclude_current_holdings": True,
        # Watched tickers the investor already knows about are downgraded to
        # watch_only by default; discovery is for finding NEW names.
        "exclude_watchlist": True,
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
        "exa_api_key_configured": bool(get_settings().exa_api_key.strip()),
        "analysis_api_key_configured": bool(get_settings().openai_api_key.strip()),
        "analysis_model": get_settings().model_important,
        "agent_model": row.model,
        "exa_agent_model": "exa-agent",
        "exa_agent_effort": get_settings().exa_agent_effort,
        "exa_finance_provider": "financial_datasets",
        "search_source": "perplexity_search",
        "pi_agent_ready": bool(
            get_settings().agent_gateway_token.strip()
            and get_settings().openai_api_key.strip()
        ),
        "pi_agent_model": get_settings().pi_agent_model.strip() or get_settings().model_important,
        "pi_agent_max_turns": get_settings().pi_agent_max_turns,
        "pi_agent_max_web_search_calls": get_settings().pi_agent_max_web_search_calls,
        "pi_agent_deep_effort": get_settings().pi_agent_deep_effort,
        "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
        "filter_version": FILTER_VERSION,
    })
    for legacy in ("model", "enable_web_search", "max_steps"):
        values.pop(legacy, None)
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
    if settings.discovery_mode == "search_local":
        return 0.005
    if settings.discovery_mode == "exa_finance":
        # Fixed Agent effort plus a conservative allowance for Exa web-search
        # and Financial Datasets provider calls during one discovery run.
        effort_cost = EXA_FIXED_EFFORT_COST.get(get_settings().exa_agent_effort, 1.0)
        return round(effort_cost + .15, 6)
    if settings.discovery_mode == "pi_agent":
        # Pi Agent: cheap Exa searches + one deep run (medium by default). The
        # project LLM endpoint does not report a reliable dollar cost.
        env = get_settings()
        search_cost = env.pi_agent_max_web_search_calls * .007
        deep_cost = EXA_FIXED_EFFORT_COST.get(env.pi_agent_deep_effort, .10)
        return round(search_cost + deep_cost, 6)
    input_rate, output_rate = MODEL_PRICING_PER_MILLION.get(settings.model, (5.0, 30.0))
    input_tokens = max(1000, len(json.dumps(context, ensure_ascii=False, default=str)) // 3)
    model_cost = (
        input_tokens / 1_000_000 * input_rate
        + settings.max_output_tokens / 1_000_000 * output_rate
    )
    enabled_tools = 1 + int(settings.enable_web_search)
    return round(model_cost + settings.max_steps * enabled_tools * .005, 6)


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
    idempotency_key = hashlib.sha256(
        f"{user_id}:manual:{config.discovery_mode}:{bucket}:{context_hash}".encode()
    ).hexdigest()
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
        idempotency_key=idempotency_key, trigger="manual",
        discovery_mode=config.discovery_mode, status=status,
        stage="budget_check" if budget_reason else "preparing_portfolio",
        requested_at=now, completed_at=now if budget_reason else None,
        model_requested=(
            get_settings().model_important
            if config.discovery_mode in ("search_local", "pi_agent")
            else ("exa-agent" if config.discovery_mode == "exa_finance" else config.model)
        ),
        portfolio_snapshot_hash=context_hash,
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


def _persist_pipeline_usage(
    db: Session, run_id: int, search: SearchResult, analysis: AnalysisResult
) -> None:
    row = db.scalar(select(StockDiscoveryUsage).where(StockDiscoveryUsage.run_id == run_id))
    if row is None:
        row = StockDiscoveryUsage(run_id=run_id)
        db.add(row)
    row.input_tokens = analysis.input_tokens
    row.output_tokens = analysis.output_tokens
    row.total_tokens = analysis.total_tokens
    row.finance_search_calls = 0
    row.web_search_calls = search.request_count
    row.tool_cost_usd = search.cost_usd
    # The project-level GPT endpoint does not expose a reliable dollar cost.
    row.model_cost_usd = 0.0
    row.total_cost_usd = search.cost_usd
    row.raw_usage = {
        "search_api_requests": search.request_count,
        "search_cost_usd": search.cost_usd,
        "analysis_model": analysis.model,
        "analysis_tokens": {
            "input": analysis.input_tokens,
            "output": analysis.output_tokens,
            "total": analysis.total_tokens,
        },
        "perplexity_model_tokens": 0,
    }


def _persist_pi_usage(db: Session, run_id: int, result: PiAgentResult) -> None:
    db.add(StockDiscoveryUsage(
        run_id=run_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        finance_search_calls=result.deep_search_calls,
        web_search_calls=result.web_search_calls,
        tool_cost_usd=result.tool_cost_usd,
        model_cost_usd=result.model_cost_usd,
        total_cost_usd=result.total_cost_usd,
        raw_usage={
            **result.usage,
            "provider": "pi_agent",
            "engine": "pi_agent",
            "deep_search_calls": result.deep_search_calls,
            "web_search_calls": result.web_search_calls,
            "internal_tool_calls": max(
                0, len(result.tool_results) - result.web_search_calls - result.deep_search_calls
            ),
        },
    ))


def _persist_pi_sources(db: Session, run_id: int, parsed: DiscoveryResult) -> None:
    seen: set[str] = set()
    for group in parsed.candidate_groups:
        for item in group.candidates:
            raw = item.model_dump(mode="json")
            for evidence in raw.get("evidence") or []:
                reference = str(evidence.get("url_or_reference") or "")
                if reference.startswith("http") and reference not in seen:
                    seen.add(reference)
                    db.add(StockDiscoverySource(
                        run_id=run_id, title=evidence.get("claim") or "",
                        url=reference, source_type=evidence.get("source_type") or "other",
                        source_origin="pi_agent_evidence",
                    ))
            for source in raw.get("sources") or []:
                url = source.get("url")
                if url and url not in seen:
                    seen.add(url)
                    db.add(StockDiscoverySource(
                        run_id=run_id, title=source.get("title") or "", url=url,
                        source_type=source.get("source_type") or "other",
                        source_origin="pi_agent",
                    ))


def _persist_agent_usage(db: Session, run_id: int, result: AgentResult) -> None:
    db.add(StockDiscoveryUsage(
        run_id=run_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        finance_search_calls=result.finance_search_calls,
        web_search_calls=result.web_search_calls,
        tool_cost_usd=result.tool_cost_usd,
        model_cost_usd=result.model_cost_usd,
        total_cost_usd=result.total_cost_usd,
        raw_usage=result.usage,
    ))


def _persist_exa_usage(db: Session, run_id: int, result: ExaAgentResult) -> None:
    db.add(StockDiscoveryUsage(
        run_id=run_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        # Retain the legacy columns while recording the exact Exa semantics in
        # raw_usage. The frontend labels these by engine.
        finance_search_calls=result.finance_data_calls,
        web_search_calls=result.web_search_calls,
        tool_cost_usd=result.tool_cost_usd,
        model_cost_usd=result.model_cost_usd,
        total_cost_usd=result.total_cost_usd,
        raw_usage={
            **result.usage,
            "provider": "exa",
            "financial_data_calls": result.finance_data_calls,
            "web_search_calls": result.web_search_calls,
        },
    ))


def _persist_exa_grounding(db: Session, run_id: int, grounding: list[dict]) -> None:
    seen: set[str] = set()
    for item in grounding:
        for citation in item.get("citations") or []:
            url = str(citation.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            db.add(StockDiscoverySource(
                run_id=run_id,
                title=str(citation.get("title") or ""),
                url=url,
                source_type="finance" if "financial" in str(item.get("field") or "").lower() else "other",
                source_origin="exa_grounding",
            ))


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


def _persist_search_sources(db: Session, run_id: int, results: list[dict]) -> None:
    seen: set[str] = set()
    for row in results:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        db.add(StockDiscoverySource(
            run_id=run_id,
            title=str(row.get("title") or ""),
            url=url,
            source_type="news",
            source_origin="perplexity_search",
        ))


_CATEGORY_GROUPS = {
    "估值错杀": ("valuation", "估值错杀", "contrarian"),
    "行业趋势": ("industry", "行业趋势", "early_theme"),
    "盈利改善": ("earnings", "盈利改善", "quality_core"),
    "事件驱动": ("event", "事件驱动", "strong_flow"),
    "技术反转": ("technical", "技术反转", "contrarian"),
    "长期成长": ("growth", "长期成长", "quality_core"),
}


def _as_legacy_result(batch: OpportunityBatch) -> DiscoveryResult:
    """Feed v0.5 analyst items through the existing local verification layer."""
    grouped: dict[str, list] = defaultdict(list)
    for item in batch.opportunities:
        grouped[item.category[0]].append(item)
    candidate_groups = []
    for category, items in grouped.items():
        group_id, group_name, group_type = _CATEGORY_GROUPS[category]
        candidates = []
        for item in items:
            evidence = [row.content for row in item.evidence]
            candidates.append({
                "ticker": item.ticker, "company_name": item.ticker,
                "exchange": None, "country": None, "sector": None, "industry": None,
                "market_cap": None, "currency": None,
                "discovery_reason": item.summary,
                "portfolio_fit": "需结合本地持仓与策略画像继续研究",
                "diversification_effect": "uncertain",
                "overlap_with_existing_holdings": [],
                "business_quality_summary": next(
                    (row.content for row in item.evidence if row.type == "financial"),
                    "本地财务数据不足",
                ),
                "investment_thesis": list(dict.fromkeys(item.why_now + item.catalysts + evidence)),
                "capital_flow_context": next(
                    (row.content for row in item.evidence if row.type == "market"), "数据不足"
                ),
                "valuation_context": item.valuation_view,
                "why_now": "；".join(item.why_now),
                "financial_snapshot": {
                    "price": None, "market_cap": None, "pe_trailing": None, "pe_forward": None,
                    "price_to_sales": None, "ev_to_ebitda": None, "revenue_growth": None,
                    "earnings_growth": None, "gross_margin": None, "operating_margin": None,
                    "free_cash_flow": None, "free_cash_flow_margin": None,
                    "return_on_invested_capital": None, "net_debt_or_cash": None,
                    "analyst_consensus": None, "data_periods": [],
                },
                "quality_level": "uncertain", "valuation_level": "uncertain",
                "momentum_state": "uncertain",
                "candidate_priority": "high" if item.confidence >= 75 else "medium" if item.confidence >= 55 else "low",
                "confidence": item.confidence / 100,
                "major_risks": item.risks, "thesis_breakers": item.risks,
                "facts_to_verify_locally": ["核对最新本地财务快照", "核对催化剂时间与来源"],
                "sources": [],
            })
        candidate_groups.append({
            "group_id": group_id, "group_name": group_name, "group_type": group_type,
            "group_summary": f"{len(items)} 个{group_name}研究机会", "candidates": candidates,
        })
    return DiscoveryResult.model_validate({
        "analysis_date": _now().date(),
        "market_context": {
            "summary": batch.market_condition, "risk_regime": "unknown",
            "liquidity_or_flow_summary": "由本地 GPT 基于原始搜索结果判断",
            "important_market_drivers": [],
            "data_limitations": ["Perplexity Search 仅提供原始检索结果，不参与分析。"],
        },
        "portfolio_diagnosis": {
            "overall_summary": "沿用本地组合数据进行候选过滤",
            "overweight_exposures": [], "underweight_or_missing_exposures": [],
            "portfolio_strengths": [], "portfolio_vulnerabilities": [],
        },
        "capital_flow_directions": {"strong_current_flows": [], "weak_or_early_flows": []},
        "candidate_groups": candidate_groups,
        "avoid_or_overheated": [], "portfolio_actions_for_research": [],
        "limitations": ["搜索结果不作为价格、估值、市值或财报数字来源。"],
    })


def _legacy_to_opportunity_batch(parsed: DiscoveryResult) -> OpportunityBatch:
    opportunities = []
    for group in parsed.candidate_groups:
        category = {
            "strong_flow": "事件驱动",
            "quality_core": "长期成长",
            "portfolio_complement": "行业趋势",
            "contrarian": "估值错杀",
            "early_theme": "行业趋势",
            "defensive": "长期成长",
            "watch_only": "等待确认",
        }.get(group.group_type, "行业趋势")
        for candidate in group.candidates:
            valid_category = category if category != "等待确认" else "行业趋势"
            evidence = []
            if candidate.business_quality_summary:
                evidence.append({"type": "financial", "content": candidate.business_quality_summary})
            if candidate.capital_flow_context:
                evidence.append({"type": "market", "content": candidate.capital_flow_context})
            if candidate.why_now:
                evidence.append({"type": "news", "content": candidate.why_now})
            if not evidence:
                evidence.append({"type": "market", "content": "数据不足，需进一步核对"})
            opportunities.append({
                "title": candidate.discovery_reason or f"{candidate.ticker} 研究机会",
                "ticker": candidate.ticker,
                "category": [valid_category],
                "summary": candidate.discovery_reason or "值得进一步研究",
                "why_now": [candidate.why_now or "需结合近期事件进一步确认"],
                "evidence": evidence,
                "catalysts": candidate.investment_thesis[:4],
                "risks": candidate.major_risks or ["数据覆盖不足"],
                "valuation_view": candidate.valuation_context or "数据不足",
                "confidence": round(candidate.confidence * 100),
                "action": ["等待确认" if candidate.candidate_priority == "low" else "深入研究"],
            })
    if not opportunities:
        raise ValueError("Agent 未返回可保存的机会")
    return OpportunityBatch.model_validate({
        "market_condition": parsed.market_context.summary or "数据不足",
        "opportunities": opportunities[:12],
    })


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


def _bounded_metric_period(value: Any) -> str | None:
    """Fit provider period labels into the legacy VARCHAR(64) display column.

    The complete provider payload remains preserved in StockDiscoveryRawPayload.
    """
    text = str(value).strip() if value is not None else ""
    return text[:64] or None


def _persist_metrics(
    db: Session,
    candidate: StockDiscoveryCandidate,
    raw: dict,
    local: dict,
    *,
    include_raw: bool = True,
    raw_source: str = "perplexity_finance",
) -> None:
    financial = raw.get("financial_snapshot") or {}
    raw_period = _bounded_metric_period(", ".join(financial.get("data_periods") or []))
    if include_raw:
        for key, value in financial.items():
            if key in ("data_periods",) or value is None:
                continue
            db.add(StockDiscoveryCandidateMetric(candidate_id=candidate.id, metric_key=key,
                value=float(value) if isinstance(value, (int, float)) else None,
                text_value=value if isinstance(value, str) else None, source=raw_source,
                data_period=raw_period,
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
            StockDiscoveryCandidateMetric.source == raw_source,
        ))
        if raw_metric:
            raw_metric.is_preferred = False
            raw_metric.has_discrepancy = discrepancy
        db.add(StockDiscoveryCandidateMetric(candidate_id=candidate.id, metric_key=key, value=float(value),
            source="yfinance", data_period=_bounded_metric_period(
                local.get("free_cash_flow_period") if key == "free_cash_flow" else local.get("as_of")
            ),
            is_preferred=True, has_discrepancy=discrepancy))


def _persist_candidates(
    db: Session,
    run: StockDiscoveryRun,
    parsed: DiscoveryResult,
    config: StockDiscoverySettings,
    *,
    raw_source: str = "perplexity_finance",
) -> list[str]:
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
        group_name="已过滤与过热候选", group_type="watch_only", summary="上游引擎原始规避或过热清单", display_order=len(groups))
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
                _persist_metrics(db, candidate, raw, {}, raw_source=raw_source)
                for source in raw.get("sources") or []:
                    url = source.get("url")
                    if url:
                        db.add(StockDiscoverySource(run_id=run.id, candidate_id=candidate.id,
                            title=source.get("title") or "", url=url, source_type=source.get("source_type") or "other",
                    source_origin=(
                        "exa_financial_datasets" if raw_source == "exa_finance" and source.get("source_type") == "finance"
                        else ("exa_web" if raw_source == "exa_finance" else (
                            "pi_agent_evidence" if raw_source == "pi_agent" else (
                                "perplexity_finance" if source.get("source_type") == "finance" else "perplexity_web"
                            )
                        ))
                    )))
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
                # The upstream metrics were committed above. Persist only the
                # preferred local facts here so the source uniqueness constraint
                # remains an audit aid rather than a retry hazard.
                _persist_metrics(db, candidate, raw, local, include_raw=False, raw_source=raw_source)
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
                reasons=[raw.get("reason") or "上游引擎标记为规避或过热"], details={"reconsideration_condition": raw.get("reconsideration_condition")}, filter_version=FILTER_VERSION))
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
    run.status = "running"; run.stage = "preparing_local_data"; run.started_at = run.started_at or _now(); db.commit()
    try:
        local_context = build_local_research_context(db, snapshot.payload)
        if run.discovery_mode == "pi_agent":
            env = get_settings()
            run.stage = "pi_planning"; db.commit()
            pi = run_pi_agent(build_pi_request(
                run_id=run.id,
                user_id=run.user_id,
                context=local_context,
                model=env.pi_agent_model.strip() or env.model_important,
                max_turns=env.pi_agent_max_turns,
                max_web_search_calls=env.pi_agent_max_web_search_calls,
                deep_effort=env.pi_agent_deep_effort,
                max_output_tokens=config.max_output_tokens,
            ))
            parsed = pi.parsed
            history_batch = _legacy_to_opportunity_batch(parsed)
            queries: list[str] = []
            run.model_used = pi.model
            db.add(StockDiscoveryRawPayload(
                run_id=run.id,
                response_json={"engine": "pi_agent", "usage": pi.usage, "events": pi.events[:200]},
                output_text=pi.output_text,
                parsed_json=parsed.model_dump(mode="json"),
                tool_results=pi.tool_results,
            ))
            _persist_pi_usage(db, run.id, pi)
            _persist_pi_sources(db, run.id, parsed)
            history_source = "pi_agent"
            measured_cost = pi.total_cost_usd
        elif run.discovery_mode == "exa_finance":
            run.stage = "running_exa_finance_agent"; db.commit()
            exa = run_exa_agent(build_exa_request(
                context=local_context,
                effort=get_settings().exa_agent_effort,
            ))
            parsed = exa.parsed
            history_batch = _legacy_to_opportunity_batch(parsed)
            queries = []
            run.model_used = exa.model
            db.add(StockDiscoveryRawPayload(
                run_id=run.id,
                response_json=exa.raw_response,
                output_text=exa.output_text,
                parsed_json=parsed.model_dump(mode="json"),
                tool_results=exa.grounding,
            ))
            _persist_exa_usage(db, run.id, exa)
            _persist_exa_grounding(db, run.id, exa.grounding)
            history_source = "exa_agent_financial_datasets"
            measured_cost = exa.total_cost_usd
        elif run.discovery_mode == "agent_finance":
            run.stage = "running_finance_agent"; db.commit()
            request = build_request(
                context=local_context,
                model=config.model,
                max_steps=config.max_steps,
                max_output_tokens=config.max_output_tokens,
                enable_web_search=config.enable_web_search,
            )
            agent = run_agent(request)
            parsed = agent.parsed
            history_batch = _legacy_to_opportunity_batch(parsed)
            queries: list[str] = []
            run.model_used = agent.model
            db.add(StockDiscoveryRawPayload(
                run_id=run.id,
                response_json=agent.raw_response,
                output_text=agent.output_text,
                parsed_json=parsed.model_dump(mode="json"),
                tool_results=agent.tool_results,
            ))
            _persist_agent_usage(db, run.id, agent)
            _persist_tool_sources(db, run.id, agent.tool_results)
            _persist_annotations(db, run.id, agent.raw_response)
            history_source = "perplexity_finance_agent"
            measured_cost = agent.total_cost_usd
        else:
            queries = build_search_queries(local_context)
            run.stage = "searching_market"; db.commit()
            search = run_search(queries)
            raw_payload = StockDiscoveryRawPayload(
                run_id=run.id,
                response_json={"search": search.raw_response},
                output_text="",
                parsed_json={},
                tool_results=search.results,
            )
            db.add(raw_payload)
            db.add(StockDiscoveryUsage(
                run_id=run.id, input_tokens=0, output_tokens=0, total_tokens=0,
                finance_search_calls=0, web_search_calls=search.request_count,
                tool_cost_usd=search.cost_usd, model_cost_usd=0.0,
                total_cost_usd=search.cost_usd,
                raw_usage={"search_api_requests": search.request_count, "perplexity_model_tokens": 0},
            ))
            _persist_search_sources(db, run.id, search.results)
            db.commit()
            run.stage = "analyzing_with_local_ai"; db.commit()
            analysis = analyze_opportunities(
                search_results=search.results,
                local_context=local_context,
                max_output_tokens=config.max_output_tokens,
            )
            history_batch = analysis.parsed
            parsed = _as_legacy_result(history_batch)
            run.model_used = analysis.model
            raw_payload.response_json = {
                "search": search.raw_response, "analysis_model": analysis.model
            }
            raw_payload.output_text = analysis.output_text
            raw_payload.parsed_json = parsed.model_dump(mode="json")
            _persist_pipeline_usage(db, run.id, search, analysis)
            history_source = "perplexity_search"
            measured_cost = search.cost_usd

        run.stage = "normalizing_candidates"
        run.analysis_date = parsed.analysis_date
        db.add(StockDiscoveryMarketContext(
            run_id=run.id,
            summary=parsed.market_context.summary,
            risk_regime=parsed.market_context.risk_regime,
            payload=parsed.market_context.model_dump(mode="json"),
        ))
        _persist_diagnosis(db, run.id, parsed)
        db.commit()
        run.stage = "local_verification"; db.commit()
        warnings = (
            _persist_candidates(db, run, parsed, config, raw_source="pi_agent")
            if run.discovery_mode == "pi_agent"
            else (
                _persist_candidates(db, run, parsed, config, raw_source="exa_finance")
                if run.discovery_mode == "exa_finance"
                else _persist_candidates(db, run, parsed, config)
            )
        )
        db.add(OpportunityHistory(
            user_id=run.user_id,
            run_id=run.id,
            query_context={
                "discovery_mode": run.discovery_mode,
                "queries": queries,
                "portfolio_snapshot_hash": run.portfolio_snapshot_hash,
            },
            market_condition=history_batch.market_condition,
            result_json=history_batch.model_dump(mode="json"),
            model_version=run.model_used or run.model_requested,
            search_source=history_source,
        ))
        if measured_cost > config.max_run_cost_usd:
            warnings.append(
                f"实际成本 ${measured_cost:.4f} 超过配置的单次预警线 "
                f"${config.max_run_cost_usd:.4f}。"
            )
        run.warnings = warnings
        run.status = "completed_with_warnings" if warnings else "completed"
        run.stage = "completed"; run.completed_at = _now(); run.next_scheduled_at = None
        db.commit(); db.refresh(run); return run
    except (AnalysisError, SearchError, PerplexityError, ExaError, PiAgentError) as exc:
        db.rollback(); run = db.get(StockDiscoveryRun, run_id)
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
        run.failure_reason = f"本地验证或持久化失败：{type(exc).__name__}"; db.commit()
        raise


def opportunity_history_payload(row: OpportunityHistory) -> dict:
    result = row.result_json or {}
    opportunities = result.get("opportunities") or []
    return {
        "id": row.id,
        "run_id": row.run_id,
        "created_at": row.created_at,
        "market_condition": row.market_condition,
        "model_version": row.model_version,
        "search_source": row.search_source,
        "opportunities": opportunities,
        "tickers": [item.get("ticker") for item in opportunities if item.get("ticker")],
        "categories": list(dict.fromkeys(
            category for item in opportunities for category in (item.get("category") or [])
        )),
        "max_confidence": max(
            (int(item.get("confidence") or 0) for item in opportunities), default=0
        ),
    }


def opportunity_history_list(db: Session, user_id: int, limit: int = 30) -> list[dict]:
    rows = db.scalars(
        select(OpportunityHistory)
        .where(OpportunityHistory.user_id == user_id)
        .order_by(OpportunityHistory.created_at.desc(), OpportunityHistory.id.desc())
        .limit(limit)
    ).all()
    return [opportunity_history_payload(row) for row in rows]


def opportunity_history_detail(
    db: Session, user_id: int, history_id: int
) -> dict | None:
    row = db.scalar(select(OpportunityHistory).where(
        OpportunityHistory.id == history_id,
        OpportunityHistory.user_id == user_id,
    ))
    if not row:
        return None
    payload = opportunity_history_payload(row)
    payload["query_context"] = row.query_context
    sources = db.scalars(
        select(StockDiscoverySource)
        .where(StockDiscoverySource.run_id == row.run_id)
        .order_by(StockDiscoverySource.id)
    ).all()
    payload["sources"] = [
        {"title": source.title, "url": source.url, "origin": source.source_origin}
        for source in sources
    ]
    return payload


def _run_payload(run: StockDiscoveryRun | None) -> dict | None:
    if not run: return None
    return {key: getattr(run, key) for key in (
        "id", "status", "stage", "trigger", "discovery_mode",
        "requested_at", "started_at", "completed_at", "analysis_date",
        "next_scheduled_at", "model_requested", "model_used", "prompt_version", "schema_version", "filter_version",
        "warnings", "failure_code", "failure_reason", "previous_successful_run_id",
        "funnel_stats",
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
    sources = list(db.scalars(select(StockDiscoverySource).where(or_(
        StockDiscoverySource.candidate_id == row.id,
        (
            (StockDiscoverySource.run_id == row.run_id)
            & StockDiscoverySource.candidate_id.is_(None)
        ),
    ))).all())
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
        "bear_case": raw.get("bear_case") or [],
        "evidence": [
            item for item in (raw.get("evidence") or [])
            if isinstance(item, dict) and item.get("claim")
        ],
        "research_depth": raw.get("research_depth") or "screened",
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
    if run.discovery_mode == "pi_agent":
        base["agent_events"] = agent_events_payload(db, run.id)
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
        "api_key_configured": bool(
            get_settings().exa_api_key.strip()
            if config.discovery_mode == "exa_finance"
            else (
                get_settings().perplexity_api_key.strip()
                and (
                    config.discovery_mode == "agent_finance"
                    or get_settings().openai_api_key.strip()
                )
                if config.discovery_mode != "pi_agent"
                else (
                    get_settings().agent_gateway_token.strip()
                    and get_settings().openai_api_key.strip()
                )
            )
        ),
        "discovery_mode": config.discovery_mode,
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
